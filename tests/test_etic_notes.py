"""Non-regression P0.3 : notes ETIC alimentees par les racines a 3 caracteres.

Defaut reproduit (audit J9) : `notes_etic.detail()` filtrait sur
`account_number[:2]`, si bien que les racines **« 617 »** (charges de personnel)
et **« 619 »** (dotations d'exploitation) ne correspondaient jamais : la note 9
de l'ETIC etait **vide** et les dotations absentes de la note 4, alors que le CPC
portait bien les comptes 6171 / 61711 / 6174 et 6193.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting import (
    create_entry,
    get_fiscal_year,
    get_journal,
    validate_entry,
)
from app.services.etats_synthese import notes_etic

pytestmark = pytest.mark.usefixtures("ctx")

EXERCICE = (date(2026, 1, 1), date(2026, 12, 31))


def _ecriture(db, ctx, lignes: list[dict], libelle: str):
    company = ctx["company"]
    entry = create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_fiscal_year(db, company.id, ctx["year"]),
        journal=get_journal(db, company.id, "OD"),
        entry_date=date(2026, 6, 30),
        label=libelle,
        lines=lignes,
    )
    return validate_entry(db, entry, user_id=ctx["user"].id)


def _note(notes: list[dict], numero: int) -> dict:
    return next(note for note in notes if note["numero"] == numero)


def test_note_9_etic_porte_les_charges_de_personnel(db, ctx):
    """La note 9 doit totaliser les comptes 617x (racine a 3 caracteres)."""
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6171", "label": "Salaires", "debit": "12000"},
            {"account_number": "61711", "label": "Appointements", "debit": "3000"},
            {"account_number": "6174", "label": "Charges sociales", "debit": "2400"},
            {"account_number": "61741", "label": "CNSS patronale", "debit": "300"},
            {"account_number": "4432", "label": "Personnel - remunerations dues", "credit": "17700"},
        ],
        "Paie 06/2026",
    )

    resultat = notes_etic(db, ctx["company"].id, *EXERCICE)
    note = _note(resultat["notes"], 9)
    comptes = {ligne[0] for ligne in note["lignes"]}
    assert comptes == {"6171", "61711", "6174", "61741"}, comptes
    assert note["total"] == Decimal("17700.00")


def test_note_4_etic_porte_les_dotations_619(db, ctx):
    """La note 4 doit inclure les dotations 619x (racine a 3 caracteres)."""
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6193", "label": "Dot. amortissements", "debit": "1500"},
            {"account_number": "2834", "label": "Amortissements", "credit": "1500"},
        ],
        "Dotation 2026",
    )

    resultat = notes_etic(db, ctx["company"].id, *EXERCICE)
    note = _note(resultat["notes"], 4)
    soldes = {ligne[0]: ligne[2] for ligne in note["lignes"]}
    assert "6193" in soldes, soldes
    assert "2834" in soldes
    assert soldes["6193"] == Decimal("1500.00")  # dotation (debit)
    assert soldes["2834"] == Decimal("-1500.00")  # amortissements cumules (credit)
    # La note presente amortissements cumules et dotations : le total est le
    # solde algebrique des deux (0,00 sur une dotation de l'exercice).
    assert note["total"] == Decimal("0.00")


def test_notes_etic_racines_2_caracteres_inchangees(db, ctx):
    """Les notes a racines de 2 caracteres continuent de fonctionner (non-regression)."""
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "2355", "label": "Materiel informatique", "debit": "9000"},
            {"account_number": "5141", "label": "Banque", "credit": "9000"},
        ],
        "Acquisition informatique",
    )

    resultat = notes_etic(db, ctx["company"].id, *EXERCICE)
    note_3 = _note(resultat["notes"], 3)
    assert "2355" in {ligne[0] for ligne in note_3["lignes"]}
    note_7 = _note(resultat["notes"], 7)
    assert "5141" in {ligne[0] for ligne in note_7["lignes"]}
