"""Tests des documents PDF (jalon J1) : etats de synthese, pieces et bordereaux.

Critere de recette verifie ici : **les montants des PDF sont identiques a l'ecran
au centime**. Les tests extraient le texte des PDF produits (bibliotheque `pypdf`)
et comparent les valeurs affichees a celles des services d'etats (`reporting`,
`etats_synthese`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.models import FiscalYear
from app.services import pdf_documents as docs
from app.services.accounting import (
    create_entry,
    get_fiscal_year,
    get_journal,
    validate_entry,
)
from app.services.etats_synthese import bilan_normal, etat_soldes_gestion, notes_etic
from app.services.invoicing import create_invoice, validate_invoice
from app.services.parties import create_third_party
from app.services.pdf import TAILLE_MAX_GREFFE, Colonne, Document, Tableau, rendre_pdf
from app.services.reporting import balance_sheet, income_statement, year_bounds

pytestmark = pytest.mark.usefixtures("ctx")

DEBUT, FIN = year_bounds(2026)


def texte(pdf: bytes) -> str:
    """Texte extrait d'un PDF (pour controler les montants affiches)."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


def ecriture(db, ctx, jour: date, libelle: str, lignes: list[dict], journal: str = "OD"):
    """Enregistre une ecriture manuelle equilibree puis la valide."""
    entry = create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=get_fiscal_year(db, ctx["company"].id, jour.year),
        journal=get_journal(db, ctx["company"].id, journal),
        entry_date=jour,
        label=libelle,
        lines=lignes,
    )
    validate_entry(db, entry, user_id=ctx["user"].id)
    return entry


@pytest.fixture()
def dossier(db, ctx) -> dict:
    """Dossier type : capital, immobilisation amortie, achats/ventes, charges.

    Soldes attendus (exercice 2026) :
    - capital 100 000 ; banque 85 500 ; immobilisation 60 000 ; amortissement 6 000 ;
      TVA recuperable 16 000 ; clients 48 000 ; fournisseurs 96 000 ; TVA collectee 8 000 ;
    - produits 40 000 ; charges 40 500 ; resultat -500.
    """
    ecriture(
        db,
        ctx,
        date(2026, 1, 2),
        "Apport en capital",
        [
            {"account_number": "5141", "label": "Banque", "debit": Decimal("100000.00")},
            {"account_number": "1111", "label": "Capital social", "credit": Decimal("100000.00")},
        ],
        journal="BQ",
    )
    ecriture(
        db,
        ctx,
        date(2026, 1, 10),
        "Acquisition d'immobilisation",
        [
            {"account_number": "2332", "label": "Materiel et outillage", "debit": Decimal("60000.00")},
            {"account_number": "34551", "label": "TVA sur immobilisation", "debit": Decimal("12000.00")},
            {"account_number": "4411", "label": "Fournisseur d'immobilisation", "credit": Decimal("72000.00")},
        ],
        journal="AC",
    )
    ecriture(
        db,
        ctx,
        date(2026, 12, 31),
        "Dotation aux amortissements",
        [
            {"account_number": "6193", "label": "Dotation aux amortissements", "debit": Decimal("6000.00")},
            {"account_number": "2833", "label": "Amortissement du materiel", "credit": Decimal("6000.00")},
        ],
    )
    ecriture(
        db,
        ctx,
        date(2026, 6, 20),
        "Achat de marchandises",
        [
            {"account_number": "6111", "label": "Achats de marchandises", "debit": Decimal("20000.00")},
            {"account_number": "34552", "label": "TVA sur charges", "debit": Decimal("4000.00")},
            {"account_number": "4411", "label": "Fournisseur", "credit": Decimal("24000.00")},
        ],
        journal="AC",
    )
    ecriture(
        db,
        ctx,
        date(2026, 6, 15),
        "Vente de marchandises",
        [
            {"account_number": "3421", "label": "Client", "debit": Decimal("48000.00")},
            {"account_number": "7111", "label": "Ventes de marchandises", "credit": Decimal("40000.00")},
            {"account_number": "4455", "label": "TVA collectee", "credit": Decimal("8000.00")},
        ],
        journal="VE",
    )
    ecriture(
        db,
        ctx,
        date(2026, 7, 1),
        "Charges externes et personnel",
        [
            {"account_number": "6131", "label": "Locations", "debit": Decimal("3000.00")},
            {"account_number": "6145", "label": "Telecommunications", "debit": Decimal("1000.00")},
            {"account_number": "6171", "label": "Remunerations", "debit": Decimal("10000.00")},
            {"account_number": "6161", "label": "Impots et taxes", "debit": Decimal("500.00")},
            {"account_number": "5141", "label": "Banque", "credit": Decimal("14500.00")},
        ],
        journal="BQ",
    )
    return {"ctx": ctx}


# ---------------------------------------------------------------------------
# Etats de synthese
# ---------------------------------------------------------------------------
def test_bilan_pdf_montants_identiques_a_lecran(db, ctx, dossier):
    """Bilan : les totaux du PDF sont ceux des services d'etats (au centime)."""
    bilan = bilan_normal(db, ctx["company"].id, DEBUT, FIN)
    ecran = balance_sheet(db, ctx["company"].id, DEBUT, FIN)
    contenu = texte(docs.pdf_bilan(db, ctx["company"], 2026))

    assert bilan["total_actif_brut"] == Decimal("209500.00")
    assert bilan["total_deductions"] == Decimal("6000.00")
    assert bilan["actif_net"] == Decimal("203500.00")
    assert bilan["total_passif_avec_resultat"] == Decimal("203500.00")
    assert bilan["resultat_exercice"] == Decimal("-500.00")
    assert bilan["equilibre"] is True
    # Reconciliation avec l'ecran : actif net = total actif - amortissements.
    assert bilan["ecran_total_actif"] == ecran["total_actif"] == Decimal("209500.00")
    assert bilan["coherent_avec_ecran"] is True
    assert bilan["ecart_ecran_actif"] == Decimal("-6000.00")

    for montant in (
        bilan["total_actif_brut"],
        bilan["total_deductions"],
        bilan["actif_net"],
        bilan["total_passif_avec_resultat"],
        ecran["total_actif"],
    ):
        assert docs.format_montant(montant) in contenu, montant
    assert "EQUILIBRE" in contenu
    assert "OK" in contenu
    assert "brut / amortissements / net" in contenu


def test_bilan_pdf_ventile_brut_amortissements_net(db, ctx, dossier):
    """Le bilan distingue les immobilisations brutes de leurs amortissements."""
    contenu = texte(docs.pdf_bilan(db, ctx["company"], 2026))

    assert "2332" in contenu  # immobilisation brute
    assert "outillage" in contenu
    assert docs.format_montant(Decimal("60000.00")) in contenu  # brut
    assert "2833" in contenu  # amortissement
    assert "TOTAL AMORTISSEMENTS ET PROVISIONS" in contenu
    assert docs.format_montant(Decimal("0.00")) in contenu  # stock/provisions a zero


def test_cpc_pdf_montants_identiques_a_lecran(db, ctx, dossier):
    """CPC : charges, produits et resultat identiques a `income_statement`."""
    cpc = income_statement(db, ctx["company"].id, DEBUT, FIN)
    contenu = texte(docs.pdf_cpc(db, ctx["company"], 2026))

    assert cpc["total_produits"] == Decimal("40000.00")
    assert cpc["total_charges"] == Decimal("40500.00")
    assert cpc["resultat"] == Decimal("-500.00")
    for montant in (cpc["total_produits"], cpc["total_charges"], cpc["resultat"]):
        assert docs.format_montant(montant) in contenu, montant
    assert "TOTAL DES CHARGES" in contenu
    assert "TOTAL DES PRODUITS" in contenu
    assert "perte" in contenu


def test_esg_pdf_soldes_de_gestion(db, ctx, dossier):
    """ESG : marge brute, valeur ajoutee, EBE, resultats et coherence avec le CPC."""
    esg = etat_soldes_gestion(db, ctx["company"].id, DEBUT, FIN)
    contenu = texte(docs.pdf_esg(db, ctx["company"], 2026))

    assert esg["marge_brute"] == Decimal("20000.00")  # 7111 - 6111
    assert esg["valeur_ajoutee"] == Decimal("16000.00")  # - (6131 + 6145)
    assert esg["ebe"] == Decimal("5500.00")  # - (6161 + 6171)
    assert esg["resultat_exploitation"] == Decimal("-500.00")  # - dotation 6193
    assert esg["resultat_courant"] == Decimal("-500.00")
    assert esg["resultat_net"] == Decimal("-500.00")
    assert esg["coherent_avec_cpc"] is True

    for libelle, montant in esg["soldes"]:
        assert libelle in contenu
        assert docs.format_montant(montant) in contenu, libelle
    assert "Coherence ESG / CPC" in contenu
    assert "OK" in contenu


def test_etic_pdf_notes_et_informations_indisponibles(db, ctx, dossier):
    """ETIC : notes annexes calculees et informations non disponibles listees."""
    etic = notes_etic(db, ctx["company"].id, DEBUT, FIN)
    contenu = texte(docs.pdf_etic(db, ctx["company"], 2026))

    assert len(etic["notes"]) == 10
    assert etic["indisponibles"]
    for note in etic["notes"]:
        assert f"Note {note['numero']}" in contenu
    assert "Immobilisations" in contenu
    assert "Immobilisations brutes" in contenu
    assert "Charges de personnel de l'exercice" in contenu
    assert "INFORMATIONS NON DISPONIBLES" in contenu
    assert "P1.4" in contenu  # origine de la donnee manquante (paie)
    assert "outillage" in contenu


def test_mention_provisoire_si_exercice_non_cloture(db, ctx, dossier):
    """Tant que l'exercice est ouvert, chaque etat porte la mention PROVISOIRE."""
    for pdf in (
        docs.pdf_bilan(db, ctx["company"], 2026),
        docs.pdf_cpc(db, ctx["company"], 2026),
        docs.pdf_esg(db, ctx["company"], 2026),
        docs.pdf_etic(db, ctx["company"], 2026),
    ):
        contenu = texte(pdf)
        assert "PROVISOIRE" in contenu
        assert "exercice non cloture" in contenu


def test_absence_de_mention_provisoire_si_exercice_clos(db, ctx, dossier):
    """Exercice cloture : la mention provisoire disparait des documents."""
    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == ctx["company"].id, FiscalYear.year == 2026
        )
    ).scalar_one()
    exercice.status = "closed"
    db.flush()

    contenu = texte(docs.pdf_bilan(db, ctx["company"], 2026))
    assert "PROVISOIRE" not in contenu
    assert "exercice non cloture" not in contenu



# ---------------------------------------------------------------------------
# Pieces comptables
# ---------------------------------------------------------------------------
def test_facture_pdf_mentions_legales_et_totaux(db, ctx):
    """Facture PDF : numero, ICE, ventilation par taux et totaux de l'ecran."""
    client = create_third_party(
        db,
        company=ctx["company"],
        kind="client",
        name="Client PDF SARL",
        ice="006789012000017",
        fiscal_id="1045678",
    )
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 5, 4),
        payment_mode="virement",
        reference="CMD-2026-14",
        lines=[
            {
                "designation": "Prestation de conseil",
                "quantity": 1,
                "unit_price": 1000,
                "vat_rate": 20,
            },
            {"designation": "Fourniture", "quantity": 2, "unit_price": 500, "vat_rate": 10},
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    contenu = texte(docs.pdf_facture(db, facture))

    assert facture.number in contenu
    assert "FACTURE" in contenu and "DE VENTE" in contenu
    assert client.ice in contenu
    assert "1045678" in contenu  # IF du client (7 chiffres, tel quel)
    assert "Facture originale" in contenu
    # Totaux de la facture (identiques a l'ecran) :
    for montant in (facture.total_ht, facture.total_vat, facture.total_ttc):
        assert docs.format_montant(montant) in contenu, montant
    assert "Ventilation de la TVA par taux" in contenu
    assert "20 %" in contenu and "10 %" in contenu
    assert "Arretee la presente facture a la somme de" in contenu
    assert "PROVISOIRE" in contenu  # exercice 2026 ouvert


def test_facture_brouillon_porte_la_mention_brouillon(db, ctx):
    """Une facture non validee est identifiee comme brouillon."""
    client = create_third_party(
        db,
        company=ctx["company"],
        kind="client",
        name="Client Brouillon",
        ice="006789012000017",
    )
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 5, 4),
        lines=[
            {"designation": "Prestation", "quantity": 1, "unit_price": 100, "vat_rate": 20}
        ],
    )
    contenu = texte(docs.pdf_facture(db, facture))
    assert "brouillon" in contenu
    assert "BROUILLON" in contenu


def test_bulletin_paie_pdf_et_validation_de_structure():
    """Bulletin de paie : rendu PDF et refus d'une structure incomplete."""
    bulletin = {
        "periode": "2026-01",
        "societe": {
            "nom": "Societe Demo",
            "ice": "001234567000099",
            "cnss_number": "1234567",
        },
        "salarie": {
            "matricule": "S001",
            "nom": "Salarie Test",
            "cnss": "987654321",
            "situation": "marie",
            "enfants": 2,
            "date_entree": date(2024, 3, 1),
        },
        "lignes": [
            {
                "libelle": "Salaire de base",
                "base": Decimal("8000.00"),
                "taux": None,
                "gain": Decimal("8000.00"),
                "retenue": None,
            },
            {
                "libelle": "CNSS (part salariale)",
                "base": Decimal("6000.00"),
                "taux": Decimal("4.48"),
                "gain": None,
                "retenue": Decimal("268.80"),
            },
            {
                "libelle": "Impot sur le revenu",
                "base": Decimal("7731.20"),
                "taux": None,
                "gain": None,
                "retenue": Decimal("1200.00"),
            },
        ],
        "totaux": {
            "brut": Decimal("8000.00"),
            "cotisations": Decimal("268.80"),
            "ir": Decimal("1200.00"),
            "net": Decimal("6531.20"),
        },
    }
    contenu = texte(docs.pdf_bulletin_paie(bulletin))
    assert "BULLETIN DE PAIE" in contenu
    assert "2026-01" in contenu
    assert "Salarie Test" in contenu
    assert "NET A PAYER" in contenu
    assert docs.format_montant(Decimal("6531.20")) in contenu
    assert docs.format_montant(Decimal("8000.00")) in contenu
    assert "4,48 %" in contenu
    assert "987654321" in contenu

    with pytest.raises(ValueError):
        docs.pdf_bulletin_paie({"periode": "2026-01", "salarie": {}})



# ---------------------------------------------------------------------------
# Bordereaux
# ---------------------------------------------------------------------------
def test_bordereau_tva_recapitule_exactement_le_releve(db, ctx):
    """Bordereau TVA : memes lignes, totaux et nom de fichier que l'EDI."""
    from app.services.invoicing import register_payment

    fournisseur = create_third_party(
        db,
        company=ctx["company"],
        kind="fournisseur",
        name="Orange",
        ice="001524628000001",
        fiscal_id="1086826",
    )
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=date(2026, 4, 2),
        reference="F-0426-1906426",
        lines=[
            {
                "designation": "Abonnement telecom",
                "quantity": 1,
                "unit_price": Decimal("98.33"),
                "vat_rate": 20,
                "account_number": "61455",
            }
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    register_payment(
        db, facture, amount="118.00", payment_date=date(2026, 6, 15), method="prelevement"
    )

    contenu = texte(docs.pdf_bordereau_tva(db, ctx["company"], 2026, quarter=2))
    assert "BORDEREAU" in contenu
    assert "ReleveDeductions_2026_T2.xml" in contenu
    assert "XML (jamais une archive ZIP)" in contenu
    assert docs.format_montant(Decimal("98.33")) in contenu  # base HT
    assert docs.format_montant(Decimal("19.67")) in contenu  # TVA deductible
    assert "Lignes ecartees du releve" in contenu
    assert "Anomalies a verifier" in contenu


def test_bordereau_greffe_checklist_et_contraintes(db, ctx):
    """Bordereau greffe : pieces a joindre et contraintes du portail."""
    ctx["company"].legal_form = "SARL"
    ctx["company"].rc = "11111"
    db.flush()

    contenu = texte(docs.pdf_bordereau_greffe(db, ctx["company"], 2026))
    assert "BORDEREAU DE DEPOT AU GREFFE" in contenu
    assert "Etats de synthese" in contenu
    assert "Rapport de gestion" in contenu
    assert "Proces-verbal de l'assemblee generale" in contenu
    assert "depotbilan.justice.gov.ma" in contenu
    assert "PDF uniquement" in contenu
    assert "10 Mo" in contenu
    assert "6 mois apres la cloture" in contenu
    assert "art. 93" in contenu
    assert "3 jours" in contenu
    assert "a deposer" in contenu


# ---------------------------------------------------------------------------
# Controles transverses
# ---------------------------------------------------------------------------
def test_tous_les_pdf_respectent_la_limite_greffe(db, ctx, dossier):
    """Chaque document produit reste sous la limite de 10 Mo du depot au greffe."""
    client = create_third_party(
        db,
        company=ctx["company"],
        kind="client",
        name="Client Limite",
        ice="006789012000017",
    )
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 5, 4),
        lines=[
            {"designation": "Prestation", "quantity": 1, "unit_price": 100, "vat_rate": 20}
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)

    documents = {
        "bilan": docs.pdf_bilan(db, ctx["company"], 2026),
        "cpc": docs.pdf_cpc(db, ctx["company"], 2026),
        "esg": docs.pdf_esg(db, ctx["company"], 2026),
        "etic": docs.pdf_etic(db, ctx["company"], 2026),
        "facture": docs.pdf_facture(db, facture),
        "bordereau_tva": docs.pdf_bordereau_tva(db, ctx["company"], 2026, quarter=1),
        "bordereau_greffe": docs.pdf_bordereau_greffe(db, ctx["company"], 2026),
    }
    for nom, pdf in documents.items():
        assert pdf.startswith(b"%PDF-"), nom
        assert 0 < len(pdf) <= TAILLE_MAX_GREFFE, nom


def test_formateurs_pdf_identiques_aux_filtres_de_linterface():
    """Les montants des PDF sont formates exactement comme a l'ecran."""
    from app.web.deps import format_amount

    for valeur in (
        None,
        Decimal("0"),
        Decimal("1234.5"),
        Decimal("-500.00"),
        Decimal("1068.49"),
        Decimal("198.81"),
        "1234.56",
    ):
        assert docs.format_montant(valeur) == format_amount(valeur)
    assert docs.format_montant_devise(Decimal("198.61")) == "198,61 DH"



def test_pagination_des_documents_volumineux():
    """Un document volumineux est pagine automatiquement et reste sous 10 Mo."""
    lignes = [
        [
            f"4111{index:04d}",
            f"Client numero {index}",
            docs.format_montant(Decimal(index * 100)),
        ]
        for index in range(300)
    ]
    document = Document(
        titre="TEST DE PAGINATION",
        sous_titre="300 lignes",
        entete=["Perimetre de test"],
        tableaux=[
            Tableau(
                titre="Auxiliaires clients",
                colonnes=(
                    Colonne("Compte", largeur=30),
                    Colonne("Libelle", largeur=80),
                    Colonne("Montant", largeur=50, alignement="right"),
                ),
                lignes=lignes,
                total=["", "TOTAL", docs.format_montant(Decimal("4485000"))],
            )
        ],
        pied="Document de test du moteur PDF",
    )
    pdf = rendre_pdf(document)
    lecteur = PdfReader(BytesIO(pdf))
    assert len(lecteur.pages) >= 3  # pagination automatique
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) <= TAILLE_MAX_GREFFE
    # Les totaux du dernier bloc apparaissent sur la derniere page :
    dernier = lecteur.pages[-1].extract_text() or ""
    assert docs.format_montant(Decimal("4485000")) in dernier

