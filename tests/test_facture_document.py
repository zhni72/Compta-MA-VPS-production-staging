"""Non-regression P0.4 : coherence ligne a ligne des documents de facture.

Defaut signale en recette (A4) : un document de facture pouvait presenter une
**ligne a 0,00** et une **ventilation de TVA a zero** alors que les totaux
generaux etaient corrects, et etre transmis au client ou au fournisseur.

Correction : les lignes a montant nul sont refusees des la **validation** et
aucun **PDF** incoherent ne peut plus etre produit (`DocumentIncoherentError`),
l'ecran d'impression affichant un avertissement explicite.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.invoicing import (
    AccountingError,
    add_line,
    controles_coherence_facture,
    create_invoice,
    validate_invoice,
)
from app.services.parties import create_third_party
from app.services.pdf_documents import DocumentIncoherentError, pdf_facture

pytestmark = pytest.mark.usefixtures("ctx")

CONNEXION = {"email": "admin@test.ma", "password": "MotDePasse123"}


def _client(db, ctx):
    return create_third_party(
        db,
        company=ctx["company"],
        kind="client",
        name="Client Document SARL",
        ice="001122334000045",
        fiscal_id="2233445",
        payment_terms_days=0,
    )


def _facture(db, ctx, *, avec_ligne_nulle: bool = False):
    tiers = _client(db, ctx)
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=tiers,
        invoice_date=date(2026, 3, 3),
        lines=[
            {
                "designation": "Prestation de service",
                "quantity": "1",
                "unit_price": "9000",
                "vat_rate": "20",
                "account_number": "7111",
            }
        ],
    )
    if avec_ligne_nulle:
        add_line(
            db,
            facture,
            designation="Ligne sans montant",
            quantity="1",
            unit_price="0",
            vat_rate="20",
            account_number="7111",
        )
    return facture


def _incoherente(db, ctx):
    """Facture validee dont la ligne est mise a zero (simulation du defaut A4)."""
    facture = _facture(db, ctx)
    validate_invoice(db, facture, user_id=ctx["user"].id)
    ligne = facture.lines[0]
    ligne.line_ht = Decimal("0")
    ligne.line_vat = Decimal("0")
    ligne.line_ttc = Decimal("0")
    db.flush()
    return facture


def test_facture_coherente_produit_un_pdf_conforme(db, ctx):
    """Cas nominal (FA26-12) : lignes, ventilation et totaux reconcilies."""
    facture = _facture(db, ctx)
    validate_invoice(db, facture, user_id=ctx["user"].id)

    assert controles_coherence_facture(facture) == []
    pdf = pdf_facture(db, facture)
    assert pdf.startswith(b"%PDF-")
    assert facture.lines[0].line_ht == Decimal("9000.00")
    assert facture.lines[0].line_vat == Decimal("1800.00")
    assert facture.total_ttc == Decimal("10800.00")


def test_validation_refuse_une_ligne_a_montant_nul(db, ctx):
    """Une ligne « designee » a 0,00 ne doit plus pouvoir etre validee (A4)."""
    facture = _facture(db, ctx, avec_ligne_nulle=True)
    anomalies = controles_coherence_facture(facture)
    assert any("montants HT/TVA/TTC a zero" in anomalie for anomalie in anomalies), anomalies

    with pytest.raises(AccountingError) as exc:
        validate_invoice(db, facture, user_id=ctx["user"].id)
    assert "ligne 2" in str(exc.value)
    assert "zero" in str(exc.value)


def test_pdf_refuse_un_document_incoherent(db, ctx):
    """Simulation du defaut A4 : ligne a zero en base -> PDF refuse."""
    facture = _incoherente(db, ctx)
    anomalies = controles_coherence_facture(facture)
    assert any("a zero" in anomalie for anomalie in anomalies), anomalies
    with pytest.raises(DocumentIncoherentError) as exc:
        pdf_facture(db, facture)
    assert "Document refuse" in str(exc.value)


def test_pdf_refuse_une_facture_sans_ligne_avec_totaux(db, ctx):
    """Facture dont les totaux subsistent sans lignes : document refuse."""
    facture = _facture(db, ctx)
    validate_invoice(db, facture, user_id=ctx["user"].id)
    for ligne in list(facture.lines):
        facture.lines.remove(ligne)
        db.delete(ligne)
    db.flush()

    anomalies = controles_coherence_facture(facture)
    assert any("aucune ligne" in anomalie for anomalie in anomalies), anomalies
    with pytest.raises(DocumentIncoherentError):
        pdf_facture(db, facture)


def test_ecrans_signalent_une_facture_incoherente(client, db, ctx):
    """Detail et apercu avant impression affichent l'avertissement."""
    facture = _incoherente(db, ctx)
    client.post("/connexion", data=CONNEXION, follow_redirects=False)

    for chemin in (f"/factures/{facture.id}", f"/factures/{facture.id}/impression"):
        page = client.get(chemin)
        assert page.status_code == 200, chemin
        assert "Document incohérent" in page.text, chemin
        assert "montants HT/TVA/TTC a zero" in page.text, chemin


def test_pdf_via_http_refuse_et_informe(client, db, ctx):
    """Le telechargement est refuse avec un message, pas un fichier incoherent."""
    facture = _incoherente(db, ctx)
    client.post("/connexion", data=CONNEXION, follow_redirects=False)
    reponse = client.get(f"/factures/{facture.id}/pdf", follow_redirects=False)
    assert reponse.status_code == 303
    assert reponse.headers["location"].startswith(f"/factures/{facture.id}?msg=")
    assert "Document+non+g%C3%A9n%C3%A9r%C3%A9" in reponse.headers["location"]
    assert "facture+incoherente" in reponse.headers["location"]
    assert "level=error" in reponse.headers["location"]

