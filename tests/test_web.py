"""Tests de l'interface graphique (Jinja2) : connexion, facturation, états.

L'interface est testée via le client HTTP de FastAPI, sur la même base SQLite en
mémoire que les tests de services : les écrans réels, les gabarits et les
contrôles de rôle sont donc vérifiés de bout en bout.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import unquote

CONNEXION = {"email": "admin@test.ma", "password": "MotDePasse123"}
CLIENT_ICE = "012345678000010"


def connecter(client):
    """Ouvre la session web de l'administrateur de test."""
    response = client.post("/connexion", data=CONNEXION, follow_redirects=False)
    assert response.status_code == 303, response.text
    return client


def creer_client(client, nom="Client Web SARL", ice=CLIENT_ICE, **extra):
    data = {"kind": "client", "name": nom}
    if ice:
        data["ice"] = ice
    data.update(extra)
    return client.post("/tiers/nouveau", data=data, follow_redirects=False)


def test_page_connexion_est_en_francais(client):
    response = client.get("/connexion")
    assert response.status_code == 200
    assert "Se connecter" in response.text
    assert "Comptabilité marocaine" in response.text


def test_acces_sans_session_redirige_vers_la_connexion(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/connexion")


def test_connexion_puis_tableau_de_bord(client):
    connecter(client)
    page = client.get("/")
    assert page.status_code == 200
    assert "Tableau de bord" in page.text
    assert "Résultat de l'exercice" in page.text
    assert "TVA" in page.text
    assert "Admin Test" in page.text


def test_mauvais_mot_de_passe_affiche_une_erreur(client):
    response = client.post(
        "/connexion", data={"email": "admin@test.ma", "password": "faux"}
    )
    assert response.status_code == 200
    assert "incorrect" in response.text


def test_creation_tiers_avec_sous_compte_pcge(client):
    connecter(client)
    response = creer_client(client, "Client Web SARL", payment_terms_days="30")
    assert response.status_code == 303
    assert "msg=" in response.headers["location"]

    page = client.get("/tiers")
    assert "Client Web SARL" in page.text
    assert "34210001" in page.text  # sous-compte créé automatiquement
    assert CLIENT_ICE in page.text


def test_flux_facture_complet_via_interface(client):
    connecter(client)
    creer_client(client)
    response = client.post(
        "/factures/nouvelle",
        data={
            "invoice_type": "vente",
            "partner_code": "CL0001",
            "invoice_date": "2026-09-18",
            "payment_mode": "virement",
            "auto_validate": "1",
            "designation": ["Prestation de conseil", "Transport"],
            "quantity": ["1", "1"],
            "unit_price": ["1000", "500"],
            "vat_rate": ["20", "10"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/factures/")
    invoice_id = location.split("?")[0].rsplit("/", 1)[-1]

    fiche = client.get(f"/factures/{invoice_id}")
    assert fiche.status_code == 200
    assert "FV202600001" in fiche.text  # numérotation à la validation
    assert "1 750,00" in fiche.text  # total TTC au format marocain
    assert "4455" in fiche.text  # compte de TVA facturée dans l'écriture générée
    assert "Validée" in fiche.text

    reglement = client.post(
        f"/factures/{invoice_id}/regler",
        data={"amount": "1000", "payment_date": "2026-09-20", "method": "virement"},
        follow_redirects=False,
    )
    assert reglement.status_code == 303
    fiche = client.get(f"/factures/{invoice_id}")
    assert "Partiellement réglée" in fiche.text
    assert "750,00" in fiche.text  # reste à payer

    impression = client.get(f"/factures/{invoice_id}/impression")
    assert impression.status_code == 200
    assert "Facture originale" in impression.text
    assert "ICE" in impression.text


def test_validation_refusee_sans_ice(client):
    connecter(client)
    creer_client(client, "Client Sans ICE SARL", ice=None)
    response = client.post(
        "/factures/nouvelle",
        data={
            "invoice_type": "vente",
            "partner_code": "CL0001",
            "invoice_date": "2026-09-18",
            "auto_validate": "1",
            "designation": ["Prestation"],
            "quantity": ["1"],
            "unit_price": ["1000"],
            "vat_rate": ["20"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    redirection = unquote(response.headers["location"])
    assert "factures/nouvelle" in redirection
    assert "ICE" in redirection
    # Aucun numéro n'a été consommé : la liste ne contient aucune facture.
    liste = client.get("/factures?type=vente")
    assert "Aucun document ne correspond aux filtres" in liste.text


def test_creation_ecriture_equilibree(client):
    connecter(client)
    response = client.post(
        "/ecritures/nouvelle",
        data={
            "journal_code": "OD",
            "entry_date": "2026-09-18",
            "label": "Apport en banque",
            "account_number": ["5141", "1111"],
            "debit": ["10000", "0"],
            "credit": ["0", "10000"],
            "auto_validate": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    page = client.get("/ecritures")
    assert "Apport en banque" in page.text
    assert "EC202600001" in page.text


def test_ecriture_desequilibree_refusee(client):
    connecter(client)
    response = client.post(
        "/ecritures/nouvelle",
        data={
            "journal_code": "OD",
            "entry_date": "2026-09-18",
            "label": "Ecriture fausse",
            "account_number": ["5141", "1111"],
            "debit": ["10000", "0"],
            "credit": ["0", "9000"],
            "auto_validate": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "ecritures/nouvelle" in response.headers["location"]
    assert "desequilibree" in unquote(response.headers["location"]).lower()


def test_pages_etats_et_tva(client):
    connecter(client)
    creer_client(client)
    client.post(
        "/factures/nouvelle",
        data={
            "invoice_type": "vente",
            "partner_code": "CL0001",
            "invoice_date": "2026-09-18",
            "auto_validate": "1",
            "designation": ["Prestation"],
            "quantity": ["1"],
            "unit_price": ["1000"],
            "vat_rate": ["20"],
        },
    )
    for url in ("/etats/balance", "/etats/grand-livre", "/etats/cpc", "/etats/bilan", "/tva"):
        page = client.get(url)
        assert page.status_code == 200, url
    balance = client.get("/etats/balance")
    assert "1 200,00" in balance.text  # 3421 clients (1 000 HT + 200 TVA)
    assert "équilibrée" in balance.text.lower() or "Equilibr" in balance.text
    tva = client.get("/tva?year=2026&quarter=3")
    assert "200,00" in tva.text  # TVA collectée du 3e trimestre


def test_parametres_societe_et_exercices(client):
    connecter(client)
    assert client.get("/parametres/societe").status_code == 200
    page = client.get("/parametres/exercices")
    assert page.status_code == 200
    assert "2026" in page.text
    # Clôture de l'exercice puis refus de saisie
    response = client.post(
        "/parametres/exercices/2026/closed", follow_redirects=False
    )
    assert response.status_code == 303
    refus = client.post(
        "/ecritures/nouvelle",
        data={
            "journal_code": "OD",
            "entry_date": "2026-09-18",
            "label": "Saisie sur exercice clos",
            "account_number": ["5141", "1111"],
            "debit": ["100", "0"],
            "credit": ["0", "100"],
            "auto_validate": "1",
        },
        follow_redirects=False,
    )
    assert refus.status_code == 303
    assert "exercice" in unquote(refus.headers["location"]).lower()
    # Réouverture pour laisser la base propre
    client.post("/parametres/exercices/2026/open")


def test_releve_deductions_edi_via_interface(client, auth_headers, db, ctx):
    """Bout en bout : achat fournisseur -> releve des deductions -> fichier XML DGI."""
    connecter(client)
    creation = client.post(
        "/tiers/nouveau",
        data={
            "kind": "fournisseur",
            "name": "Orange Maroc",
            "ice": "001524628000001",
            "fiscal_id": "1086826",
            "rc": "97815",
        },
        follow_redirects=False,
    )
    assert creation.status_code == 303
    assert "tiers" in creation.headers["location"]

    facture = client.post(
        "/factures/nouvelle",
        data={
            "invoice_type": "achat",
            "partner_code": "FR0001",
            "invoice_date": "2026-01-02",
            "payment_mode": "prelevement",
            "auto_validate": "1",
            "designation": ["Abonnement Mobile Orange"],
            "quantity": ["1"],
            "unit_price": ["98.33"],
            "vat_rate": ["20"],
        },
        follow_redirects=False,
    )
    assert facture.status_code == 303, facture.text
    invoice_id = facture.headers["location"].split("?")[0].rsplit("/", 1)[-1]

    reglement = client.post(
        f"/factures/{invoice_id}/regler",
        data={"amount": "118.00", "payment_date": "2026-01-19", "method": "espece"},
        follow_redirects=False,
    )
    assert reglement.status_code == 303

    page = client.get("/tva/edi?year=2026&quarter=1")
    assert page.status_code == 200
    assert "Relevé des déductions TVA" in page.text
    assert "Abonnement Mobile Orange" in page.text
    assert "19,67" in page.text
    assert "ReleveDeductions_2026_T1.xml" in page.text
    # Période rattachée au paiement par défaut (régime de l'encaissement) et
    # prorata de déduction paramétrable (CGI art. 106).
    assert "Date de paiement (encaissement)" in page.text
    assert "base_periode=paiement" in page.text
    assert 'name="taux_prorata"' in page.text
    assert "TVA déductible ventilée selon le CGNC" in page.text

    par_facture = client.get("/tva/edi?year=2026&quarter=1&base_periode=facture")
    assert par_facture.status_code == 200
    assert "Abonnement Mobile Orange" in par_facture.text

    prorata = client.get("/tva/edi/xml?year=2026&quarter=1&taux_prorata=50")
    assert prorata.status_code == 200
    assert "<tva>9.84</tva>" in prorata.text  # 19,67 x 50 %
    assert "<ttc>108.17</ttc>" in prorata.text  # 98,33 + 9,84

    xml = client.get("/tva/edi/xml?year=2026&quarter=1")
    assert xml.status_code == 200
    assert "xml" in xml.headers["content-type"]
    assert "<DeclarationReleveDeduction>" in xml.text
    assert "<identifiantFiscal>1234567</identifiantFiscal>" in xml.text
    assert "<periode>1</periode>" in xml.text
    assert "<regime>2</regime>" in xml.text
    assert "<tva>19.67</tva>" in xml.text
    assert "<if>1086826</if>" in xml.text  # IF fournisseur : 7 chiffres, tel quel
    assert "<ice>001524628000001</ice>" in xml.text
    assert "<tx>20</tx>" in xml.text
    assert "<prorata>" not in xml.text
    # Un acheteur etranger n'entre pas dans le releve des ventes : controle de type.
    assert "ventes" not in xml.text


def test_ice_invalide_refuse_a_la_creation_du_tiers(client, auth_headers):
    connecter(client)
    reponse = client.post(
        "/tiers/nouveau",
        data={"kind": "fournisseur", "name": "Fournisseur ICE faux", "ice": "123"},
        follow_redirects=False,
    )
    assert reponse.status_code == 303
    assert "ICE" in unquote(reponse.headers["location"])


def test_documents_pdf_via_interface(client):
    """J1 : téléchargement des PDF (états, pièces, bordereaux) depuis l'interface."""
    connecter(client)
    creer_client(client)
    creation = client.post(
        "/factures/nouvelle",
        data={
            "invoice_type": "vente",
            "partner_code": "CL0001",
            "invoice_date": "2026-09-18",
            "auto_validate": "1",
            "designation": ["Prestation de conseil"],
            "quantity": ["1"],
            "unit_price": ["1000"],
            "vat_rate": ["20"],
        },
        follow_redirects=False,
    )
    assert creation.status_code == 303
    invoice_id = creation.headers["location"].split("?")[0].rsplit("/", 1)[-1]

    for url in (
        "/etats/bilan/pdf?year=2026",
        "/etats/cpc/pdf?year=2026",
        "/etats/esg/pdf?year=2026",
        "/etats/etic/pdf?year=2026",
        "/etats/bordereau-greffe/pdf?year=2026",
        "/tva/edi/bordereau/pdf?year=2026&quarter=3",
        f"/factures/{invoice_id}/pdf",
        f"/factures/{invoice_id}/pdf?duplicata=1",
    ):
        reponse = client.get(url)
        assert reponse.status_code == 200, url
        assert reponse.headers["content-type"] == "application/pdf", url
        assert reponse.content.startswith(b"%PDF-"), url
        assert "attachment" in reponse.headers["content-disposition"], url
        assert reponse.headers["content-disposition"].endswith('.pdf"'), url

    inconnu = client.get("/etats/inconnu/pdf?year=2026", follow_redirects=False)
    assert inconnu.status_code == 303
    assert "inconnu" in unquote(inconnu.headers["location"]).lower()


def test_immobilisations_via_interface(client):
    """P1.2 : fiche d'immobilisation, dotation, cession, états et PDF depuis l'écran."""
    connecter(client)
    creation = client.post(
        "/immobilisations/nouvelle",
        data={
            "label": "Camion de livraison",
            "account_number": "2340",
            "acquisition_date": "2026-01-15",
            "service_date": "2026-01-15",
            "valeur_origine": "240000",
            "duree_annees": "5",
            "mode": "lineaire",
            "prorata_temporis": "1",
            "tva_montant": "48000",
            "comptabiliser": "1",
            "compte_contrepartie": "4411",
        },
        follow_redirects=False,
    )
    assert creation.status_code == 303
    assert "/immobilisations/IM202600001" in unquote(creation.headers["location"])

    fiche = client.get("/immobilisations/IM202600001")
    assert fiche.status_code == 200
    assert "Camion de livraison" in fiche.text
    assert "2340" in fiche.text
    assert "61934" in fiche.text and "2834" in fiche.text  # comptes dérivés du PCGE
    assert "48 000,00" in fiche.text  # annuité linéaire (240 000 / 5)
    assert "34551" in fiche.text  # TVA d'immobilisation jamais au 34552

    liste = client.get("/immobilisations")
    assert liste.status_code == 200
    assert "IM202600001" in liste.text
    assert "240 000,00" in liste.text

    dotation = client.post(
        "/immobilisations/IM202600001/doter",
        data={"exercice": "2026"},
        follow_redirects=False,
    )
    assert dotation.status_code == 303
    fiche = client.get("/immobilisations/IM202600001")
    assert "constatée" in fiche.text
    assert "48 000,00" in fiche.text

    cession = client.post(
        "/immobilisations/IM202600001/ceder",
        data={
            "date_cession": "2026-12-31",
            "prix": "200000",
            "tva_taux": "0",
            "motif": "Vente du camion",
            "regulariser_tva": "1",
        },
        follow_redirects=False,
    )
    assert cession.status_code == 303
    fiche = client.get("/immobilisations/IM202600001")
    assert fiche.status_code == 200
    assert "Cédée" in fiche.text

    etats = client.get("/immobilisations/etats?year=2026")
    assert etats.status_code == 200
    assert "Tableau des cessions" in etats.text
    assert "Régularisation de TVA (CGI art. 106)" in etats.text

    for url in (
        "/immobilisations?year=2026",
        "/immobilisations/nouvelle",
        "/immobilisations/etats?year=2026",
        "/immobilisations/etat/pdf?year=2026",
        "/immobilisations/cessions/pdf?year=2026",
        "/immobilisations/IM202600001/plan/pdf",
    ):
        reponse = client.get(url)
        assert reponse.status_code == 200, url
        if url.endswith(".pdf") or "/pdf?" in url:
            assert reponse.headers["content-type"] == "application/pdf", url
            assert reponse.content.startswith(b"%PDF-"), url


def test_interface_is_et_liasse(client, db, ctx):
    """P2.1 : écran « IS & liasse fiscale » — liasse, EFI, XML, dépôt, accusé.

    Le référentiel de codification livré couvre le **modèle normal** (code `13400`
    = capital social, seul code documenté) : l'écran est donc exercé de bout en
    bout, y compris le refus de générer un fichier non conforme.
    """
    from app.db.seed import get_or_create_fiscal_year
    from app.services.accounting import create_entry, get_journal

    connecter(client)
    exercice = get_or_create_fiscal_year(db, ctx["company"], 2026)
    create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=exercice,
        journal=get_journal(db, ctx["company"].id, "OD"),
        entry_date=date(2026, 1, 5),
        label="Constitution du capital",
        lines=[
            {"account_number": "5141", "debit": "100000", "label": "Banque"},
            {"account_number": "1111", "credit": "100000", "label": "Capital social"},
        ],
        validate=True,
    )
    db.commit()

    # 1. Exercice encore ouvert : la liasse est visible, le dépôt EDI est bloqué
    page = client.get("/liasse?year=2026&modele=normal")
    assert page.status_code == 200, page.text
    assert "IS &amp; liasse fiscale" in page.text
    assert "13400" in page.text
    assert "fiscal.exercice_non_clos" in page.text
    xml_refuse = client.get("/etats/liasse.xml?year=2026&modele=normal", follow_redirects=False)
    assert xml_refuse.status_code == 303
    assert "Erreur" in unquote(xml_refuse.headers["location"])

    # 2. Exercice clos : fichier XML validé, EFI assisté téléchargeable
    exercice.status = "closed"
    db.commit()
    page = client.get("/liasse?year=2026&modele=normal")
    assert page.status_code == 200
    assert "Conforme" in page.text
    assert "LIASSE_1234567_2026.xml" in page.text

    xml = client.get("/etats/liasse.xml?year=2026&modele=normal")
    assert xml.status_code == 200, xml.text
    assert "<Liasse>" in xml.text
    assert "<codeEdi>13400</codeEdi>" in xml.text
    assert 'filename="LIASSE_1234567_2026.xml"' in xml.headers["content-disposition"]

    efi = client.get("/etats/liasse-efi.csv?year=2026&modele=normal")
    assert efi.status_code == 200
    assert "13400" in efi.text

    # 3. Enregistrement puis dépôt avec accusé de réception
    enregistrement = client.post(
        "/liasse/enregistrer",
        data={"year": "2026", "modele": "normal", "mode_depot": "EDI", "avec_xml": "1"},
        follow_redirects=False,
    )
    assert enregistrement.status_code == 303, enregistrement.text
    assert "enregistr%C3%A9e" in enregistrement.headers["location"]

    depot = client.post(
        "/liasse/depot",
        data={
            "year": "2026",
            "modele": "normal",
            "jour": "2026-04-01",
            "accuse_le": "2026-04-09",
            "motif_rejet": "",
        },
        follow_redirects=False,
    )
    assert depot.status_code == 303, depot.text
    assert "D%C3%A9p%C3%B4t" in depot.headers["location"]

    page = client.get("/liasse?year=2026&modele=normal")
    assert "Acceptée par la DGI" in page.text
    assert "LIASSE_1234567_2026.xml" in page.text

    # 4. Registre de l'exercice sans liasse : message explicite
    page_2019 = client.get("/liasse?year=2019&modele=normal")
    assert page_2019.status_code == 200
    assert "Attention" in page_2019.text


def test_interface_paie_et_dts(client):
    """J6 : écran Paie (salarié, bulletin, écriture, paiement, DTS « 9421 »)."""
    connecter(client)

    page = client.get("/paie?year=2026")
    assert page.status_code == 200, page.text
    assert "Paie" in page.text
    assert "Nouvelle fiche salarié" in page.text

    creation = client.post(
        "/paie/salarie",
        data={
            "matricule": "WEB001",
            "nom": "ALAMI Youssef",
            "date_entree": "2024-01-15",
            "cin": "BK123456",
            "cnss": "987654321",
            "situation_familiale": "marie",
            "enfants": "2",
            "type_contrat": "cdi",
            "salaire_base": "10000",
        },
        follow_redirects=False,
    )
    assert creation.status_code == 303
    page = client.get("/paie?year=2026")
    assert "WEB001" in page.text

    preparation = client.post(
        "/paie/preparer",
        data={"periode": "2026-01"},
        follow_redirects=False,
    )
    assert preparation.status_code == 303
    page = client.get("/paie?year=2026&periode=2026-01")
    assert "Bulletins de 2026-01" in page.text
    # Bulletin de reference web : 10 000 DH bruts (sans prime), marie, 2 enfants.
    assert "053,64" in page.text  # net a payer (9 053,64 DH)
    assert "451,56" in page.text  # IR retenu

    validation = client.post(
        "/paie/valider", data={"periode": "2026-01"}, follow_redirects=False
    )
    assert validation.status_code == 303
    assert "valid%C3%A9e" in validation.headers["location"] or "validee" in (
        validation.headers["location"]
    )

    reglement = client.post(
        "/paie/payer",
        data={"periode": "2026-01", "mode": "virement"},
        follow_redirects=False,
    )
    assert reglement.status_code == 303

    # Bulletin PDF et fichier DTS XML depuis l'interface.
    import re

    page = client.get("/paie?year=2026&periode=2026-01")
    bulletin_id = int(re.search(r"/paie/bulletin/(\d+)/pdf", page.text).group(1))
    bulletin = client.get(f"/paie/bulletin/{bulletin_id}/pdf")
    assert bulletin.status_code == 200
    assert bulletin.content.startswith(b"%PDF-")

    dts_xml = client.get("/paie/dts.xml?year=2026")
    assert dts_xml.status_code == 200
    assert dts_xml.headers["content-type"].startswith("application/xml")
    assert b"<TraitementEtSalaire " in dts_xml.content

    dts_pdf = client.get("/paie/dts.pdf?year=2026")
    assert dts_pdf.status_code == 200
    assert dts_pdf.content.startswith(b"%PDF-")

    page = client.get("/paie?year=2026&periode=2026-01")
    assert "Livre de paie 2026" in page.text
    assert "Cotisations et IR retenus 2026" in page.text
    assert "9421" in page.text


def test_interface_depot_greffe(client, db, ctx, tmp_path, monkeypatch):
    """J5 : écran de dépôt au greffe (dossier, pièces, états, ZIP, certificat)."""
    import io
    import zipfile

    from app.core.config import settings
    from app.db.seed import get_or_create_fiscal_year

    monkeypatch.setattr(settings, "greffe_dir", tmp_path)
    from app.services.pdf_documents import pdf_pv_ag, pdf_rapport_gestion

    # Depuis le correctif P1 greffe (contenu bloquant), les pieces de test sont
    # des documents **reels** produits par l'application.
    pdf = pdf_pv_ag(
        db, ctx["company"], 2026, date_ag=date(2026, 6, 10), date_limite=date(2027, 6, 30)
    )
    pdf_rapport = pdf_rapport_gestion(db, ctx["company"], 2026)
    connecter(client)

    page = client.get("/greffe?year=2026")
    assert page.status_code == 200, page.text
    assert "Dépôt au greffe" in page.text
    assert "Nouveau dossier de dépôt" in page.text
    assert "depotbilan.justice.gov.ma" in page.text

    creation = client.post(
        "/greffe/dossier",
        data={
            "exercice": "2026",
            "forme_juridique": "SARL",
            "date_ag": "2026-06-10",
            "montant_taxes": "350",
        },
        follow_redirects=False,
    )
    assert creation.status_code == 303
    assert "/greffe?year=2026" in creation.headers["location"]

    page = client.get("/greffe?year=2026")
    assert "Nouveau (créé, non soumis)" in page.text
    assert "Checklist des pièces" in page.text
    assert "à joindre" in page.text
    assert "Contrôles préalables" in page.text

    import re

    depot_id = int(
        re.search(r"/greffe/(\d+)/pieces/generer", page.text).group(1)  # type: ignore[union-attr]
    )

    # Pièce externe téléversée depuis l'interface (multipart).
    envoi = client.post(
        f"/greffe/{depot_id}/pieces",
        data={"piece_code": "pv_ag"},
        files={"fichier": ("PV_AG_2026.pdf", pdf, "application/pdf")},
        follow_redirects=False,
    )
    assert envoi.status_code == 303
    page = client.get("/greffe?year=2026")
    assert "PV_AG_2026.pdf" in page.text

    # Pièce refusée (non PDF) : message d'erreur explicite.
    refuse = client.post(
        f"/greffe/{depot_id}/pieces",
        data={"piece_code": "rapport_gestion"},
        files={"fichier": ("Rapport.docx", b"contenu", "application/msword")},
        follow_redirects=False,
    )
    assert refuse.status_code == 303
    assert "n'est+pas+un+fichier+PDF" in refuse.headers["location"].replace("%27", "'")
    # La pièce corrigée (PDF) complète la checklist.
    corrige = client.post(
        f"/greffe/{depot_id}/pieces",
        data={"piece_code": "rapport_gestion"},
        files={"fichier": ("Rapport_gestion_2026.pdf", pdf_rapport, "application/pdf")},
        follow_redirects=False,
    )
    assert corrige.status_code == 303

    # Génération des états de synthèse (P1.1), du bordereau, du **rapport de
    # gestion** et du **PV d'AG** (date d'AG fournie au formulaire).
    generation = client.post(
        f"/greffe/{depot_id}/pieces/generer",
        data={"date_ag": "2026-06-10"},
        follow_redirects=False,
    )
    assert generation.status_code == 303
    page = client.get("/greffe?year=2026")
    assert "Etats_synthese_2026.pdf" in page.text
    assert "Bordereau_depot_greffe_2026.pdf" in page.text
    assert "Rapport_gestion_2026.pdf" in page.text
    assert "PV_AG_2026.pdf" in page.text

    # Téléchargements : bordereau PDF, archive ZIP, attestation de paiement.
    for url in (
        f"/greffe/{depot_id}/bordereau.pdf",
        f"/greffe/{depot_id}/attestation.pdf",
    ):
        reponse = client.get(url)
        assert reponse.status_code == 200, url
        assert reponse.content.startswith(b"%PDF-"), url

    # Clôture de l'exercice : condition du dépôt (comptes définitifs).
    exercice = get_or_create_fiscal_year(db, ctx["company"], 2026)
    exercice.status = "closed"
    db.commit()

    archive = client.get(f"/greffe/{depot_id}/dossier")
    assert archive.status_code == 200, archive.text
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zip_dossier:
        assert "00_bordereau_recapitulatif.pdf" in zip_dossier.namelist()

    # Soumission au portail : tous les contrôles sont verts.
    transition = client.post(
        f"/greffe/{depot_id}/etat",
        data={"etat": "en_cours", "motif": ""},
        follow_redirects=False,
    )
    assert transition.status_code == 303
    assert "en_cours" not in transition.headers["location"]  # message de succès
    page = client.get("/greffe?year=2026")
    assert "En cours (en traitement par le greffe)" in page.text

    # L'écran affiche le suivi des dépôts et les références légales.
    assert "Suivi des dépôts" in page.text
    assert "loi 5-96" in page.text

