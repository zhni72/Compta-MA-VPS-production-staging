"""Tests de l'export EDI « relevé des déductions » (Annexe 1 DGI) et des
contrôles associés (ICE/IF fournisseur, ventilation par type de facture)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from app.db.seed import get_or_create_fiscal_year
from app.models import Entry
from app.services.accounting import ComplianceError
from app.services.edi_tva import (
    BASE_PERIODE_FACTURE,
    EdiTvaError,
    build_rd_xml,
    collect_rd_lines,
    controle_taille,
    regime_code,
    taux_edi,
    validate_period,
    xml_filename,
)
from app.services.invoicing import create_invoice, register_payment, validate_invoice
from app.services.identifiers import normalize_fiscal_id
from app.services.parties import create_third_party
from app.services.vat import vat_return, vat_summary_by_rate

pytestmark = pytest.mark.usefixtures("ctx")

T1_2026 = (date(2026, 1, 1), date(2026, 3, 31))


def fournisseur(db, ctx, **kwargs):
    params = {
        "company": ctx["company"],
        "kind": "fournisseur",
        "name": "Orange Maroc",
        "ice": "001524628000001",
        "fiscal_id": "1086826",
        "payment_terms_days": 0,
    }
    params.update(kwargs)
    return create_third_party(db, **params)


def achat(
    db,
    ctx,
    tiers,
    *,
    ht="98,33",
    taux="20",
    jour=date(2026, 1, 2),
    reference="F-0126-1906426",
    compte="61455",
):
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=tiers,
        invoice_date=jour,
        payment_mode="prelevement",
        reference=reference,
        lines=[
            {
                "designation": "Abonnement telecom",
                "quantity": 1,
                "unit_price": Decimal(str(ht).replace(",", ".")),
                "vat_rate": Decimal(taux),
                "account_number": compte,
            }
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    return facture


def test_collecte_des_lignes_du_releve(db, ctx):
    tiers = fournisseur(db, ctx)
    facture = achat(db, ctx, tiers)
    register_payment(
        db, facture, amount="118.00", payment_date=date(2026, 1, 19), method="espece"
    )

    resultat = collect_rd_lines(db, ctx["company"], *T1_2026)
    assert resultat["totaux"]["nb_lignes"] == 1
    assert resultat["totaux"]["tva"] == Decimal("19.67")
    ligne = resultat["lignes"][0]
    assert ligne.ordre == 1
    assert ligne.num == "F-0126-1906426"
    assert ligne.if_fournisseur == "1086826"  # IF 7 chiffres, tel quel
    assert ligne.ice_fournisseur == "001524628000001"
    assert ligne.mode_id == 1  # espece = 1 dans la nomenclature DGI
    assert ligne.date_paiement == date(2026, 1, 19)
    assert ligne.date_facture == date(2026, 1, 2)
    assert ligne.mht + ligne.tva == ligne.ttc
    assert resultat["anomalies"] == []


def test_tva_nulle_exclue_du_releve(db, ctx):
    """Frais bancaires exoneres (TVA 0) : ecartes du releve, mais traces.

    Le compte de charge est corrige selon le PCGE (61473 « Frais et commissions
    sur services bancaires » et non 6141 « Etudes, recherches et documentation »).
    """
    tiers = fournisseur(
        db, ctx, name="Banque Populaire", ice="001534931000016", fiscal_id="1084612"
    )
    facture = achat(
        db, ctx, tiers, ht="27,50", taux="0", reference="260101", compte="61473"
    )
    register_payment(
        db, facture, amount="27.50", payment_date=date(2026, 1, 5), method="prelevement"
    )
    resultat = collect_rd_lines(db, ctx["company"], *T1_2026)
    assert resultat["totaux"]["nb_lignes"] == 0
    assert len(resultat["exclues"]) == 1
    assert "TVA nulle" in resultat["exclues"][0]["motif"]

    avec_zero = collect_rd_lines(db, ctx["company"], *T1_2026, include_zero_vat=True)
    assert avec_zero["totaux"]["nb_lignes"] == 1
    assert avec_zero["lignes"][0].tva == Decimal("0.00")


def test_avoir_du_fournisseur_en_deduction_negative(db, ctx):
    tiers = fournisseur(db, ctx)
    achat(db, ctx, tiers, ht="207,50", reference="F-0126-0111266")
    avoir = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=tiers,
        invoice_date=date(2026, 1, 31),
        is_credit_note=True,
        reference="AV-0126-0001",
        lines=[
            {
                "designation": "Avoir telecom",
                "quantity": 1,
                "unit_price": Decimal("207.50"),
                "vat_rate": Decimal("20"),
                "account_number": "61455",
            }
        ],
    )
    validate_invoice(db, avoir, user_id=ctx["user"].id)

    # Le regime de l'encaissement ne concerne pas les avoirs (aucun reglement) :
    # la base « facture » est utilisee pour controler la deduction negative.
    resultat = collect_rd_lines(
        db, ctx["company"], *T1_2026, base_periode=BASE_PERIODE_FACTURE
    )
    assert resultat["totaux"]["nb_lignes"] == 2
    assert resultat["totaux"]["tva"] == Decimal("0.00")  # +41,50 puis -41,50
    negatifs = [l for l in resultat["lignes"] if l.tva < 0]
    assert len(negatifs) == 1
    assert negatifs[0].num == "AV-0126-0001"

    # En base « paiement », un avoir sans reglement reste repris (deduction
    # negative) : il ne doit jamais disparaitre du releve.
    par_paiement = collect_rd_lines(db, ctx["company"], *T1_2026)
    assert par_paiement["totaux"]["nb_lignes"] == 1
    assert par_paiement["lignes"][0].tva == Decimal("-41.50")
    assert any("Aucun reglement" in a["motif"] for a in par_paiement["anomalies"])


def test_anomalies_ice_manquant_et_doublon(db, ctx):
    sans_ice = fournisseur(
        db, ctx, name="Fournisseur sans ICE", ice=None, fiscal_id="9999999"
    )
    achat(db, ctx, sans_ice, reference="F-DOUBLON")
    achat(db, ctx, sans_ice, reference="F-DOUBLON", jour=date(2026, 2, 5))

    # Controles propres a la base « facture » : ICE manquant, absence de
    # reglement, doublon (en base « paiement » une facture non reglee n'entre
    # pas dans le releve).
    resultat = collect_rd_lines(
        db, ctx["company"], *T1_2026, base_periode=BASE_PERIODE_FACTURE
    )
    motifs = [a["motif"] for a in resultat["anomalies"]]
    bloquants = [a for a in resultat["anomalies"] if a["bloquant"]]
    assert any("ICE" in m for m in motifs)
    assert any("reglement" in m for m in motifs)
    assert any("Doublon" in m for m in motifs)
    assert len(bloquants) >= 2


def test_xml_conforme_a_l_annexe_rd(db, ctx):
    tiers = fournisseur(db, ctx)
    facture = achat(db, ctx, tiers)
    register_payment(
        db, facture, amount="118.00", payment_date=date(2026, 1, 19), method="espece"
    )
    resultat = collect_rd_lines(db, ctx["company"], *T1_2026)

    xml = build_rd_xml(
        identifiant_fiscal="1234567",
        annee=2026,
        periode=1,
        regime=2,
        lignes=resultat["lignes"],
    )
    for balise in (
        "DeclarationReleveDeduction",
        "identifiantFiscal",
        "annee",
        "periode",
        "regime",
        "releveDeductions",
        "rd",
        "ord",
        "num",
        "des",
        "mht",
        "tva",
        "ttc",
        "refF",
        "if",
        "nom",
        "ice",
        "tx",
        "mp",
        "id",
        "dpai",
        "dfac",
    ):
        assert f"<{balise}>" in xml and f"</{balise}>" in xml, balise

    assert '<?xml version="1.0" encoding="UTF-8"' in xml
    assert "<identifiantFiscal>1234567</identifiantFiscal>" in xml
    assert "<annee>2026</annee>" in xml
    assert "<periode>1</periode>" in xml
    assert "<regime>2</regime>" in xml
    assert "<ord>1</ord>" in xml
    assert "<num>F-0126-1906426</num>" in xml
    assert "<mht>98.33</mht>" in xml
    assert "<tva>19.67</tva>" in xml
    assert "<ttc>118.00</ttc>" in xml
    assert "<if>1086826</if>" in xml  # IF fournisseur : 7 chiffres, utilise tel quel
    assert "<ice>001524628000001</ice>" in xml
    assert "<tx>20</tx>" in xml  # unite « pourcentage » confirmee par l'exemple DGI
    assert "<prorata>" not in xml  # non declaree dans le XSD officiel DGI
    assert "<id>1</id>" in xml  # espece
    assert "<dpai>2026-01-19</dpai>" in xml
    assert "<dfac>2026-01-02</dfac>" in xml
    assert xml.count("<rd>") == xml.count("</rd>") == 1
    # Aucune virgule decimale : le separateur EDI est le point.
    assert not re.search(r"<mht>\d+,\d+</mht>", xml)

    # Option : <prorata> pour les plateformes qui l'exigent (annexe papier).
    xml_prorata = build_rd_xml(
        identifiant_fiscal="1234567",
        annee=2026,
        periode=1,
        regime=2,
        lignes=resultat["lignes"],
        inclure_prorata=True,
    )
    assert "<prorata>100</prorata>" in xml_prorata  # pourcentage (exemple officiel DGI)
    assert "<tx>20</tx>" in xml_prorata


def test_identifiant_fiscal_7_ou_8_chiffres_sans_transformation(db, ctx):
    """Norme IF : 7 ou 8 chiffres, utilise TEL QUEL (aucun zéro ajouté/retiré)."""
    # Exemples de la norme : les IF à 7 chiffres restent à 7 chiffres.
    assert normalize_fiscal_id("1084612") == "1084612"  # Banque Populaire
    assert normalize_fiscal_id("1086826") == "1086826"  # Orange
    assert normalize_fiscal_id("1234567") == "1234567"  # déclarant
    # Un IF à 8 chiffres reste à 8 chiffres.
    assert normalize_fiscal_id("12345678") == "12345678"
    assert normalize_fiscal_id("01084612") == "01084612"
    # Les séparateurs de saisie sont retirés, sans autre transformation.
    assert normalize_fiscal_id("108 6826") == "1086826"
    assert normalize_fiscal_id("108-6826") == "1086826"
    assert normalize_fiscal_id(None) is None
    # Toute autre longueur ou format non numérique est refusé (jamais corrigé).
    for invalide in ("108682", "123456", "123456789", "IF-1086826", "10A6826"):
        with pytest.raises(ComplianceError):
            normalize_fiscal_id(invalide)

    # Le tiers conserve la valeur saisie (7 chiffres), sans zéro de tête.
    tiers = fournisseur(db, ctx, name="Orange IF court", fiscal_id="1086826")
    assert tiers.fiscal_id == "1086826"


def test_limite_de_lignes_du_releve_parametrable(db, ctx):
    """<ord> : limite par defaut prudente (127) et PARAMETRABLE."""
    from app.services.edi_tva import MAX_RD_LINES, RdLigne, limite_lignes

    modele = RdLigne(
        ordre=1,
        num="F-1",
        designation="Test",
        mht=Decimal("100.00"),
        tva=Decimal("20.00"),
        ttc=Decimal("120.00"),
        if_fournisseur="1086826",
        nom_fournisseur="Orange",
        ice_fournisseur="001524628000001",
        taux=Decimal("20"),
        prorata=Decimal("1"),
        mode_id=3,
        date_paiement=date(2026, 1, 19),
        date_facture=date(2026, 1, 2),
        facture_id=1,
    )
    # Defaut prudent : 127 (xs:byte du XSD) ; surcharge par reglage ou argument.
    assert MAX_RD_LINES == 127
    assert limite_lignes() == 127
    assert limite_lignes(500) == 500

    lignes_ok = [
        RdLigne(**{**modele.__dict__, "ordre": index}) for index in range(1, 128)
    ]
    xml = build_rd_xml(
        identifiant_fiscal="1234567", annee=2026, periode=1, regime=2, lignes=lignes_ok
    )
    assert "<ord>127</ord>" in xml

    lignes_ko = lignes_ok + [RdLigne(**{**modele.__dict__, "ordre": 128})]
    with pytest.raises(EdiTvaError):
        build_rd_xml(
            identifiant_fiscal="1234567",
            annee=2026,
            periode=1,
            regime=2,
            lignes=lignes_ko,
        )

    # La limite reelle etant a confirmer aupres de la DGI (annexe V4.0 : « Entier »),
    # elle peut etre relevee sans modification du code.
    xml_etendu = build_rd_xml(
        identifiant_fiscal="1234567",
        annee=2026,
        periode=1,
        regime=2,
        lignes=lignes_ko,
        max_lignes=500,
    )
    assert "<ord>128</ord>" in xml_etendu


def test_unite_de_tx_parametrable():
    assert taux_edi(Decimal("20")) == "20"
    assert taux_edi(Decimal("10"), "percent") == "10"
    assert taux_edi(Decimal("20"), "ratio") == "20.00"
    with pytest.raises(EdiTvaError):
        taux_edi(Decimal("20"), "inconnu")


def test_periode_et_nom_de_fichier():
    validate_period(1, 12)
    validate_period(2, 4)
    with pytest.raises(EdiTvaError):
        validate_period(2, 7)
    with pytest.raises(EdiTvaError):
        validate_period(1, 13)
    assert xml_filename(2026, 1, 2) == "ReleveDeductions_2026_T1.xml"
    assert xml_filename(2026, 3, 1) == "ReleveDeductions_2026_M3.xml"


def test_export_refuse_si_vide_ou_if_invalide(db, ctx):
    lignes_vides = collect_rd_lines(db, ctx["company"], *T1_2026)["lignes"]
    with pytest.raises(EdiTvaError):
        build_rd_xml(
            identifiant_fiscal="1234567",
            annee=2026,
            periode=1,
            regime=2,
            lignes=lignes_vides,
        )

    tiers = fournisseur(db, ctx)
    facture = achat(db, ctx, tiers)
    register_payment(db, facture, amount="118.00", payment_date=date(2026, 1, 19))
    lignes = collect_rd_lines(db, ctx["company"], *T1_2026)["lignes"]
    with pytest.raises(EdiTvaError):
        build_rd_xml(identifiant_fiscal="", annee=2026, periode=1, regime=2, lignes=lignes)
    with pytest.raises(EdiTvaError):
        build_rd_xml(identifiant_fiscal="ABC", annee=2026, periode=1, regime=2, lignes=lignes)


def test_limite_de_taille_dgi():
    assert controle_taille("a" * 999_999) == 999_999
    with pytest.raises(EdiTvaError):
        controle_taille("a" * 1_000_001)


def test_regime_et_ventilation_par_type(db, ctx):
    assert regime_code(ctx["company"]) == 2  # societe de test : trimestriel

    client = create_third_party(
        db, company=ctx["company"], kind="client", name="Client TVA", ice="004567890000013"
    )
    vente = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 2, 10),
        lines=[
            {
                "designation": "Prestation",
                "quantity": 1,
                "unit_price": Decimal("1000.00"),
                "vat_rate": Decimal("20"),
                "account_number": "7111",
            }
        ],
    )
    validate_invoice(db, vente, user_id=ctx["user"].id)
    tiers = fournisseur(db, ctx)
    achat(db, ctx, tiers, ht="100,00", taux="10", reference="F-ACHAT-TAUX10")

    ventes = vat_summary_by_rate(db, ctx["company"].id, *T1_2026, invoice_type="vente")
    achats = vat_summary_by_rate(db, ctx["company"].id, *T1_2026, invoice_type="achat")
    assert [(r["vat_rate"], r["tva"]) for r in ventes] == [
        (Decimal("20.00"), Decimal("200.00"))
    ]
    assert [(r["vat_rate"], r["tva"]) for r in achats] == [
        (Decimal("10.00"), Decimal("10.00"))
    ]
    melange = vat_summary_by_rate(db, ctx["company"].id, *T1_2026)
    assert len(melange) == 2  # 10 % et 20 % : sans filtre, ventes et achats se melangent


def test_periode_rattachee_au_paiement(db, ctx):
    """Regime de l'encaissement : la deduction est rattachee au reglement.

    Une facture de decembre 2025 payee en janvier 2026 entre dans le releve du
    T1 2026 par sa date de paiement (le modele DGI porte <dpai> et <dfac>), et
    non par sa date de facture.
    """
    get_or_create_fiscal_year(db, ctx["company"], 2025)
    tiers = fournisseur(db, ctx)
    facture = achat(db, ctx, tiers, jour=date(2025, 12, 2), reference="F-1225-0032656")
    register_payment(
        db, facture, amount="118.00", payment_date=date(2026, 1, 15), method="virement"
    )

    par_paiement = collect_rd_lines(db, ctx["company"], *T1_2026)
    assert par_paiement["base_periode"] == "paiement"
    assert par_paiement["totaux"]["nb_lignes"] == 1
    ligne = par_paiement["lignes"][0]
    assert ligne.date_paiement == date(2026, 1, 15)
    assert ligne.date_facture == date(2025, 12, 2)

    par_facture = collect_rd_lines(
        db, ctx["company"], *T1_2026, base_periode=BASE_PERIODE_FACTURE
    )
    assert par_facture["base_periode"] == "facture"
    assert par_facture["totaux"]["nb_lignes"] == 0  # facture hors periode

    with pytest.raises(EdiTvaError):
        collect_rd_lines(db, ctx["company"], *T1_2026, base_periode="exercice")


def test_tva_immobilisation_imputee_au_34551(db, ctx):
    """CGNC : TVA sur immobilisation au 34551, TVA sur charge au 34552."""
    tiers = fournisseur(db, ctx)
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=tiers,
        invoice_date=date(2026, 2, 10),
        reference="IMMO-2026-01",
        lines=[
            {
                "designation": "Equipement et outillage",
                "quantity": 1,
                "unit_price": Decimal("10000.00"),
                "vat_rate": Decimal("20"),
                "account_number": "2332",
            },
            {
                "designation": "Frais de dossier bancaire",
                "quantity": 1,
                "unit_price": Decimal("100.00"),
                "vat_rate": Decimal("20"),
                "account_number": "61473",
            },
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)

    ecriture = db.get(Entry, facture.entry_id)
    soldes: dict[str, Decimal] = {}
    for ligne in ecriture.lines:
        soldes[ligne.account_number] = (
            soldes.get(ligne.account_number, Decimal("0")) + ligne.debit - ligne.credit
        )
    assert soldes["2332"] == Decimal("10000.00")
    assert soldes["61473"] == Decimal("100.00")
    assert soldes["34551"] == Decimal("2000.00")  # TVA sur immobilisation
    assert soldes["34552"] == Decimal("20.00")  # TVA sur charge
    assert "3455" not in soldes  # le compte collectif n'est jamais mouvemente

    declaration = vat_return(db, ctx["company"].id, *T1_2026)
    assert declaration["tva_deductible"] == Decimal("2020.00")
    comptes_tva = {ligne["account_number"] for ligne in declaration["detail"]}
    assert comptes_tva == {"34551", "34552"}


def test_prorata_reduit_la_tva_deductible(db, ctx):
    """Prorata CGI art. 106 : la TVA declaree est la fraction deductible."""
    tiers = fournisseur(db, ctx)
    facture = achat(db, ctx, tiers)
    register_payment(
        db, facture, amount="118.00", payment_date=date(2026, 1, 19), method="espece"
    )

    integral = collect_rd_lines(db, ctx["company"], *T1_2026)
    assert integral["prorata"] == Decimal("1")
    assert integral["totaux"]["tva"] == Decimal("19.67")
    assert integral["anomalies"] == []

    partiel = collect_rd_lines(db, ctx["company"], *T1_2026, prorata=Decimal("0.90"))
    ligne = partiel["lignes"][0]
    assert ligne.tva == Decimal("17.70")  # 19.67 x 90 %
    assert ligne.mht == Decimal("98.33")
    assert ligne.ttc == Decimal("116.03")  # mht + tva
    assert partiel["totaux"]["tva"] == Decimal("17.70")
    assert any("Prorata" in anomalie["motif"] for anomalie in partiel["anomalies"])

    xml = build_rd_xml(
        identifiant_fiscal="1234567",
        annee=2026,
        periode=1,
        regime=2,
        lignes=partiel["lignes"],
        inclure_prorata=True,
    )
    assert "<tva>17.70</tva>" in xml
    assert "<prorata>90</prorata>" in xml
    assert "<ttc>116.03</ttc>" in xml

    with pytest.raises(EdiTvaError):
        collect_rd_lines(db, ctx["company"], *T1_2026, prorata=Decimal("1.5"))


def test_prorata_edi_ecrit_en_pourcentage():
    """<prorata> : POURCENTAGE, comme l'exemple officiel DGI (70, 80)."""
    from app.services.edi_tva import _prorata_edi

    assert _prorata_edi(Decimal("1")) == "100"
    assert _prorata_edi(Decimal("0.90")) == "90"
    assert _prorata_edi(Decimal("0.7")) == "70"
    assert _prorata_edi(Decimal("0.3333")) == "33.33"


def test_modes_de_paiement_conformes_annexe_v4():
    """Modes de paiement de l'annexe « balises RD » V4.0 (1..7)."""
    from app.models import PAYMENT_METHOD_CODES, PAYMENT_METHOD_LABELS

    assert PAYMENT_METHOD_CODES == {
        "espece": 1,
        "cheque": 2,
        "prelevement": 3,
        "virement": 4,
        "effet": 5,
        "compensation": 6,
        "autre": 7,
    }
    assert set(PAYMENT_METHOD_CODES) == set(PAYMENT_METHOD_LABELS)


def test_facture_partiellement_reglee_deduction_par_reglement(db, ctx):
    """Une facture reglee en deux fois est deduite une seule fois au total.

    Non-regression P0.2 (audit J9) : la base eligible et la TVA doivent suivre
    **la meme fraction** de reglement. Avant correction, `<mht>` restait au
    montant de la facture (100,00) alors que `<tva>` etait limitee a 9,84, ce qui
    produisait une ligne incoherente (`ttc = 109,84` au lieu de 59,00).
    """
    tiers = fournisseur(db, ctx)
    facture = achat(db, ctx, tiers, reference="F-PARTIEL")
    register_payment(
        db, facture, amount="59.00", payment_date=date(2026, 1, 19), method="espece"
    )

    premier = collect_rd_lines(db, ctx["company"], *T1_2026)
    ligne = premier["lignes"][0]
    assert ligne.mht == Decimal("49.17")  # base eligible = fraction reglee (98,33 x 1/2)
    assert ligne.tva == Decimal("9.84")  # 19,67 x (59,00 / 118,00)
    assert ligne.ttc == Decimal("59.01")  # HT + TVA (et non 118,00 avant correction)
    assert premier["totaux"]["tva"] == Decimal("9.84")
    assert any("partiellement" in a["motif"].lower() for a in premier["anomalies"])
    # aucun controle bloquant : la ligne est coherente (base x taux et HT+TVA=TTC)
    assert [a for a in premier["anomalies"] if a["bloquant"]] == []

    register_payment(
        db, facture, amount="59.00", payment_date=date(2026, 4, 10), method="espece"
    )
    t2 = collect_rd_lines(db, ctx["company"], date(2026, 4, 1), date(2026, 6, 30))
    assert t2["totaux"]["tva"] == Decimal("9.83")  # solde : 19,67 - 9,84
    assert t2["totaux"]["mht"] == Decimal("49.16")  # solde : 98,33 - 49,17

    # Le T1 reste inchange : aucune deduction ne remonte sur la periode close.
    assert collect_rd_lines(db, ctx["company"], *T1_2026)["totaux"]["tva"] == Decimal("9.84")

    # Cumul des deux periodes : la facture est deduite exactement une fois.
    assert premier["totaux"]["mht"] + t2["totaux"]["mht"] == Decimal("98.33")
    assert premier["totaux"]["tva"] + t2["totaux"]["tva"] == Decimal("19.67")



def test_releve_edi_refuse_une_ligne_incoherente(db, ctx):
    """Non-regression P0.2 : le defaut J9 (base facture / TVA proratisee) est refuse.

    Signature exacte du defaut constate en recette : `mht` au montant de la
    facture (98,33) avec une TVA limitee a la fraction reglee (9,84) et un taux
    de 20 % -> la generation du fichier EDI doit etre **bloquee**.
    """
    from app.services.edi_tva import RdLigne, verifier_lignes

    ligne = RdLigne(
        ordre=1,
        num="FA26-08",
        designation="Achat marchandises",
        mht=Decimal("98.33"),
        tva=Decimal("9.84"),
        ttc=Decimal("108.17"),
        if_fournisseur="1086826",
        nom_fournisseur="Orange Maroc",
        ice_fournisseur="001524628000001",
        taux=Decimal("20"),
        prorata=Decimal("1"),
        mode_id=4,
        date_paiement=date(2026, 1, 19),
        date_facture=date(2026, 1, 2),
        facture_id=1,
    )
    anomalies = verifier_lignes([ligne])
    assert anomalies, "la ligne incoherente aurait du etre detectee"
    assert all(a["bloquant"] for a in anomalies)
    assert any("taux/base" in a["motif"] for a in anomalies)

    with pytest.raises(EdiTvaError) as exc:
        build_rd_xml(
            identifiant_fiscal="1234567",
            annee=2026,
            periode=1,
            regime=1,
            lignes=[ligne],
        )
    assert "lignes incoherentes" in str(exc.value)
    assert "taux/base" in str(exc.value)


def test_xml_releve_partiellement_regle_coherent(db, ctx):
    """Le XML produit porte la meme fraction pour la base et la TVA (P0.2)."""
    tiers = fournisseur(db, ctx)
    facture = achat(db, ctx, tiers, reference="F-PARTIEL-XML")
    register_payment(
        db, facture, amount="59.00", payment_date=date(2026, 1, 19), method="espece"
    )
    resultat = collect_rd_lines(db, ctx["company"], *T1_2026)
    xml = build_rd_xml(
        identifiant_fiscal="1234567",
        annee=2026,
        periode=1,
        regime=1,
        lignes=resultat["lignes"],
    )
    mht = Decimal(re.search(r"<mht>([\d.]+)</mht>", xml).group(1))
    tva = Decimal(re.search(r"<tva>([\d.]+)</tva>", xml).group(1))
    ttc = Decimal(re.search(r"<ttc>([\d.]+)</ttc>", xml).group(1))
    assert mht == Decimal("49.17")  # et non 98.33 (base facture complete)
    assert tva == Decimal("9.84")
    assert ttc == mht + tva  # identite verifiee dans le fichier depose
    assert abs(tva - mht * Decimal("0.20")) <= Decimal("0.02")


def test_prorata_saisi_en_pourcentage_dans_l_interface():
    """La saisie est convertie en fraction (100 % = deduction integrale)."""
    from app.web.routes import _prorata_edi

    assert _prorata_edi("100") == Decimal("1")
    assert _prorata_edi("50") == Decimal("0.5")
    assert _prorata_edi("33,33") == Decimal("0.3333")
    assert _prorata_edi("") == Decimal("1")  # saisie vide : deduction totale
    assert _prorata_edi("0") == Decimal("1")  # hors bornes (0 exclu)
    assert _prorata_edi("250") == Decimal("1")  # hors bornes (100 maxi)


def test_ice_fournisseur_controle_a_la_creation(db, ctx):
    with pytest.raises(ComplianceError):
        fournisseur(db, ctx, name="ICE court", ice="123456")
    with pytest.raises(ComplianceError):
        fournisseur(db, ctx, name="IF non numerique", fiscal_id="IF-1086826")
    # Les separateurs de saisie sont retires : l'IF reste sur 7 chiffres (tel quel).
    tiers = fournisseur(
        db, ctx, name="Orange (IF espace)", fiscal_id="108 6826", ice="001524628000001"
    )
    assert tiers.fiscal_id == "1086826"