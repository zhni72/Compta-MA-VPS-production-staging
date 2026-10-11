"""Non-regression P1 : IS au **taux de l'exercice** et exoneration de cotisation
minimale calculee sur les **dates reelles** de la societe.

Exigences du donneur d'ordre (suite P1) :
- « calcul de l'exoneration de cotisation minimale a partir des dates reelles de
  constitution / debut d'exploitation » ;
- « lors de la future reouverture 2025, recalcul fiscal complet 2025 avec le taux
  applicable a l'exercice, sans correction manuelle » : le taux est **histo risé**
  par exercice et un exercice non parametre est **refuse** (jamais de taux devine).

Defauts corriges : `compute_is` appliquait toujours les taux 2026 (memes pour un
exercice anterieur) et `calculer_is` prenait `mois_activite = 12` par defaut,
c'est-a-dire une exoneration de cotisation minimale **supposee** et non calculee.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.rates_ma import compute_is, compute_cotisation_minimale, is_rates
from app.db.seed import get_or_create_fiscal_year
from app.services.accounting import create_entry, get_journal
from app.services.fiscal_liasse import (
    calculer_is,
    date_debut_activite,
    exoneration_cotisation_minimale,
    mois_activite_effectif,
)

pytestmark = pytest.mark.usefixtures("ctx")

ANNEE = 2026


def _chiffre_affaires(db, ctx, montant: str = "400000"):
    """CA TTC de l'exercice (vente 333 333,33 HT + TVA 20 % = 400 000 TTC)."""
    company = ctx["company"]
    return create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_or_create_fiscal_year(db, company, ANNEE),
        journal=get_journal(db, company.id, "VE"),
        entry_date=date(ANNEE, 3, 15),
        label="Ventes de l'exercice",
        lines=[
            {"account_number": "5141", "label": "Encaissement", "debit": montant},
            {"account_number": "7111", "label": "Ventes", "credit": "333333.33"},
            {"account_number": "4455", "label": "TVA collectee", "credit": "66666.67"},
        ],
        validate=True,
    )


def test_taux_is_par_exercice_et_refus_si_non_parametre():
    """Le taux applique est celui de l'exercice ; sinon refus explicite.

    L'exercice 2025 est desormais **parametre** (grille transitoire : 17,5 % si le
    benefice net fiscal ne depasse pas 300 000 DH) : le refus est verifie sur un
    exercice reellement absent du registre.
    """
    assert is_rates(2026)["standard"] == Decimal("0.20")
    assert compute_is(1_000_000, annee=2026) == Decimal("200000.00")
    assert compute_is(Decimal("92000"), annee=2025) == Decimal("16100.00")  # 17,5 %
    assert compute_is(1_000_000, annee=2025) == Decimal("200000.00")  # 20 % au-dela
    with pytest.raises(ValueError) as exc:
        compute_is(1_000_000, annee=2024)
    message = str(exc.value)
    assert "2024" in message and "non paramétré" in message
    assert "IS_RATES_BY_YEAR" in message


def test_mois_activite_depuis_dates_reelles(db, ctx):
    """Les mois d'activite viennent des dates de la societe (et non d'un 12 fixe)."""
    company = ctx["company"]
    company.date_constitution = date(2024, 7, 1)
    company.date_debut_exploitation = date(2024, 9, 1)
    db.flush()

    assert date_debut_activite(db, company) == date(2024, 9, 1)
    # De septembre 2024 a decembre 2026 : 12 + 12 + 4 = 28 mois.
    assert mois_activite_effectif(db, company, ANNEE) == 28
    etat = exoneration_cotisation_minimale(db, company, ANNEE)
    assert etat["exoneree"] is True
    assert etat["fin_exoneration"] == date(2027, 9, 1)
    assert etat["duree_exoneration_mois"] == 36


def test_exoneration_expiree_apres_36_mois(db, ctx):
    """Au-dela de 36 mois : CM = max(0,25 % assiette hors TVA ; 3 000 DH), due meme en deficit."""
    company = ctx["company"]
    company.date_debut_exploitation = date(2021, 1, 1)
    db.flush()
    _chiffre_affaires(db, ctx, "400000")
    # Charges superieures au CA : exercice deficitaire (CGI art. 144 : CM due).
    create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_or_create_fiscal_year(db, company, ANNEE),
        journal=get_journal(db, company.id, "AC"),
        entry_date=date(ANNEE, 6, 30),
        label="Charges de l'exercice",
        lines=[
            {"account_number": "6111", "label": "Achats", "debit": "500000"},
            {"account_number": "4411", "label": "Fournisseur", "credit": "500000"},
        ],
        validate=True,
    )

    etat = exoneration_cotisation_minimale(db, company, ANNEE)
    assert etat["exoneree"] is False
    assert etat["mois_activite"] == 72

    calcul = calculer_is(db, company, ANNEE)
    assert calcul["mois_activite"] == 72
    assert calcul["cotisation_minimale"] == Decimal("3000.00")  # plancher
    assert calcul["exoneration_cotisation_minimale"]["source"].startswith("dates reelles")
    assert calcul["resultat_fiscal"] < 0  # deficit
    assert calcul["impot_du"] == Decimal("3000.00")  # CM due malgre le deficit
    assert calcul["taux_is_exercice"] == "0.20"


def test_exoneration_en_cours_avec_dates_reelles(db, ctx):
    """Societe recente : exoneration de cotisation minimale appliquee automatiquement."""
    company = ctx["company"]
    company.date_debut_exploitation = date(2026, 1, 1)
    db.flush()
    _chiffre_affaires(db, ctx, "400000")

    calcul = calculer_is(db, company, ANNEE)
    assert calcul["mois_activite"] == 12
    assert calcul["exoneration_cotisation_minimale"]["exoneree"] is True
    assert calcul["cotisation_minimale"] == Decimal("0.00")


def test_repli_sur_le_premier_exercice_si_dates_absentes(db, ctx):
    """Sans date saisie, le debut du premier exercice fait foi (aucune invention)."""
    company = ctx["company"]
    assert company.date_constitution is None
    company.date_constitution = date(2024, 1, 1)
    db.flush()
    assert date_debut_activite(db, company) == date(2024, 1, 1)
    assert mois_activite_effectif(db, company, ANNEE) == 36
    assert exoneration_cotisation_minimale(db, company, ANNEE)["exoneree"] is False


def test_saisie_explicite_des_mois_prime_sur_le_calcul(db, ctx):
    """Le comptable peut saisir les mois (expertise) : la valeur saisie prime."""
    company = ctx["company"]
    company.date_debut_exploitation = date(2026, 1, 1)
    db.flush()
    _chiffre_affaires(db, ctx, "400000")
    calcul = calculer_is(db, company, ANNEE, mois_activite=48)
    assert calcul["mois_activite"] == 48
    assert calcul["cotisation_minimale"] == Decimal("3000.00")
    assert calcul["exoneration_cotisation_minimale"]["source"] == "saisie"


def test_compute_cotisation_minimale_historiese():
    """Les parametres de la cotisation minimale sont historises par exercice."""
    assert compute_cotisation_minimale(400000, 12) == Decimal("0.00")  # exoneré
    assert compute_cotisation_minimale(400000, 48) == Decimal("3000.00")  # plancher
    assert compute_cotisation_minimale(4000000, 48) == Decimal("10000.00")  # 0,25 %
    with pytest.raises(ValueError):
        compute_cotisation_minimale(400000, 48, annee=2019)
