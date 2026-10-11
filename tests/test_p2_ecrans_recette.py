"""P2 — non-regression de **recette** : contenu metier des ecrans de menu.

Deux ecrans ont echoue en recette **sur les donnees reelles** alors que les tests
passaient sur base vide (defaut de methode de test : donnees absentes = code
fautif jamais execute) :

- `/etats/etic` → HTTP 500 ``TypeError: 'decimal.Decimal' object is not iterable``.
  Le total d'une note ETIC est un **Decimal** ; le gabarit `ecran_lecture.html`
  itere `tableau.total` comme une **ligne de cellules**. Le defaut n'apparaissait
  que si le total etait **non nul** (capitaux propres de la note 10).
- `/activite` → HTTP 500 ``AttributeError: 'AuditLog' object has no attribute
  'get'``. `audit_trail.journal_audit` retourne des lignes **ORM** ; l'ecran les
  lisait comme des dictionnaires. Le defaut n'apparaissait que si le journal
  contenait **au moins un evenement** trace.

Les tests ci-dessous verifient le **contenu metier** attendu (notes ETIC, ligne
Total, montants formates, evenements du journal, utilisateur) et non le seul code
HTTP.
"""

from __future__ import annotations

import html
from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting import (
    create_entry,
    get_fiscal_year,
    get_journal,
    validate_entry,
)

pytestmark = pytest.mark.usefixtures("ctx")

CONNEXION = {"email": "admin@test.ma", "password": "MotDePasse123"}
DATE = date(2026, 6, 30)


def connecter(client) -> None:
    """Ouvre la session web de l'administrateur de test."""
    reponse = client.post("/connexion", data=CONNEXION, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text


def _ecriture(db, ctx, lignes: list[dict], libelle: str):
    """Ecriture validee de l'exercice de test (cree aussi l'evenement d'audit)."""
    entry = create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=get_fiscal_year(db, ctx["company"].id, ctx["year"]),
        journal=get_journal(db, ctx["company"].id, "OD"),
        entry_date=DATE,
        label=libelle,
        lines=lignes,
    )
    return validate_entry(db, entry, user_id=ctx["user"].id)


def _capital(db, ctx, montant: str = "500000"):
    """Capital social appele et verse : capitaux propres (11x) non nuls."""
    return _ecriture(
        db,
        ctx,
        [
            {"account_number": "5141", "label": "Banque", "debit": montant},
            {"account_number": "1111", "label": "Capital social", "credit": montant},
        ],
        "Constitution du capital",
    )


def _charges_personnel(db, ctx):
    """Charges de personnel 617x (racine a 3 caracteres de la note 9)."""
    return _ecriture(
        db,
        ctx,
        [
            {"account_number": "6171", "label": "Salaires", "debit": "12000"},
            {"account_number": "6174", "label": "Charges sociales", "debit": "5700"},
            {
                "account_number": "4432",
                "label": "Personnel - remunerations dues",
                "credit": "17700",
            },
        ],
        "Paie 06/2026",
    )


def _carte(html_brut: str, titre: str) -> str:
    """Fragment HTML de la carte portant ce titre (jusqu'a la carte suivante)."""
    contenu = html.unescape(html_brut)
    debut = contenu.find(titre)
    assert debut != -1, f"carte absente : {titre}"
    suite = contenu.find('<div class="card">', debut)
    return contenu[debut : suite if suite != -1 else len(contenu)]


# ---------------------------------------------------------------------------
# /etats/etic — le total d'une note doit etre rendu comme une ligne de cellules
# ---------------------------------------------------------------------------
def test_etic_total_non_nul_est_rendu_en_ligne_de_cellules(client, db, ctx):
    """Note 10 : le total (Decimal non nul) est rendu « Total | 500 000,00 »."""
    _capital(db, ctx)
    connecter(client)
    page = client.get("/etats/etic")
    assert page.status_code == 200, page.text
    note10 = _carte(page.text, "Note 10")
    assert "Total" in note10
    assert "500 000,00" in note10


def test_etic_note_9_rend_les_charges_de_personnel_formatees(client, db, ctx):
    """Note 9 : comptes 617x listes et montant total formate (17 700,00)."""
    _charges_personnel(db, ctx)
    connecter(client)
    page = client.get("/etats/etic")
    assert page.status_code == 200, page.text
    note9 = _carte(page.text, "Note 9")
    assert "6171" in note9 and "6174" in note9
    assert "17 700,00" in note9
    assert "Total" in note9


def test_etic_liste_les_informations_non_disponibles(client, db, ctx):
    """Les informations non calculables restent explicitement signalees."""
    connecter(client)
    page = client.get("/etats/etic")
    assert page.status_code == 200, page.text
    assert "Notes et points d'attention" in page.text
    assert "Note 1 —" in page.text


# ---------------------------------------------------------------------------
# /activite — les evenements du journal d'audit (lignes ORM) doivent etre rendus
# ---------------------------------------------------------------------------
def test_activite_rend_les_evenements_et_l_utilisateur(client, db, ctx):
    """Le journal d'audit reel est affiche : action, entite, utilisateur."""
    entry = _capital(db, ctx)
    connecter(client)
    page = client.get("/activite")
    assert page.status_code == 200, page.text
    contenu = html.unescape(page.text)
    assert "ENTRY_VALIDATED" in contenu
    assert f"Entry {entry.id}" in contenu
    # Libelle usuel : nom complet de l'utilisateur (a defaut, son courriel).
    assert (ctx["user"].full_name or ctx["user"].email) in contenu
    assert "Derniers evenements traces" in contenu


def test_activite_rend_le_tableau_e_facturation(client, db, ctx):
    """Le tableau e-facturation de l'ecran reste present (aucune donnee inventee)."""
    connecter(client)
    page = client.get("/activite")
    assert page.status_code == 200, page.text
    assert "Documents d'e-facturation" in html.unescape(page.text)


# ---------------------------------------------------------------------------
# Contrat de rendu : tout `tableau.total` doit etre une ligne de cellules
# ---------------------------------------------------------------------------
def test_ligne_total_alignee_sur_les_colonnes():
    """`_ligne_total` produit une ligne iterable alignee (contrat du gabarit)."""
    from app.web.ecrans_lecture import _ligne_total

    assert _ligne_total(["Element", "Montant"], Decimal("500000")) == [
        "Total",
        "500 000,00",
    ]
    assert _ligne_total(["Compte", "Libelle", "Montant"], Decimal("1234.5")) == [
        "",
        "Total",
        "1 234,50",
    ]
    assert _ligne_total(["Compte", "Libelle", "Montant"], None) is None
    total = _ligne_total(["A", "B", "C"], Decimal("0"))
    assert total is not None and all(isinstance(cellule, str) for cellule in total)
