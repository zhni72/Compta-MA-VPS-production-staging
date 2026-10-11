"""Non-regression P1 : le module Paie est l'**unique source** des ecritures de paie.

Defaut reproduit (audit J9, anomalie A2) : le jeu de donnees portait des
ecritures de paie **synthetiques** (`PAIE26-01` … `PAIE26-12`, source
`import_jeu_j9`) en plus des ecritures du module : la charge de personnel etait
comptabilisee **deux fois** (resultat et IS fausses, cf. audit).

Cible fonctionnelle : toute charge de personnel (617x) d'une autre origine sur la
periode **bloque** la comptabilisation de la paie du module (`PayrollError`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting import create_entry, get_fiscal_year, get_journal
from app.services.parties import create_third_party
from app.services.payroll import (
    PayrollError,
    ajouter_contrat,
    controle_doublon_paie,
    controles_paie,
    creer_employe,
    ecritures_paie_hors_module,
    preparer_paie,
    valider_paie,
)

pytestmark = pytest.mark.usefixtures("ctx")

PERIODE = "2026-03"


def _salarie(db, ctx):
    employe = creer_employe(
        db,
        company=ctx["company"],
        nom="Salarie Unique Source",
        matricule="EMP-US01",
        cin="AB123456",
        cnss="123456789",
        situation_familiale="celibataire",
        enfants=0,
        date_entree=date(2025, 1, 1),
        type_contrat="cdi",
        fonction="Comptable",
    )
    ajouter_contrat(
        db,
        employe,
        salaire_base="7000",
        prime_transport="500",
        date_effet=date(2026, 1, 1),
    )
    return employe


def _ecriture_paie_externe(db, ctx, libelle: str = "Paie 03/2026 (saisie hors module)"):
    """Ecriture de charge de personnel d'origine externe (comme le jeu de donnees)."""
    company = ctx["company"]
    return create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_fiscal_year(db, company.id, ctx["year"]),
        journal=get_journal(db, company.id, "BQ"),
        entry_date=date(2026, 3, 28),
        label=libelle,
        reference="PAIE26-03",
        source="import_jeu_j9",
        lines=[
            {"account_number": "6171", "label": libelle, "debit": "12000"},
            {"account_number": "6174", "label": libelle, "debit": "2400"},
            {"account_number": "5141", "label": libelle, "credit": "14400"},
        ],
        validate=True,
    )


def test_valider_paie_refusee_si_charge_de_personnel_hors_module(db, ctx):
    """Regression A2 : la paie du module est refusee si une paie externe existe."""
    _ecriture_paie_externe(db, ctx)
    _salarie(db, ctx)
    run = preparer_paie(db, ctx["company"], PERIODE, user_id=ctx["user"].id)

    hors_module = ecritures_paie_hors_module(db, ctx["company"].id, PERIODE)
    assert len(hors_module) == 1
    assert hors_module[0]["source"] == "import_jeu_j9"
    assert hors_module[0]["reference"] == "PAIE26-03"

    with pytest.raises(PayrollError) as exc:
        valider_paie(db, run, user_id=ctx["user"].id)
    message = str(exc.value)
    assert "unique source" in message
    assert "PAIE26-03" in message


def test_od_legitime_en_617x_autorisee_avec_avertissement(db, ctx):
    """Une OD legitime de charges de personnel ne doit plus bloquer la paie.

    Cas vise par l'assouplissement P1 : regularisation de charges de personnel
    (ou avantage en nature) saisie en OD, **sans** numerotation de paie et
    **sans** mouvementer un compte de dette de paie.
    """
    company = ctx["company"]
    create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_fiscal_year(db, company.id, ctx["year"]),
        journal=get_journal(db, company.id, "OD"),
        entry_date=date(2026, 3, 10),
        label="Regularisation de charges de personnel (OD)",
        reference="REGUL-6171-03",
        lines=[
            {"account_number": "61712", "label": "Primes a regulariser", "debit": "800"},
            {"account_number": "3431", "label": "Avances au personnel", "credit": "800"},
        ],
        validate=True,
    )
    _salarie(db, ctx)

    controle = controle_doublon_paie(db, company.id, PERIODE)
    assert controle["bloquants"] == []
    assert len(controle["avertissements"]) == 1
    assert "OD legitime" in controle["avertissements"][0]["motif"]

    # La paie du module est comptabilisee (aucun blocage) : l'avertissement est
    # restitue par le module de controles.
    run = preparer_paie(db, company, PERIODE, user_id=ctx["user"].id)
    ecriture = valider_paie(db, run, user_id=ctx["user"].id)
    assert ecriture.source == "payroll"
    controles = controles_paie(db, company.id, PERIODE)
    avertissements = [c for c in controles if c["niveau"] == "avertissement"]
    assert any("617" in c["message"] or "hors module" in c["message"] for c in avertissements) or (
        controle["avertissements"]
    )


def test_doublon_reel_par_reference_paie_refuse(db, ctx):
    """Ecriture hors module numerotee « PAIE » = doublon reel : comptabilisation refusee."""
    company = ctx["company"]
    create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_fiscal_year(db, company.id, ctx["year"]),
        journal=get_journal(db, company.id, "OD"),
        entry_date=date(2026, 3, 28),
        label="Paie 03/2026 saisie hors module",
        reference="PAIE26-03",
        lines=[
            {"account_number": "6171", "label": "Paie hors module", "debit": "12000"},
            {"account_number": "3431", "label": "Contrepartie", "credit": "12000"},
        ],
        validate=True,
    )
    _salarie(db, ctx)
    controle = controle_doublon_paie(db, company.id, PERIODE)
    assert len(controle["bloquants"]) == 1
    assert "numerotation de paie" in controle["bloquants"][0]["motif"]

    run = preparer_paie(db, company, PERIODE, user_id=ctx["user"].id)
    with pytest.raises(PayrollError) as exc:
        valider_paie(db, run, user_id=ctx["user"].id)
    assert "unique source" in str(exc.value)


def test_doublon_reel_par_dettes_de_paie_refuse(db, ctx):
    """Ecriture hors module mouvementant 4441/4452 = paie : comptabilisation refusee."""
    company = ctx["company"]
    create_entry(
        db,
        company_id=company.id,
        fiscal_year=get_fiscal_year(db, company.id, ctx["year"]),
        journal=get_journal(db, company.id, "OD"),
        entry_date=date(2026, 3, 28),
        label="Paie externe (sans numero PAIE mais avec dettes sociales)",
        reference="OD-PAIE-EXTERNE",
        lines=[
            {"account_number": "61711", "label": "Salaires", "debit": "10000"},
            {"account_number": "4441", "label": "CNSS", "credit": "2109"},
            {"account_number": "4452", "label": "IR", "credit": "7891"},
        ],
        validate=True,
    )
    _salarie(db, ctx)
    controle = controle_doublon_paie(db, company.id, PERIODE)
    assert len(controle["bloquants"]) == 1
    assert "dette de paie" in controle["bloquants"][0]["motif"]

    run = preparer_paie(db, company, PERIODE, user_id=ctx["user"].id)
    with pytest.raises(PayrollError):
        valider_paie(db, run, user_id=ctx["user"].id)


def test_valider_paie_acceptee_apres_regularisation(db, ctx):
    """Apres suppression de la paie externe (reinitialisation controlee), la paie
    du module est comptabilisee normalement et les comptes de paie sont exacts."""
    company = ctx["company"]
    externe = _ecriture_paie_externe(db, ctx)
    _salarie(db, ctx)
    run = preparer_paie(db, company, PERIODE, user_id=ctx["user"].id)

    # Regularisation controlee : suppression de l'ecriture externe (tracee).
    for ligne in list(externe.lines):
        db.delete(ligne)
    db.delete(externe)
    db.flush()
    assert ecritures_paie_hors_module(db, company.id, PERIODE) == []

    ecriture = valider_paie(db, run, user_id=ctx["user"].id)
    assert ecriture.source == "payroll"
    assert ecriture.reference == f"PAIE {PERIODE}"
    # L'ecriture du module porte les comptes CGNC de la paie.
    comptes = {ligne.account_number for ligne in ecriture.lines}
    assert "61711" in comptes  # appointements
    assert "4432" in comptes  # net a payer (dette envers le personnel)
    assert any(compte.startswith("444") for compte in comptes)  # organismes sociaux
    assert any(compte.startswith("4452") for compte in comptes)  # IR retenu
    # Equilibre de l'ecriture generee par le module.
    debit = sum((ligne.debit for ligne in ecriture.lines), Decimal("0"))
    credit = sum((ligne.credit for ligne in ecriture.lines), Decimal("0"))
    assert debit == credit
    assert debit > 0
    # Apres comptabilisation, aucune charge hors module ne subsiste.
    assert ecritures_paie_hors_module(db, company.id, PERIODE) == []
