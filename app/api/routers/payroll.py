"""Paie et DTS « 9421 » (P1.4) : salaries, contrats, bulletins, DTS."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, User
from app.models.declaration import DECLARATION_DTS, DEPOT_EDI, DEPOT_EFI
from app.schemas import (
    DtsSoumissionRequest,
    EmployeeCreate,
    EmployeeRead,
    PayContractCreate,
    PayContractRead,
    PayrollPayRequest,
    PayrollPrepareRequest,
    PayrollRunRead,
    PayslipRead,
    TaxDeclarationRead,
)
from app.services.edi_dts import (
    DtsError,
    build_dts_xml,
    construire_dts,
    enregistrer_declaration,
    etat_de_saisie_efi,
    list_declarations,
    pdf_bordereau_dts,
    soumettre_declaration,
    valider_xsd,
    xml_filename,
)
from app.services.payroll import (
    PayrollError,
    etat_cotisations,
    get_employe,
    get_run,
    journal_de_paie,
    list_bulletins,
    list_employes,
    livre_de_paie,
    payer_paie,
    preparer_paie,
    recapitulatif_annuel,
    valider_paie,
)
from app.services.payroll import ajouter_contrat as creer_contrat
from app.services.payroll import controles_paie as controles
from app.services.payroll import creer_employe

router = APIRouter(prefix="/payroll", tags=["paie"])

MUTATION_ROLES = ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")
# La validation de la paie (ecriture) et son reglement sont reserves a
# l'ADMIN / l'EXPERT_COMPTABLE : ce sont des operations d'engagement comptable.
MUTATIONS_VALIDATION = ("ADMIN", "EXPERT_COMPTABLE")


def _reponse_pdf(pdf: bytes, nom: str) -> Response:
    """Reponse de telechargement de fichier (PDF ou XML)."""
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get("/employees", response_model=list[EmployeeRead], summary="Lister les salaries")
def list_employes_route(
    actifs: bool = Query(default=True, description="Salaries actifs uniquement"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list:
    return list_employes(db, company.id, actifs_seulement=actifs)


@router.post(
    "/employees",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer une fiche salarie",
)
def creer_employe_route(
    payload: EmployeeCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        employe = creer_employe(
            db, company=company, user_id=user.id, **payload.model_dump()
        )
        db.commit()
    except (PayrollError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(employe)
    return employe


@router.get(
    "/employees/{reference}",
    summary="Fiche d'un salarie (matricule ou identifiant) avec ses contrats",
)
def get_employe_route(
    reference: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        employe = get_employe(db, company.id, reference)
    except PayrollError as exc:
        raise http_error(exc) from exc
    return {
        "salarie": EmployeeRead.model_validate(employe),
        "contrats": [
            PayContractRead.model_validate(contrat) for contrat in employe.contrats
        ],
        "personnes_a_charge": employe.personnes_a_charge,
    }


@router.post(
    "/employees/{reference}/contrats",
    response_model=PayContractRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un element contractuel de remuneration",
)
def creer_contrat_route(
    reference: str,
    payload: PayContractCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        employe = get_employe(db, company.id, reference)
        contrat = creer_contrat(
            db, employe, user_id=user.id, **payload.model_dump()
        )
        db.commit()
    except (PayrollError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(contrat)
    return contrat


@router.post(
    "/runs",
    response_model=PayrollRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Preparer (calculer) la paie d'une periode",
)
def preparer_paie_route(
    payload: PayrollPrepareRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        run = preparer_paie(
            db,
            company,
            payload.periode,
            variables=payload.variables,
            date_paie=payload.date_paie,
            user_id=user.id,
        )
        db.commit()
    except (PayrollError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(run)
    return run


@router.get("/runs/{periode}", summary="Cycle de paie d'une periode et ses bulletins")
def get_run_route(
    periode: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    run = get_run(db, company.id, periode)
    if run is None:
        raise http_error(PayrollError(f"Aucune paie pour la période {periode}."))
    return {
        "cycle": PayrollRunRead.model_validate(run),
        "bulletins": [
            PayslipRead.model_validate(bulletin) for bulletin in list_bulletins(db, run)
        ],
        "controles": controles(db, company.id, periode),
    }


@router.post(
    "/runs/{periode}/valider",
    summary="Valider la paie : ecriture globale et bulletins figes",
)
def valider_paie_route(
    periode: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATIONS_VALIDATION)),
) -> dict:
    run = get_run(db, company.id, periode)
    if run is None:
        raise http_error(PayrollError(f"Aucune paie pour la période {periode}."))
    try:
        ecriture = valider_paie(db, run, user_id=user.id)
        db.commit()
    except (PayrollError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "periode": periode,
        "entry_number": ecriture.entry_number,
        "statut": run.statut,
        "total_brut": str(run.total_brut),
        "total_net": str(run.total_net),
        "total_ir": str(run.total_ir),
        "cout_employeur": str(run.total_employeur),
    }


@router.post(
    "/runs/{periode}/payer",
    summary="Regler le net a payer (banque ou caisse)",
)
def payer_paie_route(
    periode: str,
    payload: PayrollPayRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATIONS_VALIDATION)),
) -> dict:
    run = get_run(db, company.id, periode)
    if run is None:
        raise http_error(PayrollError(f"Aucune paie pour la période {periode}."))
    try:
        ecriture = payer_paie(
            db, run, date_paiement=payload.date_paiement, mode=payload.mode,
            user_id=user.id,
        )
        db.commit()
    except (PayrollError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "periode": periode,
        "entry_number": ecriture.entry_number,
        "statut": run.statut,
        "mode": run.mode_paiement,
        "montant": str(run.total_net),
    }


@router.get("/controles", summary="Controles de la paie d'une periode")
def controles_route(
    periode: str = Query(..., description="AAAA-MM"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return controles(db, company.id, periode)


@router.get("/journal", summary="Journal de paie d'une periode")
def journal_route(
    periode: str = Query(..., description="AAAA-MM"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return journal_de_paie(db, company.id, periode)


@router.get("/livre", summary="Livre de paie annuel (cumuls mensuels par salarie)")
def livre_route(
    annee: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return livre_de_paie(db, company.id, annee)


@router.get("/cotisations", summary="Etat des cotisations et de l'IR retenu par mois")
def cotisations_route(
    annee: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return etat_cotisations(db, company.id, annee)


@router.get("/recapitulatif", summary="Recapitulatif annuel par salarie")
def recapitulatif_route(
    annee: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return recapitulatif_annuel(db, company.id, annee)


@router.get("/bulletin/{payslip_id}/pdf", summary="Bulletin de paie (PDF)")
def bulletin_pdf_route(
    payslip_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    from app.models import Payslip  # noqa: PLC0415 - import local (lisibilite)
    from app.services.payroll import bulletin_dict  # noqa: PLC0415
    from app.services.pdf_documents import pdf_bulletin_paie  # noqa: PLC0415

    bulletin = db.get(Payslip, payslip_id)
    if bulletin is None or bulletin.company_id != company.id:
        raise http_error(PayrollError(f"Bulletin {payslip_id} introuvable."))
    pdf = pdf_bulletin_paie(bulletin_dict(db, company, bulletin))
    return _reponse_pdf(pdf, f"Bulletin_{bulletin.periode}_{payslip_id}.pdf")


# ---------------------------------------------------------------------------
# DTS « 9421 »
# ---------------------------------------------------------------------------
@router.get(
    "/dts/{annee}",
    summary="Modele de la DTS « 9421 » (declarant, salaries, cotisations, controles)",
)
def dts_modele_route(
    annee: int,
    mode: str = Query(default=DEPOT_EDI, description="EDI ou EFI"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        return construire_dts(db, company, annee, mode=mode)
    except DtsError as exc:
        raise http_error(exc) from exc


@router.get(
    "/dts/{annee}/xml",
    summary="Fichier XML EDI de la DTS « 9421 » (mode EDI)",
)
def dts_xml_route(
    annee: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        modele = construire_dts(db, company, annee, mode=DEPOT_EDI)
        xml = build_dts_xml(modele)
    except DtsError as exc:
        raise http_error(exc) from exc
    return Response(
        content=xml.encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{xml_filename(company, annee)}"'
            )
        },
    )


@router.get(
    "/dts/{annee}/efi",
    summary="Etat de saisie EFI (saisie assistee sur SIMPL, ligne par salarie)",
)
def dts_efi_route(
    annee: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    try:
        modele = construire_dts(db, company, annee, mode=DEPOT_EFI)
    except DtsError as exc:
        raise http_error(exc) from exc
    return etat_de_saisie_efi(modele)


@router.get(
    "/dts/{annee}/fiche-pdf",
    summary="Fiche recapitulative de la DTS (PDF)",
)
def dts_pdf_route(
    annee: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        modele = construire_dts(db, company, annee)
    except DtsError as exc:
        raise http_error(exc) from exc
    return _reponse_pdf(pdf_bordereau_dts(modele), f"DTS_{annee}_recapitulatif.pdf")


@router.post(
    "/dts/{annee}/declaration",
    response_model=TaxDeclarationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Produire et enregistrer la DTS (XML + registre des declarations)",
)
def dts_enregistrer_route(
    annee: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATIONS_VALIDATION)),
) -> object:
    try:
        modele = construire_dts(db, company, annee, mode=DEPOT_EDI)
        xml = build_dts_xml(modele)
        declaration = enregistrer_declaration(
            db, company, modele, xml=xml, user_id=user.id
        )
        db.commit()
    except (DtsError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(declaration)
    return declaration


@router.post(
    "/dts/declarations/{declaration_id}/depot",
    response_model=TaxDeclarationRead,
    summary="Enregistrer le depot de la DTS (accuse de reception ou rejet)",
)
def dts_depot_route(
    declaration_id: int,
    payload: DtsSoumissionRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATIONS_VALIDATION)),
) -> object:
    from app.models import TaxDeclaration  # noqa: PLC0415 - import local

    declaration = db.get(TaxDeclaration, declaration_id)
    if declaration is None or declaration.company_id != company.id:
        raise http_error(DtsError(f"Déclaration {declaration_id} introuvable."))
    try:
        soumettre_declaration(
            db,
            declaration,
            jour=payload.jour,
            accuse_le=payload.accuse_le,
            motif_rejet=payload.motif_rejet,
            user_id=user.id,
        )
        db.commit()
    except DtsError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(declaration)
    return declaration


@router.get(
    "/dts/declarations",
    response_model=list[TaxDeclarationRead],
    summary="Registre des declarations (tracabilite des depots)",
)
def dts_declarations_route(
    type_declaration: str = Query(default=DECLARATION_DTS),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list:
    return list_declarations(db, company.id, type_declaration=type_declaration)


@router.get(
    "/dts/{annee}/validation-xsd",
    summary="Validation du fichier DTS contre le XSD officiel (si fourni)",
)
def dts_validation_route(
    annee: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        modele = construire_dts(db, company, annee, mode=DEPOT_EDI)
        xml = build_dts_xml(modele)
    except DtsError as exc:
        raise http_error(exc) from exc
    return valider_xsd(xml)
