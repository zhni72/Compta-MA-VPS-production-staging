"""P1B - Responsive UX : verrouillage des bandes, du tiroir et des conteneurs.

Ne teste **aucune** logique metier : uniquement la source de presentation
(breakpoints 1024 / 768 / 390 px, tiroir de navigation, bandeau sans
debordement, tableaux dans un conteneur defilant) et le rendu des ecrans de
reference. Le classement pixel (scrollWidth reel) reste une recette manuelle
sur les 4 largeurs 1440 / 1024 / 768 / 390.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
CSS = RACINE / "app" / "web" / "static" / "css" / "app.css"
BASE = RACINE / "app" / "web" / "templates" / "base.html"
GABARITS = RACINE / "app" / "web" / "templates"

CONNEXION = {"email": "admin@test.ma", "password": "MotDePasse123"}

ECRANS = [
    ("/", "Tableau de bord"),
    ("/ecritures", "Saisie des ecritures"),
    ("/ecritures/nouvelle", "Formulaire d'ecriture"),
    ("/etats/journal", "Journal"),
    ("/etats/grand-livre", "Grand livre"),
    ("/etats/balance", "Balance"),
    ("/etats/bilan", "Bilan"),
    ("/etats/cpc", "CPC"),
    ("/etats/esg", "ESG"),
    ("/etats/etic", "ETIC"),
    ("/immobilisations", "Immobilisations"),
    ("/stocks", "Stocks"),
    ("/paie", "Paie"),
    ("/tva", "TVA"),
    ("/liasse", "IS & liasse"),
    ("/greffe", "Greffe"),
    ("/e-facturation", "E-facturation"),
    ("/audit", "Audit"),
    ("/parametres/societe", "Parametres"),
]

CONTENEURS_VALIDES = {"table-wrap", "body", "invoice-print"}

MOTIF_TABLEAU = re.compile(r"<div\b([^>]*)>|</div>|<table\b")


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def _base() -> str:
    return BASE.read_text(encoding="utf-8")


def _classes_ouvertes_a_chaque_tableau(texte: str) -> list[set[str]]:
    """Classes des ``<div>`` encore ouverts a chaque ``<table>`` rencontre."""
    piles: list[set[str]] = []
    releve: list[set[str]] = []
    for rencontre in MOTIF_TABLEAU.finditer(texte):
        jeton = rencontre.group(0)
        if jeton == "</div>":
            if piles:
                piles.pop()
        elif jeton.startswith("<div"):
            attributs = rencontre.group(1) or ""
            classe = re.search(r'class="([^"]*)"', attributs)
            piles.append(set(classe.group(1).split()) if classe else set())
        else:
            union: set[str] = set()
            for niveau in piles:
                union |= niveau
            releve.append(union)
    return releve


# --------------------------------------------------------------------------- #
#                                    CSS                                       #
# --------------------------------------------------------------------------- #
def test_bandes_de_largeur_standardisees():
    """1440 (base) + les trois bandes imposees : 1024 / 768 / 390 px."""
    css = _css()
    for bande in ("1024px", "768px", "390px"):
        assert f"@media (max-width: {bande})" in css, f"bande absente : {bande}"
    # Les anciennes bandes (1100 / 760) sont retirees : une seule logique.
    assert "@media (max-width: 1100px)" not in css
    assert "@media (max-width: 760px)" not in css


def test_sidebar_jamais_supprimee_et_tiroir_present():
    """Le menu n'est plus masque par display:none : il devient un tiroir."""
    css = _css()
    assert ".sidebar { display: none; }" not in css
    assert "translateX(-100%)" in css, "tiroir off-canvas absent"
    assert "body.nav-open .sidebar" in css
    assert ".nav-toggle { display: none; }" in css  # masque sur desktop
    assert "position: fixed" in css  # tiroir en tablette / mobile


def test_bandeau_et_hamburger_sans_debordement():
    css, base = _css(), _base()
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in base
    assert 'class="nav-toggle"' in base
    assert 'class="nav-backdrop"' in base
    assert 'id="main-nav"' in base
    assert "nav-open" in base
    # Bandeau enveloppant : aucune ligne ne peut forcer un scroll horizontal.
    assert "flex-wrap: wrap;" in css


def test_groupe_actif_toujours_identifiable():
    css, base = _css(), _base()
    assert ".sidebar button.group-title.has-active" in css
    assert "has-active" in base
    assert ".sidebar a.active" in css


def test_cibles_tactiles_et_formulaires_adaptatifs():
    css = _css()
    assert ".btn { min-height: 40px; }" in css
    assert "min-height: 42px" in css  # liens du tiroir
    assert ".filters .field { flex: 1 1 180px; }" in css
    # Grilles KPI et formulaires : 1 colonne en 390 px.
    bloc_390 = css[css.index("@media (max-width: 390px)") :]
    assert "grid-template-columns: minmax(0, 1fr)" in bloc_390
    assert ".form-grid.cols-4" in css and ".form-grid.cols-2" in css


def test_tableaux_dans_un_conteneur_defilant():
    """Chaque <table> a un ancetre defilant (.table-wrap / corps de carte)."""
    css = _css()
    assert ".table-wrap { overflow-x: auto" in css
    assert re.search(r"\.card > \.body \{\s*overflow-x: auto;", css), "corps de carte non defilant"
    assert re.search(r"\.invoice-print \{[^}]*overflow-x: auto;", css), "facture non defilante"

    anomalie: list[str] = []
    for fichier in sorted(GABARITS.glob("*.html")):
        texte = fichier.read_text(encoding="utf-8")
        if "<table" not in texte:
            continue
        for classes in _classes_ouvertes_a_chaque_tableau(texte):
            if not classes & CONTENEURS_VALIDES:
                anomalie.append(f"{fichier.name} -> {sorted(classes)}")
    assert anomalie == [], "tableau sans conteneur defilant :\n" + "\n".join(anomalie)


def test_impression_sans_troncature():
    """L'impression sort des conteneurs de defilement : rien n'est coupe."""
    css = _css()
    assert (
        ".table-wrap, .card > .body, .invoice-print { overflow: visible !important; }"
        in css
    )


# --------------------------------------------------------------------------- #
#                          RENDU DES ECRANS DE REFERENCE                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("chemin,label", ECRANS, ids=[e[1] for e in ECRANS])
def test_ecran_responsif(client, db, ctx, chemin, label):
    """L'ecran est servi et porte la coquille responsive (viewport + menu)."""
    client.post("/connexion", data=CONNEXION, follow_redirects=False)
    reponse = client.get(chemin, follow_redirects=False)
    assert reponse.status_code in (200, 303), f"{label} ({chemin}) -> {reponse.status_code}"
    if reponse.status_code != 200:
        return
    html = reponse.text
    assert "width=device-width" in html, f"{label} : viewport absent"
    assert 'class="nav-toggle"' in html, f"{label} : bouton hamburger absent"
    assert "/static/css/app.css" in html, f"{label} : feuille de style absente"
    assert 'id="main-nav"' in html, f"{label} : navigation absente"

