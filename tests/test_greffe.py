"""Tests du module Depot au greffe du tribunal (P1.5).

Verifie les criteres de recette du CDC § 3.5 : **checklist par forme juridique**
(loi 5-96 art. 10/93, loi 17-95 art. 14, guide de novembre 2025), **controle des
10 Mo**, **calcul de la date limite d'AG** (cloture + 6 mois), **transitions des
7 etats** du portail avec motif, **alerte des 3 jours** apres approbation (rejet
automatique au-dela), **archivage du certificat** (SHA-256), **assembleur ZIP**
du dossier, alertes d'amende hors delai et provision **6195 / 1515**.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import get_or_create_fiscal_year
from app.models import GREFFE_ETATS, PIECE_TABLEAU_FINANCEMENT, GreffeEvent, PeriodLock
from app.models.greffe import GreffeDocument
from app.services import greffe
from app.services.period_locks import verrouiller_periode

pytestmark = pytest.mark.usefixtures("ctx")

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
TAILLE_10_MO = 10 * 1024 * 1024


@pytest.fixture(autouse=True)
def stockage_greffe(tmp_path, monkeypatch):
    """Archive les pieces du greffe dans un dossier temporaire (jamais le depot)."""
    monkeypatch.setattr(settings, "greffe_dir", tmp_path)
    return tmp_path


def _cloturer(db, company, year: int) -> None:
    """Cloture l'exercice (les comptes definitifs sont exiges par le greffe)."""
    exercice = get_or_create_fiscal_year(db, company, year)
    exercice.status = "closed"
    db.commit()


def _dossier(db, ctx, *, exercice: int | None = None, **kwargs) -> greffe.GreffeDeposit:
    """Dossier de depot type : SARL de l'exercice de test, deja cloture."""
    year = exercice or ctx["year"]
    _cloturer(db, ctx["company"], year)
    parametres = {
        "company": ctx["company"],
        "exercice": year,
        "user_id": ctx["user"].id,
        "forme_juridique": "SARL",
        "date_ag": date(year, 6, 10),
        "montant_taxes": Decimal("350"),
    }
    parametres.update(kwargs)
    return greffe.creer_depot(db, **parametres)


def _pieces_obligatoires(db, ctx, depot) -> None:
    """Fournit toutes les pieces exigees : etats, bordereau, rapport et PV **generes**.

    Depuis le correctif P1 greffe, le **rapport de gestion** et le **PV d'AG**
    sont rediges par l'application a partir des comptes (un PDF vide n'est plus
    accepte) : le dossier est donc complete par `generer_pieces`.
    """
    greffe.generer_pieces(db, depot, company=ctx["company"], user_id=ctx["user"].id)
    db.commit()


def _codes(controles: list[dict]) -> set[str]:
    """Codes des controles presents (independamment de leur niveau)."""
    return {controle["code"] for controle in controles}


def _codes_bloquants(controles: list[dict]) -> set[str]:
    """Codes des controles de niveau bloquant."""
    return {
        controle["code"]
        for controle in controles
        if controle["niveau"] == "bloquant"
    }


def _dossier_approuve(db, ctx, *, montant: str = "350"):
    """Dossier complet soumis puis approuve par le greffe (pret a payer)."""
    depot = _dossier(db, ctx, montant_taxes=Decimal(montant))
    _pieces_obligatoires(db, ctx, depot)
    greffe.changer_etat(db, depot, "en_cours", user_id=ctx["user"].id)
    greffe.changer_etat(
        db, depot, "approuve", motif="Notification d'approbation", user_id=ctx["user"].id
    )
    db.commit()
    return depot


# ---------------------------------------------------------------------------
# Checklist et referentiels
# ---------------------------------------------------------------------------
def test_catalogue_pieces_par_forme_juridique():
    """Le rapport du CAC n'est exige que pour la SCA (SA/SARL : si CAC nomme)."""
    for forme in ("SNC", "SARL", "SA"):
        obligatoires = greffe.pieces_obligatoires(forme)
        assert greffe.PIECE_ETATS_SYNTHESE in obligatoires
        assert greffe.PIECE_RAPPORT_GESTION in obligatoires
        assert greffe.PIECE_PV_AG in obligatoires
        assert greffe.PIECE_RAPPORT_CAC not in obligatoires
    obligatoires_sca = greffe.pieces_obligatoires("SCA")
    assert greffe.PIECE_RAPPORT_CAC in obligatoires_sca
    # Le tableau de financement depend des seuils : jamais bloquant.
    for forme in ("SNC", "SARL", "SA", "SCS", "SCA"):
        assert PIECE_TABLEAU_FINANCEMENT not in greffe.pieces_obligatoires(forme)
    # Forme inconnue : socle commun exige (prudence).
    assert greffe.PIECE_PV_AG in greffe.pieces_obligatoires(None)


def test_catalogue_pieces_coherent_avec_le_bordereau():
    """Le catalogue du module (P1.5) et le bordereau PDF (J1) doivent concorder.

    Les deux referentiels decrivent les memes pieces avec des libelles
    differents (prose du bordereau remis au greffe, libelles du module) : la
    table de correspondance ci-dessous **epingle** l'egalite des deux listes,
    si bien que faire evoluer l'une sans l'autre fait echouer ce test.
    """
    from app.services.pdf_documents import PIECES_GREFFE_COMMUNES, PIECES_GREFFE_PAR_FORME

    correspondances = {
        "Etats de synthese (bilan, CPC, ESG, ETIC) certifies conformes": (
            greffe.PIECE_ETATS_SYNTHESE
        ),
        "Rapport de gestion": greffe.PIECE_RAPPORT_GESTION,
        (
            "Proces-verbal de l'assemblee generale d'approbation et texte des "
            "resolutions"
        ): greffe.PIECE_PV_AG,
        "Rapport du ou des commissaires aux comptes": greffe.PIECE_RAPPORT_CAC,
        "Rapport du commissaire aux comptes (si nomme)": greffe.PIECE_RAPPORT_CAC,
    }
    # 1. Le bordereau ne contient aucune piece inconnue du catalogue.
    libelles_bordereau = set(PIECES_GREFFE_COMMUNES)
    for pieces in PIECES_GREFFE_PAR_FORME.values():
        libelles_bordereau |= set(pieces)
    assert libelles_bordereau <= set(correspondances)
    assert set(correspondances.values()) <= {
        piece.code for piece in greffe.CATALOGUE_PIECES
    }

    # 2. Pour chaque forme, le bordereau et le catalogue listent les memes pieces
    #    (les pieces produites par le module restent hors liste du bordereau).
    for forme in ("SNC", "SARL", "SA", "SCA"):
        attendues = set(PIECES_GREFFE_COMMUNES)
        attendues |= set(PIECES_GREFFE_PAR_FORME.get(forme, ()))
        bordereau = {correspondances[libelle] for libelle in attendues}
        obligatoires = set(greffe.pieces_obligatoires(forme))
        conditionnelles = {
            piece.code
            for piece in greffe.CATALOGUE_PIECES
            if piece.conditionnelle_pour(forme)
        }
        assert bordereau - obligatoires <= conditionnelles, forme
        assert obligatoires - bordereau <= {
            greffe.PIECE_ETAT_COMPLEMENTAIRE,
            greffe.PIECE_JUSTIFICATIF_PAIEMENT,
        }, forme


def test_date_limite_ag_et_ajout_de_mois():
    """Cloture + 6 mois (loi 5-96, art. 10), avec ajustement de fin de mois."""
    assert greffe.date_limite_ag(date(2026, 12, 31)) == date(2027, 6, 30)
    assert greffe.date_limite_ag(date(2025, 12, 31)) == date(2026, 6, 30)
    assert greffe.ajouter_mois(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert greffe.ajouter_mois(date(2026, 3, 15), 12) == date(2027, 3, 15)


def test_verification_pdf_et_limite_10_mo():
    """Une piece doit etre un PDF de 10 Mo maximum (guide de novembre 2025)."""
    assert greffe.verifier_piece_pdf("piece.pdf", PDF) == len(PDF)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.verifier_piece_pdf("scan.docx", b"contenu word")
    assert "PDF" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.verifier_piece_pdf("scanne.pdf", b"%PDF" + b"0" * TAILLE_10_MO)
    assert "10 Mo" in str(erreur.value)
    # 10 Mo pile reste acceptable (limite du portail).
    assert greffe.verifier_piece_pdf("limite.pdf", b"%PDF" + b"0" * (TAILLE_10_MO - 4))
    assert greffe.taille_lisible(TAILLE_10_MO) == "10.00 Mo"


def test_nom_fichier_securise():
    """Le nom archive ne permet pas de sortir du dossier de stockage."""
    assert greffe.nom_fichier_securise("../../etc/passwd") == "passwd.pdf"
    assert greffe.nom_fichier_securise("PV AG 2026.PDF") == "PV_AG_2026.pdf"
    nom = greffe.nom_fichier_securise("Rapport généré (2026).PDF")
    assert nom.endswith(".pdf") and "(" not in nom and "é" not in nom
    assert greffe.nom_fichier_securise(None) == "piece.pdf"
    assert greffe.nom_fichier_securise("...") == "piece.pdf"


# ---------------------------------------------------------------------------
# Dossier de depot : creation et controles bloquants
# ---------------------------------------------------------------------------
def test_creation_dossier_et_unicite_par_exercice(db, ctx):
    """Un seul dossier par exercice : la date limite decoule de la cloture."""
    depot = _dossier(db, ctx, date_ag=date(ctx["year"], 3, 20))
    db.commit()
    assert depot.statut == "nouveau"
    assert depot.forme_juridique == "SARL"
    assert depot.date_limite_depot == date(ctx["year"] + 1, 6, 30)  # 31/12 + 6 mois
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.creer_depot(db, company=ctx["company"], exercice=ctx["year"])
    assert "existe deja" in str(erreur.value)


def test_forme_juridique_non_supportee(db, ctx):
    """Seules les formes des lois 5-96 et 17-95 sont prises en charge."""
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.creer_depot(
            db, company=ctx["company"], exercice=ctx["year"], forme_juridique="GIE"
        )
    assert "non supportee" in str(erreur.value)


def test_controles_bloquants_exercice_non_clos_et_checklist(db, ctx):
    """Exercice non clos et checklist incomplete bloquent la soumission."""
    get_or_create_fiscal_year(db, ctx["company"], ctx["year"])  # reste ouvert
    depot = greffe.creer_depot(
        db,
        company=ctx["company"],
        exercice=ctx["year"],
        user_id=ctx["user"].id,
        forme_juridique="SARL",
    )
    db.commit()
    controles = greffe.controles_depot(db, depot)
    assert "greffe.exercice_non_clos" in _codes(controles)
    assert "greffe.checklist_incomplete" in _codes(controles)
    assert _codes_bloquants(controles) >= {
        "greffe.exercice_non_clos",
        "greffe.checklist_incomplete",
    }
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "en_cours")
    assert "Soumission au portail refusée" in str(erreur.value)


def test_identite_societe_exigee_par_le_portail(db, ctx):
    """RC / IF / ICE doivent etre renseignes et conformes (blocage n° 5)."""
    ctx["company"].rc = None
    ctx["company"].ice = "123"
    db.commit()
    depot = _dossier(db, ctx)
    _pieces_obligatoires(db, ctx, depot)
    controles = greffe.controles_depot(db, depot)
    assert "greffe.identite_incomplete" in _codes_bloquants(controles)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "en_cours")
    assert "registre de commerce" in str(erreur.value)


def test_soumission_apres_pieces_et_controles_verts(db, ctx):
    """Avec toutes les pieces exigees et l'exercice clos, la soumission passe."""
    depot = _dossier(db, ctx)
    _pieces_obligatoires(db, ctx, depot)
    completude = greffe.taux_completude(db, depot)
    # Le justificatif de paiement n'existe qu'apres approbation.
    assert completude["manquantes"] == [
        "Justificatif de paiement des taxes"
    ] or completude["complete"]
    assert not _codes_bloquants(greffe.controles_depot(db, depot)) - {
        "greffe.exercice_non_clos"
    }
    greffe.changer_etat(db, depot, "en_cours", user_id=ctx["user"].id)
    db.commit()
    assert depot.statut == "en_cours"
    assert depot.date_soumission == date.today()


# ---------------------------------------------------------------------------
# Cycle de vie des 7 etats
# ---------------------------------------------------------------------------
def test_cycle_de_vie_des_sept_etats_et_journal(db, ctx):
    """Chaque transition est historisee avec son motif (journal des etats)."""
    depot = _dossier(db, ctx)
    _pieces_obligatoires(db, ctx, depot)
    greffe.changer_etat(db, depot, "en_cours", user_id=ctx["user"].id)
    greffe.changer_etat(
        db, depot, "rejete", motif="Pièce illisible : PV d'AG", user_id=ctx["user"].id
    )
    greffe.changer_etat(
        db, depot, "en_cours", motif="PV re-téléversé", user_id=ctx["user"].id
    )
    greffe.changer_etat(
        db, depot, "approuve", motif="Dossier conforme", user_id=ctx["user"].id
    )
    greffe.enregistrer_paiement(db, depot, montant="350", reference="CMI-1")
    greffe.changer_etat(
        db, depot, "depose", motif="Certificat en ligne", user_id=ctx["user"].id
    )
    db.commit()
    evenements = db.query(GreffeEvent).filter_by(deposit_id=depot.id).all()
    assert [(e.etat_avant, e.etat_apres) for e in evenements] == [
        ("nouveau", "en_cours"),
        ("en_cours", "rejete"),
        ("rejete", "en_cours"),
        ("en_cours", "approuve"),
        ("approuve", "depose"),
    ]
    assert evenements[1].motif == "Pièce illisible : PV d'AG"
    assert depot.statut == "depose"
    assert depot.dernier_motif == "Certificat en ligne"
    assert depot.statut in GREFFE_ETATS


def test_transitions_refusees_et_motif_obligatoire(db, ctx):
    """Etats terminaux, transitions interdites et motif obligatoire."""
    depot = _dossier(db, ctx)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "approuve", motif="trop tôt")
    assert "Transition refusée" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "nouveau")
    assert "déjà à l'état" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "annule")
    assert "motif est obligatoire" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "inexistant")
    assert "inconnu" in str(erreur.value)
    # Un dossier depose ne peut plus etre re-soumis (unicite par exercice).
    _pieces_obligatoires(db, ctx, depot)
    greffe.changer_etat(db, depot, "en_cours", user_id=ctx["user"].id)
    greffe.changer_etat(db, depot, "approuve", motif="Approbation du greffe")
    greffe.enregistrer_paiement(db, depot, montant="350")
    greffe.changer_etat(
        db, depot, "depose", motif="Dépôt final", user_id=ctx["user"].id
    )
    db.commit()
    assert greffe.GREFFE_TRANSITIONS["depose"] == ()
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "en_cours")
    assert "Transition refusée" in str(erreur.value)
    assert "greffe.dossier_deja_depose" in _codes_bloquants(
        greffe.controles_depot(db, depot)
    )


def test_soumission_hors_delai_avertissement_puis_forcage(db, ctx):
    """Un depot hors delai est un avertissement, bloquant a la soumission."""
    # AG tenue **apres** la limite (cloture + 6 mois) : generation possible (le PV
    # exige une date) et avertissement « hors delai » au meme titre qu'une date
    # absente.
    depot = _dossier(db, ctx, exercice=2025, date_ag=date(2026, 9, 30))
    _pieces_obligatoires(db, ctx, depot)
    db.commit()
    assert depot.date_limite_depot == date(2026, 6, 30)
    controles = greffe.controles_depot(db, depot)
    assert "greffe.ag_hors_delai" in _codes(controles)
    assert "greffe.ag_hors_delai" not in _codes_bloquants(controles)
    controles_soumission = greffe.controles_depot(db, depot, pour_soumission=True)
    assert "greffe.ag_hors_delai" in _codes_bloquants(controles_soumission)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "en_cours")
    assert "Délai d'approbation dépassé" in str(erreur.value)
    greffe.changer_etat(
        db, depot, "en_cours", forcer_hors_delai=True, user_id=ctx["user"].id
    )
    db.commit()
    assert depot.statut == "en_cours"


# ---------------------------------------------------------------------------
# Alerte "3 jours" et paiement des taxes
# ---------------------------------------------------------------------------
def test_alerte_paiement_trois_jours_puis_extinction(db, ctx):
    """L'alerte 3 jours nait de l'approbation et disparait au paiement."""
    depot = _dossier_approuve(db, ctx)
    assert depot.date_limite_paiement == date.today() + timedelta(days=3)
    alertes = greffe.alertes_depot(db, depot)
    codes = {alerte["code"] for alerte in alertes}
    assert "greffe.paiement_3_jours" in codes
    alerte = next(a for a in alertes if a["code"] == "greffe.paiement_3_jours")
    assert alerte["jours_restants"] == 3
    assert alerte["montant"] == Decimal("350.00")
    assert "greffe.paiement_3_jours" in _codes(greffe.controles_depot(db, depot))

    greffe.enregistrer_paiement(
        db, depot, montant="350", moyen="cmi", reference="CMI-2026-1",
        user_id=ctx["user"].id,
    )
    db.commit()
    assert greffe.total_paye(db, depot) == Decimal("350.00")
    assert greffe.solde_taxes(db, depot) == Decimal("0.00")
    assert all(
        a["code"] not in ("greffe.paiement_3_jours", "greffe.paiement_en_retard")
        for a in greffe.alertes_depot(db, depot)
    )
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.enregistrer_paiement(db, depot, montant="10")
    assert "déjà réglé" in str(erreur.value)


def test_alerte_rejet_automatique_apres_le_delai(db, ctx):
    """Au-dela de 3 jours, l'alerte devient rouge (rejet automatique)."""
    depot = _dossier_approuve(db, ctx)
    demain = depot.date_limite_paiement + timedelta(days=1)
    alertes = greffe.alertes_depot(db, depot, aujourdhui=demain)
    alerte = next(a for a in alertes if a["code"] == "greffe.paiement_en_retard")
    assert alerte["niveau"] == "urgent"
    assert "rejet automatique" in alerte["message"]
    controles = greffe.controles_depot(db, depot, aujourdhui=demain)
    assert "greffe.paiement_3_jours" in _codes_bloquants(controles)


def test_paiement_impossible_avant_approbation(db, ctx):
    """Le portail n'ouvre le paiement qu'apres approbation du dossier."""
    depot = _dossier(db, ctx)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.enregistrer_paiement(db, depot, montant="350")
    assert "après approbation" in str(erreur.value)
    _pieces_obligatoires(db, ctx, depot)
    greffe.changer_etat(db, depot, "en_cours", user_id=ctx["user"].id)
    greffe.changer_etat(db, depot, "approuve", motif="Approbation du greffe")
    db.commit()
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.enregistrer_paiement(db, depot, montant="350", moyen="mobile")
    assert "Moyen de paiement" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.enregistrer_paiement(db, depot, montant="0")
    assert "supérieur à zéro" in str(erreur.value)


def test_depot_final_exige_le_paiement_integral(db, ctx):
    """Aucun depot definitif tant que les taxes ne sont pas reglees."""
    depot = _dossier_approuve(db, ctx, montant="350")
    greffe.enregistrer_paiement(db, depot, montant="100")
    db.commit()
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "depose", motif="Dépôt")
    assert "paiement intégral" in str(erreur.value)
    assert greffe.solde_taxes(db, depot) == Decimal("250.00")


def test_depot_verrouille_l_exercice_p16(db, ctx):
    """Un dossier « Depose » fige l'exercice (verrou P1.6)."""
    depot = _dossier_approuve(db, ctx)
    greffe.enregistrer_paiement(db, depot, montant="350")
    greffe.changer_etat(
        db, depot, "depose", motif="Dépôt sur le portail", user_id=ctx["user"].id
    )
    db.commit()
    verrou = db.query(PeriodLock).filter_by(company_id=ctx["company"].id).one()
    assert verrou.periode is None  # exercice entier
    assert str(depot.exercice) in (verrou.motif or "")
    # Un verrou deja pose n'est pas une erreur (nouvelle tentative idempotente).
    resultat = greffe.verrouiller_apres_depot(db, depot, user_id=ctx["user"].id)
    assert resultat["verrouille"] is False
    assert "Verrou deja pose" in resultat["motif"]


# ---------------------------------------------------------------------------
# Assembleur ZIP, certificat de depot, amende hors delai
# ---------------------------------------------------------------------------
def test_assembler_dossier_zip_manifeste_et_integrite(db, ctx):
    """Le ZIP contient les pieces, le bordereau et un manifeste d'empreintes."""
    depot = _dossier_approuve(db, ctx)
    greffe.enregistrer_paiement(db, depot, montant="350")
    greffe.generer_pieces(db, depot, company=ctx["company"], user_id=ctx["user"].id)
    db.commit()
    archive = greffe.assembler_dossier(db, ctx["company"], depot)
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_dossier:
        noms = zip_dossier.namelist()
        manifeste = zip_dossier.read("manifeste.json").decode("utf-8")
        bordereau = zip_dossier.read("00_bordereau_recapitulatif.pdf")
    assert "00_bordereau_recapitulatif.pdf" in noms
    assert "manifeste.json" in noms
    assert any("pv_ag" in nom for nom in noms)
    assert any("etats_synthese" in nom for nom in noms)
    assert any("attestation" in nom.lower() for nom in noms)
    assert bordereau.startswith(b"%PDF")
    assert len(bordereau) <= TAILLE_10_MO
    assert "https://depotbilan.justice.gov.ma" in manifeste
    assert "hash_sha256" in manifeste

    # Une piece alteree sur le disque fait echouer l'assemblage (integrite).
    document = next(
        doc
        for doc in db.scalars(
            select(GreffeDocument).where(GreffeDocument.deposit_id == depot.id)
        )
        if doc.piece_code == greffe.PIECE_PV_AG
    )
    # Une piece **remplacee sur le disque** par un autre PV valide fait echouer
    # l'assemblage : l'empreinte SHA-256 archivee ne correspond plus.
    from app.services.pdf_documents import pdf_pv_ag

    (settings.greffe_racine / document.chemin).write_bytes(
        pdf_pv_ag(db, ctx["company"], ctx["year"], date_ag=date(ctx["year"], 6, 9))
    )
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.assembler_dossier(db, ctx["company"], depot)
    assert "empreinte SHA-256 différente" in str(erreur.value)
    # Une piece vide ou corrompue est refusee **encore plus tot** (P1 greffe) :
    # le controle de contenu est bloquant avant l'assemblage.
    (settings.greffe_racine / document.chemin).write_bytes(b"%PDF-1.4 pirate")
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.assembler_dossier(db, ctx["company"], depot)
    assert "illisible" in str(erreur.value)


def test_archive_refusee_si_controle_bloquant(db, ctx):
    """Aucune archive sans « tout vert » (checklist incomplete)."""
    depot = _dossier(db, ctx)  # pieces non fournies
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.assembler_dossier(db, ctx["company"], depot)
    assert "contrôles bloquants" in str(erreur.value)


def test_certificat_de_depot_archive_sha256(db, ctx):
    """Le certificat est archive avec son empreinte et l'alerte disparait."""
    depot = _dossier_approuve(db, ctx)
    greffe.enregistrer_paiement(db, depot, montant="350")
    greffe.changer_etat(db, depot, "depose", motif="Dépôt final", user_id=ctx["user"].id)
    db.commit()
    assert "greffe.certificat_manquant" in _codes(greffe.alertes_depot(db, depot))
    greffe.enregistrer_certificat(
        db,
        depot,
        nom_fichier="certificat_depot_2026.pdf",
        contenu=PDF,
        reference="CERT-2026-0001",
        user_id=ctx["user"].id,
    )
    db.commit()
    assert depot.certificat_hash == greffe.empreinte_sha256(PDF)
    assert depot.certificat_nom == "certificat_depot_2026.pdf"
    assert depot.certificat_depose_le is not None
    assert greffe.lire_certificat(depot) == PDF
    assert "greffe.certificat_manquant" not in _codes(greffe.alertes_depot(db, depot))
    with pytest.raises(greffe.GreffeError):
        greffe.verifier_piece_pdf("certificat.pdf", b"certificat non pdf")


def test_pieces_figees_apres_depot(db, ctx):
    """Un dossier « Depose » ne se modifie plus (unicite du depot)."""
    depot = _dossier_approuve(db, ctx)
    greffe.enregistrer_paiement(db, depot, montant="350")
    greffe.changer_etat(db, depot, "depose", motif="Dépôt final")
    db.commit()
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.ajouter_piece(
            db, depot, piece_code=greffe.PIECE_PV_AG, nom_fichier="pv.pdf", contenu=PDF
        )
    assert "« Déposé »" in str(erreur.value)
    with pytest.raises(greffe.GreffeError):
        greffe.supprimer_piece(db, depot, greffe.PIECE_PV_AG)
    # Sur un dossier ouvert, retirer une piece absente n'est pas une erreur.
    autre = _dossier(db, ctx, exercice=2025)
    db.commit()
    assert greffe.supprimer_piece(db, autre, greffe.PIECE_RAPPORT_CAC) is False


def test_amende_hors_delai_et_provision_6195_1515(db, ctx):
    """L'amende hors delai se provisionne en 6195 / 1515, une seule fois."""
    from app.models import Entry

    depot = _dossier(db, ctx, exercice=2025, date_ag=None)
    greffe.changer_etat(
        db, depot, "amender", motif="Dépôt hors délai", user_id=ctx["user"].id
    )
    db.commit()
    assert depot.statut == "amender"
    assert depot.amende_motif == "Dépôt hors délai"
    alertes = {alerte["code"] for alerte in greffe.alertes_depot(db, depot)}
    assert "greffe.dossier_amender" in alertes
    assert "greffe.ag_hors_delai" in alertes
    assert "greffe.amende_a_preciser" in _codes(greffe.controles_depot(db, depot))

    resultat = greffe.comptabiliser_amende(
        db, ctx["company"], depot, montant="1500", user_id=ctx["user"].id
    )
    db.commit()
    assert resultat["comptes"] == {"dotation": "6195", "provision": "1515"}
    assert resultat["montant"] == Decimal("1500.00")
    assert depot.amende_montant == Decimal("1500.00")
    ecriture = db.get(Entry, resultat["entry_id"])
    assert ecriture.status == "validated"
    assert ecriture.source == "greffe"
    assert ecriture.source_id == depot.id
    assert sum(ligne.debit for ligne in ecriture.lines) == Decimal("1500.00")
    assert sum(ligne.credit for ligne in ecriture.lines) == Decimal("1500.00")
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.comptabiliser_amende(db, ctx["company"], depot, montant="1500")
    assert "déjà provisionnée" in str(erreur.value)


def test_amende_refusee_sur_dossier_non_amender(db, ctx):
    """La provision d'amende n'a de sens que pour un dossier « Amender »."""
    depot = _dossier(db, ctx)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.comptabiliser_amende(db, ctx["company"], depot, montant="1000")
    assert "Amender" in str(erreur.value)
    depot2 = _dossier(db, ctx, exercice=2025)
    greffe.changer_etat(db, depot2, "amender", motif="Hors délai")
    db.commit()
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.comptabiliser_amende(db, ctx["company"], depot2)
    assert "Montant de l'amende inconnu" in str(erreur.value)


def test_etat_depots_et_alertes_globales(db, ctx):
    """Le tableau de bord agrege les dossiers, les etats et les alertes."""
    _dossier_approuve(db, ctx)
    depot_2025 = _dossier(db, ctx, exercice=2025, date_ag=None)
    greffe.changer_etat(db, depot_2025, "amender", motif="Hors délai")
    db.commit()
    etat = greffe.etat_depots(db, ctx["company"].id)
    assert etat["nb_dossiers"] == 2
    assert etat["compteurs"]["approuve"] == 1
    assert etat["compteurs"]["amender"] == 1
    exercices = {ligne["exercice"] for ligne in etat["dossiers"]}
    assert exercices == {ctx["year"], 2025}
    assert etat["nb_alertes_urgentes"] >= 1  # amende hors délai (urgent)
    globales = greffe.alertes_greffe(db, ctx["company"].id)
    assert {alerte["niveau"] for alerte in globales} <= {"urgent", "attention"}
    assert globales[0]["niveau"] == "urgent"  # triees par urgence
    etat_2025 = greffe.etat_depots(db, ctx["company"].id, exercice=2025)
    assert etat_2025["nb_dossiers"] == 1
    assert etat_2025["dossiers"][0]["amende_montant"] is None
    assert etat_2025["dossiers"][0]["certificat_archive"] is False
