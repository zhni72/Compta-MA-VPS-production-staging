"""Audit & tracabilite (P1.6) : journal, chainage, verrouillages, banque, cloture."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import BankStatement, Company, Entry, FiscalYear, PeriodLock, User
from app.services.accounting import AccountingError, get_fiscal_year
from app.services.audit_trail import (
    export_journal_csv,
    journal_audit,
    sceller_ecritures,
    verifier_chainage,
)
from app.services.banking import (
    BankingError,
    alertes_ecarts_anciens,
    candidats_rapprochement,
    de_rapprocher,
    etat_rapprochement,
    importer_releve,
    lignes_a_rapprocher,
    parser_csv_releve,
    rapprocher,
    rapprocher_automatiquement,
)
from app.services.closing import (
    cloturer_exercice,
    controle_a_nouveaux,
    reouvrir_exercice,
)
from app.services.period_locks import (
    PeriodLockError,
    deverrouiller_periode,
    periodes_verrouillees,
    resume_verrouillages,
    verrouiller_periode,
)

router = APIRouter(prefix="/audit", tags=["audit et tracabilite"])


@router.get("", summary="Journal d'audit filtre (qui a fait quoi, quand, sur quoi)")
def get_journal_audit(
    action: str | None = Query(default=None),
    entity: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    entrees = journal_audit(
        db,
        company_id=company.id,
        action=action,
        entity=entity,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": entree.id,
            "created_at": entree.created_at,
            "user_id": entree.user_id,
            "action": entree.action,
            "entity": entree.entity,
            "entity_id": entree.entity_id,
            "ip_address": entree.ip_address,
            "payload": entree.payload_json,
        }
        for entree in entrees
    ]


@router.get("/export", summary="Export CSV du journal (donnees personnelles masquees)")
def export_audit_csv(
    action: str | None = Query(default=None),
    entity: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    anonymiser: bool = Query(default=True, description="Minimisation loi 09-08"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    contenu = export_journal_csv(
        db,
        company_id=company.id,
        anonymiser=anonymiser,
        action=action,
        entity=entity,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    return Response(
        content=contenu.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="journal_audit.csv"'},
    )


@router.get("/chainage", summary="Verification de la piste fiable (hash et chainage)")
def get_chainage(
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return verifier_chainage(db, company.id)


@router.post("/chainage/sceller", summary="Sceller les ecritures non chainees (reprise)")
def post_sceller(
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> dict:
    resultat = sceller_ecritures(db, company.id)
    db.commit()
    return {
        "total_ecritures": resultat["total_ecritures"],
        "nb_scellees": resultat["nb_scellees"],
        "derniere_empreinte": resultat["derniere_empreinte"],
    }


@router.get("/ecritures/{entry_id}/piste", summary="Piste d'audit d'une ecriture")
def get_piste_ecriture(
    entry_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    from app.services.audit_trail import ecritures_de_la_piece, piste_ecriture

    entry = db.get(Entry, entry_id)
    if entry is None or entry.company_id != company.id:
        raise http_error(AccountingError(f"Ecriture {entry_id} introuvable"))
    piste = piste_ecriture(db, entry)
    piste["ecritures_liees"] = ecritures_de_la_piece(
        db, source=entry.source, source_id=entry.source_id or 0
    )
    return piste


# ---------------------------------------------------------------------------
# Verrouillage de periode
# ---------------------------------------------------------------------------
@router.get("/verrouillages", summary="Verrous de periode d'un exercice")
def get_verrouillages(
    year: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    resume = resume_verrouillages(db, company.id, year)
    verrous = periodes_verrouillees(db, company.id, year=year)
    return {
        **{cle: valeur for cle, valeur in resume.items() if cle != "annuel"},
        "verrous": [
            {
                "id": verrou.id,
                "periode": verrou.periode,
                "libelle": verrou.libelle,
                "motif": verrou.motif,
                "locked_at": verrou.locked_at,
                "locked_by": verrou.locked_by,
            }
            for verrou in verrous
        ],
    }


@router.post(
    "/verrouillages",
    status_code=status.HTTP_201_CREATED,
    summary="Verrouiller un mois ou un exercice",
)
def post_verrouillage(
    year: int = Query(..., ge=2000, le=2100),
    periode: int | None = Query(
        default=None, ge=1, le=12, description="Mois ; absent = exercice entier"
    ),
    motif: str | None = Query(default=None),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> dict:
    try:
        verrou = verrouiller_periode(
            db,
            company_id=company.id,
            year=year,
            periode=periode,
            motif=motif,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, PeriodLockError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {"id": verrou.id, "periode": verrou.periode, "libelle": verrou.libelle}


@router.delete("/verrouillages/{lock_id}", summary="Deverrouiller (motif obligatoire)")
def delete_verrouillage(
    lock_id: int,
    motif: str = Query(..., description="Motif du deverrouillage (piste d'audit)"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> dict:
    verrou = db.get(PeriodLock, lock_id)
    if verrou is None or verrou.company_id != company.id:
        raise http_error(AccountingError(f"Verrou {lock_id} introuvable"))
    try:
        trace = deverrouiller_periode(db, verrou, motif=motif, user_id=user.id)
        db.commit()
    except (AccountingError, PeriodLockError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return trace


# ---------------------------------------------------------------------------
# Cloture d'exercice et a-nouveaux (correction de l'ecart 9)
# ---------------------------------------------------------------------------
@router.get("/cloture/{year}", summary="Etat des a-nouveaux d'un exercice")
def get_cloture(
    year: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company.id, FiscalYear.year == year
        )
    ).scalar_one_or_none()
    if exercice is None:
        raise http_error(AccountingError(f"Exercice {year} introuvable"))
    return {
        "exercice": year,
        "statut": exercice.status,
        "closed_at": exercice.closed_at,
        "a_nouveaux": controle_a_nouveaux(db, company, year),
    }


@router.post("/cloture/{year}", summary="Cloturer un exercice et generer les a-nouveaux")
def post_cloture(
    year: int,
    generer_ouverture: bool = Query(default=True),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> dict:
    try:
        resultat = cloturer_exercice(
            db, company, year, user_id=user.id, generer_ouverture=generer_ouverture
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    a_nouveaux = resultat.pop("a_nouveaux", None) or {}
    resultat.pop("entry", None)
    return {
        **resultat,
        "a_nouveaux": {cle: valeur for cle, valeur in a_nouveaux.items() if cle != "entry"},
    }


@router.post("/cloture/{year}/reouvrir", summary="Reouvrir un exercice clos (encadre)")
def post_reouverture(
    year: int,
    motif: str = Query(..., min_length=10, description="Motif obligatoire (tracabilite)"),
    regenerer_a_nouveaux: bool = Query(
        default=False,
        description="Regeneration des a-nouveaux de N+1 (obligatoire si elles existent)",
    ),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> dict:
    try:
        resultat = reouvrir_exercice(
            db,
            company,
            year,
            motif=motif,
            user_id=user.id,
            regenerer_a_nouveaux=regenerer_a_nouveaux,
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    return resultat



# ---------------------------------------------------------------------------
# Rapprochement bancaire
# ---------------------------------------------------------------------------
@router.get("/releves", summary="Releves bancaires importes")
def get_releves(
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    releves = db.execute(
        select(BankStatement)
        .where(BankStatement.company_id == company.id)
        .order_by(BankStatement.date_to.desc())
    ).scalars()
    return [
        {
            "id": releve.id,
            "compte": releve.account_number,
            "date_from": releve.date_from,
            "date_to": releve.date_to,
            "closing_balance": releve.closing_balance,
            "nb_lignes": len(releve.lines),
            "nb_non_rapprochees": len([l for l in releve.lines if not l.reconciled]),
        }
        for releve in releves
    ]


@router.post(
    "/releves", status_code=status.HTTP_201_CREATED, summary="Importer un releve bancaire (CSV)"
)
async def post_releve(
    account_number: str = Form(...),
    date_from: date = Form(...),
    date_to: date = Form(...),
    closing_balance: Decimal = Form(...),
    opening_balance: Decimal = Form(Decimal("0")),
    fichier: UploadFile = File(...),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    contenu = (await fichier.read()).decode("utf-8", errors="replace")
    try:
        lignes = parser_csv_releve(contenu)
        releve = importer_releve(
            db,
            company=company,
            account_number=account_number,
            date_from=date_from,
            date_to=date_to,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            lignes=lignes,
            file_name=fichier.filename,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, BankingError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {"id": releve.id, "nb_lignes": len(releve.lines)}


@router.get("/releves/{releve_id}", summary="Releve, etat de rapprochement et candidats")
def get_releve(
    releve_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    releve = db.get(BankStatement, releve_id)
    if releve is None or releve.company_id != company.id:
        raise http_error(AccountingError(f"Releve {releve_id} introuvable"))
    return {
        "releve": {
            "id": releve.id,
            "compte": releve.account_number,
            "date_from": releve.date_from,
            "date_to": releve.date_to,
            "opening_balance": releve.opening_balance,
            "closing_balance": releve.closing_balance,
            "file_name": releve.file_name,
        },
        "etat": etat_rapprochement(db, releve),
        "a_rapprocher": [
            {
                "statement_line_id": element["ligne"].id,
                "date": element["ligne"].line_date,
                "label": element["ligne"].label,
                "montant": element["ligne"].montant,
                "candidats": element["candidats"],
            }
            for element in lignes_a_rapprocher(db, releve)
        ],
    }


@router.post("/releves/{releve_id}/rapprocher-auto", summary="Appariement automatique")
def post_rapprochement_auto(
    releve_id: int,
    tolerance_jours: int = Query(default=7, ge=0, le=60),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    releve = db.get(BankStatement, releve_id)
    if releve is None or releve.company_id != company.id:
        raise http_error(AccountingError(f"Releve {releve_id} introuvable"))
    resultat = rapprocher_automatiquement(
        db, releve, tolerance_jours=tolerance_jours, user_id=user.id
    )
    db.commit()
    return resultat


@router.post(
    "/releves/lignes/{ligne_id}/rapprocher", summary="Rapprocher (ou ajuster) une ligne"
)
def post_rapprochement(
    ligne_id: int,
    entry_line_id: int | None = Query(default=None),
    motif: str | None = Query(default=None),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    from app.models import BankStatementLine, EntryLine

    ligne = db.get(BankStatementLine, ligne_id)
    if ligne is None:
        raise http_error(AccountingError(f"Ligne de releve {ligne_id} introuvable"))
    releve = db.get(BankStatement, ligne.statement_id)
    if releve is None or releve.company_id != company.id:
        raise http_error(AccountingError("Ligne de releve hors dossier"))
    entry_line = db.get(EntryLine, entry_line_id) if entry_line_id else None
    try:
        rapprochement = rapprocher(
            db,
            ligne,
            entry_line,
            type_rapprochement="rapproche" if entry_line is not None else "ajustement",
            motif=motif,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, BankingError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "reconciliation_id": rapprochement.id,
        "statement_line_id": ligne.id,
        "entry_line_id": rapprochement.entry_line_id,
        "type": rapprochement.reconciliation_type,
    }


@router.delete("/releves/lignes/{ligne_id}/rapprocher", summary="Annuler un rapprochement")
def delete_rapprochement(
    ligne_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    from app.models import BankStatementLine

    ligne = db.get(BankStatementLine, ligne_id)
    if ligne is None:
        raise http_error(AccountingError(f"Ligne de releve {ligne_id} introuvable"))
    releve = db.get(BankStatement, ligne.statement_id)
    if releve is None or releve.company_id != company.id:
        raise http_error(AccountingError("Ligne de releve hors dossier"))
    try:
        de_rapprocher(db, ligne, user_id=user.id)
        db.commit()
    except (AccountingError, BankingError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {"statement_line_id": ligne.id, "reconciled": False}


@router.get("/alertes", summary="Alertes de tracabilite (ecarts bancaires anciens)")
def get_alertes(
    jours: int = Query(default=90, ge=1, le=365),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return alertes_ecarts_anciens(db, company.id, jours=jours)

