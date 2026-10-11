"""Tests de l'API HTTP : authentification, RBAC et flux facture -> etats."""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from app.db import seed as seed_module

API = "/api"  # API REST montee sous /api (isolation API / interface)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_authentification_obligatoire(client):
    response = client.get(API + "/invoices")
    assert response.status_code == 401


def test_connexion_et_profil(client, auth_headers):
    response = client.get(API + "/auth/me", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "admin@test.ma"
    assert "ADMIN" in payload["role_codes"]
    assert "EXPERT_COMPTABLE" in payload["role_codes"]


def test_identifiants_invalides(client):
    response = client.post(
        API + "/auth/token", data={"username": "admin@test.ma", "password": "mauvais"}
    )
    assert response.status_code == 401


def test_flux_facture_puis_etats(client, auth_headers, db, ctx):
    # 1. Creation du client (avec ICE)
    creation_client = client.post(
        API + "/parties",
        headers=auth_headers,
        json={"kind": "client", "name": "Client API SARL", "ice": "008901234000011"},
    )
    assert creation_client.status_code == 201, creation_client.text
    code_client = creation_client.json()["code"]
    assert creation_client.json()["account_number"] == "34210001"

    # 2. Creation et validation de la facture
    creation_facture = client.post(
        API + "/invoices",
        headers=auth_headers,
        json={
            "invoice_type": "vente",
            "partner_code": code_client,
            "invoice_date": "2026-07-01",
            "auto_validate": True,
            "lines": [
                {
                    "designation": "Prestation de service",
                    "quantity": 1,
                    "unit_price": 1000,
                    "vat_rate": 20,
                }
            ],
        },
    )
    assert creation_facture.status_code == 201, creation_facture.text
    facture = creation_facture.json()
    assert facture["number"] == "FV202600001"
    assert facture["status"] == "validated"
    assert facture["total_ttc"] == "1200.0" or float(facture["total_ttc"]) == 1200.0

    # 3. Etats comptables
    balance = client.get(API + "/reports/balance?year=2026", headers=auth_headers)
    assert balance.status_code == 200
    assert balance.json()["equilibre"] is True

    bilan = client.get(API + "/reports/bilan?year=2026", headers=auth_headers)
    assert bilan.json()["equilibre"] is True
    assert float(bilan.json()["resultat_exercice"]) == 1000.0

    # 4. Declaration de TVA du 3e trimestre
    declaration = client.get(API + "/vat/return?year=2026&quarter=3", headers=auth_headers)
    assert declaration.status_code == 200
    assert float(declaration.json()["tva_collectee"]) == 200.0
    assert declaration.json()["echeance"] == "2026-10-20"

    # 5. Reglement total
    reglement = client.post(
        API + f"/invoices/{facture['id']}/payments",
        headers=auth_headers,
        json={"amount": 1200, "method": "virement", "payment_date": "2026-07-15"},
    )
    assert reglement.status_code == 200, reglement.text
    assert reglement.json()["status"] == "paid"


def test_facture_sans_ice_renvoie_422(client, auth_headers):
    code_client = client.post(
        API + "/parties",
        headers=auth_headers,
        json={"kind": "client", "name": "Client Sans ICE SARL"},
    ).json()["code"]

    response = client.post(
        API + "/invoices",
        headers=auth_headers,
        json={
            "invoice_type": "vente",
            "partner_code": code_client,
            "invoice_date": "2026-07-01",
            "auto_validate": True,
            "lines": [{"designation": "Prestation", "unit_price": 500, "vat_rate": 20}],
        },
    )
    assert response.status_code == 422
    assert "ICE" in response.json()["detail"]


def test_role_lecteur_ne_peut_pas_facturer(client, auth_headers, db, ctx):
    # Le tiers est cree par l'administrateur.
    code_client = client.post(
        API + "/parties",
        headers=auth_headers,
        json={"kind": "client", "name": "Client Lecture SARL", "ice": "009012345000018"},
    ).json()["code"]

    seed_module.create_user(
        db,
        "lecteur@test.ma",
        "MotDePasse123",
        roles=("LECTEUR",),
        company=ctx["company"],
    )
    db.commit()
    token = client.post(
        API + "/auth/token", data={"username": "lecteur@test.ma", "password": "MotDePasse123"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Lecture autorisee pour le role LECTEUR.
    assert client.get(API + "/parties", headers=headers).status_code == 200
    # Ecriture interdite : creation de tiers et facturation reserves aux autres roles.
    assert (
        client.post(
            API + "/parties",
            headers=headers,
            json={"kind": "client", "name": "Tiers interdit", "ice": "010123456000015"},
        ).status_code
        == 403
    )
    response = client.post(
        API + "/invoices",
        headers=headers,
        json={
            "invoice_type": "vente",
            "partner_code": code_client,
            "invoice_date": "2026-07-01",
            "lines": [{"designation": "Prestation", "unit_price": 100, "vat_rate": 20}],
        },
    )
    assert response.status_code == 403
    assert "role" in response.json()["detail"].lower()


def test_compte_invalide_refuse(client, auth_headers):
    # Numero non numerique : refuse par le service (codification decimale CGNC).
    response = client.post(
        API + "/accounts", headers=auth_headers, json={"number": "12AB", "label": "Compte invalide"}
    )
    assert response.status_code == 400
    # Numero trop court : refuse par la validation d'entree (422).
    trop_court = client.post(
        API + "/accounts", headers=auth_headers, json={"number": "88", "label": "Trop court"}
    )
    assert trop_court.status_code == 422


def test_api_etats_pdf_et_bordereaux(client, auth_headers):
    """J1 : etats CGNC en JSON, documents PDF (etats, bordereaux) via l'API."""
    esg = client.get(API + "/reports/esg?year=2026", headers=auth_headers)
    assert esg.status_code == 200
    corps = esg.json()
    for cle in ("marge_brute", "valeur_ajoutee", "ebe", "resultat_net", "soldes"):
        assert cle in corps
    assert len(corps["soldes"]) == 6
    assert corps["coherent_avec_cpc"] is True

    etic = client.get(API + "/reports/etic?year=2026", headers=auth_headers)
    assert etic.status_code == 200
    assert len(etic.json()["notes"]) == 10
    assert etic.json()["indisponibles"]

    for url in (
        API + "/reports/bilan/pdf?year=2026",
        API + "/reports/cpc/pdf?year=2026",
        API + "/reports/esg/pdf?year=2026",
        API + "/reports/etic/pdf?year=2026",
        API + "/reports/bordereau-greffe/pdf?year=2026",
        API + "/vat/edi/bordereau?year=2026&quarter=1",
    ):
        reponse = client.get(url, headers=auth_headers)
        assert reponse.status_code == 200, url
        assert reponse.headers["content-type"] == "application/pdf", url
        assert reponse.content.startswith(b"%PDF-"), url

    inconnu = client.get(API + "/reports/inconnu/pdf?year=2026", headers=auth_headers)
    assert inconnu.status_code == 400




def test_api_stocks(client, auth_headers):
    """P1.3 : API des stocks (article, mouvements CMUP, inventaire, dépréciation, états)."""
    article = client.post(
        API + "/stocks",
        headers=auth_headers,
        json={
            "reference": "API001",
            "label": "Article API",
            "stock_account": "3111",
            "unit": "U",
            "valuation_method": "cmup",
            "alert_threshold": "2",
        },
    )
    assert article.status_code == 201, article.text
    assert article.json()["valuation_method"] == "cmup"
    assert article.json()["quantity_on_hand"] == "0.000"

    entree = client.post(
        API + "/stocks/API001/mouvements",
        headers=auth_headers,
        json={
            "movement_date": "2026-01-10",
            "movement_type": "entree",
            "quantity": "10",
            "unit_cost": "100",
            "reason": "achat",
        },
    )
    assert entree.status_code == 201, entree.text
    assert entree.json()["value"] == "1000.00"
    assert entree.json()["entry_number"].startswith("EC")  # ecriture de variation

    sortie = client.post(
        API + "/stocks/API001/mouvements",
        headers=auth_headers,
        json={
            "movement_date": "2026-03-10",
            "movement_type": "sortie",
            "quantity": "4",
            "reason": "vente",
        },
    )
    assert sortie.json()["value"] == "-400.00"
    assert sortie.json()["unit_cost"] == "100.0000"

    fiche = client.get(API + "/stocks/API001", headers=auth_headers)
    assert fiche.status_code == 200
    assert fiche.json()["etat"]["value"] == "600.00"
    assert fiche.json()["etat"]["quantity"] == "6.000"
    assert len(fiche.json()["mouvements"]) == 2

    etat = client.get(API + "/stocks/etat", headers=auth_headers)
    assert etat.json()["total_valeur"] == "600.00"
    assert etat.json()["conforme"] is True

    variation = client.get(API + "/stocks/variation?exercice=2026", headers=auth_headers)
    assert variation.json()["total_entrees"] == "1000.00"
    assert variation.json()["total_sorties"] == "400.00"
    assert variation.json()["total_final"] == "600.00"

    inventaire = client.post(
        API + "/stocks/inventaire",
        headers=auth_headers,
        json={
            "count_date": "2026-06-30",
            "lignes": [{"reference": "API001", "physical_quantity": "5"}],
            "visumotif": "Ecart de 16 % constate (PV d'inventaire)",
        },
    )
    assert inventaire.status_code == 201, inventaire.text
    assert inventaire.json()["ecart_valeur"] == "-100.00"
    assert inventaire.json()["nb_ecarts"] == 1

    provision = client.post(
        API + "/stocks/API001/provisions",
        headers=auth_headers,
        json={
            "exercice": 2026,
            "inventory_value": "300",
            "motif": "Valeur d'inventaire devenue inferieure (obsolescence)",
        },
    )
    assert provision.status_code == 201, provision.text
    assert provision.json()["compte_provision"] == "3911"
    assert provision.json()["dotation"] == "200.00"
    provisions = client.get(API + "/stocks/provisions?exercice=2026", headers=auth_headers)
    assert provisions.json()["total_provision"] == "200.00"

    controles = client.get(API + "/stocks/controles?exercice=2026", headers=auth_headers)
    assert controles.status_code == 200
    assert isinstance(controles.json(), list)
    sous_seuil = client.get(API + "/stocks?sous_seuil=true", headers=auth_headers)
    assert sous_seuil.status_code == 200


def test_api_audit_tracabilite_et_cloture(client, auth_headers):
    """P1.6 : journal d'audit, piste fiable, verrouillages, à-nouveaux, banque."""
    journal = client.get(API + "/audit", headers=auth_headers)
    assert journal.status_code == 200
    entrees = journal.json()
    assert isinstance(entrees, list)
    assert all("action" in entree for entree in entrees)

    export = client.get(API + "/audit/export", headers=auth_headers)
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert export.text.startswith("\ufeff")
    assert "horodatage;utilisateur_id;action" in export.text

    chainage = client.get(API + "/audit/chainage", headers=auth_headers)
    assert chainage.status_code == 200
    assert chainage.json()["integre"] is True

    # Verrouillage mensuel : refus d'ecriture + trace de la tentative.
    verrou = client.post(
        API + "/audit/verrouillages",
        params={"year": 2026, "periode": 6, "motif": "TVA de juin deposee"},
        headers=auth_headers,
    )
    assert verrou.status_code == 201, verrou.text
    verrous = client.get(
        API + "/audit/verrouillages", params={"year": 2026}, headers=auth_headers
    )
    assert verrous.json()["mois"] == [6]
    assert verrous.json()["nb_verrous"] == 1

    refus = client.post(
        API + "/entries",
        headers=auth_headers,
        json={
            "entry_date": "2026-06-30",
            "journal_code": "OD",
            "label": "Ecriture interdite",
            "lines": [
                {"account_number": "6131", "debit": "100.00"},
                {"account_number": "5141", "credit": "100.00"},
            ],
        },
    )
    assert refus.status_code == 400
    assert "verrouillee" in refus.json()["detail"]

    deverrouillage = client.request(
        "DELETE",
        API + f"/audit/verrouillages/{verrou.json()['id']}",
        params={"motif": "Correction d'une erreur de saisie"},
        headers=auth_headers,
    )
    assert deverrouillage.status_code == 200
    assert deverrouillage.json()["periode"] == 6

    # A-nouveaux : controle initial (aucun) puis generation a la cloture 2026.
    controle = client.get(API + "/audit/cloture/2026", headers=auth_headers)
    assert controle.status_code == 200
    assert controle.json()["a_nouveaux"]["existe"] is False

    cloture = client.post(API + "/audit/cloture/2026", headers=auth_headers)
    assert cloture.status_code == 200, cloture.text
    corps = cloture.json()
    assert corps["statut"] == "closed"
    assert corps["a_nouveaux"]["genere"] is False  # dossier vierge dans ce test
    controle = client.get(API + "/audit/cloture/2026", headers=auth_headers)
    assert controle.json()["statut"] == "closed"

    # Reouverture encadree (P1) : motif obligatoire, tracabilite.
    sans_motif = client.post(API + "/audit/cloture/2026/reouvrir", headers=auth_headers)
    assert sans_motif.status_code == 422  # motif exige (min_length=10)
    reouverture = client.post(
        API + "/audit/cloture/2026/reouvrir",
        params={"motif": "Correction d'une charge omise (controle interne)"},
        headers=auth_headers,
    )
    assert reouverture.status_code == 200, reouverture.text
    assert reouverture.json()["statut"] == "open"
    assert reouverture.json()["statut_avant"] == "closed"

    # Rapprochement bancaire : import puis etat.
    importation = client.post(
        API + "/audit/releves",
        data={
            "account_number": "5141",
            "date_from": "2026-05-01",
            "date_to": "2026-05-31",
            "closing_balance": "0",
        },
        files={
            "fichier": (
                "releve.csv",
                "date;libelle;reference;debit;credit\n2026-05-04;Test;REF;100,00;\n",
                "text/csv",
            )
        },
        headers=auth_headers,
    )
    assert importation.status_code == 201, importation.text
    releve_id = importation.json()["id"]
    detail = client.get(API + f"/audit/releves/{releve_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["etat"]["solde_bancaire"] == "0.00"
    assert detail.json()["a_rapprocher"]

    alertes = client.get(API + "/audit/alertes", headers=auth_headers)
    assert alertes.status_code == 200
    assert isinstance(alertes.json(), list)


def test_api_immobilisations(client, auth_headers):
    """P1.2 : API des immobilisations (fiche, plan, dotation, cession, états)."""
    comptes = client.get(API + "/assets/comptes/2332", headers=auth_headers)
    assert comptes.status_code == 200
    assert comptes.json()["amortissement"] == "2833"
    assert comptes.json()["dotation"] == "61933"

    creation = client.post(
        API + "/assets",
        headers=auth_headers,
        json={
            "label": "Ordinateur portable",
            "account_number": "2355",
            "acquisition_date": "2026-02-01",
            "service_date": "2026-02-01",
            "valeur_origine": "12000.00",
            "duree_annees": 5,
            "tva_montant": "2400.00",
        },
    )
    assert creation.status_code == 201, creation.text
    corps = creation.json()
    code = corps["code"]
    assert code == "IM202600001"
    assert corps["statut"] == "en_service"
    assert corps["tva_compte"] == "34551"

    fiche = client.get(API + f"/assets/{code}", headers=auth_headers)
    assert fiche.status_code == 200
    detail = fiche.json()
    # Mise en service en fevrier : prorata temporis = 11/12 (CGI art. 10).
    assert detail["plan"][0]["annuite"] == "2200.00"
    assert detail["comptes"]["dotation"] == "61935"
    assert Decimal(detail["vnc"]) == Decimal("12000.00")

    dotation = client.post(
        API + f"/assets/{code}/dotation", headers=auth_headers, json={"exercice": 2026}
    )
    assert dotation.status_code == 200, dotation.text
    assert dotation.json()["compte_dotation"] == "61935"
    assert dotation.json()["annuite"] == "2200.00"

    doublon = client.post(
        API + f"/assets/{code}/dotation", headers=auth_headers, json={"exercice": 2026}
    )
    assert doublon.status_code == 400
    assert "deja constatee" in doublon.json()["detail"]

    etat = client.get(API + "/assets/etat?exercice=2026", headers=auth_headers)
    assert etat.status_code == 200
    assert Decimal(etat.json()["total_brut"]) == Decimal("12000.00")
    # VNC apres la dotation de 2026 (2 200,00 au titre du prorata temporis) :
    assert Decimal(etat.json()["total_vnc"]) == Decimal("9800.00")

    amortissements = client.get(API + "/assets/amortissements?exercice=2026", headers=auth_headers)
    assert amortissements.json()["total_dotation"] == "2200.00"

    controles = client.get(API + "/assets/controles?exercice=2026", headers=auth_headers)
    assert controles.status_code == 200
    assert all(c["niveau"] in ("bloquant", "avertissement") for c in controles.json())

    cession = client.post(
        API + f"/assets/{code}/cession",
        headers=auth_headers,
        json={"date_cession": "2026-12-31", "prix": "9000.00", "motif": "Vente"},
    )
    assert cession.status_code == 200, cession.text
    assert Decimal(cession.json()["vnc"]) == Decimal("9800.00")
    assert Decimal(cession.json()["resultat_cession"]) == Decimal("-800.00")
    assert Decimal(cession.json()["regularisation_tva"]) == Decimal("2400.00")

    cessions = client.get(API + "/assets/cessions?exercice=2026", headers=auth_headers)
    assert len(cessions.json()["lignes"]) == 1
    assert cessions.json()["lignes"][0]["code"] == code


def test_api_is_et_liasse(client, auth_headers, db, ctx):
    """P2.1 : API liasse — dossier IS, EFI, validation XSD, XML, registre, accusé.

    Le référentiel de codification livré décrit la **seule correspondance documentée**
    (modèle normal, tableau 1, code `13400` = capital social) : le test l'exerce de
    bout en bout (aucun code n'est deviné par l'application, cf. ambiguïté A22).
    """
    from app.db.seed import get_or_create_fiscal_year
    from app.services.accounting import create_entry, get_journal

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
    exercice.status = "closed"  # P1.6 : le dépôt exige un exercice clos
    db.commit()

    # 1. Dossier IS / liasse
    dossier = client.get(API + "/liasse/2026?modele=normal", headers=auth_headers)
    assert dossier.status_code == 200, dossier.text
    corps = dossier.json()
    assert corps["modele"] == "liasse_modele_normal"
    assert corps["liasse"]["nb_cellules"] == 1
    # Exercice sans produit ni charge : le calcul fiscal reste cohérent (IS nul)
    assert Decimal(str(corps["fiscal"]["calcul"]["is_theorique"])) == Decimal("0.00")
    cellule = corps["liasse"]["tableaux"][0]["cellules"][0]
    assert (cellule["code_edi"], cellule["valeur"]) == ("13400", "-100000.00")
    assert corps["reconciliation"]["conforme"] is True

    # 2. EFI assisté (JSON + CSV)
    efi = client.get(API + "/liasse/2026/efi?modele=normal", headers=auth_headers)
    assert efi.status_code == 200, efi.text
    assert efi.json()["nb_lignes"] == 1
    assert efi.json()["feuilles"][0]["onglet"] == "Tableau 1"
    efi_csv = client.get(API + "/liasse/2026/efi.csv?modele=normal", headers=auth_headers)
    assert efi_csv.status_code == 200
    assert "13400" in efi_csv.text and "tableau_id" in efi_csv.text

    # 3. Validation XSD réelle
    validation = client.get(
        API + "/liasse/2026/validation-xsd?modele=normal", headers=auth_headers
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["validation"]["valide"] is True
    assert validation.json()["bloquants"] == []

    # 4. Fichier XML EDI (validé)
    xml = client.get(API + "/liasse/2026/xml?modele=normal", headers=auth_headers)
    assert xml.status_code == 200, xml.text
    assert xml.headers["content-type"].startswith("application/xml")
    assert 'filename="LIASSE_1234567_2026.xml"' in xml.headers["content-disposition"]
    assert "<Liasse>" in xml.text
    assert "<codeEdi>13400</codeEdi>" in xml.text
    assert "<identifiantFiscal>1234567</identifiantFiscal>" in xml.text

    # 5. Enregistrement de la liasse (déclaration brouillon avec fichier EDI)
    depot = client.post(
        API + "/liasse/2026/enregistrer",
        headers=auth_headers,
        json={"modele": "normal", "mode_depot": "EDI", "avec_xml": True},
    )
    assert depot.status_code == 201, depot.text
    declaration = depot.json()
    assert declaration["type"] == "LIASSE"
    assert declaration["periode"] == "2026"
    assert declaration["statut"] == "brouillon"
    assert declaration["nb_lignes"] == 1
    assert len(declaration["fichier_hash"]) == 64
    assert "conforme au schéma XSD" in declaration["notes"]

    # 6. Accusé de réception puis registre
    accuse = client.post(
        API + "/liasse/2026/depot",
        headers=auth_headers,
        json={"jour": "2026-04-01", "accuse_le": "2026-04-09"},
    )
    assert accuse.status_code == 200, accuse.text
    assert accuse.json()["statut"] == "acceptee"
    assert accuse.json()["accuse_le"] == "2026-04-09"
    registre = client.get(API + "/liasse/declarations", headers=auth_headers)
    assert registre.status_code == 200
    assert [ligne["periode"] for ligne in registre.json()] == ["2026"]


def test_api_liasse_refusee_sans_exercice_clos(client, auth_headers, db, ctx):
    """Sans exercice clos, le fichier EDI est refusé (422) et le dossier l'explique."""
    from app.db.seed import get_or_create_fiscal_year

    get_or_create_fiscal_year(db, ctx["company"], 2026)
    db.commit()
    dossier = client.get(API + "/liasse/2026?modele=normal", headers=auth_headers)
    assert dossier.status_code == 200
    codes = {controle["code"] for controle in dossier.json()["controles"]}
    assert "fiscal.exercice_non_clos" in codes
    assert "liasse.codification_absente" in codes

    xml = client.get(API + "/liasse/2026/xml?modele=normal", headers=auth_headers)
    assert xml.status_code in (400, 422)
    assert "refus" in xml.json()["detail"].lower()

    depot_sans_liasse = client.post(
        API + "/liasse/2026/depot", headers=auth_headers, json={"jour": "2026-04-01"}
    )
    assert depot_sans_liasse.status_code == 404


def test_api_paie_et_dts(client, auth_headers):
    """P1.4 : API paie (salarié, bulletin, écriture, paiement) et DTS « 9421 »."""
    salarie = client.post(
        API + "/payroll/employees",
        headers=auth_headers,
        json={
            "matricule": "API001",
            "nom": "ALAMI Youssef",
            "date_entree": "2024-01-15",
            "cin": "BK123456",
            "cnss": "987654321",
            "situation_familiale": "marie",
            "enfants": 2,
            "type_contrat": "cdi",
        },
    )
    assert salarie.status_code == 201, salarie.text
    assert salarie.json()["matricule"] == "API001"

    contrat = client.post(
        API + "/payroll/employees/API001/contrats",
        headers=auth_headers,
        json={
            "salaire_base": "10000",
            "prime_transport": "500",
            "date_effet": "2026-01-01",
        },
    )
    assert contrat.status_code == 201, contrat.text
    assert Decimal(contrat.json()["salaire_base"]) == Decimal("10000.00")

    preparation = client.post(
        API + "/payroll/runs",
        headers=auth_headers,
        json={"periode": "2026-01"},
    )
    assert preparation.status_code == 201, preparation.text
    assert Decimal(preparation.json()["total_brut"]) == Decimal("10500.00")
    assert Decimal(preparation.json()["total_net"]) == Decimal("9433.23")

    cycle = client.get(API + "/payroll/runs/2026-01", headers=auth_headers)
    assert cycle.status_code == 200
    bulletin = cycle.json()["bulletins"][0]
    assert Decimal(bulletin["ir"]) == Decimal("560.67")
    assert Decimal(bulletin["base_cnss"]) == Decimal("6000.00")

    validation = client.post(API + "/payroll/runs/2026-01/valider", headers=auth_headers)
    assert validation.status_code == 200, validation.text
    assert validation.json()["entry_number"].startswith("EC")
    assert validation.json()["statut"] == "valide"

    reglement = client.post(
        API + "/payroll/runs/2026-01/payer",
        headers=auth_headers,
        json={"mode": "virement"},
    )
    assert reglement.status_code == 200, reglement.text
    assert reglement.json()["statut"] == "paye"

    bulletin_pdf = client.get(
        API + f"/payroll/bulletin/{bulletin['id']}/pdf", headers=auth_headers
    )
    assert bulletin_pdf.status_code == 200
    assert bulletin_pdf.content.startswith(b"%PDF-")

    livre = client.get(API + "/payroll/livre?annee=2026", headers=auth_headers)
    assert Decimal(livre.json()["totaux"]["brut"]) == Decimal("10500.00")
    cotisations = client.get(API + "/payroll/cotisations?annee=2026", headers=auth_headers)
    assert cotisations.json()["totaux"]["ir"] == "560.67"
    recapitulatif = client.get(API + "/payroll/recapitulatif?annee=2026", headers=auth_headers)
    assert recapitulatif.json()["nb_salaries"] == 1

    modele = client.get(API + "/payroll/dts/2026", headers=auth_headers)
    assert modele.status_code == 200, modele.text
    assert modele.json()["totaux"]["ir_retenu"] == "560.67"
    assert [s["matricule"] for s in modele.json()["personnel_permanent"]] == ["API001"]

    xml = client.get(API + "/payroll/dts/2026/xml", headers=auth_headers)
    assert xml.status_code == 200, xml.text
    assert xml.headers["content-type"].startswith("application/xml")
    assert "<TraitementEtSalaire " in xml.text  # modele officiel V5.1
    assert "<totalMtIrPrelevePP>560.67</totalMtIrPrelevePP>" in xml.text

    validation_xsd = client.get(API + "/payroll/dts/2026/validation-xsd", headers=auth_headers)
    assert validation_xsd.json()["valide"] is None  # XSD non fourni (écart n° 6)

    efi = client.get(API + "/payroll/dts/2026/efi", headers=auth_headers)
    assert efi.status_code == 200
    assert efi.json()[0]["numero_cnss"] == "987654321"

    declaration = client.post(API + "/payroll/dts/2026/declaration", headers=auth_headers)
    assert declaration.status_code == 201, declaration.text
    assert declaration.json()["statut"] == "brouillon"
    assert len(declaration.json()["fichier_hash"]) == 64

    depot = client.post(
        API + f"/payroll/dts/declarations/{declaration.json()['id']}/depot",
        headers=auth_headers,
        json={"accuse_le": "2026-04-20"},
    )
    assert depot.status_code == 200, depot.text
    assert depot.json()["statut"] == "acceptee"
    registre = client.get(API + "/payroll/dts/declarations", headers=auth_headers)
    assert len(registre.json()) == 1

    fiche = client.get(API + "/payroll/dts/2026/fiche-pdf", headers=auth_headers)
    assert fiche.status_code == 200
    assert fiche.content.startswith(b"%PDF-")


def test_api_greffe_depot_pieces_paiement_et_certificat(
    client, auth_headers, db, ctx, tmp_path, monkeypatch
):
    """P1.5 : API du dépôt au greffe (checklist, pièces, états, taxes, certificat)."""
    from app.core.config import settings
    from app.services.pdf_documents import pdf_pv_ag, pdf_rapport_gestion

    monkeypatch.setattr(settings, "greffe_dir", tmp_path)  # aucune écriture au dépôt
    # Depuis le correctif P1 greffe, un PDF vide est refusé : les pièces de test
    # sont des documents **réels** produits par l'application.
    pdf = pdf_pv_ag(
        db, ctx["company"], 2026, date_ag=date(2026, 6, 10), date_limite=date(2027, 6, 30)
    )
    pdf_rapport = pdf_rapport_gestion(db, ctx["company"], 2026)

    # 1. Catalogue des pièces par forme juridique (guide de novembre 2025).
    catalogue = client.get(
        API + "/greffe/pieces", params={"forme_juridique": "SARL"}, headers=auth_headers
    )
    assert catalogue.status_code == 200, catalogue.text
    codes = {piece["code"] for piece in catalogue.json()["pieces"]}
    assert {"etats_synthese", "rapport_gestion", "pv_ag"} <= codes
    assert "10 Mo" in catalogue.json()["texte_limite"]

    # 2. L'exercice doit être clos pour déposer (contrôle bloquant n° 1).
    cloture = client.post(API + "/audit/cloture/2026", headers=auth_headers)
    assert cloture.status_code == 200, cloture.text

    depot = client.post(
        API + "/greffe/depots",
        headers=auth_headers,
        json={
            "exercice": 2026,
            "forme_juridique": "SARL",
            "date_ag": "2026-06-10",
            "montant_taxes": "350",
            "notes": "dépôt API",
        },
    )
    assert depot.status_code == 201, depot.text
    corps = depot.json()
    depot_id = corps["id"]
    assert corps["statut"] == "nouveau"
    assert corps["date_limite_depot"] == "2027-06-30"  # clôture 31/12 + 6 mois
    # Unicité par exercice (contrôle bloquant n° 6).
    doublon = client.post(
        API + "/greffe/depots",
        headers=auth_headers,
        json={"exercice": 2026, "forme_juridique": "SARL"},
    )
    assert doublon.status_code == 400, doublon.text

    # 3. Checklist et contrôles : pièces manquantes.
    checklist = client.get(API + f"/greffe/depots/{depot_id}/checklist", headers=auth_headers)
    assert checklist.status_code == 200
    assert checklist.json()["completude"]["complete"] is False
    controles = client.get(API + f"/greffe/depots/{depot_id}/controles", headers=auth_headers)
    assert "greffe.checklist_incomplete" in {c["code"] for c in controles.json()}

    # 4. Téléversement d'une pièce externe (PDF) puis refus d'un non-PDF.
    envoi = client.post(
        API + f"/greffe/depots/{depot_id}/pieces",
        params={"piece_code": "pv_ag"},
        files={"fichier": ("PV_AG_2026.pdf", pdf, "application/pdf")},
        headers=auth_headers,
    )
    assert envoi.status_code == 201, envoi.text
    assert envoi.json()["taille_octets"] == len(pdf)
    assert len(envoi.json()["hash_sha256"]) == 64
    refuse = client.post(
        API + f"/greffe/depots/{depot_id}/pieces",
        params={"piece_code": "rapport_gestion"},
        files={"fichier": ("Rapport.docx", b"contenu word", "application/msword")},
        headers=auth_headers,
    )
    assert refuse.status_code == 400
    assert "PDF" in refuse.json()["detail"]
    # La pièce corrigée est acceptée (rapport de gestion au format PDF).
    corrige = client.post(
        API + f"/greffe/depots/{depot_id}/pieces",
        params={"piece_code": "rapport_gestion"},
        files={"fichier": ("Rapport_gestion_2026.pdf", pdf_rapport, "application/pdf")},
        headers=auth_headers,
    )
    assert corrige.status_code == 201, corrige.text
    # Un PDF **vide** (constat de recette : 193 octets, page blanche) est refusé :
    # le contenu est obligatoire, pas seulement le type et la taille.
    vide = client.post(
        API + f"/greffe/depots/{depot_id}/pieces",
        params={"piece_code": "tableau_financement"},
        files={
            "fichier": (
                "tableau_financement_vide.pdf",
                b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
                b"trailer<</Root 1 0 R>>\n%%EOF\n",
                "application/pdf",
            )
        },
        headers=auth_headers,
    )
    assert vide.status_code == 400, vide.text
    assert "illisible" in vide.json()["detail"]

    # 5. Génération des pièces produites par Compta MA (états, bordereau, rapport,
    # PV d'AG) : le rapport de gestion et le PV sont **rédigés** par l'application.
    generation = client.post(
        API + f"/greffe/depots/{depot_id}/pieces/generer", headers=auth_headers
    )
    assert generation.status_code == 200, generation.text
    pieces = {piece["piece_code"] for piece in generation.json()["documents"]}
    assert {
        "etats_synthese",
        "etat_complementaire",
        "rapport_gestion",
        "pv_ag",
    } <= pieces

    # 6. Cycle de vie : soumission puis approbation (délai de paiement à 3 jours).
    soumission = client.post(
        API + f"/greffe/depots/{depot_id}/etat",
        headers=auth_headers,
        json={"etat": "en_cours"},
    )
    assert soumission.status_code == 200, soumission.text
    approbation = client.post(
        API + f"/greffe/depots/{depot_id}/etat",
        headers=auth_headers,
        json={"etat": "approuve", "motif": "Notification du greffe"},
    )
    assert approbation.status_code == 200, approbation.text
    limite = date.fromisoformat(approbation.json()["date_limite_paiement"])
    assert limite == date.today() + timedelta(days=3)

    alertes = client.get(API + "/greffe/alertes", headers=auth_headers)
    assert alertes.status_code == 200
    assert any(alerte["code"].startswith("greffe.paiement") for alerte in alertes.json())

    # 7. Paiement des taxes (CMI) : l'alerte disparaît.
    paiement = client.post(
        API + f"/greffe/depots/{depot_id}/paiements",
        headers=auth_headers,
        json={"montant": "350", "moyen": "cmi", "reference": "CMI-2026-77"},
    )
    assert paiement.status_code == 201, paiement.text
    taxes = client.get(API + f"/greffe/depots/{depot_id}/paiements", headers=auth_headers)
    assert taxes.json()["total_paye"] == "350.00"
    assert taxes.json()["solde"] == "0.00"
    trop = client.post(
        API + f"/greffe/depots/{depot_id}/paiements",
        headers=auth_headers,
        json={"montant": "10"},
    )
    assert trop.status_code == 400

    # 8. Dépôt final puis archivage du certificat (SHA-256).
    depot_final = client.post(
        API + f"/greffe/depots/{depot_id}/etat",
        headers=auth_headers,
        json={"etat": "depose", "motif": "Dépôt finalisé sur le portail"},
    )
    assert depot_final.status_code == 200, depot_final.text
    certificat = client.post(
        API + f"/greffe/depots/{depot_id}/certificat",
        params={"reference": "CERT-2026-0001"},
        files={"fichier": ("certificat.pdf", pdf, "application/pdf")},
        headers=auth_headers,
    )
    assert certificat.status_code == 200, certificat.text
    assert len(certificat.json()["certificat_hash"]) == 64
    telechargement = client.get(
        API + f"/greffe/depots/{depot_id}/certificat", headers=auth_headers
    )
    assert telechargement.status_code == 200
    assert telechargement.content == pdf

    # 9. Archive ZIP du dossier (pièces + bordereau + manifeste).
    dossier = client.get(API + f"/greffe/depots/{depot_id}/dossier", headers=auth_headers)
    assert dossier.status_code == 200, dossier.text
    assert dossier.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(dossier.content)) as archive:
        noms = archive.namelist()
        assert "00_bordereau_recapitulatif.pdf" in noms
        assert "manifeste.json" in noms
        assert archive.read("00_bordereau_recapitulatif.pdf").startswith(b"%PDF")

    # 10. Suivi global et bordereau PDF.
    etat = client.get(API + "/greffe/etat", headers=auth_headers)
    assert etat.json()["compteurs"]["depose"] == 1
    bordereau = client.get(API + f"/greffe/depots/{depot_id}/bordereau", headers=auth_headers)
    assert bordereau.status_code == 200
    assert bordereau.content.startswith(b"%PDF-")

