"""Rapprochement bancaire (P1.6).

Chaine : **import du releve** (CSV normalise) -> appariement **automatique**
(montant identique, date proche) -> appariement **manuel** -> **etat de
rapprochement** (solde comptable / solde bancaire / ecarts justifies).

Convention de signe (identique au compte de tresorerie) :
- `debit`  = **entree** d'argent (le compte 5141 est debite) ;
- `credit` = **sortie** d'argent (le compte 5141 est credite).

Aucun solde n'est duplique : l'etat se calcule depuis les ecritures validees
(`entry_lines`) et les lignes de releve (`bank_statement_lines`).
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.rates_ma import money
from app.models import (
    ENTRY_STATUS_VALIDATED,
    BankReconciliation,
    BankStatement,
    BankStatementLine,
    Company,
    Entry,
    EntryLine,
)
from app.services.accounting import AccountingError

ENTETES_RELEVE = ("date", "libelle", "reference", "debit", "credit")
TOLERANCE_JOURS = 15
ALERTE_ECART_JOURS = 90  # 3 mois (CDC § 3.6, alerte n° 6)


class BankingError(AccountingError):
    """Erreur metier de rapprochement bancaire."""


def _montant_releve(valeur: str | None) -> Decimal:
    """Convertit un montant de releve (virgule decimale, espaces de milliers)."""
    if valeur is None or not str(valeur).strip():
        return money(0)
    texte = (
        str(valeur)
        .strip()
        .replace("\u202f", "")
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    try:
        return money(texte)
    except Exception as exc:  # noqa: BLE001 - message utilisateur
        raise BankingError(f"Montant invalide dans le releve : {valeur!r}") from exc


def parser_csv_releve(contenu: str) -> list[dict]:
    """Lit un releve CSV normalise (``date;libelle;reference;debit;credit``)."""
    lecteur = csv.DictReader(io.StringIO(contenu.lstrip("\ufeff")), delimiter=";")
    if lecteur.fieldnames is None:
        raise BankingError(
            "Releve vide : entete attendue date;libelle;reference;debit;credit"
        )
    manquants = [
        colonne for colonne in ("date", "libelle") if colonne not in lecteur.fieldnames
    ]
    if manquants:
        raise BankingError(
            f"Colonnes obligatoires absentes du releve : {', '.join(manquants)}"
        )
    lignes: list[dict] = []
    for index, brut in enumerate(lecteur, start=2):
        if not any((valeur or "").strip() for valeur in brut.values()):
            continue
        try:
            jour = date.fromisoformat(str(brut["date"]).strip())
        except ValueError as exc:
            raise BankingError(
                f"Ligne {index} : date invalide {brut['date']!r} "
                "(format attendu AAAA-MM-JJ)"
            ) from exc
        lignes.append(
            {
                "date": jour,
                "label": str(brut.get("libelle") or "").strip() or "Sans libelle",
                "reference": (str(brut.get("reference") or "").strip() or None),
                "debit": _montant_releve(brut.get("debit")),
                "credit": _montant_releve(brut.get("credit")),
            }
        )
    if not lignes:
        raise BankingError("Aucune ligne exploitable dans le releve importe.")
    return lignes


def importer_releve(
    db: Session,
    *,
    company: Company,
    account_number: str,
    date_from: date,
    date_to: date,
    opening_balance: Decimal | str = 0,
    closing_balance: Decimal | str = 0,
    lignes: list[dict],
    file_name: str | None = None,
    user_id: int | None = None,
) -> BankStatement:
    """Importe un releve bancaire et ses lignes."""
    if not lignes:
        raise BankingError("Un releve doit contenir au moins une ligne.")
    if date_to < date_from:
        raise BankingError("La periode du releve est incoherente (fin avant debut).")
    statement = BankStatement(
        company_id=company.id,
        account_number=str(account_number).strip(),
        date_from=date_from,
        date_to=date_to,
        opening_balance=money(opening_balance),
        closing_balance=money(closing_balance),
        file_name=file_name,
        imported_by=user_id,
    )
    db.add(statement)
    db.flush()
    for ligne in lignes:
        statement.lines.append(
            BankStatementLine(
                line_date=ligne["date"],
                label=ligne["label"],
                reference=ligne.get("reference"),
                debit=money(ligne.get("debit") or 0),
                credit=money(ligne.get("credit") or 0),
            )
        )
    db.flush()
    log_action(
        db,
        action="BANK_STATEMENT_IMPORTED",
        entity="BankStatement",
        entity_id=statement.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "compte": statement.account_number,
            "periode": f"{date_from}..{date_to}",
            "nb_lignes": len(statement.lines),
            "solde_final": statement.closing_balance,
        },
    )
    return statement


def mouvement(ligne: BankStatementLine | EntryLine) -> Decimal:
    """Montant signe d'une ligne (positif au debit = entree d'argent)."""
    return money(ligne.debit - ligne.credit)


def candidats_rapprochement(
    db: Session, ligne: BankStatementLine, *, tolerance_jours: int = TOLERANCE_JOURS
) -> list[dict]:
    """Ecritures candidates pour une ligne de releve (meme montant, date proche)."""
    statement = db.get(BankStatement, ligne.statement_id)
    if statement is None:
        return []
    montant = mouvement(ligne)
    debut = ligne.line_date - timedelta(days=tolerance_jours)
    fin = ligne.line_date + timedelta(days=tolerance_jours)
    lignes = db.execute(
        select(EntryLine, Entry)
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(
            Entry.company_id == statement.company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
            EntryLine.account_number == statement.account_number,
            Entry.entry_date >= debut,
            Entry.entry_date <= fin,
        )
        .order_by(Entry.entry_date)
    ).all()
    deja = set(db.execute(select(BankReconciliation.entry_line_id)).scalars())
    candidats: list[dict] = []
    for entry_line, entry in lignes:
        if entry_line.id in deja:
            continue
        ecart = money(mouvement(entry_line) - montant)
        candidats.append(
            {
                "entry_line_id": entry_line.id,
                "entry_id": entry.id,
                "entry_number": entry.entry_number,
                "entry_date": entry.entry_date,
                "label": entry_line.label or entry.label,
                "montant": mouvement(entry_line),
                "ecart": ecart,
                "exact": ecart == 0,
                "jours_ecart": abs((entry.entry_date - ligne.line_date).days),
            }
        )
    candidats.sort(key=lambda candidat: (not candidat["exact"], candidat["jours_ecart"]))
    return candidats



def rapprocher(
    db: Session,
    ligne: BankStatementLine,
    entry_line: EntryLine | None = None,
    *,
    type_rapprochement: str = "rapproche",
    motif: str | None = None,
    user_id: int | None = None,
) -> BankReconciliation:
    """Apparie une ligne de releve avec une ligne d'ecriture (ou en ajustement)."""
    if ligne.reconciled:
        raise BankingError(
            f"Ligne de releve {ligne.id} deja rapprochee : de-rapprochez-la d'abord."
        )
    if type_rapprochement not in ("rapproche", "ajustement"):
        raise BankingError("Type de rapprochement invalide (rapproche ou ajustement).")
    if type_rapprochement == "ajustement" and not motif:
        raise BankingError("Un ajustement exige un motif (ecriture a passer).")
    rapprochement = BankReconciliation(
        statement_line_id=ligne.id,
        entry_line_id=None if entry_line is None else entry_line.id,
        reconciliation_type=type_rapprochement,
        montant=mouvement(ligne),
        motif=motif,
        created_by=user_id,
    )
    db.add(rapprochement)
    ligne.reconciled = True
    ligne.entry_line_id = None if entry_line is None else entry_line.id
    ligne.match_type = type_rapprochement
    ligne.note = motif
    db.flush()
    statement = db.get(BankStatement, ligne.statement_id)
    log_action(
        db,
        action="BANK_LINE_RECONCILED",
        entity="BankStatementLine",
        entity_id=ligne.id,
        user_id=user_id,
        company_id=None if statement is None else statement.company_id,
        payload={
            "type": type_rapprochement,
            "montant": mouvement(ligne),
            "entry_line_id": None if entry_line is None else entry_line.id,
            "motif": motif,
        },
    )
    return rapprochement


def de_rapprocher(
    db: Session, ligne: BankStatementLine, *, user_id: int | None = None
) -> None:
    """Annule le rapprochement d'une ligne de releve."""
    rapprochement = db.execute(
        select(BankReconciliation).where(
            BankReconciliation.statement_line_id == ligne.id
        )
    ).scalar_one_or_none()
    if rapprochement is None:
        raise BankingError("Aucun rapprochement a annuler pour cette ligne.")
    db.delete(rapprochement)
    ligne.reconciled = False
    ligne.entry_line_id = None
    ligne.match_type = None
    ligne.note = None
    db.flush()
    statement = db.get(BankStatement, ligne.statement_id)
    log_action(
        db,
        action="BANK_LINE_UNRECONCILED",
        entity="BankStatementLine",
        entity_id=ligne.id,
        user_id=user_id,
        company_id=None if statement is None else statement.company_id,
        payload={"montant": mouvement(ligne)},
    )


def rapprocher_automatiquement(
    db: Session,
    statement: BankStatement,
    *,
    tolerance_jours: int = 7,
    user_id: int | None = None,
) -> dict:
    """Appariement automatique : montant exact et date proche (propositions sures)."""
    rapprochees: list[dict] = []
    for ligne in list(statement.lines):
        if ligne.reconciled:
            continue
        candidats = candidats_rapprochement(db, ligne, tolerance_jours=tolerance_jours)
        exacts = [candidat for candidat in candidats if candidat["exact"]]
        if len(exacts) != 1:  # aucun candidat ou ambiguite : decision manuelle
            continue
        candidat = exacts[0]
        rapprocher(
            db,
            ligne,
            db.get(EntryLine, candidat["entry_line_id"]),
            motif="Appariement automatique",
            user_id=user_id,
        )
        rapprochees.append(
            {
                "statement_line_id": ligne.id,
                "entry_number": candidat["entry_number"],
                "montant": candidat["montant"],
            }
        )
    return {
        "statement_id": statement.id,
        "nb_rapprochees": len(rapprochees),
        "rapprochees": rapprochees,
        "nb_restantes": len([l for l in statement.lines if not l.reconciled]),
    }



def etat_rapprochement(db: Session, statement: BankStatement) -> dict:
    """Etat de rapprochement : solde comptable, solde bancaire et ecarts justifies.

    Controle attendu (CDC § 3.6) : ``solde comptable + ecarts = solde bancaire``.
    """
    from app.services.closing import soldes_a_la_date

    soldes = soldes_a_la_date(db, statement.company_id, statement.date_to)
    solde_comptable = money(soldes.get(statement.account_number, Decimal("0")))
    non_rapprochees = [ligne for ligne in statement.lines if not ligne.reconciled]
    ajustements = [
        ligne
        for ligne in statement.lines
        if ligne.reconciled and ligne.match_type == "ajustement"
    ]
    ecarts_non_justifies = money(
        sum((mouvement(ligne) for ligne in non_rapprochees), Decimal("0"))
    )
    ecarts_ajustes = money(sum((mouvement(ligne) for ligne in ajustements), Decimal("0")))
    solde_reconstitue = money(solde_comptable + ecarts_non_justifies + ecarts_ajustes)
    ecart = money(statement.closing_balance - solde_reconstitue)
    return {
        "statement_id": statement.id,
        "account_number": statement.account_number,
        "date_from": statement.date_from,
        "date_to": statement.date_to,
        "solde_comptable": solde_comptable,
        "solde_bancaire": money(statement.closing_balance),
        "ecarts_non_justifies": ecarts_non_justifies,
        "ecarts_ajustes": ecarts_ajustes,
        "solde_reconstitue": solde_reconstitue,
        "ecart": ecart,
        "nb_lignes": len(statement.lines),
        "nb_rapprochees": len(statement.lines) - len(non_rapprochees),
        "nb_non_rapprochees": len(non_rapprochees),
        "justifie": ecart == 0,
    }


def alertes_ecarts_anciens(
    db: Session, company_id: int, *, jours: int = ALERTE_ECART_JOURS
) -> list[dict]:
    """Lignes de releve non rapprochees depuis plus de trois mois (alerte rouge)."""
    limite = date.today() - timedelta(days=jours)
    lignes = db.execute(
        select(BankStatementLine, BankStatement)
        .join(BankStatement, BankStatement.id == BankStatementLine.statement_id)
        .where(
            BankStatement.company_id == company_id,
            BankStatementLine.reconciled.is_(False),
            BankStatementLine.line_date <= limite,
        )
        .order_by(BankStatementLine.line_date)
    ).all()
    return [
        {
            "statement_line_id": ligne.id,
            "statement_id": statement.id,
            "compte": statement.account_number,
            "date": ligne.line_date,
            "label": ligne.label,
            "montant": mouvement(ligne),
            "anciennete_jours": (date.today() - ligne.line_date).days,
        }
        for ligne, statement in lignes
    ]


def lignes_a_rapprocher(db: Session, statement: BankStatement) -> list[dict]:
    """Lignes de releve restant a rapprocher, avec leurs candidats (ecran)."""
    resultats: list[dict] = []
    for ligne in statement.lines:
        if ligne.reconciled:
            continue
        resultats.append(
            {
                "ligne": ligne,
                "candidats": candidats_rapprochement(db, ligne)[:5],
            }
        )
    return resultats

