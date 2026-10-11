"""Non-regression P1 : soldes crediteurs de tresorerie (reclassement CGNC).

Regle : un compte de tresorerie **debiteur** (banques, cheques postaux,
tresorerie generale, autres etablissements) ne peut pas presenter un solde
crediteur : un solde crediteur est un **concours bancaire** a reclasser en
**tresorerie-passif** (`5541` / `5548`). Une **caisse** credi trice reste une
anomalie de saisie (aucun compte de caisse crediteur au CGNC).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.seed import get_or_create_fiscal_year
from app.services.accounting import AccountingError, create_entry, get_journal
from app.services.tresorerie import (
    controler_tresorerie,
    reclasser_solde_crediteur,
    reclasser_soldes_crediteurs,
    reference_reclassement,
)

pytestmark = pytest.mark.usefixtures("ctx")

MOTIF = "Reclassement du decouvert bancaire en tresorerie-passif (5541)"


def _ecriture(db, ctx, lignes: list[dict], libelle: str):
    company = ctx["company"]
    return create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_or_create_fiscal_year(db, company, ctx["year"]),
        journal=get_journal(db, company.id, "OD"),
        entry_date=date(2026, 6, 30),
        label=libelle,
        lines=lignes,
        validate=True,
    )


def _banque_crediteurs(db, ctx, montant: str = "5000"):
    """Charges payees alors que la banque ne presente que 1000 DH : decouvert."""
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "5141", "label": "Encaissement client", "debit": "1000"},
            {"account_number": "3421", "label": "Client", "credit": "1000"},
        ],
        "Encaissement",
    )
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6148", "label": "Charges externes", "debit": "6000"},
            {"account_number": "5141", "label": "Paiement fournisseur", "credit": "6000"},
        ],
        "Paiement",
    )
    return controler_tresorerie(db, ctx["company"].id, 2026)


def test_controle_detecte_le_solde_crediteur(db, ctx):
    controle = _banque_crediteurs(db, ctx)
    assert controle["conforme"] is False
    constat = controle["soldes_crediteurs"][0]
    assert constat["compte"] == "5141"
    assert constat["solde"] == Decimal("-5000.00")
    assert constat["compte_reclassement"] == "5541"
    assert controle["total_a_reclasser"] == Decimal("5000.00")


def test_reclassement_vers_tresorerie_passif(db, ctx):
    _banque_crediteurs(db, ctx)
    resultat = reclasser_solde_crediteur(
        db, ctx["company"], compte="5141", year=2026, motif=MOTIF, user_id=ctx["user"].id
    )
    assert resultat["compte_passif"] == "5541"
    assert resultat["montant"] == Decimal("5000.00")
    assert resultat["reference"] == reference_reclassement("5141", 2026)

    controle = controler_tresorerie(db, ctx["company"].id, 2026)
    assert controle["conforme"] is True
    # Le decouvert figure desormais au passif (5541) et non plus a l'actif.
    from app.services.reporting import movements

    soldes = {
        ligne["account_number"]: ligne["solde"]
        for ligne in movements(db, ctx["company"].id, date(2026, 1, 1), date(2026, 12, 31))
    }
    assert soldes["5141"] == Decimal("0.00")
    assert soldes["5541"] == Decimal("-5000.00")


def test_reclassement_idempotent_et_motive(db, ctx):
    _banque_crediteurs(db, ctx)
    with pytest.raises(AccountingError) as exc:
        reclasser_solde_crediteur(
            db, ctx["company"], compte="5141", year=2026, motif="court", user_id=ctx["user"].id
        )
    assert "motif" in str(exc.value).lower()

    reclasser_solde_crediteur(
        db, ctx["company"], compte="5141", year=2026, motif=MOTIF, user_id=ctx["user"].id
    )
    with pytest.raises(AccountingError) as exc:
        reclasser_solde_crediteur(
            db, ctx["company"], compte="5141", year=2026, motif=MOTIF, user_id=ctx["user"].id
        )
    assert "deja effectue" in str(exc.value)


def test_caisse_crediteurs_non_reclassable(db, ctx):
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "5161", "label": "Sortie de caisse", "credit": "200"},
            {"account_number": "6148", "label": "Fournitures", "debit": "200"},
        ],
        "Sortie de caisse sans alimentation",
    )
    controle = controler_tresorerie(db, ctx["company"].id, 2026)
    constats = {c["compte"]: c for c in controle["soldes_crediteurs"]}
    assert "5161" in constats
    assert constats["5161"]["compte_reclassement"] is None
    with pytest.raises(AccountingError) as exc:
        reclasser_solde_crediteur(
            db, ctx["company"], compte="5161", year=2026, motif=MOTIF, user_id=ctx["user"].id
        )
    assert "caisse" in str(exc.value).lower()

    resultat = reclasser_soldes_crediteurs(
        db, ctx["company"], 2026, motif=MOTIF, user_id=ctx["user"].id
    )
    assert resultat["effectues"] == []
    assert len(resultat["non_reclassables"]) == 1
    assert resultat["conforme_apres"] is False


def test_reclassement_automatique_tous_comptes(db, ctx):
    _banque_crediteurs(db, ctx)
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "5148", "label": "Autre etablissement", "credit": "1500"},
            {"account_number": "6148", "label": "Frais", "debit": "1500"},
        ],
        "Frais bancaires autre etablissement",
    )
    resultat = reclasser_soldes_crediteurs(
        db, ctx["company"], 2026, motif=MOTIF, user_id=ctx["user"].id
    )
    comptes = {reclassement["compte"]: reclassement for reclassement in resultat["effectues"]}
    assert set(comptes) == {"5141", "5148"}
    assert comptes["5141"]["compte_passif"] == "5541"
    assert comptes["5148"]["compte_passif"] == "5548"
    assert resultat["conforme_apres"] is True
    assert resultat["non_reclassables"] == []
