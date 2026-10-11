"""Interface graphique (Jinja2) : ecrans de gestion 100 % francais.

Toute la logique metier est deleguee a `app/services` : l'interface ne fait que
collecter la saisie, appeler le service et afficher le resultat.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.seed import create_user as creer_utilisateur
from app.db.seed import get_or_create_fiscal_year
from app.db.session import get_db
from app.services import assets as immobilisations
from app.services import audit_trail as piste
from app.services import banking
from app.services import closing as cloture
from app.services import edi_dts
from app.services import greffe as depot_greffe
from app.services import liasse_edi
from app.services import payroll as paie
from app.services import pdf_documents as documents_pdf
from app.services import period_locks as verrous
from app.services import stocks as magasin
from app.services.edi_tva import (
    BASE_PERIODE_DEFAUT,
    BASES_PERIODE,
    build_rd_xml,
    collect_rd_lines,
    controle_taille,
    regime_code,
    xml_filename,
)
from app.services.identifiers import (
    ComplianceError,
    validate_fiscal_id,
    validate_ice,
)
from app.models import (
    ASSET_METHOD_LABELS,
    ASSET_STATUS_LABELS,
    VALUATION_METHOD_LABELS,
    BankStatement,
    BankStatementLine,
    CGNC_CLASSES,
    ENTRY_STATUS_VALIDATED,
    INVOICE_STATUS_CANCELLED,
    INVOICE_STATUS_DRAFT,
    INVOICE_STATUS_PAID,
    INVOICE_STATUS_PARTIALLY_PAID,
    INVOICE_STATUS_VALIDATED,
    Account,
    Company,
    Entry,
    FiscalYear,
    Invoice,
    InvoiceLine,
    Journal,
    Payment,
    Payslip,
    PeriodLock,
    Role,
    ThirdParty,
    User,
    VatRate,
)
from app.services.accounting import (
    AccountingError,
    create_entry,
    get_fiscal_year,
    get_journal,
    reverse_entry,
    validate_entry,
)
from app.services.accounts import InvalidAccountNumber, ensure_account
from app.services.invoicing import (
    add_line,
    cancel_invoice,
    controles_coherence_facture,
    create_invoice,
    register_payment,
    validate_invoice,
)
from app.services.parties import create_third_party, find_third_party
from app.services.reporting import (
    balance_generale,
    balance_sheet,
    grand_livre,
    income_statement,
    journal_entries,
    year_bounds,
)
from app.services.vat import period_bounds, vat_return, vat_summary_by_rate
from app.web.deps import (
    COMPANY_COOKIE,
    ROLE_LABELS_WEB,
    SESSION_COOKIE,
    NotAuthorized,
    format_amount,
    get_web_company,
    get_web_user,
    login_user,
    logout_user,
    render,
)

router = APIRouter(tags=["interface"])


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------
def redirect_to(path: str, msg: str = "", level: str = "success") -> RedirectResponse:
    """Redirection (POST -> GET) avec message affiche une seule fois."""
    if msg:
        separateur = "&" if "?" in path else "?"
        path = f"{path}{separateur}{urlencode({'msg': msg, 'level': level})}"
    return RedirectResponse(path, status_code=303)


def tiers_map(db: Session, company_id: int) -> dict[int, str]:
    """{id_tiers: 'CL0001 - Raison sociale'} pour l'affichage des tableaux."""
    rows = db.execute(
        select(ThirdParty.id, ThirdParty.code, ThirdParty.name).where(
            ThirdParty.company_id == company_id
        )
    ).all()
    return {row[0]: f"{row[1]} - {row[2]}" for row in rows}


def safe_float(value: str | None, default: float = 0.0) -> float:
    """Convertit une saisie utilisateur (virgule ou point) en nombre."""
    if value is None or str(value).strip() == "":
        return default
    texte = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        return default


def current_year(company: Company | None, db: Session) -> int:
    """Exercice courant : le plus récent ouvert de la société, sinon l'année civile."""
    if company is not None:
        fiscal_year = db.execute(
            select(FiscalYear)
            .where(FiscalYear.company_id == company.id)
            .order_by(FiscalYear.year.desc())
        ).scalars().first()
        if fiscal_year is not None:
            return fiscal_year.year
    return date.today().year


def selected_fiscal_year(db: Session, company: Company, year: int) -> FiscalYear | None:
    return db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company.id, FiscalYear.year == year
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Connexion / deconnexion
# ---------------------------------------------------------------------------
@router.get("/connexion", response_class=HTMLResponse)
def page_connexion(request: Request, next: str = "/") -> HTMLResponse:
    if request.cookies.get(SESSION_COOKIE):
        return RedirectResponse(next or "/", status_code=303)
    return render(request, "login.html", title="Connexion", next_url=next)


@router.post("/connexion")
def connexion(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user = db.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        return render(
            request,
            "login.html",
            title="Connexion",
            msg="Adresse e-mail ou mot de passe incorrect.",
            level="error",
            email=email,
            next_url=next,
        )
    response = redirect_to(next or "/", f"Bienvenue {user.full_name}.")
    login_user(response, user)
    return response


@router.get("/deconnexion")
def deconnexion() -> RedirectResponse:
    response = redirect_to("/connexion", "Vous avez été déconnecté.", "info")
    logout_user(response)
    return response


# ---------------------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def tableau_de_bord(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to(
            "/parametres/societe",
            "Aucun dossier comptable : créez la fiche de votre société.",
            "warning",
        )
    exercice = year or current_year(company, db)
    debut, fin = year_bounds(exercice)

    cpc = income_statement(db, company.id, debut, fin)
    balance = balance_generale(db, company.id, debut, fin)

    def solde(prefixe: str) -> Decimal:
        return sum(
            (l["solde"] for l in balance["lines"] if l["account_number"].startswith(prefixe)),
            Decimal("0"),
        )

    trimestre = (date.today().month - 1) // 3 + 1
    tva_debut, tva_fin = period_bounds(exercice, quarter=trimestre)
    tva = vat_return(db, company.id, tva_debut, tva_fin)

    derniers = db.execute(
        select(Invoice)
        .where(Invoice.company_id == company.id)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .limit(8)
    ).scalars().all()
    en_attente = [
        f
        for f in db.execute(
            select(Invoice)
            .where(
                Invoice.company_id == company.id,
                Invoice.status.in_(
                    (INVOICE_STATUS_VALIDATED, INVOICE_STATUS_PARTIALLY_PAID)
                ),
            )
            .order_by(Invoice.due_date)
        ).scalars().all()
        if f.remaining_amount > 0
    ]
    clients_sans_ice = db.execute(
        select(func.count())
        .select_from(ThirdParty)
        .where(
            ThirdParty.company_id == company.id,
            ThirdParty.kind == "client",
            ThirdParty.is_individual.is_(False),
            ThirdParty.ice.is_(None),
        )
    ).scalar_one()

    return render(
        request,
        "dashboard.html",
        user=user,
        company=company,
        title="Tableau de bord",
        active="tableau-de-bord",
        year=exercice,
        today=date.today(),
        resultat=cpc["resultat"],
        total_produits=cpc["total_produits"],
        total_charges=cpc["total_charges"],
        tva_periode=f"T{trimestre} {exercice}",
        tva_collectee=tva["tva_collectee"],
        tva_deductible=tva["tva_deductible"],
        tva_a_payer=tva["tva_a_payer"],
        echeance_tva=tva["echeance"],
        tresorerie=solde("514") + solde("516") + solde("511"),
        creances_clients=solde("342"),
        dettes_fournisseurs=-solde("441"),
        derniers_documents=derniers,
        factures_impayees=en_attente[:8],
        nb_factures_impayees=len(en_attente),
        tiers_map=tiers_map(db, company.id),
        alerts=clients_sans_ice,
    )


# ---------------------------------------------------------------------------
# Tiers : clients, fournisseurs, salaries
# ---------------------------------------------------------------------------
@router.get("/tiers", response_class=HTMLResponse)
def liste_tiers(
    request: Request,
    kind: str | None = Query(default=None),
    search: str | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    stmt = select(ThirdParty).where(ThirdParty.company_id == company.id)
    if kind in ("client", "fournisseur", "salarie"):
        stmt = stmt.where(ThirdParty.kind == kind)
    if search:
        stmt = stmt.where(ThirdParty.name.ilike(f"%{search}%"))
    tiers = db.execute(stmt.order_by(ThirdParty.code)).scalars().all()
    return render(
        request,
        "tiers_liste.html",
        user=user,
        company=company,
        title="Clients & fournisseurs",
        active="tiers",
        tiers=tiers,
        kind=kind or "",
        search=search or "",
    )


@router.get("/tiers/nouveau", response_class=HTMLResponse)
def formulaire_tiers(
    request: Request,
    kind: str = Query(default="client"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    return render(
        request,
        "tiers_formulaire.html",
        user=user,
        company=company,
        title="Nouveau tiers",
        active="tiers",
        kind=kind if kind in ("client", "fournisseur", "salarie") else "client",
    )


@router.post("/tiers/nouveau")
def creer_tiers(
    request: Request,
    kind: str = Form("client"),
    name: str = Form(...),
    ice: str = Form(""),
    fiscal_id: str = Form(""),
    rc: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    is_individual: str = Form(""),
    payment_terms_days: str = Form("0"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    # Un particulier n'a pas d'ICE (dispense legale) ; un professionnel doit en avoir un.
    particulier = is_individual == "1"
    try:
        tiers = create_third_party(
            db,
            company=company,
            kind=kind,
            name=name.strip(),
            ice=None if particulier else (ice.strip() or None),
            fiscal_id=fiscal_id.strip() or None,
            rc=rc.strip() or None,
            address=address.strip() or None,
            city=city.strip() or None,
            phone=phone.strip() or None,
            email=email.strip() or None,
            is_individual=particulier,
            payment_terms_days=int(safe_float(payment_terms_days, 0)),
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/tiers/nouveau", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/tiers?kind={kind}",
        f"Tiers {tiers.code} créé (compte {tiers.account_number}).",
    )


@router.get("/tiers/{code}", response_class=HTMLResponse)
def fiche_tiers(
    code: str,
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    tiers = find_third_party(db, company.id, code)
    if tiers is None:
        return redirect_to("/tiers", "Tiers introuvable.", "error")
    debut, fin = year_bounds(current_year(company, db))
    livre = grand_livre(db, company.id, tiers.account_number, debut, fin)
    documents = db.execute(
        select(Invoice)
        .where(Invoice.company_id == company.id, Invoice.partner_id == tiers.id)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .limit(50)
    ).scalars().all()
    return render(
        request,
        "tiers_fiche.html",
        user=user,
        company=company,
        title=f"{tiers.code} - {tiers.name}",
        active="tiers",
        tiers=tiers,
        livre=livre,
        documents=documents,
    )


# ---------------------------------------------------------------------------
# Factures (ventes, achats, avoirs) et reglements
# ---------------------------------------------------------------------------
@router.get("/factures", response_class=HTMLResponse)
def liste_factures(
    request: Request,
    type: str = Query(default="vente"),
    statut: str = Query(default=""),
    search: str = Query(default=""),
    avoir: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    type_facture = "achat" if type == "achat" else "vente"
    stmt = select(Invoice).where(
        Invoice.company_id == company.id, Invoice.invoice_type == type_facture
    )
    if statut:
        stmt = stmt.where(Invoice.status == statut)
    if search:
        stmt = stmt.where(Invoice.number.ilike(f"%{search}%"))
    if avoir == "1":
        stmt = stmt.where(Invoice.is_credit_note.is_(True))
    elif avoir == "0":
        stmt = stmt.where(Invoice.is_credit_note.is_(False))
    documents = db.execute(
        stmt.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).limit(300)
    ).scalars().all()
    totaux = {
        "ttc": sum((f.total_ttc for f in documents if f.status != INVOICE_STATUS_CANCELLED), Decimal("0")),
        "reste": sum((f.remaining_amount for f in documents if f.status != INVOICE_STATUS_CANCELLED), Decimal("0")),
    }
    return render(
        request,
        "factures_liste.html",
        user=user,
        company=company,
        title="Factures de vente" if type_facture == "vente" else "Factures d'achat",
        active="ventes" if type_facture == "vente" else "achats",
        documents=documents,
        type_facture=type_facture,
        statut=statut,
        search=search,
        avoir=avoir,
        totaux=totaux,
        tiers_map=tiers_map(db, company.id),
    )


@router.get("/factures/nouvelle", response_class=HTMLResponse)
def formulaire_facture(
    request: Request,
    type: str = Query(default="vente"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    type_facture = "achat" if type == "achat" else "vente"
    kind_tiers = "fournisseur" if type_facture == "achat" else "client"
    tiers = db.execute(
        select(ThirdParty)
        .where(ThirdParty.company_id == company.id, ThirdParty.kind == kind_tiers)
        .order_by(ThirdParty.name)
    ).scalars().all()
    return render(
        request,
        "factures_formulaire.html",
        user=user,
        company=company,
        title=f"Nouvelle facture {'d\'achat' if type_facture == 'achat' else 'de vente'}",
        active="ventes" if type_facture == "vente" else "achats",
        type_facture=type_facture,
        tiers=tiers,
        today=date.today(),
    )


@router.post("/factures/nouvelle")
def creer_facture(
    request: Request,
    invoice_type: str = Form("vente"),
    partner_code: str = Form(...),
    invoice_date: str = Form(...),
    due_date: str = Form(""),
    payment_mode: str = Form("virement"),
    reference: str = Form(""),
    notes: str = Form(""),
    is_credit_note: str = Form(""),
    auto_validate: str = Form(""),
    designation: list[str] = Form(default=[]),
    quantity: list[str] = Form(default=[]),
    unit_price: list[str] = Form(default=[]),
    vat_rate: list[str] = Form(default=[]),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    tiers = find_third_party(db, company.id, partner_code)
    if tiers is None:
        return redirect_to("/factures", "Tiers sélectionné introuvable.", "error")

    lignes: list[dict] = []
    for index, libelle in enumerate(designation):
        if not libelle.strip():
            continue
        lignes.append(
            {
                "designation": libelle.strip(),
                "quantity": safe_float(quantity[index] if index < len(quantity) else "1", 1),
                "unit_price": safe_float(unit_price[index] if index < len(unit_price) else "0"),
                "vat_rate": safe_float(vat_rate[index] if index < len(vat_rate) else "20", 20),
            }
        )
    if not lignes:
        return redirect_to(
            f"/factures/nouvelle?type={invoice_type}",
            "Ajoutez au moins une ligne à la facture.",
            "error",
        )
    try:
        facture = create_invoice(
            db,
            company=company,
            invoice_type="achat" if invoice_type == "achat" else "vente",
            partner=tiers,
            invoice_date=date.fromisoformat(invoice_date),
            due_date=date.fromisoformat(due_date) if due_date else None,
            payment_mode=payment_mode or None,
            reference=reference.strip() or None,
            notes=notes.strip() or None,
            is_credit_note=is_credit_note == "1",
            lines=lignes,
        )
        message = (
            "Facture enregistrée en brouillon "
            f"({format_amount(facture.total_ttc)} DH TTC)."
        )
        if auto_validate == "1":
            validate_invoice(db, facture, user_id=user.id)
            message = (
                f"Facture {facture.number} validée et comptabilisée "
                f"({format_amount(facture.total_ttc)} DH TTC)."
            )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to(
            f"/factures/nouvelle?type={invoice_type}", f"Erreur : {exc}", "error"
        )
    return redirect_to(f"/factures/{facture.id}", message)


@router.get("/factures/{invoice_id}", response_class=HTMLResponse)
def detail_facture(
    invoice_id: int,
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    facture = db.get(Invoice, invoice_id)
    if facture is None or facture.company_id != company.id:
        return redirect_to("/factures", "Facture introuvable.", "error")
    tiers = db.get(ThirdParty, facture.partner_id)
    ecriture = db.get(Entry, facture.entry_id) if facture.entry_id else None
    reglements = db.execute(
        select(Payment).where(Payment.invoice_id == facture.id).order_by(Payment.payment_date)
    ).scalars().all()
    return render(
        request,
        "factures_detail.html",
        user=user,
        company=company,
        title=facture.number or f"Brouillon #{facture.id}",
        active="ventes" if facture.invoice_type == "vente" else "achats",
        facture=facture,
        tiers=tiers,
        ecriture=ecriture,
        reglements=reglements,
        incoherences=controles_coherence_facture(facture),
        today=date.today(),
    )


@router.post("/factures/{invoice_id}/valider")
def valider_facture(
    invoice_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    facture = db.get(Invoice, invoice_id)
    if facture is None or facture.company_id != company.id:
        return redirect_to("/factures", "Facture introuvable.", "error")
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")
    ):
        return redirect_to(
            f"/factures/{invoice_id}",
            "Votre rôle ne permet pas de valider une facture.",
            "error",
        )
    try:
        validate_invoice(db, facture, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to(f"/factures/{invoice_id}", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/factures/{invoice_id}",
        f"Facture {facture.number} validée : numéro attribué et écriture comptable générée.",
    )


@router.post("/factures/{invoice_id}/regler")
def regler_facture(
    invoice_id: int,
    amount: str = Form(...),
    payment_date: str = Form(""),
    method: str = Form("virement"),
    reference: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    facture = db.get(Invoice, invoice_id)
    if facture is None or facture.company_id != company.id:
        return redirect_to("/factures", "Facture introuvable.", "error")
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE", "CAISSIER")
    ):
        return redirect_to(
            f"/factures/{invoice_id}",
            "Votre rôle ne permet pas d'enregistrer un règlement.",
            "error",
        )
    try:
        register_payment(
            db,
            facture,
            amount=safe_float(amount),
            payment_date=date.fromisoformat(payment_date) if payment_date else date.today(),
            method=method,
            reference=reference.strip() or None,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to(f"/factures/{invoice_id}", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/factures/{invoice_id}",
        f"Règlement enregistré. Reste à payer : {format_amount(facture.remaining_amount)} DH.",
    )


@router.post("/factures/{invoice_id}/annuler")
def annuler_facture(
    invoice_id: int,
    reason: str = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    facture = db.get(Invoice, invoice_id)
    if facture is None or facture.company_id != company.id:
        return redirect_to("/factures", "Facture introuvable.", "error")
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")
    ):
        return redirect_to(
            f"/factures/{invoice_id}",
            "Votre rôle ne permet pas d'annuler une facture.",
            "error",
        )
    try:
        cancel_invoice(db, facture, reason=reason.strip(), user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to(f"/factures/{invoice_id}", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/factures/{invoice_id}",
        "Facture annulée : contre-écriture générée, numéro conservé (pas de trou).",
    )


@router.get("/factures/{invoice_id}/impression", response_class=HTMLResponse)
def imprimer_facture(
    invoice_id: int,
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    facture = db.get(Invoice, invoice_id)
    if facture is None or facture.company_id != company.id:
        return redirect_to("/factures", "Facture introuvable.", "error")
    tiers = db.get(ThirdParty, facture.partner_id)
    # Ventilation de la TVA par taux (obligatoire sur la facture marocaine).
    ventilation: dict[Decimal, dict] = {}
    for ligne in facture.lines:
        entree = ventilation.setdefault(ligne.vat_rate, {"base": Decimal("0"), "tva": Decimal("0")})
        entree["base"] += ligne.line_ht
        entree["tva"] += ligne.line_vat
    return render(
        request,
        "factures_impression.html",
        user=user,
        company=company,
        title=f"Impression {facture.number or 'brouillon'}",
        active="",
        facture=facture,
        tiers=tiers,
        incoherences=controles_coherence_facture(facture),
        ventilation_tva=[
            {"taux": taux, "base": valeurs["base"], "tva": valeurs["tva"]}
            for taux, valeurs in sorted(ventilation.items())
        ],
    )


@router.get("/reglements", response_class=HTMLResponse)
def liste_reglements(
    request: Request,
    type: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    stmt = select(Payment).where(Payment.company_id == company.id)
    if type in ("vente", "achat"):
        stmt = stmt.join(Invoice, Invoice.id == Payment.invoice_id).where(
            Invoice.invoice_type == type
        )
    reglements = db.execute(
        stmt.order_by(Payment.payment_date.desc(), Payment.id.desc()).limit(300)
    ).scalars().all()
    return render(
        request,
        "reglements_liste.html",
        user=user,
        company=company,
        title="Règlements",
        active="reglements",
        reglements=reglements,
        type=type,
        tiers_map=tiers_map(db, company.id),
        total=sum((r.amount for r in reglements), Decimal("0")),
        factures={
            f.id: (f.number or f"#{f.id}")
            for f in db.execute(
                select(Invoice).where(Invoice.company_id == company.id)
            ).scalars().all()
        },
    )


# ---------------------------------------------------------------------------
# Saisie comptable (ecritures)
# ---------------------------------------------------------------------------
@router.get("/ecritures", response_class=HTMLResponse)
def liste_ecritures(
    request: Request,
    journal_code: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercice = current_year(company, db)
    debut, fin = year_bounds(exercice)
    stmt = (
        select(Entry)
        .where(Entry.company_id == company.id)
        .order_by(Entry.entry_date.desc(), Entry.id.desc())
        .limit(300)
    )
    if journal_code:
        journal = db.execute(
            select(Journal).where(
                Journal.company_id == company.id, Journal.code == journal_code
            )
        ).scalar_one_or_none()
        if journal is not None:
            stmt = stmt.where(Entry.journal_id == journal.id)
    if date_from:
        stmt = stmt.where(Entry.entry_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(Entry.entry_date <= date.fromisoformat(date_to))
    ecritures = db.execute(stmt).scalars().all()
    journaux = db.execute(
        select(Journal).where(Journal.company_id == company.id).order_by(Journal.code)
    ).scalars().all()
    return render(
        request,
        "ecritures_liste.html",
        user=user,
        company=company,
        title="Saisie des écritures",
        active="ecritures",
        ecritures=ecritures,
        journaux=journaux,
        journal_code=journal_code,
        date_from=date_from,
        date_to=date_to,
        exercice=exercice,
        debut=debut,
        fin=fin,
        journaux_map={j.id: j.code for j in journaux},
    )


@router.get("/ecritures/nouvelle", response_class=HTMLResponse)
def formulaire_ecriture(
    request: Request,
    journal_code: str = Query(default="OD"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    journaux = db.execute(
        select(Journal).where(Journal.company_id == company.id).order_by(Journal.code)
    ).scalars().all()
    comptes = db.execute(select(Account).order_by(Account.number)).scalars().all()
    return render(
        request,
        "ecritures_formulaire.html",
        user=user,
        company=company,
        title="Nouvelle écriture comptable",
        active="ecritures",
        journaux=journaux,
        journal_code=journal_code,
        today=date.today(),
        comptes=[(a.number, a.label) for a in comptes],
    )


@router.post("/ecritures/nouvelle")
def creer_ecriture(
    request: Request,
    journal_code: str = Form("OD"),
    entry_date: str = Form(...),
    label: str = Form(...),
    reference: str = Form(""),
    account_number: list[str] = Form(default=[]),
    debit: list[str] = Form(default=[]),
    credit: list[str] = Form(default=[]),
    line_label: list[str] = Form(default=[]),
    auto_validate: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    lignes: list[dict] = []
    for index, compte in enumerate(account_number):
        montant_debit = safe_float(debit[index] if index < len(debit) else "0")
        montant_credit = safe_float(credit[index] if index < len(credit) else "0")
        if not compte.strip() and montant_debit == 0 and montant_credit == 0:
            continue
        lignes.append(
            {
                "account_number": compte.strip(),
                "debit": montant_debit,
                "credit": montant_credit,
                "label": (line_label[index] if index < len(line_label) else "") or None,
            }
        )
    try:
        journal = get_journal(db, company.id, journal_code)
        jour = date.fromisoformat(entry_date)
        fiscal_year = get_fiscal_year(db, company.id, jour.year)
        ecriture = create_entry(
            db,
            company_id=company.id,
            fiscal_year=fiscal_year,
            journal=journal,
            entry_date=jour,
            label=label.strip(),
            reference=reference.strip() or None,
            created_by=user.id,
            lines=lignes,
            validate=auto_validate == "1",
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/ecritures/nouvelle", f"Erreur : {exc}", "error")
    return redirect_to(
        "/ecritures",
        f"Écriture {ecriture.entry_number or '(brouillon)'} enregistrée "
        f"dans le journal {journal_code}.",
    )


@router.post("/ecritures/{entry_id}/valider")
def valider_ecriture(
    entry_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    ecriture = db.get(Entry, entry_id)
    if ecriture is None or ecriture.company_id != company.id:
        return redirect_to("/ecritures", "Écriture introuvable.", "error")
    try:
        validate_entry(db, ecriture, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to("/ecritures", f"Erreur : {exc}", "error")
    return redirect_to("/ecritures", f"Écriture {ecriture.entry_number} validée.")


@router.post("/ecritures/{entry_id}/extourner")
def extourner_ecriture(
    entry_id: int,
    reason: str = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    ecriture = db.get(Entry, entry_id)
    if ecriture is None or ecriture.company_id != company.id:
        return redirect_to("/ecritures", "Écriture introuvable.", "error")
    try:
        extourne = reverse_entry(db, ecriture, reason=reason.strip(), user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to("/ecritures", f"Erreur : {exc}", "error")
    return redirect_to("/ecritures", f"Contre-écriture {extourne.entry_number} générée.")


# ---------------------------------------------------------------------------
# Plan comptable (PCGE / CGNC)
# ---------------------------------------------------------------------------
@router.get("/comptes", response_class=HTMLResponse)
def liste_comptes(
    request: Request,
    prefix: str = Query(default=""),
    account_class: str = Query(default=""),
    search: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    stmt = select(Account).order_by(Account.number)
    if prefix:
        stmt = stmt.where(Account.number.like(f"{prefix}%"))
    if account_class.isdigit():
        stmt = stmt.where(Account.account_class == int(account_class))
    if search:
        stmt = stmt.where(Account.label.ilike(f"%{search}%"))
    comptes = db.execute(stmt.limit(500)).scalars().all()
    return render(
        request,
        "comptes_liste.html",
        user=user,
        company=company,
        title="Plan comptable (CGNC)",
        active="comptes",
        comptes=comptes,
        prefix=prefix,
        account_class=account_class,
        search=search,
        total_comptes=db.execute(select(func.count()).select_from(Account)).scalar_one(),
    )


@router.post("/comptes/nouveau")
def creer_compte(
    number: str = Form(...),
    label: str = Form(...),
    is_collectif: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        ensure_account(db, number.strip(), label=label.strip(), is_collectif=is_collectif == "1")
        db.commit()
    except (InvalidAccountNumber, ValueError) as exc:
        db.rollback()
        return redirect_to("/comptes", f"Erreur : {exc}", "error")
    return redirect_to("/comptes", f"Compte {number.strip()} créé dans le plan comptable.")


# ---------------------------------------------------------------------------
# Etats comptables
# ---------------------------------------------------------------------------
def _periode_etats(exercice: int, month: str, quarter: str) -> tuple[date, date, str]:
    """Bornes de la période d'édition + libellé lisible pour l'en-tête."""
    if month.isdigit():
        debut, fin = period_bounds(exercice, month=int(month))
        return debut, fin, f"mois {int(month):02d}/{exercice}"
    if quarter.isdigit():
        debut, fin = period_bounds(exercice, quarter=int(quarter))
        return debut, fin, f"{int(quarter)}e trimestre {exercice}"
    debut, fin = year_bounds(exercice)
    return debut, fin, f"exercice {exercice}"


@router.get("/etats/balance", response_class=HTMLResponse)
def page_balance(
    request: Request,
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    prefix: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercice = year or current_year(company, db)
    debut, fin, libelle = _periode_etats(exercice, month, quarter)
    balance = balance_generale(db, company.id, debut, fin, prefix=prefix or None)
    par_classe: dict[int, dict] = {}
    for ligne in balance["lines"]:
        agregat = par_classe.setdefault(
            ligne["account_class"], {"debit": Decimal("0"), "credit": Decimal("0")}
        )
        agregat["debit"] += ligne["debit"]
        agregat["credit"] += ligne["credit"]
    return render(
        request,
        "etats_balance.html",
        user=user,
        company=company,
        title="Balance générale",
        active="balance",
        balance=balance,
        libelle=libelle,
        debut=debut,
        fin=fin,
        exercice=exercice,
        month=month,
        quarter=quarter,
        prefix=prefix,
        par_classe=[
            {
                "classe": classe,
                "libelle": CGNC_CLASSES.get(classe, ""),
                "debit": valeurs["debit"],
                "credit": valeurs["credit"],
                "solde": valeurs["debit"] - valeurs["credit"],
            }
            for classe, valeurs in sorted(par_classe.items())
        ],
    )


@router.get("/etats/grand-livre", response_class=HTMLResponse)
def page_grand_livre(
    request: Request,
    account_number: str = Query(default=""),
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercice = year or current_year(company, db)
    debut, fin, libelle = _periode_etats(exercice, month, quarter)
    livre = (
        grand_livre(db, company.id, account_number.strip(), debut, fin)
        if account_number.strip()
        else None
    )
    comptes = db.execute(
        select(Account).order_by(Account.number).limit(400)
    ).scalars().all()
    return render(
        request,
        "etats_grand_livre.html",
        user=user,
        company=company,
        title="Grand livre",
        active="grand-livre",
        livre=livre,
        account_number=account_number,
        libelle=libelle,
        exercice=exercice,
        month=month,
        quarter=quarter,
        comptes=comptes,
    )


@router.get("/etats/cpc", response_class=HTMLResponse)
def page_cpc(
    request: Request,
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercice = year or current_year(company, db)
    debut, fin, libelle = _periode_etats(exercice, month, quarter)
    return render(
        request,
        "etats_cpc.html",
        user=user,
        company=company,
        title="Compte de produits et charges",
        active="cpc",
        cpc=income_statement(db, company.id, debut, fin),
        libelle=libelle,
        exercice=exercice,
        month=month,
        quarter=quarter,
    )


@router.get("/etats/bilan", response_class=HTMLResponse)
def page_bilan(
    request: Request,
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercice = year or current_year(company, db)
    debut, fin, libelle = _periode_etats(exercice, month, quarter)
    return render(
        request,
        "etats_bilan.html",
        user=user,
        company=company,
        title="Bilan",
        active="bilan",
        bilan=balance_sheet(db, company.id, debut, fin),
        cgnc=CGNC_CLASSES,
        libelle=libelle,
        exercice=exercice,
        month=month,
        quarter=quarter,
    )


# ---------------------------------------------------------------------------
# Journaux comptables
# ---------------------------------------------------------------------------
@router.get("/etats/journal", response_class=HTMLResponse)
def page_journal(
    request: Request,
    journal_code: str = Query(default=""),
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercice = year or current_year(company, db)
    debut, fin, libelle = _periode_etats(exercice, month, quarter)
    lignes = journal_entries(
        db, company.id, debut, fin, journal_code=journal_code or None
    )
    journaux = db.execute(
        select(Journal).where(Journal.company_id == company.id).order_by(Journal.code)
    ).scalars().all()
    return render(
        request,
        "etats_journal.html",
        user=user,
        company=company,
        title="Journal comptable",
        active="journal" if not journal_code else "paie-ecritures",
        lignes=lignes,
        journaux=journaux,
        journal_code=journal_code,
        libelle=libelle,
        exercice=exercice,
        month=month,
        quarter=quarter,
        total_debit=sum((l["debit"] for l in lignes), Decimal("0")),
        total_credit=sum((l["credit"] for l in lignes), Decimal("0")),
    )


# ---------------------------------------------------------------------------
# Declarations fiscales (TVA)
# ---------------------------------------------------------------------------
@router.get("/tva", response_class=HTMLResponse)
def page_tva(
    request: Request,
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercice = year or current_year(company, db)
    # Par défaut : période en cours selon le régime déclaratif de la société.
    if not month and not quarter:
        if company.vat_regime == "mensuel":
            month = str(date.today().month)
        else:
            quarter = str((date.today().month - 1) // 3 + 1)
    debut, fin, libelle = _periode_etats(exercice, month, quarter)
    declaration = vat_return(db, company.id, debut, fin)
    debut_exercice, fin_exercice = year_bounds(exercice)
    cpc = income_statement(db, company.id, debut_exercice, fin_exercice)
    taux = db.execute(select(VatRate).order_by(VatRate.rate.desc())).scalars().all()
    return render(
        request,
        "tva_declaration.html",
        user=user,
        company=company,
        title="Déclaration de TVA",
        active="tva",
        declaration=declaration,
        ventilation_ventes=vat_summary_by_rate(
            db, company.id, debut, fin, invoice_type="vente"
        ),
        ventilation_achats=vat_summary_by_rate(
            db, company.id, debut, fin, invoice_type="achat"
        ),
        taux=taux,
        libelle=libelle,
        debut=debut,
        fin=fin,
        exercice=exercice,
        month=month,
        quarter=quarter,
        seuil_mensuel=1000000,
        ca_annuel=cpc["total_produits"],
        regime_conseille="mensuel" if cpc["total_produits"] >= 1000000 else "trimestriel",
    )


# ---------------------------------------------------------------------------
# Releve des deductions TVA - export EDI (fichier XML a deposer sur Simpl-TVA)
# ---------------------------------------------------------------------------
def _periode_edi(company: Company, year: int | None, month: str, quarter: str):
    """Periode du relevé : mois ou trimestre selon le regime de la societe."""
    exercice = year or date.today().year
    if not month and not quarter:
        if company.vat_regime == "mensuel":
            month = str(date.today().month)
        else:
            quarter = str((date.today().month - 1) // 3 + 1)
    debut, fin, libelle = _periode_etats(exercice, month, quarter)
    return debut, fin, libelle, exercice, month, quarter


def _base_periode_edi(valeur: str) -> str:
    """Base de rattachement de la periode : paiement (defaut) ou facture."""
    return valeur if valeur in BASES_PERIODE else BASE_PERIODE_DEFAUT


def _prorata_edi(valeur: str) -> Decimal:
    """Prorata de deduction saisi en pourcentage (100 = deduction integrale).

    Le prorata est applique a la TVA deductible (CGI art. 106) ; hors bornes
    (0, 100], la deduction est consideree comme integrale.
    """
    pourcentage = Decimal(str(safe_float(valeur, 100.0)))
    if not Decimal("0") < pourcentage <= Decimal("100"):
        return Decimal("1")
    return (pourcentage / Decimal("100")).quantize(Decimal("0.0001"))


@router.get("/tva/edi", response_class=HTMLResponse)
def page_tva_edi(
    request: Request,
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    include_zero: str = Query(default=""),
    tx_unit: str = Query(default="percent"),
    prorata: str = Query(default=""),
    base_periode: str = Query(default=BASE_PERIODE_DEFAUT),
    taux_prorata: str = Query(default="100"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    debut, fin, libelle, exercice, month, quarter = _periode_edi(
        company, year, month, quarter
    )
    regime = regime_code(company)
    periode = int(month or quarter or 0)
    base_periode = _base_periode_edi(base_periode)
    prorata_valeur = _prorata_edi(taux_prorata)
    collecte = collect_rd_lines(
        db,
        company,
        debut,
        fin,
        include_zero_vat=include_zero == "1",
        prorata=prorata_valeur,
        base_periode=base_periode,
    )
    return render(
        request,
        "tva_edi.html",
        user=user,
        company=company,
        title="Relevé des déductions TVA (export EDI)",
        active="tva-edi",
        collecte=collecte,
        lignes=collecte["lignes"],
        anomalies=collecte["anomalies"],
        anomalies_bloquantes=[a for a in collecte["anomalies"] if a["bloquant"]],
        exclues=collecte["exclues"],
        totaux=collecte["totaux"],
        regime=regime,
        periode=periode,
        tx_unit=tx_unit,
        prorata=prorata,
        base_periode=base_periode,
        taux_prorata=taux_prorata,
        prorata_valeur=prorata_valeur,
        include_zero=include_zero,
        libelle=libelle,
        debut=debut,
        fin=fin,
        exercice=exercice,
        month=month,
        quarter=quarter,
        nom_fichier=xml_filename(exercice, periode, regime),
    )


@router.get("/tva/edi/xml")
def telecharger_tva_edi(
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    include_zero: str = Query(default=""),
    tx_unit: str = Query(default="percent"),
    prorata: str = Query(default=""),
    base_periode: str = Query(default=BASE_PERIODE_DEFAUT),
    taux_prorata: str = Query(default="100"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    debut, fin, libelle, exercice, month, quarter = _periode_edi(
        company, year, month, quarter
    )
    regime = regime_code(company)
    periode = int(month or quarter or 0)
    base_periode = _base_periode_edi(base_periode)
    prorata_valeur = _prorata_edi(taux_prorata)
    try:
        collecte = collect_rd_lines(
            db,
            company,
            debut,
            fin,
            include_zero_vat=include_zero == "1",
            prorata=prorata_valeur,
            base_periode=base_periode,
        )
        xml = build_rd_xml(
            identifiant_fiscal=company.fiscal_id or "",
            annee=exercice,
            periode=periode,
            regime=regime,
            lignes=collecte["lignes"],
            tx_unit=tx_unit,
            declarant_nom=company.name,
            inclure_prorata=prorata == "1",
        )
        controle_taille(xml)
    except AccountingError as exc:
        return redirect_to("/tva/edi", f"Export impossible : {exc}", "error")
    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{xml_filename(exercice, periode, regime)}"'
        },
    )


# ---------------------------------------------------------------------------
# Parametres : societe, exercices, utilisateurs
# ---------------------------------------------------------------------------
@router.get("/parametres/societe", response_class=HTMLResponse)
def page_societe(
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return render(
        request,
        "parametres_societe.html",
        user=user,
        company=company,
        title="Fiche de la société",
        active="societe",
        societes=db.execute(select(Company).order_by(Company.id)).scalars().all(),
        total_comptes_plan=db.execute(
            select(func.count()).select_from(Account)
        ).scalar_one(),
        exercices=db.execute(
            select(FiscalYear).order_by(FiscalYear.year.desc())
        ).scalars().all(),
        annee_courante=date.today().year,
    )


@router.post("/parametres/societe")
def enregistrer_societe(
    request: Request,
    name: str = Form(...),
    legal_form: str = Form(""),
    ice: str = Form(""),
    fiscal_id: str = Form(""),
    rc: str = Form(""),
    patente: str = Form(""),
    cnss_number: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    vat_regime: str = Form("trimestriel"),
    require_ice: str = Form(""),
    year: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Cree la societe si elle n'existe pas, sinon met a jour sa fiche."""
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE")
    ):
        raise NotAuthorized()
    if company is None:
        company = Company(name=name.strip())
        db.add(company)
        db.flush()
    company.name = name.strip()
    company.legal_form = legal_form.strip() or None
    try:
        company.ice = validate_ice(ice)
        # IF : 7 ou 8 chiffres, utilise TEL QUEL (aucune transformation).
        company.fiscal_id = validate_fiscal_id(fiscal_id)
    except ComplianceError as exc:
        db.rollback()
        return redirect_to("/parametres/societe", f"Erreur : {exc}", "error")
    company.rc = rc.strip() or None
    company.patente = patente.strip() or None
    company.cnss_number = cnss_number.strip() or None
    company.address = address.strip() or None
    company.city = city.strip() or None
    company.phone = phone.strip() or None
    company.email = email.strip() or None
    company.vat_regime = (
        vat_regime if vat_regime in ("mensuel", "trimestriel") else "trimestriel"
    )
    company.require_ice = require_ice == "1"
    if year.isdigit():
        get_or_create_fiscal_year(db, company, int(year))
    db.commit()
    return redirect_to("/parametres/societe", "Fiche société enregistrée.")


@router.get("/parametres/exercices", response_class=HTMLResponse)
def page_exercices(
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    exercices = db.execute(
        select(FiscalYear)
        .where(FiscalYear.company_id == company.id)
        .order_by(FiscalYear.year.desc())
    ).scalars().all()
    stats = {}
    for exercice in exercices:
        debut, fin = year_bounds(exercice.year)
        stats[exercice.year] = {
            "ecritures": db.execute(
                select(func.count())
                .select_from(Entry)
                .where(
                    Entry.company_id == company.id,
                    Entry.entry_date >= debut,
                    Entry.entry_date <= fin,
                )
            ).scalar_one(),
            "documents": db.execute(
                select(func.count())
                .select_from(Invoice)
                .where(
                    Invoice.company_id == company.id,
                    Invoice.invoice_date >= debut,
                    Invoice.invoice_date <= fin,
                )
            ).scalar_one(),
        }
    return render(
        request,
        "parametres_exercices.html",
        user=user,
        company=company,
        title="Exercices comptables",
        active="exercices",
        exercices=exercices,
        stats=stats,
        annee_courante=date.today().year,
    )


@router.post("/parametres/exercices/nouveau")
def creer_exercice(
    year: int = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE")
    ):
        raise NotAuthorized()
    get_or_create_fiscal_year(db, company, year)
    db.commit()
    return redirect_to("/parametres/exercices", f"Exercice {year} ouvert.")


@router.post("/parametres/exercices/{year}/{statut}")
def changer_statut_exercice(
    year: int,
    statut: str,
    motif: str = Form(""),
    regenerer_a_nouveaux: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Change l'etat d'un exercice **par les services metier** (P1, A9/A10).

    - ``open`` : **reouverture encadree** (motif obligatoire, verrous verifies,
      impact sur N+1 restitue et regeneration des a-nouveaux demandee
      explicitement) ;
    - ``closed`` : clôture par le service (controle du bilan) ;
    - ``locked`` : verrouillage definitif trace d'un exercice clos.

    Aucun changement de statut n'est ecrit directement en base.
    """
    if company is None:
        return redirect_to("/parametres/societe", "Créez d'abord votre société.", "warning")
    if statut not in ("open", "closed", "locked"):
        return redirect_to("/parametres/exercices", "Statut invalide.", "error")
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE")
    ):
        raise NotAuthorized()
    exercice = selected_fiscal_year(db, company, year)
    if exercice is None:
        return redirect_to("/parametres/exercices", "Exercice introuvable.", "error")
    try:
        if statut == "open":
            resultat = cloture.reouvrir_exercice(
                db,
                company,
                year,
                motif=motif,
                user_id=user.id,
                regenerer_a_nouveaux=regenerer_a_nouveaux == "1",
            )
            db.commit()
            return redirect_to(
                "/parametres/exercices",
                f"Exercice {year} réouvert (motif tracé). Impact : "
                f"{resultat['impact_suivant']}.",
                "warning",
            )
        if statut == "closed":
            resultat = cloture.cloturer_exercice(db, company, year, user_id=user.id)
            db.commit()
            return redirect_to(
                "/parametres/exercices",
                f"Exercice {year} clôturé : résultat net "
                f"{format_amount(resultat['resultat_net'])} DH, à-nouveaux "
                f"{'générés' if resultat['a_nouveaux'] else 'non générés'}.",
            )
        resultat = cloture.verrouiller_exercice(
            db, company, year, motif=motif, user_id=user.id
        )
        db.commit()
        return redirect_to(
            "/parametres/exercices",
            f"Exercice {year} verrouillé définitivement (motif tracé).",
            "warning",
        )
    except AccountingError as exc:
        db.rollback()
        return redirect_to("/parametres/exercices", f"Opération refusée : {exc}", "error")


@router.get("/parametres/utilisateurs", response_class=HTMLResponse)
def page_utilisateurs(
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    utilisateurs = db.execute(select(User).order_by(User.id)).scalars().all()
    roles = db.execute(select(Role).order_by(Role.id)).scalars().all()
    return render(
        request,
        "parametres_utilisateurs.html",
        user=user,
        company=company,
        title="Utilisateurs & rôles",
        active="utilisateurs",
        utilisateurs=utilisateurs,
        roles=roles,
    )


@router.post("/parametres/utilisateurs")
def creer_compte_utilisateur(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(""),
    password: str = Form(...),
    roles: list[str] = Form(default=[]),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not user.is_superadmin and not user.role_codes.intersection(("ADMIN",)):
        raise NotAuthorized()
    if len(password) < 8:
        return redirect_to(
            "/parametres/utilisateurs",
            "Le mot de passe doit contenir au moins 8 caractères.",
            "error",
        )
    roles_choisis = tuple(roles) or ("COMPTABLE",)
    try:
        creer_utilisateur(
            db,
            email.strip().lower(),
            password,
            full_name=full_name.strip() or email.strip(),
            roles=roles_choisis,
            company=company,
            is_superadmin=False,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return redirect_to("/parametres/utilisateurs", f"Erreur : {exc}", "error")
    return redirect_to(
        "/parametres/utilisateurs",
        f"Utilisateur {email.strip()} créé avec le(s) rôle(s) {', '.join(roles_choisis)}.",
    )


# ---------------------------------------------------------------------------
# Documents PDF (etats de synthese, pieces, bordereaux) — jalon J1
# ---------------------------------------------------------------------------
def _reponse_pdf(pdf: bytes, nom_fichier: str) -> Response:
    """Reponse HTTP de telechargement d'un PDF (nom de fichier normalise)."""
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


def _societe_pdf(company: Company | None):
    """Controle commun : la fiche societe doit exister."""
    if company is None:
        return redirect_to(
            "/parametres/societe", "Créez d'abord votre société.", "warning"
        )
    return None


@router.get("/etats/bordereau-greffe/pdf")
def telecharger_bordereau_greffe(
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Bordereau et checklist du depot des etats de synthese au greffe (PDF)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    pdf = documents_pdf.pdf_bordereau_greffe(db, company, exercice)
    return _reponse_pdf(
        pdf,
        documents_pdf.nom_fichier_pdf("Bordereau_greffe", exercice, company.name),
    )


@router.get("/etats/{etat}/pdf")
def telecharger_etat_pdf(
    etat: str,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Telechargement PDF d'un etat de synthese : bilan, cpc, esg ou etic."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    generateurs = {
        "bilan": documents_pdf.pdf_bilan,
        "cpc": documents_pdf.pdf_cpc,
        "esg": documents_pdf.pdf_esg,
        "etic": documents_pdf.pdf_etic,
    }
    generateur = generateurs.get(etat.lower())
    if generateur is None:
        return redirect_to(
            f"/etats/bilan?year={exercice}", f"État PDF inconnu : {etat}", "error"
        )
    pdf = generateur(db, company, exercice)
    return _reponse_pdf(
        pdf, documents_pdf.nom_fichier_pdf(etat.upper(), exercice, company.name)
    )


@router.get("/factures/{invoice_id}/pdf")
def telecharger_facture_pdf(
    invoice_id: int,
    duplicata: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Facture au format PDF (mentions CGI art. 145, original ou duplicata)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    facture = db.get(Invoice, invoice_id)
    if facture is None or facture.company_id != company.id:
        return redirect_to("/factures", "Facture introuvable.", "error")
    try:
        pdf = documents_pdf.pdf_facture(db, facture, duplicata=duplicata == "1")
    except documents_pdf.DocumentIncoherentError as exc:
        return redirect_to(
            f"/factures/{invoice_id}", f"Document non généré : {exc}", "error"
        )
    return _reponse_pdf(
        pdf,
        documents_pdf.nom_fichier_pdf(
            "Facture",
            facture.number or f"brouillon-{facture.id}",
            "duplicata" if duplicata == "1" else "originale",
        ),
    )


@router.get("/tva/edi/bordereau/pdf")
def telecharger_bordereau_tva(
    year: int | None = Query(default=None),
    month: str = Query(default=""),
    quarter: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Bordereau recapitulatif du releve des deductions TVA (PDF, avant depot)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    debut, fin, libelle, exercice, month, quarter = _periode_edi(
        company, year, month, quarter
    )
    try:
        pdf = documents_pdf.pdf_bordereau_tva(
            db,
            company,
            exercice,
            month=int(month) if month else None,
            quarter=int(quarter) if quarter else None,
        )
    except AccountingError as exc:
        return redirect_to("/tva/edi", f"Bordereau impossible : {exc}", "error")
    return _reponse_pdf(
        pdf,
        documents_pdf.nom_fichier_pdf(
            "Bordereau_TVA", exercice, f"P{month or quarter or 0}", company.name
        ),
    )


# ---------------------------------------------------------------------------
# Immobilisations et amortissements (P1.2)
# ---------------------------------------------------------------------------
def _contexte_immobilisations(
    request: Request,
    *,
    user: User,
    company: Company,
    exercice: int,
    **extra: object,
) -> dict:
    """Contexte commun des ecrans d'immobilisations (statuts, methodes, controles)."""
    return {
        "user": user,
        "company": company,
        "exercice": exercice,
        "statuts": ASSET_STATUS_LABELS,
        "methodes": ASSET_METHOD_LABELS,
        **extra,
    }


@router.get("/immobilisations", response_class=HTMLResponse)
def page_immobilisations(
    request: Request,
    statut: str = Query(default=""),
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Liste des immobilisations : totaux, etat par poste et contrôles de cohérence."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    fiches = immobilisations.list_assets(db, company.id, statut=statut or None)
    etat = immobilisations.etat_immobilisations(db, company.id, exercice)
    controles = immobilisations.controles_immobilisations(db, company.id, exercice)
    return render(
        request,
        "immobilisations_liste.html",
        title="Immobilisations",
        active="immobilisations",
        **_contexte_immobilisations(
            request,
            user=user,
            company=company,
            exercice=exercice,
            fiches=fiches,
            etat=etat,
            controles=controles,
            statut=statut,
            vnc_par_fiche={
                fiche.id: immobilisations.valeur_nette_comptable(fiche)
                for fiche in fiches
            },
            bloquants=len([c for c in controles if c["niveau"] == "bloquant"]),
            avertissements=len([c for c in controles if c["niveau"] == "avertissement"]),
        ),
    )


@router.get("/immobilisations/etats", response_class=HTMLResponse)
def page_etats_immobilisations(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Etats du module : immobilisations, amortissements déductibles, cessions."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    return render(
        request,
        "immobilisations_etats.html",
        title="Etats des immobilisations",
        active="immobilisations-etats",
        **_contexte_immobilisations(
            request,
            user=user,
            company=company,
            exercice=exercice,
            etat=immobilisations.etat_immobilisations(db, company.id, exercice),
            amortissements=immobilisations.amortissements_deductibles(
                db, company.id, exercice
            ),
            cessions=immobilisations.tableau_cessions(db, company.id, exercice),
            controles=immobilisations.controles_immobilisations(db, company.id, exercice),
        ),
    )


@router.get("/immobilisations/etat/pdf")
def telecharger_etat_immobilisations(
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Etat des immobilisations (brut / amortissements / net) au format PDF."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    pdf = documents_pdf.pdf_etat_immobilisations(db, company, exercice)
    return _reponse_pdf(
        pdf, documents_pdf.nom_fichier_pdf("Etat_immobilisations", exercice, company.name)
    )


@router.get("/immobilisations/cessions/pdf")
def telecharger_tableau_cessions(
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Tableau des cessions de l'exercice au format PDF."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    pdf = documents_pdf.pdf_tableau_cessions(db, company, exercice)
    return _reponse_pdf(
        pdf, documents_pdf.nom_fichier_pdf("Cessions", exercice, company.name)
    )



@router.get("/immobilisations/nouvelle", response_class=HTMLResponse)
def formulaire_immobilisation(
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Formulaire de création d'une fiche d'immobilisation."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    comptes = list(
        db.execute(
            select(Account.number, Account.label)
            .where(
                Account.number.like("2%"),
                ~Account.number.like("28%"),
                ~Account.number.like("29%"),
            )
            .order_by(Account.number)
        ).all()
    )
    return render(
        request,
        "immobilisations_formulaire.html",
        title="Nouvelle immobilisation",
        active="immobilisations",
        **_contexte_immobilisations(
            request,
            user=user,
            company=company,
            exercice=date.today().year,
            comptes=comptes,
            tva_immo=settings.vat_deductible_asset_account,
            prorata_defaut=settings.immo_prorata_temporis,
            coefficients={
                "court": settings.coefficient_degressif_court,
                "moyen": settings.coefficient_degressif_moyen,
                "long": settings.coefficient_degressif_long,
            },
        ),
    )


@router.post("/immobilisations/nouvelle")
def creer_immobilisation_web(
    label: str = Form(...),
    account_number: str = Form(...),
    acquisition_date: str = Form(...),
    service_date: str = Form(""),
    valeur_origine: str = Form(...),
    valeur_residuelle: str = Form("0"),
    duree_annees: str = Form("0"),
    mode: str = Form("lineaire"),
    coefficient: str = Form(""),
    prorata_temporis: str = Form(""),
    tva_montant: str = Form("0"),
    comptabiliser: str = Form(""),
    compte_contrepartie: str = Form(""),
    third_party_id: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Enregistre une fiche d'immobilisation (et son écriture d'acquisition si demandé)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection

    def _jour(valeur: str) -> date | None:
        valeur = (valeur or "").strip()
        if not valeur:
            return None
        try:
            return date.fromisoformat(valeur)
        except ValueError as exc:
            raise AccountingError(f"Date invalide : {valeur}") from exc

    try:
        fiche = immobilisations.creer_immobilisation(
            db,
            company=company,
            label=label,
            account_number=account_number.strip(),
            acquisition_date=_jour(acquisition_date),
            service_date=_jour(service_date),
            valeur_origine=safe_float(valeur_origine, 0),
            valeur_residuelle=safe_float(valeur_residuelle, 0),
            duree_annees=int(safe_float(duree_annees, 0)),
            mode=mode,
            coefficient=safe_float(coefficient, 0) or None,
            prorata_temporis=(
                True if prorata_temporis == "1" else False
            ),
            tva_montant=safe_float(tva_montant, 0),
            third_party_id=int(third_party_id) if third_party_id.strip().isdigit() else None,
            notes=notes.strip() or None,
            user_id=user.id,
            comptabiliser=comptabiliser == "1",
            compte_contrepartie=compte_contrepartie.strip() or None,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/immobilisations/nouvelle", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/immobilisations/{fiche.code}",
        f"Immobilisation {fiche.code} créée au compte {fiche.account_number}.",
    )


@router.post("/immobilisations/dotations")
def comptabiliser_dotations_web(
    year: int = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Constate en une action les dotations de toutes les immobilisations en service."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        resultats = immobilisations.comptabiliser_dotations(
            db, company, year, user_id=user.id
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to(
            f"/immobilisations?year={year}", f"Erreur : {exc}", "error"
        )
    comptabilisees = [r for r in resultats if r["erreur"] is None]
    erreurs = [r for r in resultats if r["erreur"] is not None]
    niveau = "warning" if erreurs else "success"
    return redirect_to(
        f"/immobilisations?year={year}",
        f"Dotations {year} : {len(comptabilisees)} écriture(s) validée(s)"
        + (f", {len(erreurs)} fiche(s) en erreur." if erreurs else "."),
        niveau,
    )



@router.get("/immobilisations/{code}", response_class=HTMLResponse)
def fiche_immobilisation(
    code: str,
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Fiche d'immobilisation : plan, journal des mouvements, actions (dotation, sortie)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        fiche = immobilisations.get_asset(db, company.id, code)
    except AccountingError as exc:
        return redirect_to("/immobilisations", f"Erreur : {exc}", "error")
    exercice = date.today().year
    return render(
        request,
        "immobilisations_fiche.html",
        title=f"Immobilisation {fiche.code}",
        active="immobilisations",
        **_contexte_immobilisations(
            request,
            user=user,
            company=company,
            exercice=exercice,
            fiche=fiche,
            plan=immobilisations.plan_amortissement(fiche),
            comptes=immobilisations.comptes_immobilisation(db, fiche.account_number),
            cumul=immobilisations.amortissements_cumules(fiche),
            vnc=immobilisations.valeur_nette_comptable(fiche),
            dotation_annee=(
                immobilisations.dotation_constatee(fiche, exercice)
                or immobilisations.dotation_exercice(fiche, exercice)
            ),
            regularisation=immobilisations.regularisation_tva_art106(
                fiche, date(exercice, 12, 31)
            ),
            jour=date.today(),
        ),
    )


@router.get("/immobilisations/{code}/plan/pdf")
def telecharger_plan_amortissement(
    code: str,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Plan d'amortissement d'une immobilisation au format PDF."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        fiche = immobilisations.get_asset(db, company.id, code)
    except AccountingError as exc:
        return redirect_to("/immobilisations", f"Erreur : {exc}", "error")
    pdf = documents_pdf.pdf_plan_amortissement(db, company, fiche)
    return _reponse_pdf(
        pdf, documents_pdf.nom_fichier_pdf("Plan_amortissement", fiche.code)
    )



@router.post("/immobilisations/{code}/doter")
def doter_immobilisation(
    code: str,
    exercice: int = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Constate la dotation aux amortissements d'un exercice (6193x / 283x)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        fiche = immobilisations.get_asset(db, company.id, code)
        operation = immobilisations.comptabiliser_dotation(
            db, fiche, exercice, user_id=user.id
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to(f"/immobilisations/{code}", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/immobilisations/{code}",
        f"Dotation {exercice} constatée : {format_amount(operation['annuite'])} DH "
        f"({operation['compte_dotation']} / {operation['compte_amortissement']}), "
        f"écriture {operation['entry_number']}.",
    )


@router.post("/immobilisations/{code}/ceder")
def ceder_immobilisation_web(
    code: str,
    date_cession: str = Form(...),
    prix: str = Form(...),
    tva_taux: str = Form("0"),
    compte_encaissement: str = Form(""),
    regulariser_tva: str = Form("1"),
    motif: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Cède une immobilisation : produit, sortie d'actif et régularisation art. 106."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        fiche = immobilisations.get_asset(db, company.id, code)
        resultat = immobilisations.ceder_immobilisation(
            db,
            fiche,
            date_cession=date.fromisoformat(date_cession),
            prix=safe_float(prix, 0),
            tva_taux=safe_float(tva_taux, 0),
            compte_encaissement=compte_encaissement.strip() or None,
            regulariser_tva=regulariser_tva == "1",
            motif=motif.strip() or None,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to(f"/immobilisations/{code}", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/immobilisations/{code}",
        f"Cession enregistrée (écriture {resultat['entry_number']}) : VNC "
        f"{format_amount(resultat['vnc'])} DH, résultat "
        f"{format_amount(resultat['resultat_cession'])} DH, TVA régularisée "
        f"{format_amount(resultat['regularisation']['montant'])} DH.",
    )


@router.post("/immobilisations/{code}/rebut")
def rebut_immobilisation(
    code: str,
    date_rebut: str = Form(...),
    motif: str = Form(...),
    regulariser_tva: str = Form("1"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Met une immobilisation au rebut (sortie d'actif sans contrepartie)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        fiche = immobilisations.get_asset(db, company.id, code)
        resultat = immobilisations.mettre_au_rebut(
            db,
            fiche,
            date_rebut=date.fromisoformat(date_rebut),
            motif=motif,
            regulariser_tva=regulariser_tva == "1",
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to(f"/immobilisations/{code}", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/immobilisations/{code}",
        f"Mise au rebut enregistrée (écriture {resultat['entry_number']}) : VNC "
        f"{format_amount(resultat['vnc'])} DH.",
    )



# ---------------------------------------------------------------------------
# Audit & tracabilite (P1.6) : journal, piste fiable, rapprochement bancaire
# ---------------------------------------------------------------------------
@router.get("/audit", response_class=HTMLResponse)
def page_audit(
    request: Request,
    action: str = Query(default=""),
    entity: str = Query(default=""),
    user_id: str = Query(default=""),
    search: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Journal d'audit : filtres, export CSV et controle de la piste fiable."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection

    def _jour(valeur: str) -> date | None:
        try:
            return date.fromisoformat(valeur) if valeur else None
        except ValueError:
            return None

    entrees = piste.journal_audit(
        db,
        company_id=company.id,
        action=action or None,
        entity=entity or None,
        user_id=int(user_id) if user_id.isdigit() else None,
        search=search or None,
        date_from=_jour(date_from),
        date_to=_jour(date_to),
        limit=300,
    )
    return render(
        request,
        "audit_journal.html",
        user=user,
        company=company,
        title="Journal d'audit",
        active="audit",
        entrees=entrees,
        actions=piste.actions_journal(db, company.id),
        utilisateurs=piste.utilisateurs_journal(db, company.id),
        filtre={
            "action": action,
            "entity": entity,
            "user_id": user_id,
            "search": search,
            "date_from": date_from,
            "date_to": date_to,
        },
        controle=piste.verifier_chainage(db, company.id),
        alertes=banking.alertes_ecarts_anciens(db, company.id),
        nb_entrees=len(entrees),
    )


@router.get("/audit/export")
def exporter_journal(
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Export CSV du journal d'audit (donnees personnelles masquees — loi 09-08)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    contenu = piste.export_journal_csv(db, company_id=company.id)
    return Response(
        content=contenu.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="journal_audit.csv"'},
    )


@router.post("/audit/sceller")
def sceller_la_piste(
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Scelle les ecritures validees anterieures a la piste d'audit (reprise de dossier)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE")
    ):
        raise NotAuthorized()
    resultat = piste.sceller_ecritures(db, company.id)
    db.commit()
    return redirect_to(
        "/audit",
        f"Piste d'audit : {resultat['nb_scellees']} écriture(s) scellée(s) sur "
        f"{resultat['total_ecritures']}.",
    )



@router.get("/rapprochement", response_class=HTMLResponse)
def page_rapprochement(
    request: Request,
    releve_id: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Rapprochement bancaire : relevés, appariement et état de rapprochement."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    releves = list(
        db.execute(
            select(BankStatement)
            .where(BankStatement.company_id == company.id)
            .order_by(BankStatement.date_to.desc())
        ).scalars()
    )
    courant = None
    if releve_id is not None:
        courant = next((r for r in releves if r.id == releve_id), None)
    elif releves:
        courant = releves[0]
    return render(
        request,
        "rapprochement_bancaire.html",
        user=user,
        company=company,
        title="Rapprochement bancaire",
        active="rapprochement",
        releves=releves,
        courant=courant,
        etat=banking.etat_rapprochement(db, courant) if courant else None,
        a_rapprocher=banking.lignes_a_rapprocher(db, courant) if courant else [],
        comptes_tresorerie=list(
            db.execute(
                select(Account.number, Account.label)
                .where(Account.number.like("51%"))
                .order_by(Account.number)
            ).all()
        ),
        alertes=banking.alertes_ecarts_anciens(db, company.id),
    )


@router.post("/rapprochement/importer")
def importer_releve_web(
    account_number: str = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    closing_balance: str = Form("0"),
    opening_balance: str = Form("0"),
    contenu: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Importe un relevé collé au format CSV normalisé (point-virgule)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        lignes = banking.parser_csv_releve(contenu)
        releve = banking.importer_releve(
            db,
            company=company,
            account_number=account_number,
            date_from=date.fromisoformat(date_from),
            date_to=date.fromisoformat(date_to),
            opening_balance=safe_float(opening_balance, 0),
            closing_balance=safe_float(closing_balance, 0),
            lignes=lignes,
            file_name="saisie manuelle",
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/rapprochement", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/rapprochement?releve_id={releve.id}",
        f"Relevé importé : {len(releve.lines)} ligne(s).",
    )


@router.post("/rapprochement/{releve_id}/auto")
def rapprochement_automatique_web(
    releve_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Apparie automatiquement les lignes du relevé (montant exact, date proche)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    releve = db.get(BankStatement, releve_id)
    if releve is None or releve.company_id != company.id:
        return redirect_to("/rapprochement", "Relevé introuvable.", "error")
    resultat = banking.rapprocher_automatiquement(db, releve, user_id=user.id)
    db.commit()
    return redirect_to(
        f"/rapprochement?releve_id={releve.id}",
        f"Appariement automatique : {resultat['nb_rapprochees']} ligne(s) rapprochée(s), "
        f"{resultat['nb_restantes']} restante(s).",
    )



@router.post("/rapprochement/lignes/{ligne_id}/rapprocher")
def rapprocher_ligne_web(
    ligne_id: int,
    entry_line_id: str = Form(""),
    motif: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Rapproche (ou ajuste) une ligne de relevé avec une écriture de trésorerie."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    ligne = db.get(BankStatementLine, ligne_id)
    if ligne is None:
        return redirect_to("/rapprochement", "Ligne de relevé introuvable.", "error")
    releve = db.get(BankStatement, ligne.statement_id)
    if releve is None or releve.company_id != company.id:
        return redirect_to("/rapprochement", "Ligne hors dossier.", "error")
    ecriture = db.get(EntryLine, int(entry_line_id)) if entry_line_id.isdigit() else None
    try:
        banking.rapprocher(
            db,
            ligne,
            ecriture,
            type_rapprochement="rapproche" if ecriture is not None else "ajustement",
            motif=motif or None,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to(
            f"/rapprochement?releve_id={releve.id}", f"Erreur : {exc}", "error"
        )
    return redirect_to(f"/rapprochement?releve_id={releve.id}", "Ligne rapprochée.")


@router.post("/rapprochement/lignes/{ligne_id}/de-rapprocher")
def de_rapprocher_ligne_web(
    ligne_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Annule le rapprochement d'une ligne de relevé."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    ligne = db.get(BankStatementLine, ligne_id)
    if ligne is None:
        return redirect_to("/rapprochement", "Ligne de relevé introuvable.", "error")
    releve_id = ligne.statement_id
    try:
        banking.de_rapprocher(db, ligne, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to(
            f"/rapprochement?releve_id={releve_id}", f"Erreur : {exc}", "error"
        )
    return redirect_to(f"/rapprochement?releve_id={releve_id}", "Rapprochement annulé.")



# ---------------------------------------------------------------------------
# Cloture d'exercice et verrouillage de periode (P1.6 — ecart 9)
# ---------------------------------------------------------------------------
@router.post("/parametres/exercices/{year}/cloturer")
def cloturer_exercice_web(
    year: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Clôture l'exercice et génère les **à-nouveaux** de l'exercice suivant (écart 9)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE")
    ):
        raise NotAuthorized()
    try:
        resultat = cloture.cloturer_exercice(db, company, year, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to("/parametres/exercices", f"Erreur : {exc}", "error")
    a_nouveaux = resultat.get("a_nouveaux") or {}
    message = (
        f"Exercice {year} clôturé (résultat "
        f"{format_amount(resultat['resultat_net'])} DH)."
    )
    if a_nouveaux.get("genere"):
        message += (
            f" À-nouveaux {a_nouveaux['exercice_cible']} générés : écriture "
            f"{a_nouveaux['entry_number']} ({a_nouveaux['nb_lignes']} lignes, "
            f"{format_amount(a_nouveaux['total_debit'])} DH)."
        )
    elif a_nouveaux:
        message += f" À-nouveaux non générés : {a_nouveaux.get('motif', '')}"
    return redirect_to("/parametres/exercices", message)


@router.post("/parametres/exercices/{year}/verrouiller")
def verrouiller_periode_web(
    year: int,
    periode: str = Form(""),
    motif: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Verrouille un mois (1-12) ou l'exercice entier : plus aucune saisie possible."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE")
    ):
        raise NotAuthorized()
    try:
        verrou = verrous.verrouiller_periode(
            db,
            company_id=company.id,
            year=year,
            periode=int(periode) if periode.strip() else None,
            motif=motif.strip() or None,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/parametres/exercices", f"Erreur : {exc}", "error")
    return redirect_to(
        "/parametres/exercices",
        f"Verrouillage posé sur {verrou.libelle} de l'exercice {year} : saisie interdite.",
    )


@router.post("/parametres/verrous/{lock_id}/deverrouiller")
def deverrouiller_periode_web(
    lock_id: int,
    motif: str = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Déverrouille une période (ADMIN / EXPERT_COMPTABLE, avec motif tracé)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    if not user.is_superadmin and not user.role_codes.intersection(
        ("ADMIN", "EXPERT_COMPTABLE")
    ):
        raise NotAuthorized()
    verrou = db.get(PeriodLock, lock_id)
    if verrou is None or verrou.company_id != company.id:
        return redirect_to("/parametres/exercices", "Verrou introuvable.", "error")
    try:
        verrous.deverrouiller_periode(db, verrou, motif=motif, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        return redirect_to("/parametres/exercices", f"Erreur : {exc}", "error")
    return redirect_to("/parametres/exercices", "Période déverrouillée (motif tracé).")



# ---------------------------------------------------------------------------
# Stocks et inventaire permanent (P1.3)
# ---------------------------------------------------------------------------
@router.get("/stocks", response_class=HTMLResponse)
def page_stocks(
    request: Request,
    year: int | None = Query(default=None),
    sous_seuil: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Etat de stock valorise (CMUP/FIFO), alertes de seuil et controles du module."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    return render(
        request,
        "stocks_liste.html",
        user=user,
        company=company,
        title="Stocks",
        active="stocks",
        exercice=exercice,
        etat=magasin.etat_stocks(db, company.id, sous_seuil=sous_seuil == "1"),
        articles=magasin.list_items(db, company.id),
        methodes=VALUATION_METHOD_LABELS,
        controles=magasin.controles_stocks(db, company.id, exercice),
        variation=magasin.variation_stocks(db, company.id, exercice),
        sous_seuil=sous_seuil,
    )


@router.post("/stocks/article")
def creer_article_web(
    reference: str = Form(...),
    label: str = Form(...),
    stock_account: str = Form("3111"),
    unit: str = Form("U"),
    family: str = Form(""),
    valuation_method: str = Form("cmup"),
    alert_threshold: str = Form("0"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Cree une fiche article (compte de stock 3xxx, methode de valorisation)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        article = magasin.creer_article(
            db,
            company=company,
            reference=reference,
            label=label,
            stock_account=stock_account,
            unit=unit,
            family=family.strip() or None,
            valuation_method=valuation_method,
            alert_threshold=safe_float(alert_threshold, 0),
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/stocks", f"Erreur : {exc}", "error")
    return redirect_to(
        "/stocks",
        f"Article {article.reference} créé (compte {article.stock_account}, "
        f"{magasin.VALUATION_METHOD_LABELS.get(article.valuation_method, '')}).",
    )


@router.post("/stocks/{reference}/mouvement")
def mouvement_stock_web(
    reference: str,
    movement_date: str = Form(...),
    movement_type: str = Form("entree"),
    quantity: str = Form(...),
    unit_cost: str = Form(""),
    reason: str = Form("achat"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Enregistre une entree ou une sortie valorisee (CMUP/FIFO) et son ecriture."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        article = magasin.get_item(db, company.id, reference)
        mouvement = magasin.enregistrer_mouvement(
            db,
            article=article,
            movement_date=date.fromisoformat(movement_date),
            movement_type=movement_type,
            quantity=safe_float(quantity, 0),
            unit_cost=safe_float(unit_cost, 0) if unit_cost.strip() else None,
            reason=reason,
            user_id=user.id,
        )
        operation = magasin.comptabiliser_mouvement(db, mouvement, user_id=user.id)
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/stocks", f"Erreur : {exc}", "error")
    return redirect_to(
        "/stocks",
        f"{'Entrée' if mouvement.quantity > 0 else 'Sortie'} de "
        f"{abs(mouvement.quantity)} {article.unit} sur {article.reference} : "
        f"{format_amount(abs(mouvement.value))} DH (écriture {operation['entry_number']}).",
    )


@router.post("/stocks/stock-final")
def stock_final_web(
    exercice: int = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Constate le stock final et la variation (regime intermittent, 3111 / 6114)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        resultat = magasin.constater_stock_final(db, company, exercice, user_id=user.id)
        db.commit()
    except (AccountingError, ValueError) as exc:
        db.rollback()
        return redirect_to("/stocks", f"Erreur : {exc}", "error")
    if not resultat["genere"]:
        return redirect_to(
            "/stocks", f"Stock final {exercice} : {resultat['motif']}", "warning"
        )
    return redirect_to(
        "/stocks",
        f"Stock final {exercice} constaté : écriture {resultat['entry_number']} "
        f"(écart {format_amount(resultat['total_ecart'])} DH).",
    )


# ---------------------------------------------------------------------------
# Depot au greffe du tribunal (P1.5)
# ---------------------------------------------------------------------------
@router.get("/greffe", response_class=HTMLResponse)
def page_greffe(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Dossier de depot au greffe : checklist, controles, suivi des 7 etats."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    depot = depot_greffe.depot_par_exercice(db, company.id, exercice)
    return render(
        request,
        "greffe_dossier.html",
        user=user,
        company=company,
        title="Dépôt au greffe",
        active="greffe",
        exercice=exercice,
        depot=depot,
        etats=depot_greffe.GREFFE_ETAT_LABELS,
        etats_possibles=(
            [
                (code, depot_greffe.GREFFE_ETAT_LABELS[code])
                for code in depot_greffe.GREFFE_TRANSITIONS.get(depot.statut, ())
            ]
            if depot is not None
            else []
        ),
        moyens=depot_greffe.GREFFE_MOYEN_LABELS,
        catalogue=depot_greffe.checklist(db, depot) if depot else [],
        pieces_disponibles=depot_greffe.CATALOGUE_PIECES if depot else [],
        completude=depot_greffe.taux_completude(db, depot) if depot else None,
        controles=depot_greffe.controles_depot(db, depot) if depot else [],
        alertes=depot_greffe.alertes_depot(db, depot) if depot else [],
        taxes=(
            {
                "montant": depot.montant_taxes,
                "paye": depot_greffe.total_paye(db, depot),
                "solde": depot_greffe.solde_taxes(db, depot),
            }
            if depot
            else None
        ),
        journal=list(depot.events) if depot else [],
        dossiers=depot_greffe.list_depots(db, company.id),
        formes=depot_greffe.FORMES_SUPPORTEES,
        portail=depot_greffe.URL_PORTAIL,
    )


@router.post("/greffe/dossier")
def creer_dossier_greffe_web(
    exercice: int = Form(...),
    forme_juridique: str = Form(""),
    date_ag: str = Form(""),
    montant_taxes: str = Form("0"),
    notes: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Cree le dossier de depot de l'exercice (date limite : cloture + 6 mois)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        depot = depot_greffe.creer_depot(
            db,
            company=company,
            exercice=exercice,
            user_id=user.id,
            forme_juridique=forme_juridique or None,
            date_ag=date.fromisoformat(date_ag) if date_ag else None,
            montant_taxes=montant_taxes or "0",
            notes=notes or None,
        )
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/greffe?year={depot.exercice}",
        f"Dossier {depot.exercice} créé (forme {depot.forme_juridique}) — date limite "
        f"d'AG et de dépôt : {depot.date_limite_depot.strftime('%d/%m/%Y')}.",
    )


def _dossier_web(
    db: Session, company: Company, deposit_id: int
):
    """Retrouve un dossier de depot en le cloisonnant a la societe active."""
    try:
        return depot_greffe.get_depot(db, company.id, deposit_id), None
    except depot_greffe.GreffeError as exc:
        return None, redirect_to("/greffe", f"Erreur : {exc}", "error")


@router.post("/greffe/{deposit_id}/pieces/generer")
def generer_pieces_greffe_web(
    deposit_id: int,
    date_ag: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Genere les pieces produites par l'application (etats, bordereau, rapport, PV).

    Le **rapport de gestion** et le **PV d'AG** sont rediges a partir des comptes
    de l'exercice (P1 greffe) : la **date d'assemblée générale** est obligatoire
    (formulaire ou date deja enregistree sur le dossier) — elle est reportee sur
    le PV.
    """
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        date_assemblee = date.fromisoformat(date_ag) if date_ag.strip() else None
    except ValueError:
        return redirect_to("/greffe", f"Date d'AG invalide : « {date_ag} ».", "error")
    try:
        resultat = depot_greffe.generer_pieces(
            db, depot, company=company, user_id=user.id, date_ag=date_assemblee
        )
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/greffe?year={depot.exercice}",
        f"{len(resultat['documents'])} pièce(s) générée(s) : "
        + ", ".join(document.nom_fichier for document in resultat["documents"]),
    )


@router.post("/greffe/{deposit_id}/pieces")
def televerser_piece_greffe_web(
    deposit_id: int,
    piece_code: str = Form(...),
    fichier: UploadFile = File(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Televerse une piece PDF du dossier (controle 10 Mo du portail)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        document = depot_greffe.ajouter_piece(
            db,
            depot,
            piece_code=piece_code,
            nom_fichier=fichier.filename,
            contenu=fichier.file.read(),
            user_id=user.id,
        )
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/greffe?year={depot.exercice}",
        f"Pièce « {document.libelle} » archivée "
        f"({depot_greffe.taille_lisible(document.taille_octets)}, "
        f"SHA-256 {document.hash_sha256[:16]}…).",
    )


@router.post("/greffe/{deposit_id}/pieces/{piece_code}/supprimer")
def supprimer_piece_greffe_web(
    deposit_id: int,
    piece_code: str,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Retire une piece du dossier (fichier archive et ligne)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        supprime = depot_greffe.supprimer_piece(db, depot, piece_code, user_id=user.id)
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    if not supprime:
        return redirect_to("/greffe", "Pièce introuvable dans ce dossier.", "warning")
    return redirect_to(f"/greffe?year={depot.exercice}", "Pièce retirée du dossier.")


@router.post("/greffe/{deposit_id}/etat")
def changer_etat_greffe_web(
    deposit_id: int,
    etat: str = Form(...),
    motif: str = Form(""),
    forcer: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Fait evoluer le dossier dans les 7 etats du portail (transitions controlees)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        depot_greffe.changer_etat(
            db,
            depot,
            etat,
            motif=motif or None,
            user_id=user.id,
            forcer_hors_delai=forcer == "1",
        )
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/greffe?year={depot.exercice}",
        f"Dossier {depot.exercice} : état « {depot.etat_libelle} » enregistré.",
    )


@router.post("/greffe/{deposit_id}/paiement")
def paiement_greffe_web(
    deposit_id: int,
    montant: str = Form(...),
    moyen: str = Form("cmi"),
    reference: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Enregistre le paiement des taxes (delai de 3 jours des l'approbation)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        depot_greffe.enregistrer_paiement(
            db,
            depot,
            montant=montant,
            moyen=moyen,
            reference=reference or None,
            user_id=user.id,
        )
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    solde = depot_greffe.solde_taxes(db, depot)
    return redirect_to(
        f"/greffe?year={depot.exercice}",
        f"Paiement de {format_amount(montant)} DH enregistré — reste à payer "
        f"{format_amount(solde)} DH.",
    )


@router.post("/greffe/{deposit_id}/certificat")
def certificat_greffe_web(
    deposit_id: int,
    fichier: UploadFile = File(...),
    reference: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Archive le certificat de depot signe (preuve legale, SHA-256 en base)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        depot_greffe.enregistrer_certificat(
            db,
            depot,
            nom_fichier=fichier.filename,
            contenu=fichier.file.read(),
            reference=reference or None,
            user_id=user.id,
        )
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/greffe?year={depot.exercice}",
        f"Certificat de dépôt archivé (SHA-256 {depot.certificat_hash[:16]}…).",
    )


@router.post("/greffe/{deposit_id}/amende")
def amende_greffe_web(
    deposit_id: int,
    montant: str = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Provisionne l'amende hors delai (dotation 6195 / provision 1515)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        resultat = depot_greffe.comptabiliser_amende(
            db, company, depot, montant=montant, user_id=user.id
        )
        db.commit()
    except (depot_greffe.GreffeError, ValueError) as exc:
        db.rollback()
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/greffe?year={depot.exercice}",
        f"Amende provisionnée : écriture {resultat['entry_number']} "
        f"({format_amount(resultat['montant'])} DH en 6195 / 1515).",
    )


@router.get("/greffe/{deposit_id}/dossier")
def telecharger_dossier_greffe_web(
    deposit_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Archive ZIP du dossier (pieces PDF + bordereau + manifeste des empreintes)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        archive = depot_greffe.assembler_dossier(db, company, depot)
    except (depot_greffe.GreffeError, ValueError) as exc:
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="Dossier_greffe_{depot.exercice}.zip"'
            )
        },
    )


@router.get("/greffe/{deposit_id}/bordereau.pdf")
def bordereau_greffe_web(
    deposit_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Bordereau recapitulatif du dossier (PDF)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    return _reponse_pdf(
        depot_greffe.pdf_recapitulatif_dossier(db, company, depot),
        f"Bordereau_greffe_{depot.exercice}.pdf",
    )


@router.get("/greffe/{deposit_id}/attestation.pdf")
def attestation_greffe_web(
    deposit_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Attestation de paiement des taxes (PDF)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    return _reponse_pdf(
        depot_greffe.pdf_attestation_paiement(db, company, depot),
        f"Attestation_paiement_taxes_{depot.exercice}.pdf",
    )


@router.get("/greffe/{deposit_id}/certificat.pdf")
def certificat_pdf_greffe_web(
    deposit_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Telechargement du certificat de depot archive."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    depot, erreur = _dossier_web(db, company, deposit_id)
    if erreur is not None:
        return erreur
    try:
        contenu = depot_greffe.lire_certificat(depot)
    except depot_greffe.GreffeError as exc:
        return redirect_to("/greffe", f"Erreur : {exc}", "error")
    return _reponse_pdf(contenu, depot.certificat_nom or "certificat_depot.pdf")


# ---------------------------------------------------------------------------
# Paie et DTS « 9421 » (P1.4)
# ---------------------------------------------------------------------------
@router.get("/paie", response_class=HTMLResponse)
def page_paie(
    request: Request,
    year: int | None = Query(default=None),
    periode: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Paie : salaries, bulletins du mois, ecriture, etats et DTS « 9421 »."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    periode = periode or f"{exercice}-01"
    run = paie.get_run(db, company.id, periode)
    try:
        dts_modele = edi_dts.construire_dts(db, company, exercice)
    except edi_dts.DtsError:
        dts_modele = None
    return render(
        request,
        "paie_liste.html",
        user=user,
        company=company,
        title="Paie",
        active="paie",
        exercice=exercice,
        periode=periode,
        employes=paie.list_employes(db, company.id, actifs_seulement=False),
        run=run,
        bulletins=paie.list_bulletins(db, run) if run else [],
        controles=paie.controles_paie(db, company.id, periode),
        livre=paie.livre_de_paie(db, company.id, exercice),
        cotisations=paie.etat_cotisations(db, company.id, exercice),
        dts=dts_modele,
        dts_declarations=edi_dts.list_declarations(db, company.id),
        contrats=paie.CONTRAT_LABELS,
        situations=paie.SITUATION_LABELS,
        paiements=paie.PAIEMENT_PAIE_LABELS,
    )


@router.post("/paie/salarie")
def creer_salarie_web(
    matricule: str = Form(...),
    nom: str = Form(...),
    date_entree: str = Form(...),
    cin: str = Form(""),
    cnss: str = Form(""),
    situation_familiale: str = Form("celibataire"),
    enfants: int = Form(0),
    type_contrat: str = Form("cdi"),
    fonction: str = Form(""),
    salaire_base: str = Form("0"),
    exoneration: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Cree la fiche salarie et son premier element contractuel de remuneration."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        employe = paie.creer_employe(
            db,
            company=company,
            matricule=matricule,
            nom=nom,
            date_entree=date.fromisoformat(date_entree),
            cin=cin or None,
            cnss=cnss or None,
            situation_familiale=situation_familiale,
            enfants=enfants,
            type_contrat=type_contrat,
            fonction=fonction or None,
            exoneration_art_57_20=exoneration == "1",
            user_id=user.id,
        )
        if Decimal(salaire_base or "0") > 0:
            paie.ajouter_contrat(
                db,
                employe,
                salaire_base=salaire_base,
                date_effet=date.fromisoformat(date_entree),
                user_id=user.id,
            )
        db.commit()
    except (paie.PayrollError, ValueError) as exc:
        db.rollback()
        return redirect_to("/paie", f"Erreur : {exc}", "error")
    return redirect_to(
        "/paie",
        f"Salarié {employe.matricule} créé ({employe.personnes_a_charge} personne(s) "
        "à charge).",
    )


@router.post("/paie/preparer")
def preparer_paie_web(
    periode: str = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Prepare (calcule) la paie de la periode demandee."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    try:
        run = paie.preparer_paie(db, company, periode, user_id=user.id)
        db.commit()
    except (paie.PayrollError, ValueError) as exc:
        db.rollback()
        return redirect_to("/paie", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/paie?periode={periode}",
        f"Paie {periode} préparée : {len(paie.list_bulletins(db, run))} bulletin(s), "
        f"net {format_amount(run.total_net)} DH.",
    )


@router.post("/paie/valider")
def valider_paie_web(
    periode: str = Form(...),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Valide la paie : ecriture globale (equilibre controle) et bulletins figes."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    run = paie.get_run(db, company.id, periode)
    if run is None:
        return redirect_to("/paie", f"Aucune paie préparée pour {periode}.", "warning")
    try:
        ecriture = paie.valider_paie(db, run, user_id=user.id)
        db.commit()
    except (paie.PayrollError, ValueError) as exc:
        db.rollback()
        return redirect_to("/paie", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/paie?periode={periode}",
        f"Paie {periode} validée : écriture {ecriture.entry_number} "
        f"({format_amount(run.total_brut)} DH de brut).",
    )


@router.post("/paie/payer")
def payer_paie_web(
    periode: str = Form(...),
    mode: str = Form("virement"),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Regle le net a payer (virement 5141 ou caisse 5161)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    run = paie.get_run(db, company.id, periode)
    if run is None:
        return redirect_to("/paie", f"Aucune paie préparée pour {periode}.", "warning")
    try:
        ecriture = paie.payer_paie(db, run, mode=mode, user_id=user.id)
        db.commit()
    except (paie.PayrollError, ValueError) as exc:
        db.rollback()
        return redirect_to("/paie", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/paie?periode={periode}",
        f"Salaires réglés par {mode} : écriture {ecriture.entry_number} "
        f"({format_amount(run.total_net)} DH).",
    )


@router.get("/paie/bulletin/{payslip_id}/pdf")
def bulletin_pdf_web(
    payslip_id: int,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Bulletin de paie (PDF, gabarit P1.1)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    bulletin = db.get(Payslip, payslip_id)
    if bulletin is None or bulletin.company_id != company.id:
        return redirect_to("/paie", "Bulletin introuvable dans ce dossier.", "error")
    pdf = documents_pdf.pdf_bulletin_paie(paie.bulletin_dict(db, company, bulletin))
    return _reponse_pdf(
        pdf,
        documents_pdf.nom_fichier_pdf("Bulletin_paie", bulletin.periode, payslip_id),
    )


@router.get("/paie/dts.xml")
def dts_xml_web(
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Fichier XML EDI de la DTS « 9421 »."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    try:
        modele = edi_dts.construire_dts(db, company, exercice)
        xml = edi_dts.build_dts_xml(modele)
    except edi_dts.DtsError as exc:
        return redirect_to("/paie", f"Erreur : {exc}", "error")
    return Response(
        content=xml.encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{edi_dts.xml_filename(company, exercice)}"'
            )
        },
    )


@router.get("/paie/dts.pdf")
def dts_pdf_web(
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Fiche recapitulative de la DTS (PDF)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    try:
        modele = edi_dts.construire_dts(db, company, exercice)
    except edi_dts.DtsError as exc:
        return redirect_to("/paie", f"Erreur : {exc}", "error")
    return _reponse_pdf(
        edi_dts.pdf_bordereau_dts(modele), f"DTS_{exercice}_recapitulatif.pdf"
    )


# ---------------------------------------------------------------------------
# IS & liasse fiscale EDI Simpl-IS (P2.1)
# ---------------------------------------------------------------------------
ROLES_LIASSE = ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")
ROLES_DEPOT_LIASSE = ("ADMIN", "EXPERT_COMPTABLE")


def _date_option(valeur: str) -> date | None:
    """Date de formulaire (`AAAA-MM-JJ`) ; vide -> None."""
    valeur = (valeur or "").strip()
    if not valeur:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError as exc:
        raise ValueError(f"Date invalide « {valeur} » (format attendu AAAA-MM-JJ).") from exc


def _dossier_liasse_web(db, company, exercice: int, modele: str) -> tuple[dict, dict | None]:
    """Dossier de liasse + fichier EDI controle (l'ecran reste consultable)."""
    dossier = liasse_edi.dossier_liasse(db, company, exercice, modele=modele)
    try:
        production = liasse_edi.produire_liasse_xml(
            db, company, exercice, modele=modele, forcer=True
        )
    except liasse_edi.LiasseError:
        production = None
    return dossier, production


@router.get("/liasse", response_class=HTMLResponse)
def page_liasse(
    request: Request,
    year: int | None = Query(default=None),
    modele: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """IS & liasse fiscale : resultat fiscal, liasse, EFI assiste et depot."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    modele_choisi = modele or liasse_edi.MODELE_PAR_DEFAUT
    dossier = None
    production = None
    erreur = ""
    try:
        dossier, production = _dossier_liasse_web(db, company, exercice, modele_choisi)
    except Exception as exc:  # exercice absent, modele inconnu, schema illisible
        erreur = str(exc)
    return render(
        request,
        "liasse.html",
        user=user,
        company=company,
        title="IS & liasse fiscale",
        active="liasse",
        exercice=exercice,
        modele_choisi=modele_choisi,
        modeles=[
            (nom, liasse_edi.MODELE_LABELS.get(nom, nom))
            for nom in liasse_edi.MODELES_LIASSE
        ],
        dossier=dossier,
        production=production,
        erreur=erreur,
        declarations=liasse_edi.list_declarations(db, company.id),
    )


@router.post("/liasse/enregistrer")
def liasse_enregistrer_web(
    year: int = Form(...),
    modele: str = Form(""),
    mode_depot: str = Form("EFI"),
    avec_xml: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Enregistre la liasse (tableaux, cellules) et sa declaration (brouillon)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    if not user.is_superadmin and not user.role_codes.intersection(ROLES_LIASSE):
        raise NotAuthorized()
    modele_choisi = modele or liasse_edi.MODELE_PAR_DEFAUT
    try:
        liasse = liasse_edi.dossier_liasse(db, company, year, modele=modele_choisi)["liasse"]
        xml = validation = None
        if avec_xml == "1":
            production = liasse_edi.produire_liasse_xml(
                db, company, year, modele=modele_choisi
            )
            xml = production["xml"]
            validation = production["validation"]
        declaration = liasse_edi.enregistrer_liasse(
            db,
            company,
            liasse,
            mode_depot=mode_depot,
            xml=xml,
            validation=validation,
            user_id=user.id,
        )
        db.commit()
    except liasse_edi.LiasseError as exc:
        db.rollback()
        return redirect_to(
            f"/liasse?year={year}&modele={modele_choisi}", f"Erreur : {exc}", "error"
        )
    return redirect_to(
        f"/liasse?year={year}&modele={modele_choisi}",
        f"Liasse {declaration.periode} enregistrée ({declaration.nb_lignes} cellule(s), "
        f"dépôt {declaration.mode_depot}).",
    )


@router.post("/liasse/depot")
def liasse_depot_web(
    year: int = Form(...),
    modele: str = Form(""),
    jour: str = Form(""),
    accuse_le: str = Form(""),
    motif_rejet: str = Form(""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Enregistre le depot (ou l'accuse de reception) dans le registre."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    if not user.is_superadmin and not user.role_codes.intersection(ROLES_DEPOT_LIASSE):
        raise NotAuthorized()
    declaration = liasse_edi.declaration_liasse(db, company.id, year)
    if declaration is None:
        return redirect_to(
            f"/liasse?year={year}",
            "Aucune liasse enregistrée : enregistrez-la d'abord.",
            "warning",
        )
    try:
        liasse_edi.soumettre_declaration(
            db,
            declaration,
            jour=_date_option(jour),
            accuse_le=_date_option(accuse_le),
            motif_rejet=motif_rejet.strip() or None,
            user_id=user.id,
        )
        db.commit()
    except (liasse_edi.LiasseError, ValueError) as exc:
        db.rollback()
        return redirect_to(f"/liasse?year={year}&modele={modele}", f"Erreur : {exc}", "error")
    return redirect_to(
        f"/liasse?year={year}&modele={modele}",
        f"Dépôt enregistré : déclaration « {declaration.statut_libelle} ».",
    )


@router.get("/etats/liasse.xml")
def liasse_xml_web(
    year: int | None = Query(default=None),
    modele: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Fichier XML EDI de la liasse (refuse si bloquant ou si le XSD le rejette)."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    modele_choisi = modele or liasse_edi.MODELE_PAR_DEFAUT
    try:
        production = liasse_edi.produire_liasse_xml(
            db, company, exercice, modele=modele_choisi
        )
    except liasse_edi.LiasseError as exc:
        return redirect_to(
            f"/liasse?year={exercice}&modele={modele_choisi}", f"Erreur : {exc}", "error"
        )
    return Response(
        content=production["xml"].encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{production["nom_fichier"]}"'
        },
    )


@router.get("/etats/liasse-efi.csv")
def liasse_efi_csv_web(
    year: int | None = Query(default=None),
    modele: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> Response:
    """Etat de saisie EFI (CSV) : `codeEdi`, libelle, valeur, lignes a completer."""
    redirection = _societe_pdf(company)
    if redirection is not None:
        return redirection
    exercice = year or date.today().year
    modele_choisi = modele or liasse_edi.MODELE_PAR_DEFAUT
    try:
        liasse = liasse_edi.dossier_liasse(db, company, exercice, modele=modele_choisi)[
            "liasse"
        ]
    except liasse_edi.LiasseError as exc:
        return redirect_to(
            f"/liasse?year={exercice}&modele={modele_choisi}", f"Erreur : {exc}", "error"
        )
    return Response(
        content=liasse_edi.efi_liasse_csv(liasse),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="LIASSE_EFI_{exercice}_'
                f'{company.fiscal_id or "IF"}.csv"'
            )
        },
    )

