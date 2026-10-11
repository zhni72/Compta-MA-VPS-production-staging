"""Tests des outils d'import : mapping PCGE, tableau d'achat, plan comptable.

Ces outils manipulent des donnees fiscales (comptes de charge, TVA deductible) :
les regles sont verrouillees par des tests pour qu'une erreur de mapping
(6141 « Etudes, recherches et documentation » au lieu de 61473 « Frais et
commissions sur services bancaires ») ou une ligne a TVA nulle ne passe plus
inapercue.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from tools import charger_plan_comptable, import_achats_fournisseurs as outil_import
from tools import normalize_fiscal_ids as normalisation

PROJET = Path(__file__).resolve().parents[1]


def test_mapping_des_comptes_de_charge_pcge():
    """L'ancien compte 6141 est corrige en 61473 ; les autres sont conserves."""
    compte, motif = outil_import.compte_pcge("6141")
    assert compte == "61473"
    assert "6141 -> 61473" in motif
    assert "services bancaires" in motif

    compte, motif = outil_import.compte_pcge("61455")
    assert compte == "61455"
    assert motif == ""


def test_tableau_dachat_du_dossier():
    """Le tableau d'achat de reference ne contient que des lignes deductibles."""
    lignes = outil_import.lire_source(outil_import.SOURCE_DEFAUT)

    assert len(lignes) == 42
    assert all(ligne["tva"] > 0 for ligne in lignes)  # frais exoneres retires
    assert {ligne["compte_source"] for ligne in lignes} == {"61473", "61455"}
    assert all(ligne["compte_source"] != "6141" for ligne in lignes)
    assert sum((ligne["ht"] for ligne in lignes), Decimal("0")) == Decimal("4858.05")
    assert sum((ligne["tva"] for ligne in lignes), Decimal("0")) == Decimal("902.05")
    assert sum((ligne["ttc"] for ligne in lignes), Decimal("0")) == Decimal("5760.10")
    # Les IF sont nettoyes des separateurs de saisie.
    assert {ligne["if_frs"] for ligne in lignes} == {"1084612", "1086826"}


def test_plan_comptable_de_reference():
    """Le plan PCGE du projet contient bien 890 comptes et les comptes TVA."""
    comptes = {compte["number"]: compte for compte in charger_plan_comptable.lire_plan(
        PROJET / "app" / "data" / "plan_comptable_cgnc.csv"
    )}

    assert len(comptes) == 890
    assert comptes["34551"]["label"] == "Etat - TVA récupérable sur immobilisations"
    assert comptes["34552"]["label"] == "Etat - TVA récupérable sur charges"
    # Libellé repris tel quel du PCGE (orthographe d'origine conservee).
    assert comptes["61473"]["label"] == "Frais et commisions sur services bancaires"
    assert comptes["3455"]["is_collectif"] is True


def test_comptes_standards_crees_si_le_plan_est_incomplet(db):
    """`preparer_comptes` cree les comptes manquants (contrainte FK du plan)."""
    crees = outil_import.preparer_comptes(
        db, [{"compte_source": "6141"}, {"compte_source": "61455"}]
    )

    assert {"34551", "34552", "61455", "61473"} <= set(crees)
    assert outil_import.preparer_comptes(db, []) == []  # idempotent


def test_identifiants_fiscaux_equivalents_et_sans_transformation():
    """Norme IF (7 ou 8 chiffres, tel quel) et tolerance de migration."""
    # Les separateurs de saisie sont retires, sans autre transformation.
    assert outil_import.if_numerique("108 6826") == "1086826"
    # Meme fournisseur : IF identique, et forme zfill heritee (7 vs 8 chiffres).
    assert outil_import.identifiants_equivalents("1084612", "1084612") is True
    assert outil_import.identifiants_equivalents("01084612", "1084612") is True
    assert outil_import.identifiants_equivalents("1084612", "01084612") is True
    assert outil_import.identifiants_equivalents("1086826", "1084612") is False
    assert outil_import.identifiants_equivalents(None, "1084612") is False


def test_retrait_du_zero_initial_herite():
    """L'outil de maintenance sait retirer le zero ajoute par l'ancienne regle."""
    assert normalisation.zero_initial_a_retirer("01084612") == "1084612"
    assert normalisation.zero_initial_a_retirer("01086826") == "1086826"
    assert normalisation.zero_initial_a_retirer("01234567") == "1234567"
    # Un IF de 7 chiffres (norme) n'est jamais modifie.
    assert normalisation.zero_initial_a_retirer("1084612") is None
    # Un IF de 8 chiffres ne commencant pas par 0 n'est jamais modifie.
    assert normalisation.zero_initial_a_retirer("12345678") is None
    assert normalisation.zero_initial_a_retirer(None) is None
