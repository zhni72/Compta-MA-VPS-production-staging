"""Tests du rapprochement bancaire (P1.6) : import, appariement, etat, alertes."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import BankStatement, EntryLine
from app.services import banking
from app.services.accounting import create_entry, get_journal
from app.services.banking import BankingError
from app.services.closing import get_fiscal_year

pytestmark = pytest.mark.usefixtures("ctx")

RELEVE_CSV = """date;libelle;reference;debit;credit
2026-06-02;Virement client Alpha;VIR-001;12 000,00;
2026-06-05;Loyer agence;CHQ-1234;;3 500,00
2026-06-20;Frais bancaires;FRAIS-06;;275,00
"""


def _ecriture(db, ctx, jour: date, libelle: str, lignes: list[dict], journal: str = "BQ"):
    """Ecriture bancaire validee."""
    return create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=get_fiscal_year(db, ctx["company"].id, jour.year),
        journal=get_journal(db, ctx["company"].id, journal),
        entry_date=jour,
        label=libelle,
        lines=lignes,
        validate=True,
        created_by=ctx["user"].id,
    )


@pytest.fixture()
def releve(db, ctx) -> BankStatement:
    """Releve de juin 2026 importe (3 lignes, solde final 8 225,00)."""
    return banking.importer_releve(
        db,
        company=ctx["company"],
        account_number="5141",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 30),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("8225.00"),
        lignes=banking.parser_csv_releve(RELEVE_CSV),
        file_name="releve_juin_2026.csv",
        user_id=ctx["user"].id,
    )


def test_parsing_du_releve_csv_normalise():
    """Le lecteur accepte la virgule decimale et le format marocain des montants."""
    lignes = banking.parser_csv_releve(RELEVE_CSV)
    assert len(lignes) == 3
    assert lignes[0]["date"] == date(2026, 6, 2)
    assert lignes[0]["debit"] == Decimal("12000.00")
    assert lignes[0]["credit"] == Decimal("0.00")
    assert lignes[2]["credit"] == Decimal("275.00")
    assert lignes[0]["reference"] == "VIR-001"

    with pytest.raises(BankingError, match="date invalide"):
        banking.parser_csv_releve("date;libelle\n02/06/2026;Test\n")
    with pytest.raises(BankingError, match="Colonnes obligatoires"):
        banking.parser_csv_releve("jour;montant\n2026-06-02;100\n")


def test_import_du_releve_et_journalisation(db, ctx, releve):
    """L'import cree le releve, ses lignes et trace l'operation."""
    from app.models import AuditLog

    assert releve.id is not None
    assert releve.account_number == "5141"
    assert len(releve.lines) == 3
    assert releve.closing_balance == Decimal("8225.00")
    assert releve.file_name == "releve_juin_2026.csv"
    assert all(ligne.reconciled is False for ligne in releve.lines)
    actions = [ligne.action for ligne in db.execute(select(AuditLog)).scalars()]
    assert "BANK_STATEMENT_IMPORTED" in actions

    with pytest.raises(BankingError, match="au moins une ligne"):
        banking.importer_releve(
            db,
            company=ctx["company"],
            account_number="5141",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 30),
            lignes=[],
        )


def test_rapprochement_automatique_puis_manuel(db, ctx, releve):
    """Appariement automatique (montant exact), manuel, et etat de rapprochement."""
    _ecriture(
        db,
        ctx,
        date(2026, 6, 2),
        "Encaissement client Alpha",
        [
            {"account_number": "5141", "label": "Banque", "debit": Decimal("12000.00")},
            {"account_number": "3421", "label": "Client Alpha", "credit": Decimal("12000.00")},
        ],
    )
    _ecriture(
        db,
        ctx,
        date(2026, 6, 5),
        "Loyer agence",
        [
            {"account_number": "6131", "label": "Loyer", "debit": Decimal("3500.00")},
            {"account_number": "5141", "label": "Banque", "credit": Decimal("3500.00")},
        ],
    )
    resultat = banking.rapprocher_automatiquement(
        db, releve, tolerance_jours=7, user_id=ctx["user"].id
    )
    assert resultat["nb_rapprochees"] == 2  # virement + loyer (montants exacts)
    assert resultat["nb_restantes"] == 1  # frais bancaires sans ecriture

    frais = [ligne for ligne in releve.lines if not ligne.reconciled][0]
    assert frais.label == "Frais bancaires"
    with pytest.raises(BankingError, match="motif"):
        banking.rapprocher(db, frais, None, type_rapprochement="ajustement")
    banking.rapprocher(
        db,
        frais,
        None,
        type_rapprochement="ajustement",
        motif="Frais bancaires a comptabiliser (6147)",
        user_id=ctx["user"].id,
    )
    assert frais.reconciled is True
    assert frais.match_type == "ajustement"
    with pytest.raises(BankingError, match="deja rapprochee"):
        banking.rapprocher(db, frais, None, motif="doublon")

    etat = banking.etat_rapprochement(db, releve)
    assert etat["solde_comptable"] == Decimal("8500.00")  # 12000 - 3500
    assert etat["solde_bancaire"] == Decimal("8225.00")
    assert etat["ecarts_ajustes"] == Decimal("-275.00")
    assert etat["solde_reconstitue"] == Decimal("8225.00")
    assert etat["ecart"] == Decimal("0.00")
    assert etat["justifie"] is True
    assert etat["nb_rapprochees"] == 3
    assert etat["nb_non_rapprochees"] == 0


def test_de_rapprochement_et_alertes_d_ecarts_anciens(db, ctx, releve):
    """De-rapprochement (controle) et alerte sur les ecarts de plus de 3 mois."""
    _ecriture(
        db,
        ctx,
        date(2026, 6, 2),
        "Encaissement client Alpha",
        [
            {"account_number": "5141", "label": "Banque", "debit": Decimal("12000.00")},
            {"account_number": "3421", "label": "Client Alpha", "credit": Decimal("12000.00")},
        ],
    )
    banking.rapprocher_automatiquement(
        db, releve, tolerance_jours=7, user_id=ctx["user"].id
    )
    ligne_virement = [ligne for ligne in releve.lines if ligne.reconciled][0]
    banking.de_rapprocher(db, ligne_virement, user_id=ctx["user"].id)
    assert ligne_virement.reconciled is False
    assert ligne_virement.entry_line_id is None
    assert ligne_virement.match_type is None
    with pytest.raises(BankingError, match="Aucun rapprochement"):
        banking.de_rapprocher(db, ligne_virement)

    # Une ligne ancienne non rapprochee declenche l'alerte des 3 mois.
    restantes = [ligne for ligne in releve.lines if not ligne.reconciled]
    restantes[0].line_date = date.today() - timedelta(days=120)
    db.flush()
    alertes = banking.alertes_ecarts_anciens(db, ctx["company"].id)
    assert len(alertes) >= 1
    assert alertes[0]["anciennete_jours"] >= 90
    assert alertes[0]["compte"] == "5141"
    assert alertes[0]["montant"] != 0


def test_candidats_et_absence_de_double_appariement(db, ctx, releve):
    """Les candidats proposent les ecritures non deja rapprochees."""
    _ecriture(
        db,
        ctx,
        date(2026, 6, 3),
        "Encaissement client Alpha",
        [
            {"account_number": "5141", "label": "Banque", "debit": Decimal("12000.00")},
            {"account_number": "3421", "label": "Client Alpha", "credit": Decimal("12000.00")},
        ],
    )
    ligne = [ligne for ligne in releve.lines if ligne.label.startswith("Virement")][0]
    candidats = banking.candidats_rapprochement(db, ligne)
    assert len(candidats) == 1
    candidat = candidats[0]
    assert candidat["exact"] is True
    assert candidat["jours_ecart"] == 1
    assert candidat["entry_number"].startswith("EC")

    entry_line = db.get(EntryLine, candidat["entry_line_id"])
    banking.rapprocher(db, ligne, entry_line, user_id=ctx["user"].id)
    # Une ligne deja rapprochee ne propose plus de candidat, et l'ecriture
    # correspondante n'est plus proposee ailleurs (pas de double appariement).
    autres = [ligne_releve for ligne_releve in releve.lines if not ligne_releve.reconciled]
    for autre in autres:
        for propose in banking.candidats_rapprochement(db, autre):
            assert propose["entry_line_id"] != candidat["entry_line_id"]


def test_lignes_a_rapprocher_pour_l_ecran(db, ctx, releve):
    """L'ecran de rapprochement recoit les lignes restantes et leurs candidats."""
    restantes = banking.lignes_a_rapprocher(db, releve)
    assert len(restantes) == 3
    assert restantes[0]["ligne"].label.startswith("Virement")
    assert restantes[0]["candidats"] == []
    assert restantes[0]["ligne"].montant == Decimal("12000.00")

