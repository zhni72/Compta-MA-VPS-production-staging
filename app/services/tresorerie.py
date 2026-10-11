"""Tresorerie : controle des **soldes crediteurs** et reclassement CGNC (P1).

Regle comptable : un compte de tresorerie **debiteur** (banques, cheques postaux,
tresorerie generale, autres etablissements) ne peut pas presenter un solde
crediteur — un solde crediteur est un **concours bancaire** a loger en
**tresorerie-passif** (`5541` Banques (solde crediteur), `5548` autres
etablissements). Le PCGE prevoit explicitement ces comptes de contrepartie.

Le module :
- **detecte** les soldes crediteurs des comptes de tresorerie debiteurs
  (`controler_tresorerie`) ;
- **reclasse** le solde vers le compte de passif du meme etablissement
  (`reclasser_solde_crediteur`), par une **ecriture OD tracee** (source
  `reclass_tresorerie`, reference unique `RECLASS-TRESO-<annee>-<compte>`) ;
- traite les caisses creditrices comme une **anomalie a corriger** (aucun compte
  de caisse crediteur n'existe au CGNC : une caisse ne peut pas etre negative).

Usage : `controler_tresorerie(db, company_id, 2026)` puis, si besoin,
`reclasser_soldes_crediteurs(db, company, 2026, motif=..., user_id=...)`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.rates_ma import money
from app.models import Company, Entry, EntryLine, ENTRY_STATUS_VALIDATED
from app.services.accounting import AccountingError, create_entry, get_fiscal_year, get_journal
from app.services.reporting import movements, year_bounds

SOURCE_RECLASSEMENT = "reclass_tresorerie"

# Comptes de tresorerie **debiteurs** -> compte de tresorerie-passif de contrepartie.
CORRESPONDANCE_SOLDE_CREDITEUR: dict[str, str] = {
    "5141": "5541",  # Banques (solde debiteur)      -> Banques (solde crediteur)
    "5143": "5541",  # Tresorerie Generale           -> Banques (solde crediteur)
    "5146": "5541",  # Cheques postaux               -> Banques (solde crediteur)
    "5148": "5548",  # Autres etablissements         -> Autres etablissements (crediteurs)
}
# Caisses : un solde crediteur y est **impossible** (anomalie a corriger).
COMPTES_CAISSE = ("5161", "51611", "51613", "51614", "5165")


def controler_tresorerie(db: Session, company_id: int, year: int) -> dict:
    """Controle des soldes crediteurs des comptes de tresorerie (lecture seule)."""
    debut, fin = year_bounds(year)
    anomalies: list[dict] = []
    total = money(0)
    for ligne in movements(db, company_id, debut, fin):
        compte = ligne["account_number"]
        solde = money(ligne["solde"])
        if compte.startswith(COMPTES_CAISSE):
            if solde < 0:
                anomalies.append(
                    {
                        "compte": compte,
                        "libelle": ligne["label"],
                        "solde": solde,
                        "compte_reclassement": None,
                        "motif": (
                            "Caisse credi trice : impossible physiquement — corrigez la "
                            "saisie (aucun compte de caisse crediteur au CGNC)"
                        ),
                    }
                )
                total += money(-solde)
            continue
        if compte in CORRESPONDANCE_SOLDE_CREDITEUR and solde < 0:
            anomalies.append(
                {
                    "compte": compte,
                    "libelle": ligne["label"],
                    "solde": solde,
                    "compte_reclassement": CORRESPONDANCE_SOLDE_CREDITEUR[compte],
                    "motif": (
                        "Solde crediteur de tresorerie : concours bancaire a reclasser en "
                        f"{CORRESPONDANCE_SOLDE_CREDITEUR[compte]}"
                    ),
                }
            )
            total += money(-solde)
    return {
        "exercice": year,
        "soldes_crediteurs": anomalies,
        "conforme": not anomalies,
        "total_a_reclasser": money(total),
    }


def reference_reclassement(compte: str, year: int) -> str:
    """Reference unique et **idempotente** d'une ecriture de reclassement."""
    return f"RECLASS-TRESO-{year}-{compte}"


def reclasser_solde_crediteur(
    db: Session,
    company: Company,
    *,
    compte: str,
    year: int,
    motif: str,
    user_id: int | None = None,
) -> dict:
    """Reclasse le solde crediteur d'un compte de tresorerie vers son passif.

    Cree une ecriture OD **tracee** (debit du compte de tresorerie, credit du
    compte de passif `5541`/`5548`) du montant exact du solde crediteur. Refuse :
    - un compte sans contrepartie CGNC (caisse) : anomalie a corriger ;
    - un compte dont le solde n'est pas crediteur ;
    - un reclassement **deja effectue** pour le meme exercice (idempotence).
    """
    motif = (motif or "").strip()
    if len(motif) < 10:
        raise AccountingError(
            "Reclassement refuse : un motif explicite est obligatoire (tracabilite)."
        )
    if compte in COMPTES_CAISSE:
        raise AccountingError(
            f"Compte {compte} : une caisse credi trice est une anomalie de saisie, "
            "il n'existe pas de compte de caisse crediteur au CGNC."
        )
    cible = CORRESPONDANCE_SOLDE_CREDITEUR.get(compte)
    if cible is None:
        raise AccountingError(
            f"Compte {compte} : aucun compte de tresorerie-passif de contrepartie "
            "n'est parametre."
        )
    # Idempotence : un reclassement deja passe pour l'exercice est signale comme tel
    # (avant le controle de solde, qui ne presente plus de solde crediteur apres
    # reclassement).
    reference = reference_reclassement(compte, year)
    existante = db.execute(
        select(Entry).where(
            Entry.company_id == company.id,
            Entry.reference == reference,
            Entry.status == ENTRY_STATUS_VALIDATED,
        )
    ).scalar_one_or_none()
    if existante is not None:
        raise AccountingError(
            f"Reclassement deja effectue pour {compte} en {year} "
            f"(ecriture {existante.entry_number})."
        )
    controle = controler_tresorerie(db, company.id, year)
    constat = next(
        (ligne for ligne in controle["soldes_crediteurs"] if ligne["compte"] == compte),
        None,
    )
    if constat is None or constat["solde"] >= 0:
        raise AccountingError(
            f"Compte {compte} : aucun solde crediteur a reclasser sur l'exercice {year}."
        )
    montant = money(-constat["solde"])
    exercice = get_fiscal_year(db, company.id, year)
    # Date : fin d'exercice si l'exercice est clos, sinon aujourd'hui dans l'exercice.
    jour = exercice.end_date if exercice.status != "open" else min(date.today(), exercice.end_date)
    jour = max(jour, exercice.start_date)
    ecriture = create_entry(
        db,
        company_id=company.id,
        fiscal_year=exercice,
        journal=get_journal(db, company.id, "OD"),
        entry_date=jour,
        label=f"Reclassement du solde crediteur de {compte} en tresorerie-passif",
        reference=reference,
        source=SOURCE_RECLASSEMENT,
        created_by=user_id,
        lines=[
            {"account_number": compte, "label": "Solde crediteur reclassé", "debit": montant},
            {"account_number": cible, "label": "Tresorerie - solde crediteur", "credit": montant},
        ],
        validate=True,
    )
    log_action(
        db,
        action="TREASURY_RECLASSIFIED",
        entity="Entry",
        entity_id=ecriture.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "compte_source": compte,
            "compte_passif": cible,
            "montant": str(montant),
            "exercice": year,
            "motif": motif,
            "reference": reference,
        },
    )
    return {
        "compte": compte,
        "compte_passif": cible,
        "montant": montant,
        "entry_id": ecriture.id,
        "entry_number": ecriture.entry_number,
        "reference": reference,
    }


def reclasser_soldes_crediteurs(
    db: Session,
    company: Company,
    year: int,
    *,
    motif: str,
    user_id: int | None = None,
) -> dict:
    """Reclasse **tous** les soldes crediteurs eligibles d'un exercice.

    Retourne les reclassements effectues et les anomalies **non** reclassables
    (caisses credi trices) qui restent a corriger manuellement.
    """
    controle = controler_tresorerie(db, company.id, year)
    effectues: list[dict] = []
    non_reclassables: list[dict] = []
    for constat in controle["soldes_crediteurs"]:
        if constat["compte_reclassement"] is None:
            non_reclassables.append(constat)
            continue
        effectues.append(
            reclasser_solde_crediteur(
                db,
                company,
                compte=constat["compte"],
                year=year,
                motif=motif,
                user_id=user_id,
            )
        )
    return {
        "exercice": year,
        "effectues": effectues,
        "non_reclassables": non_reclassables,
        "conforme_apres": controler_tresorerie(db, company.id, year)["conforme"],
    }

