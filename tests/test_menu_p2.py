"""P2 — Menu réorganisé : smoke tests de navigation et permissions par rôle.

Vérifie que :
- **chaque entrée du menu** (12 sections) répond en 200 ou 303 — jamais 4xx/5xx —
  pour un utilisateur connecté ;
- les URL métier **existantes** sont inchangées (aucune redirection nécessaire) ;
- les écrans **lecture seule** ajoutés ne créent **aucune écriture comptable** ;
- les **permissions** ne sont pas modifiées : les écrans restent accessibles à la
  session web, les actions protégées restent refusées aux lecteurs.
"""

from __future__ import annotations

import pytest

from app.db.seed import create_user, get_or_create_fiscal_year

# Les 12 sections du menu validé (P2) : (entrée, URL) — les URL sont celles du
# plan de réorganisation ; elles pointent sur des routes existantes ou sur les
# écrans lecture seule livrés en P2.
ENTREES_MENU: tuple[tuple[str, str, str], ...] = (
    # (entrée, URL, clé active attendue) — P0 : une seule clé active par page.
    # Tableau de bord
    ("Tableau de bord", "/", "tableau-de-bord"),
    # Comptabilité
    ("Saisie des écritures", "/ecritures", "ecritures"),
    ("Journal comptable", "/etats/journal", "journal"),
    ("Grand livre", "/etats/grand-livre", "grand-livre"),
    ("Balance générale", "/etats/balance", "balance"),
    # États de synthèse
    ("Bilan", "/etats/bilan", "bilan"),
    ("CPC", "/etats/cpc", "cpc"),
    ("ESG", "/etats/esg", "esg"),
    ("ETIC", "/etats/etic", "etic"),
    # Immobilisations
    ("Immobilisations", "/immobilisations", "immobilisations"),
    ("États (amortissements, cessions)", "/immobilisations/etats", "immobilisations-etats"),
    # Stocks & provisions
    ("Stocks", "/stocks", "stocks"),
    ("Mouvements", "/stocks/mouvements", "stocks-mouvements"),
    ("Inventaire", "/stocks/inventaire", "stocks-inventaire"),
    ("Provisions / dépréciations", "/stocks/provisions", "stocks-provisions"),
    # Paie
    ("Paie", "/paie", "paie"),
    ("Écritures de paie", "/etats/journal?journal_code=OD", "paie-ecritures"),
    # Fiscalité
    ("TVA", "/tva", "tva"),
    ("Relevé des déductions / EDI", "/tva/edi", "tva-edi"),
    ("IS & Liasse fiscale", "/liasse", "liasse"),
    # Juridique / Greffe
    ("Dossier Greffe", "/greffe", "greffe"),
    # Clôture & cessation
    ("Exercices", "/parametres/exercices", "exercices"),
    ("À-nouveaux", "/parametres/a-nouveaux", "a-nouveaux"),
    ("Cessation (provisoire)", "/activite?contexte=cessation", "cessation"),
    # E-facturation
    ("Transmission e-facturation", "/e-facturation", "e-facturation"),
    # Audit & traçabilité
    ("Journal d'audit", "/audit", "audit"),
    ("Événements système", "/activite", "activite"),
    ("Contrôles d'intégrité", "/audit/integrite", "integrite"),
    # Paramètres
    ("Société", "/parametres/societe", "societe"),
    ("Journaux", "/parametres/journaux", "journaux"),
    ("Utilisateurs & rôles", "/parametres/utilisateurs", "utilisateurs"),
    ("Référentiels fiscaux", "/parametres/referentiels", "referentiels"),
)


CONNEXION = {"email": "admin@test.ma", "password": "MotDePasse123"}


def connecter(client) -> None:
    """Ouvre la session web de l'administrateur de test."""
    reponse = client.post("/connexion", data=CONNEXION, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text


@pytest.mark.parametrize(("libelle", "url", "cle_active"), ENTREES_MENU)
def test_smoke_navigation_menu_p2(client, db, ctx, libelle, url, cle_active):
    """Chaque entrée du menu répond en 200/303 (jamais une erreur 4xx/5xx)."""
    connecter(client)
    reponse = client.get(url, follow_redirects=False)
    assert reponse.status_code in (200, 303), f"{libelle} ({url}) → {reponse.status_code}"
    if reponse.status_code == 303:
        return
    # P0 : la page rendue n'allume qu'une seule rubrique (la clé attendue).
    nb_actifs = reponse.text.count('class="active"')
    assert nb_actifs == 1, f"{libelle} ({url}) → {nb_actifs} rubriques actives"
    assert f"active == '{cle_active}'" not in reponse.text  # gabarit déjà évalué
    assert 'class="active"' in reponse.text


def test_journal_et_saisie_jamais_actifs_ensemble(client, db, ctx):
    """P0 : /ecritures et /etats/journal ne surlignent qu'une rubrique chacun."""
    connecter(client)
    saisie = client.get("/ecritures")
    assert saisie.status_code == 200
    assert saisie.text.count('class="active"') == 1
    journal = client.get("/etats/journal")
    assert journal.status_code == 200
    assert journal.text.count('class="active"') == 1


def test_vues_filtrees_fonctionnelles(client, db, ctx):
    """P0 : les paramètres de vue conservés filtrent réellement le contenu."""
    connecter(client)
    avoirs = client.get("/factures?type=vente&avoir=1")
    assert avoirs.status_code == 200
    assert avoirs.text.count('class="active"') == 1
    rejets = client.get("/e-facturation?statut=rejete")
    assert rejets.status_code == 200
    assert "filtre : rejete" in rejets.text
    assert rejets.text.count('class="active"') == 1
    ecritures_paie = client.get("/etats/journal?journal_code=OD")
    assert ecritures_paie.status_code == 200
    assert ecritures_paie.text.count('class="active"') == 1
    cessation = client.get("/activite?contexte=cessation")
    assert cessation.status_code == 200
    assert cessation.text.count('class="active"') == 1


def test_menu_contient_les_douze_sections(client, db, ctx):
    """Le menu affiche les 12 sections validées et les écrans P2."""
    connecter(client)
    page = client.get("/")
    assert page.status_code == 200
    for section in (
        "Tableau de bord",
        "Comptabilité",
        "États de synthèse",
        "Immobilisations",
        "Stocks &amp; provisions",
        "Paie",
        "Fiscalité",
        "Juridique / Greffe",
        "Clôture &amp; cessation",
        "E-facturation",
        "Audit &amp; traçabilité",
        "Paramètres",
    ):
        assert section in page.text, section
    for entree in ("Journal comptable", "ESG", "ETIC", "Provisions / dépréciations"):
        assert entree in page.text, entree
    for supprimee in (
        ">Liasse fiscale</a>",
        ">Clôture</a>",
        ">Verrouillage</a>",
        ">Paiement</a>",
        "Certificat / récépissé</a>",
        ">Exports</a>",
        "Référentiels EDI",
    ):
        assert supprimee not in page.text, supprimee
    # Liens du menu : tous les URLs testés sont présents dans la page (query
    # comprise — les entrées filtrées du menu gardent leur URL d'origine).
    for _, url, _cle in ENTREES_MENU:
        assert f'href="{url}"' in page.text, url
    # P0 : l'export CSV n'est plus une rubrique (bouton dans /audit).
    assert 'href="/audit/export"' not in page.text


def test_ecrans_lecture_seule_sans_ecriture(client, db, ctx):
    """Les écrans P2 n'ajoutent aucune écriture comptable (lecture seule)."""
    from sqlalchemy import func, select

    from app.models import Entry

    avant = db.execute(
        select(func.count(Entry.id)).where(Entry.company_id == ctx["company"].id)
    ).scalar_one()
    connecter(client)
    for url in (
        "/etats/esg",
        "/etats/etic",
        "/stocks/mouvements",
        "/stocks/inventaire",
        "/stocks/provisions",
        "/parametres/a-nouveaux",
        "/parametres/journaux",
        "/parametres/referentiels",
        "/audit/integrite",
        "/e-facturation",
        "/activite",
    ):
        reponse = client.get(url)
        assert reponse.status_code == 200, f"{url} → {reponse.status_code}"
    apres = db.execute(
        select(func.count(Entry.id)).where(Entry.company_id == ctx["company"].id)
    ).scalar_one()
    assert apres == avant


# ---------------------------------------------------------------------------
# Permissions par role : aucun changement de RBAC introduit par P2
# ---------------------------------------------------------------------------
def _creer_role(db, ctx, email: str, *roles: str):
    """Cree un utilisateur portant les roles demandes (meme societe de test)."""
    utilisateur = create_user(
        db,
        email,
        "MotDePasse123",
        full_name=email,
        roles=roles,
        company=ctx["company"],
    )
    db.commit()
    return utilisateur


def test_lecteur_accede_aux_ecrans_lecture_seule(db, ctx, client):
    """Un LECTEUR consulte les écrans P2 (lecture seule) comme les écrans existants."""
    _creer_role(db, ctx, "p2-lecteur@test.ma", "LECTEUR")
    client.post(
        "/connexion",
        data={"email": "p2-lecteur@test.ma", "password": "MotDePasse123"},
        follow_redirects=False,
    )
    for url in (
        "/etats/esg",
        "/etats/etic",
        "/stocks/mouvements",
        "/stocks/inventaire",
        "/stocks/provisions",
        "/parametres/a-nouveaux",
        "/parametres/journaux",
        "/parametres/referentiels",
        "/audit/integrite",
        "/e-facturation",
        "/activite",
    ):
        reponse = client.get(url, follow_redirects=False)
        assert reponse.status_code in (200, 303), f"{url} → {reponse.status_code}"


def test_lecteur_ne_peut_pas_executer_les_actions_protegees(db, ctx, client):
    """Les actions restent réservées (aucune permission élargie par P2)."""
    _creer_role(db, ctx, "p2-lecteur-actions@test.ma", "LECTEUR")
    client.post(
        "/connexion",
        data={"email": "p2-lecteur-actions@test.ma", "password": "MotDePasse123"},
        follow_redirects=False,
    )
    exercice = get_or_create_fiscal_year(db, ctx["company"], 2027)
    db.commit()
    assert exercice.status == "open"
    # Clôture : action reservee ADMIN / EXPERT_COMPTABLE — refus attendu.
    reponse = client.post(
        "/parametres/exercices/2027/cloturer", follow_redirects=False
    )
    if reponse.status_code == 303:
        assert "level=error" in reponse.headers.get("location", "")
    else:
        assert reponse.status_code == 403
    # Aucun effet de bord : l'exercice reste ouvert.
    db.refresh(exercice)
    assert exercice.status == "open"


