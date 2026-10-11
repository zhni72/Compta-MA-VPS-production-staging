"""Tests du service PDF (moteur ReportLab retenu au POC du jalon J0).

L'import de `reportlab` est ignore proprement si la dependance n'est pas
installee : les tests de rendu sont alors sautes, sans casser la suite.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.pdf import (
    TAILLE_MAX_GREFFE,
    Colonne,
    Document,
    PdfError,
    Tableau,
    controle_taille_pdf,
    moteur_disponible,
    rendre_pdf,
)

pytest.importorskip("reportlab", reason="moteur PDF ReportLab non installe")


def document_simple() -> Document:
    """Document de test : un tableau de trois lignes avec totaux."""
    return Document(
        titre="Balance generale — test",
        sous_titre="Compta MA",
        entete=["Societe Demo — IF 1234567"],
        tableaux=[
            Tableau(
                titre="Comptes de charges",
                colonnes=[
                    Colonne("Compte"),
                    Colonne("Libelle"),
                    Colonne("Debit", alignement="right"),
                ],
                lignes=[
                    ["61455", "Frais de telephone", "4 162,05"],
                    ["61473", "Frais bancaires", "696,00"],
                ],
                total=["TOTAL", "", "4 858,05"],
            )
        ],
        pied="Document de travail",
        filigrane="BROUILLON",
    )


def test_moteur_pdf_disponible():
    """Le moteur de rendu est ReportLab (decision D1 du CDC GLOBAL)."""
    assert moteur_disponible().startswith("reportlab")


def test_rendu_pdf_reel():
    """Le rendu produit un PDF valide, de taille conforme au depot au greffe."""
    pdf = rendre_pdf(document_simple())

    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf[-2048:]
    assert len(pdf) > 1000
    assert len(pdf) <= TAILLE_MAX_GREFFE  # limite du portail greffe (10 Mo)
    assert controle_taille_pdf(pdf) == len(pdf)


def test_controle_taille_refuse_un_pdf_trop_volumineux():
    """Un PDF depassant la limite demandee est refuse (controle bloquant)."""
    pdf = rendre_pdf(document_simple())
    with pytest.raises(PdfError):
        controle_taille_pdf(pdf, limite=len(pdf) - 1)
    with pytest.raises(PdfError):
        rendre_pdf(document_simple(), taille_max=len(pdf) - 1)


def test_document_vide_reste_rendu():
    """Un document sans tableau ne doit pas lever (bordereau vide)."""
    pdf = rendre_pdf(Document(titre="Bordereau", entete=["Sans tableau"]))
    assert pdf.startswith(b"%PDF-")


def test_montants_decimaux_rendus_en_texte():
    """Les montants Decimal sont convertis proprement (aucune exception)."""
    document = Document(
        titre="Controle des montants",
        tableaux=[
            Tableau(
                colonnes=[Colonne("Montant")],
                lignes=[[str(Decimal("198.61"))]],
            )
        ],
    )
    assert rendre_pdf(document).startswith(b"%PDF-")
