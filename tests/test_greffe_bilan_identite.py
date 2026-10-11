"""Correctifs de generation du dossier Greffe : bilan **net** et identite harmonisee.

Defauts de recette corriges ici :

1. **Total du bilan** : le rapport de gestion et le PV d'AG portaient le *total
   actif brut* de l'ecran (387 520 DH) au lieu du **total du bilan net equilibre**
   issu des etats de synthese (375 520 DH = brut - amortissements). Le brut ne doit
   apparaitre que « pour memoire » et **jamais** comme total approuve.
2. **Identite** : forme juridique, siege social et qualite (SARL AU / associe
   unique) doivent provenir de la **fiche societe** et etre identiques dans le
   rapport de gestion, le PV d'AG et le bordereau du dossier.
3. **Archive** : une **seule version active** par piece ; aucune piece presente mais
   invalide (PDF de 193 octets, document anterieur a la date d'AG) ne peut entrer
   dans l'archive finale.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import get_or_create_fiscal_year
from app.models.greffe import GreffeDocument
from app.services import greffe
from app.services.accounting import (
    create_entry,
    get_fiscal_year,
    get_journal,
    validate_entry,
)
from app.services.etats_synthese import bilan_normal
from app.services.pdf_documents import (
    _donnees_gestion,
    forme_juridique,
    pdf_pv_ag,
    pdf_rapport_gestion,
    siege_social,
)

pytestmark = pytest.mark.usefixtures("ctx")

PDF_193_OCTETS = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)


@pytest.fixture(autouse=True)
def stockage_greffe(tmp_path, monkeypatch):
    """Stockage des pieces dans un dossier temporaire (jamais le depot)."""
    monkeypatch.setattr(settings, "greffe_dir", tmp_path)
    return tmp_path


def _ecriture(db, ctx, lignes: list[dict], libelle: str):
    entry = create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=get_fiscal_year(db, ctx["company"].id, ctx["year"]),
        journal=get_journal(db, ctx["company"].id, "OD"),
        entry_date=date(ctx["year"], 12, 31),
        label=libelle,
        lines=lignes,
    )
    return validate_entry(db, entry, user_id=ctx["user"].id)


def _exercice_avec_amortissements(db, ctx) -> None:
    """Capital, immobilisation amortie et exploitation : brut != net."""
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "5141", "label": "Banque", "debit": "300000"},
            {"account_number": "1111", "label": "Capital social", "credit": "300000"},
        ],
        "Apport en capital",
    )
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "2332", "label": "Materiel et outillage", "debit": "100000"},
            {"account_number": "5141", "label": "Banque", "credit": "100000"},
        ],
        "Acquisition d'immobilisation",
    )
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6193", "label": "Dotation aux amortissements", "debit": "20000"},
            {"account_number": "2833", "label": "Amortissement du materiel", "credit": "20000"},
        ],
        "Dotation aux amortissements",
    )


def _dossier(db, ctx, *, date_ag: date | None = date(2026, 6, 10)):
    exercice = get_or_create_fiscal_year(db, ctx["company"], ctx["year"])
    exercice.status = "closed"
    db.commit()
    return greffe.creer_depot(
        db,
        company=ctx["company"],
        exercice=ctx["year"],
        user_id=ctx["user"].id,
        forme_juridique="SARL",
        date_ag=date_ag,
        montant_taxes=Decimal("350"),
    )


def _texte(contenu: bytes) -> str:
    return greffe.analyser_piece_pdf(contenu).texte_normalise


def _montant(valeur: Decimal) -> str:
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",")


# ---------------------------------------------------------------------------
# 1. Total du bilan : net equilibre, jamais le brut
# ---------------------------------------------------------------------------
def test_donnees_gestion_expose_le_total_net_equilibre(db, ctx):
    """`total_bilan` = actif net equilibre ; le total actif brut reste a part."""
    _exercice_avec_amortissements(db, ctx)
    donnees = _donnees_gestion(db, ctx["company"].id, ctx["year"])
    bilan = bilan_normal(
        db,
        ctx["company"].id,
        date(ctx["year"], 1, 1),
        date(ctx["year"], 12, 31),
    )
    assert donnees["total_actif_brut"] == Decimal("300000.00")
    assert donnees["total_deductions"] == Decimal("20000.00")
    assert donnees["total_bilan"] == Decimal("280000.00") == bilan["actif_net"]
    assert donnees["total_bilan"] == donnees["total_passif_avec_resultat"]
    assert donnees["equilibre"] is True
    assert donnees["total_bilan"] != donnees["total_actif_brut"]


def test_rapport_de_gestion_porte_le_total_net(db, ctx):
    """Le rapport de gestion affiche le total net ; le brut n'est que « pour memoire »."""
    _exercice_avec_amortissements(db, ctx)
    texte = _texte(pdf_rapport_gestion(db, ctx["company"], ctx["year"]))
    assert f"total du bilan net (actif net) {_montant(Decimal('280000.00'))}" in texte
    assert "pour memoire : total actif brut 300 000,00" in texte
    assert "amortissements et provisions deduits de l'actif 20 000,00" in texte
    assert "total du bilan net (actif = passif) 280 000,00 dh" in texte
    # Le brut ne doit jamais etre introduit comme total du bilan.
    assert "total du bilan 300 000,00" not in texte
    assert "total du bilan net (actif net) 300 000,00" not in texte


def test_pv_ag_approuve_le_total_net_et_cite_le_brut_pour_memoire(db, ctx):
    """1re resolution : total du bilan **net** ; le brut seulement pour memoire."""
    _exercice_avec_amortissements(db, ctx)
    texte = _texte(pdf_pv_ag(db, ctx["company"], ctx["year"], date_ag=date(2026, 6, 10)))
    assert f"total du bilan net {_montant(Decimal('280000.00'))} dh" in texte
    assert "total actif brut de 300 000,00 dh ramene au net" in texte
    assert "actif net = passif" in texte
    assert "total du bilan 300 000,00" not in texte



# ---------------------------------------------------------------------------
# 2. Identite harmonisee (fiche societe) dans les documents du dossier
# ---------------------------------------------------------------------------
def test_identite_harmonisee_dans_rapport_pv_et_bordereau(db, ctx):
    """Forme juridique, siege et qualite issus de la fiche societe, partout."""
    company = ctx["company"]
    company.legal_form = "SARL AU"
    company.address = "12 rue des Tests"
    company.city = "Casablanca"
    db.commit()
    _exercice_avec_amortissements(db, ctx)
    depot = _dossier(db, ctx)

    assert forme_juridique(company) == "SARL AU"
    assert siege_social(company) == "12 rue des Tests, Casablanca"

    rapport = _texte(pdf_rapport_gestion(db, company, ctx["year"]))
    pv = _texte(pdf_pv_ag(db, company, ctx["year"], date_ag=date(2026, 6, 10)))
    bordereau = _texte(greffe.pdf_recapitulatif_dossier(db, company, depot))
    for texte in (rapport, pv, bordereau):
        assert "sarl au" in texte
        assert "12 rue des tests, casablanca" in texte
    assert "associe unique de la societe" in pv
    assert "associe unique de la societe" in rapport
    assert "associe unique" in bordereau


def test_siege_social_signale_l_information_manquante(db, ctx):
    """Fiche societe incomplete : la mention « a completer » remplace le vide."""
    company = ctx["company"]
    company.address = None
    company.city = "Casablanca"
    db.commit()
    assert siege_social(company) == (
        "Casablanca (adresse a completer dans la fiche societe)"
    )
    company.city = None
    assert "a completer dans la fiche societe" in siege_social(company)


def test_forme_juridique_deduite_de_la_raison_sociale(db, ctx):
    """SARL AU sans forme declaree : deduite de la raison sociale (pas inventee)."""
    company = ctx["company"]
    company.legal_form = None
    company.name = "SOCIETE RECETTE MAROC SARL AU"
    assert forme_juridique(company) == "SARL AU"
    company.name = "Atlas Test SARL"
    assert forme_juridique(company) == "SARL"



# ---------------------------------------------------------------------------
# 3. Archive : une seule version active, aucune piece invalide
# ---------------------------------------------------------------------------
def _piece_sans_controle(db, ctx, depot, contenu: bytes, *, code: str, nom: str):
    """Insere une piece **sans passer** par les controles (recette J9)."""
    chemin_relatif = f"{depot.company_id}/{depot.id}/{code}_{nom}"
    chemin = settings.greffe_racine / chemin_relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    document = GreffeDocument(
        deposit_id=depot.id,
        piece_code=code,
        libelle=nom,
        nom_fichier=nom,
        chemin=chemin_relatif,
        taille_octets=len(contenu),
        hash_sha256=greffe.empreinte_sha256(contenu),
        source=greffe.SOURCE_TELEVERSE,
        created_by=ctx["user"].id,
    )
    db.add(document)
    db.commit()
    return document


def test_archive_refuse_une_piece_invalide_presente(db, ctx):
    """Un PDF de 193 octets present dans le dossier bloque l'archive finale."""
    _exercice_avec_amortissements(db, ctx)
    depot = _dossier(db, ctx)
    greffe.generer_pieces(db, depot, company=ctx["company"], date_ag=date(2026, 6, 10))
    db.commit()
    # Le dossier de recette J9 conservait un PV de 193 octets : on reproduit ce cas
    # (piece presente mais invalide) en remplacant le PV valide.
    greffe.supprimer_piece(db, depot, greffe.PIECE_PV_AG)
    db.commit()
    _piece_sans_controle(
        db, ctx, depot, PDF_193_OCTETS, code=greffe.PIECE_PV_AG, nom="pv_ag_j9.pdf"
    )
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.assembler_dossier(db, ctx["company"], depot)
    message = str(erreur.value)
    assert "pv_ag_j9.pdf" in message
    assert "invalide" in message or "bloquant" in message


def test_archive_une_seule_version_par_piece(db, ctx):
    """L'archive contient exactement une piece par code (bordereau compris)."""
    _exercice_avec_amortissements(db, ctx)
    depot = _dossier(db, ctx)
    greffe.generer_pieces(db, depot, company=ctx["company"], date_ag=date(2026, 6, 10))
    db.commit()
    archive = greffe.assembler_dossier(db, ctx["company"], depot)
    with zipfile.ZipFile(io.BytesIO(archive)) as contenu:
        noms = contenu.namelist()
    assert noms.count("00_bordereau_recapitulatif.pdf") == 1
    codes = [nom.split("_")[1] for nom in noms if nom[:2].isdigit()]
    assert sorted(codes) == sorted(set(codes))
    assert not [nom for nom in noms if "_j9" in nom]


def test_generation_remplace_le_bordereau_precedent(db, ctx):
    """Regenerer le bordereau ne laisse ni doublon en base ni fichier orphelin."""
    _exercice_avec_amortissements(db, ctx)
    depot = _dossier(db, ctx)
    premier = greffe.generer_pieces(
        db, depot, company=ctx["company"], date_ag=date(2026, 6, 10)
    )
    db.commit()
    ancien_fichier = premier["bordereau"].chemin.split("/")[-1]
    second = greffe.generer_pieces(
        db, depot, company=ctx["company"], date_ag=date(2026, 6, 10)
    )
    db.commit()
    lignes = list(
        db.scalars(
            select(GreffeDocument).where(
                GreffeDocument.deposit_id == depot.id,
                GreffeDocument.piece_code == greffe.PIECE_ETAT_COMPLEMENTAIRE,
            )
        )
    )
    assert len(lignes) == 1
    assert lignes[0].chemin == second["bordereau"].chemin
    dossier = settings.greffe_racine / str(depot.company_id) / str(depot.id)
    fichiers = [chemin.name for chemin in dossier.iterdir() if chemin.is_file()]
    assert fichiers.count(ancien_fichier) == 1
    assert len(fichiers) == len(set(fichiers))

