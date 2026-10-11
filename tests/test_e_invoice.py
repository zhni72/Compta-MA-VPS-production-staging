"""Tests de la facture électronique (P2.3).

Vérifie le contrôle des **mentions obligatoires**, le **fichier structuré** (format
interne explicitement **non conforme** : la spécification DGI n'est pas publiée —
incohérence A24), le **cycle de vie** (généré → transmis → accepté/rejeté), le
**canal DGI paramétrable** (simulation par défaut : aucune requête réseau) et les
**contrôles de dossier**.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import (
    AuditLog,
    CANAL_API,
    CANAL_MANUEL,
    CONFORMITE_NON_VALIDEE,
    FORMAT_INTERNE,
    STATUT_ACCEPTE,
    STATUT_ENVOYE,
    STATUT_GENERE,
    STATUT_REJETE,
)
from app.services import e_invoice
from app.services.invoicing import create_invoice, validate_invoice
from app.services.parties import create_third_party

pytestmark = pytest.mark.usefixtures("ctx")

ANNEE = 2026


def _client(db, ctx, **extra):
    """Fiche client avec ICE (exigé à la vente) et identifiant fiscal."""
    parametres = {
        "company": ctx["company"],
        "kind": "client",
        "name": "Client E-Facture SARL",
        "ice": "001987654000012",
        "fiscal_id": "2045678",
        "rc": "98765",
        "address": "45 avenue de la Facture",
        "city": "Rabat",
    }
    parametres.update(extra)
    return create_third_party(db, **parametres)


def _facture(db, ctx, *, valider: bool = True, tiers=None, numero: bool = True):
    """Facture de vente (validée par defaut) prête pour la facture électronique."""
    client = tiers or _client(db, ctx)
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 2, 10),
        due_date=date(2026, 3, 12),
        payment_mode="virement",
        reference="BC-2026-0042",
        lines=[
            {
                "designation": "Prestation de conseil",
                "quantity": 2,
                "unit_price": Decimal("5000"),
                "vat_rate": Decimal("20"),
                "account_number": "7121",
            }
        ],
    )
    if valider:
        validate_invoice(db, facture, user_id=ctx["user"].id)
    else:
        db.commit()
    if numero and not facture.number:
        facture.number = "FV2026-0001"
        db.commit()
    return facture


def _codes(controles: list[dict]) -> dict[str, dict]:
    """Contrôles indexés par code de mention."""
    return {controle["code"]: controle for controle in controles}


# ---------------------------------------------------------------------------
# Mentions obligatoires
# ---------------------------------------------------------------------------
def test_catalogue_des_mentions_obligatoires():
    """Le catalogue couvre identités, identifiants, contenu et paiement."""
    mentions = e_invoice.mentions_obligatoires()
    codes = {mention["code"] for mention in mentions}
    assert {"numero", "date", "vendeur_if", "vendeur_ice", "client_identite"} <= codes
    assert {"designation", "quantite_prix", "taux_tva", "montants"} <= codes
    assert len([m for m in mentions if m["niveau"] == "bloquant"]) >= 10
    # Les références citées sont vérifiables (CGI 2026) : l'article 145 ne porte PAS
    # les mentions de la facture (il traite de la tenue de la comptabilité) — A23.
    references = " ".join(mention["reference"] for mention in mentions)
    assert "CGI art. 146" in references
    assert "art. 145" not in references


def test_facture_validee_ne_signale_aucun_bloquant(db, ctx):
    """Une facture validée complète passe tous les contrôles bloquants."""
    facture = _facture(db, ctx)
    controles = e_invoice.controles_mentions(db, ctx["company"], facture)
    assert _codes(controles)["montants"]["present"] is True
    assert _codes(controles)["vendeur_ice"]["present"] is True
    assert e_invoice.controles_bloquants(controles) == []
    assert e_invoice.mentions_manquantes(controles) == []


def test_facture_brouillon_et_numero_manquant_sont_bloquants(db, ctx):
    """Une facture non validée et une facture sans numéro bloquent la génération."""
    brouillon = _facture(db, ctx, valider=False)
    bloquants = e_invoice.controles_bloquants(
        e_invoice.controles_mentions(db, ctx["company"], brouillon)
    )
    assert [controle["code"] for controle in bloquants] == ["facture_validee"]
    with pytest.raises(e_invoice.EInvoiceError) as erreur:
        e_invoice.generer_document(db, ctx["company"], brouillon)
    assert "facture_validee" not in str(erreur.value)  # le message est en français
    assert "Facture validée" in str(erreur.value)

    validee = _facture(db, ctx, numero=False)
    validee.number = None
    db.commit()
    bloquants = e_invoice.controles_bloquants(
        e_invoice.controles_mentions(db, ctx["company"], validee)
    )
    assert "numero" in [controle["code"] for controle in bloquants]


def test_identifiant_client_absent_est_un_avertissement(db, ctx, monkeypatch):
    """L'identifiant fiscal du client manquant est signalé sans bloquer."""
    monkeypatch.setattr(settings, "require_ice_on_sales", False)
    client = _client(db, ctx, fiscal_id=None, ice=None)
    facture = _facture(db, ctx, tiers=client)
    controles = e_invoice.controles_mentions(db, ctx["company"], facture)
    assert _codes(controles)["client_if"]["present"] is False
    assert _codes(controles)["client_if"]["niveau"] == "avertissement"
    assert e_invoice.controles_bloquants(controles) == []
    assert [m["code"] for m in e_invoice.mentions_manquantes(controles)] == ["client_if"]


# ---------------------------------------------------------------------------
# Fichier et conformite
# ---------------------------------------------------------------------------
def test_fichier_structure_et_conformite_non_validee(db, ctx):
    """Le fichier est un format interne portant explicitement sa non-conformité."""
    facture = _facture(db, ctx)
    xml = e_invoice.build_e_invoice_xml(
        db, ctx["company"], facture, pdf_nom="Facture_FV2026-0001.pdf"
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert f'<FactureElectronique version="{FORMAT_INTERNE}" type="vente">' in xml
    assert "<nom>Atlas Test SARL</nom>" in xml
    assert "<nom>Client E-Facture SARL</nom>" in xml
    assert f"<numero>{facture.number}</numero>" in xml
    assert "<date>2026-02-10</date>" in xml
    assert "<tauxTva>20.00</tauxTva>" in xml
    assert "<montantHT>10000.00</montantHT>" in xml
    assert "<totalTva>2000.00</totalTva>" in xml
    assert "<totalTtc>12000.00</totalTtc>" in xml
    assert "<piece>Facture_FV2026-0001.pdf</piece>" in xml
    assert f"<conformite>{CONFORMITE_NON_VALIDEE}</conformite>" in xml
    assert e_invoice.xml_filename(ctx["company"], facture) == (
        f"FactureElectronique_{facture.number}.xml"
    )

    validation = e_invoice.valider_conformite(xml)
    assert validation["valide"] is None  # jamais « conforme » sans schéma officiel
    assert "A24" in validation["message"]


def test_valider_conformite_avec_schema_fourni(db, ctx, tmp_path):
    """Dès qu'un schéma est fourni, la validation devient réelle (lxml)."""
    facture = _facture(db, ctx)
    xml = e_invoice.build_e_invoice_xml(db, ctx["company"], facture)
    schema = tmp_path / "facture.xsd"
    schema.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="FactureElectronique" type="xs:anyType"/>'
        "</xs:schema>",
        encoding="utf-8",
    )
    assert e_invoice.valider_conformite(xml, schema=str(schema))["valide"] is True
    mauvais = tmp_path / "strict.xsd"
    mauvais.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="FactureElectronique"><xs:complexType>'
        '<xs:sequence><xs:element name="inexistant"/>'
        "</xs:sequence><xs:anyAttribute/></xs:complexType></xs:element></xs:schema>",
        encoding="utf-8",
    )
    refuse = e_invoice.valider_conformite(xml, schema=str(mauvais))
    assert refuse["valide"] is False
    assert "Écarts au schéma" in refuse["message"]


# ---------------------------------------------------------------------------
# Cycle de vie : generation, canal DGI, accuse de reception
# ---------------------------------------------------------------------------
def test_generer_document_hash_et_regeneration(db, ctx):
    """Le document est généré avec son empreinte SHA-256 et reste régénérable."""
    facture = _facture(db, ctx)
    objet = e_invoice.generer_document(
        db, ctx["company"], facture, pdf_nom="Facture.pdf", user_id=ctx["user"].id
    )
    db.commit()
    assert objet.statut == STATUT_GENERE
    assert objet.statut_libelle.startswith("Généré")
    assert objet.format == FORMAT_INTERNE
    assert len(objet.hash_sha256 or "") == 64
    assert "<FactureElectronique" in (objet.xml or "")
    assert "non publiée" in (objet.notes or "")
    assert "A24" in (objet.notes or "")
    assert e_invoice.document(db, ctx["company"].id, facture.id).id == objet.id

    # Régénération autorisée tant que le document n'est pas terminal (idempotente)
    e_invoice.generer_document(db, ctx["company"], facture)
    db.commit()
    assert len(e_invoice.list_documents(db, ctx["company"].id)) == 1
    journal = (
        db.execute(select(AuditLog).where(AuditLog.action == "E_INVOICE_GENERATED"))
        .scalars()
        .all()
    )
    assert len(journal) == 2


def test_envoyer_par_simulation_sans_endpoint(db, ctx):
    """Sans endpoint configuré, la transmission est une simulation (aucun réseau)."""
    facture = _facture(db, ctx)
    objet = e_invoice.generer_document(db, ctx["company"], facture)
    assert settings.e_invoice_endpoint is None
    objet = e_invoice.envoyer(db, objet, jour=date(2026, 3, 1), user_id=ctx["user"].id)
    db.commit()
    assert objet.statut == STATUT_ENVOYE
    assert objet.canal == CANAL_API
    assert objet.envoye_le == date(2026, 3, 1)
    assert objet.identifiant_dgi is None
    assert "simulation=True" in (objet.accuse or "")
    assert "repli EFI" in (objet.accuse or "")


def test_envoyer_refuse_canal_inconnu_et_le_canal_manuel_est_accepte(db, ctx):
    """Un canal inconnu est refusé ; le dépôt manuel (repli EFI) est accepté."""
    facture = _facture(db, ctx)
    objet = e_invoice.generer_document(db, ctx["company"], facture)
    with pytest.raises(e_invoice.EInvoiceError):
        e_invoice.envoyer(db, objet, canal="courrier")
    assert objet.statut == STATUT_GENERE
    objet = e_invoice.envoyer(db, objet, canal=CANAL_MANUEL)
    assert objet.canal == CANAL_MANUEL
    assert objet.statut == STATUT_ENVOYE


def test_accuse_de_reception_accepte_puis_document_fige(db, ctx):
    """L'accusé de réception accepté clôt le document (plus de régénération)."""
    facture = _facture(db, ctx)
    objet = e_invoice.generer_document(db, ctx["company"], facture)
    with pytest.raises(e_invoice.EInvoiceError):
        e_invoice.enregistrer_accuse(db, objet, identifiant_dgi="DGI")  # non transmis
    objet = e_invoice.envoyer(db, objet, jour=date(2026, 3, 1))
    objet = e_invoice.enregistrer_accuse(
        db,
        objet,
        identifiant_dgi="DGI-EF-2026-0001",
        accuse="Facture acceptée par la plateforme",
        jour=date(2026, 3, 2),
        user_id=ctx["user"].id,
    )
    db.commit()
    assert objet.statut == STATUT_ACCEPTE
    assert objet.identifiant_dgi == "DGI-EF-2026-0001"
    assert objet.accuse_le == date(2026, 3, 2)
    with pytest.raises(e_invoice.EInvoiceError):
        e_invoice.enregistrer_accuse(db, objet)
    with pytest.raises(e_invoice.EInvoiceError):
        e_invoice.generer_document(db, ctx["company"], facture)
    with pytest.raises(e_invoice.EInvoiceError):
        e_invoice.envoyer(db, objet)


def test_rejet_exige_un_motif_et_fige_le_document(db, ctx):
    """Un rejet doit être motivé ; le document rejeté est terminal."""
    facture = _facture(db, ctx)
    objet = e_invoice.generer_document(db, ctx["company"], facture)
    objet = e_invoice.envoyer(db, objet)
    with pytest.raises(e_invoice.EInvoiceError):
        e_invoice.enregistrer_accuse(db, objet, accepte=False)
    objet = e_invoice.enregistrer_accuse(
        db, objet, accepte=False, accuse="ICE du client invalide"
    )
    db.commit()
    assert objet.statut == STATUT_REJETE
    assert objet.accuse == "ICE du client invalide"
    assert objet.statut_libelle.startswith("Rejeté")


# ---------------------------------------------------------------------------
# Controles de dossier et situation
# ---------------------------------------------------------------------------
def test_controles_e_facturation_et_situation(db, ctx):
    """Les contrôles de dossier signalent les documents à traiter, sans bloquant."""
    facture = _facture(db, ctx)
    codes = {
        controle["code"]: controle
        for controle in e_invoice.controles_e_facturation(db, ctx["company"], annee=ANNEE)
    }
    assert codes["efacture.canal_non_configure"]["niveau"] == "information"
    assert codes["efacture.specification_absente"]["niveau"] == "information"
    assert "A24" in codes["efacture.specification_absente"]["message"]
    assert codes["efacture.document_manquant"]["niveau"] == "avertissement"
    assert facture.number in codes["efacture.document_manquant"]["message"]
    assert e_invoice.controles_bloquants_dossier(list(codes.values())) == []

    objet = e_invoice.generer_document(db, ctx["company"], facture)
    db.commit()
    codes = {
        controle["code"]: controle
        for controle in e_invoice.controles_e_facturation(db, ctx["company"], annee=ANNEE)
    }
    assert "efacture.transmission_en_attente" in codes
    assert "efacture.document_manquant" not in codes

    e_invoice.envoyer(db, objet)
    db.commit()
    codes = {
        controle["code"]: controle
        for controle in e_invoice.controles_e_facturation(db, ctx["company"], annee=ANNEE)
    }
    assert "efacture.accuse_en_attente" in codes

    situation = e_invoice.situation(db, ctx["company"], annee=ANNEE)
    assert situation["documents"][0].invoice_id == facture.id
    assert situation["sans_document"] == []
    assert situation["canal"].startswith("non configuré")
    assert situation["simulation"] is True
    assert situation["format"] == FORMAT_INTERNE
    assert situation["conformite"] == CONFORMITE_NON_VALIDEE
    assert any(mention["code"] == "vendeur_ice" for mention in situation["mentions"])


def test_list_documents_filtres(db, ctx):
    """Le registre des documents se filtre par statut et par facture."""
    facture = _facture(db, ctx)
    objet = e_invoice.generer_document(db, ctx["company"], facture)
    db.commit()
    assert len(e_invoice.list_documents(db, ctx["company"].id, statut=STATUT_GENERE)) == 1
    assert len(e_invoice.list_documents(db, ctx["company"].id, statut=STATUT_ENVOYE)) == 0
    assert (
        len(e_invoice.list_documents(db, ctx["company"].id, invoice_id=objet.invoice_id)) == 1
    )
    assert (
        e_invoice.document(db, ctx["company"].id, 999999) is None
    )