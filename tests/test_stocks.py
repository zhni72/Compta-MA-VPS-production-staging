"""Tests du module Stocks & inventaire permanent (P1.3).

Verifie les criteres de recette du CDC § 3.3 : CMUP recalcule apres chaque entree,
FIFO strict sur trois lots, **Σ (quantite x cout) = valeur du compte de stock** au
centime, ecritures de variation (6114/6124), inventaire physique et ecarts valorises,
depreciations (391x / 61961), seuil d'alerte, permanence des methodes et verrouillage
de periode (P1.6).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Account, FiscalYear, StockMovement
from app.services import stocks
from app.services.accounting import AccountingError, PeriodLockedError
from app.services.period_locks import verrouiller_periode
from app.services.reporting import movements

pytestmark = pytest.mark.usefixtures("ctx")


def _article(db, ctx, **kwargs):
    """Article type : marchandises groupe A (compte 3111)."""
    parametres = {
        "company": ctx["company"],
        "reference": "ART001",
        "label": "Article de test",
        "stock_account": "3111",
        "unit": "U",
        "alert_threshold": Decimal("5"),
        "valuation_method": "cmup",
    }
    parametres.update(kwargs)
    return stocks.creer_article(db, **parametres)


def _entree(db, ctx, article, jour: date, quantite: str, cout: str, **kwargs):
    """Entree de stock valorisee."""
    return stocks.enregistrer_mouvement(
        db,
        article=article,
        movement_date=jour,
        movement_type="entree",
        quantity=quantite,
        unit_cost=cout,
        reason=kwargs.pop("reason", "achat"),
        user_id=ctx["user"].id,
        **kwargs,
    )


def _sortie(db, ctx, article, jour: date, quantite: str, **kwargs):
    """Sortie de stock valorisee."""
    return stocks.enregistrer_mouvement(
        db,
        article=article,
        movement_date=jour,
        movement_type="sortie",
        quantity=quantite,
        reason=kwargs.pop("reason", "vente"),
        user_id=ctx["user"].id,
        **kwargs,
    )


def _solde_compte(db, ctx, compte: str) -> Decimal:
    """Solde d'un compte (cumul depuis l'origine) d'apres les ecritures validees."""
    lignes = movements(
        db, ctx["company"].id, date(1900, 1, 1), date(2030, 12, 31), prefix=compte
    )
    return sum((ligne["solde"] for ligne in lignes), Decimal("0"))


# ---------------------------------------------------------------------------
# Fiches articles et comptes derives
# ---------------------------------------------------------------------------
def test_derivation_des_comptes_de_stock(db, ctx):
    """Comptes de variation et de provision derives d'un compte de stock (CGNC)."""
    assert stocks.compte_variation("3111") == "6114"
    assert stocks.compte_variation("3121") == "6124"
    assert stocks.compte_variation("3151") == "7132"
    assert stocks.compte_provision("3111") == "3911"
    assert stocks.compte_provision("3121") == "3912"
    assert stocks.compte_provision("3151") == "3915"
    for compte in ("3111", "3121", "3131", "3151"):
        assert db.execute(
            select(Account.number).where(
                Account.number == stocks.compte_provision(compte)
            )
        ).scalar_one_or_none(), compte
    assert stocks.COMPTE_DOTATION_DEPRECIATION == "61961"


def test_creation_article_et_controles(db, ctx):
    """Creation d'une fiche article et refus des saisies non conformes."""
    article = _article(db, ctx)
    assert article.reference == "ART001"
    assert article.stock_account == "3111"
    assert article.valuation_method == "cmup"
    assert article.quantity_on_hand == Decimal("0.000")
    assert article.sous_seuil is False  # pas de stock : seuil non atteint sans stock

    with pytest.raises(stocks.StockError, match="reference"):
        _article(db, ctx, reference="ART001")  # doublon
    with pytest.raises(stocks.StockError, match="classe 3"):
        _article(db, ctx, reference="ART002", stock_account="6111")
    with pytest.raises(stocks.StockError, match="LIFO"):
        _article(db, ctx, reference="ART003", valuation_method="lifo")
    with pytest.raises(stocks.StockError, match="designation"):
        _article(db, ctx, reference="ART004", label="")


def test_changement_de_methode_refuse_apres_mouvement(db, ctx):
    """Permanence des methodes : la valorisation ne change plus apres un mouvement."""
    article = _article(db, ctx, valuation_method="fifo")
    stocks.changer_methode_valorisation(db, article, "cmup")
    assert article.valuation_method == "cmup"
    _entree(db, ctx, article, date(2026, 1, 10), "1", "100")
    with pytest.raises(stocks.StockError, match="permanence des methodes"):
        stocks.changer_methode_valorisation(db, article, "fifo")


# ---------------------------------------------------------------------------
# Valorisation CMUP / FIFO
# ---------------------------------------------------------------------------
def test_cmup_recalcule_apres_chaque_entree(db, ctx):
    """CMUP = (valeur stock + valeur entree) / (quantite + quantite) apres chaque entree."""
    article = _article(db, ctx)
    _entree(db, ctx, article, date(2026, 1, 10), "10", "100")
    etat = stocks.etat_article(article)
    assert etat["quantity"] == Decimal("10.000")
    assert etat["value"] == Decimal("1000.00")
    assert etat["cmup"] == Decimal("100.0000")

    _entree(db, ctx, article, date(2026, 2, 10), "10", "200")
    etat = stocks.etat_article(article)
    assert etat["quantity"] == Decimal("20.000")
    assert etat["value"] == Decimal("3000.00")
    assert etat["cmup"] == Decimal("150.0000")  # (1000 + 2000) / (10 + 10)
    assert article.cmup == Decimal("150.00")  # cache recalcule
    assert article.quantity_on_hand == Decimal("20.000")

    sortie = _sortie(db, ctx, article, date(2026, 3, 1), "5")
    assert sortie.unit_cost == Decimal("150.0000")
    assert sortie.value == Decimal("-750.00")
    etat = stocks.etat_article(article)
    assert etat["quantity"] == Decimal("15.000")
    assert etat["value"] == Decimal("2250.00")
    # Critere d'acceptation : quantite x CMUP = valeur, au centime
    assert stocks.money(stocks.quantite(etat["quantity"]) * etat["cmup"]) == etat["value"]


def test_fifo_consomme_les_lots_les_plus_anciens(db, ctx):
    """FIFO : la consommation suit strictement la file des trois lots."""
    article = _article(db, ctx, valuation_method="fifo")
    _entree(db, ctx, article, date(2026, 1, 5), "10", "100")  # lot 1
    _entree(db, ctx, article, date(2026, 2, 5), "10", "200")  # lot 2
    _entree(db, ctx, article, date(2026, 3, 5), "10", "300")  # lot 3
    assert stocks.etat_article(article)["value"] == Decimal("6000.00")

    # Sortie de 15 : 10 a 100 + 5 a 200 = 2 000 DH (file FIFO).
    resultat = stocks.cout_fifo(article, Decimal("15"))
    assert resultat["valeur"] == Decimal("2000.00")
    assert [couche["quantite"] for couche in resultat["couches"]] == [
        Decimal("10.000"),
        Decimal("5.000"),
    ]
    assert resultat["couches"][0]["cout_unitaire"] == Decimal("100.0000")
    assert resultat["couches"][1]["cout_unitaire"] == Decimal("200.0000")

    sortie = _sortie(db, ctx, article, date(2026, 4, 1), "15")
    assert sortie.value == Decimal("-2000.00")
    etat = stocks.etat_article(article)
    assert etat["quantity"] == Decimal("15.000")
    assert etat["value"] == Decimal("4000.00")  # 5 x 200 + 10 x 300
    # Sortie de 5 : consomme le reste du lot 2 (5 x 200 = 1 000 DH).
    reste = stocks.cout_fifo(article, Decimal("5"))
    assert reste["valeur"] == Decimal("1000.00")
    assert reste["couches"][0]["cout_unitaire"] == Decimal("200.0000")


def test_sorties_refusees_stock_negatif_et_valorisation_nulle(db, ctx):
    """Controles bloquants : stock negatif interdit, sortie non valorisee refusee."""
    article = _article(db, ctx)
    _entree(db, ctx, article, date(2026, 1, 10), "10", "100")
    with pytest.raises(stocks.StockError, match="stock negatif interdit"):
        _sortie(db, ctx, article, date(2026, 2, 1), "11")
    # Option explicite : stock negatif autorise (alerte dans les controles).
    _sortie(db, ctx, article, date(2026, 2, 1), "11", allow_negative=True)
    assert stocks.etat_article(article)["quantity"] == Decimal("-1.000")

    # Article sans valorisation : sortie refusee (aucun mouvement a 0 DH).
    vide = _article(db, ctx, reference="ART002", label="Article non valorise")
    comptage = stocks.inventaire_physique(
        db,
        company=ctx["company"],
        count_date=date(2026, 3, 31),
        lignes=[{"reference": "ART002", "physical_quantity": "5"}],
        visumotif="Inventaire initial constate",
        user_id=ctx["user"].id,
    )
    assert comptage.lines[0].gap_value == Decimal("0.00")
    with pytest.raises(stocks.StockError, match="non valorisee"):
        _sortie(db, ctx, vide, date(2026, 4, 1), "1")


def test_ecritures_de_variation_et_valeur_du_compte_de_stock(db, ctx):
    """Entree : 3111 / 6114 ; sortie : 6114 / 3111 ; solde = valeur des fiches."""
    article = _article(db, ctx)
    entree = _entree(db, ctx, article, date(2026, 1, 10), "10", "100")
    operation = stocks.comptabiliser_mouvement(db, entree, user_id=ctx["user"].id)
    lignes = {
        ligne.account_number: (ligne.debit, ligne.credit)
        for ligne in operation["entry"].lines
    }
    assert lignes["3111"] == (Decimal("1000.00"), Decimal("0.00"))
    assert lignes["6114"] == (Decimal("0.00"), Decimal("1000.00"))
    assert operation["entry_number"].startswith("EC")
    with pytest.raises(stocks.StockError, match="deja comptabilise"):
        stocks.comptabiliser_mouvement(db, entree)

    sortie = _sortie(db, ctx, article, date(2026, 2, 1), "4")
    stocks.comptabiliser_mouvement(db, sortie, user_id=ctx["user"].id)

    # Critere d'acceptation : Σ (quantite x cout) = valeur du compte de stock
    etat = stocks.etat_article(article)
    assert etat["value"] == Decimal("600.00")
    assert _solde_compte(db, ctx, "3111") == Decimal("600.00")
    # 6114 : 1 000 credite a l'entree, 400 debite a la sortie -> solde -600 = variation
    # (le cout des marchandises vendues = achats 6111 - variation 6114).
    assert _solde_compte(db, ctx, "6114") == Decimal("-600.00")
    etat_global = stocks.etat_stocks(db, ctx["company"].id, au=date(2026, 12, 31))
    assert etat_global["ecart"] == Decimal("0.00")
    assert etat_global["conforme"] is True


# ---------------------------------------------------------------------------
# Inventaire physique et ecarts
# ---------------------------------------------------------------------------
def test_inventaire_physique_valorise_l_ecart_et_ecritures(db, ctx):
    """Inventaire : ecart valorise au CMUP, ecriture de variation, stock aligne."""
    article = _article(db, ctx)
    entree = _entree(db, ctx, article, date(2026, 1, 10), "20", "150")
    stocks.comptabiliser_mouvement(db, entree, user_id=ctx["user"].id)
    assert _solde_compte(db, ctx, "3111") == Decimal("3000.00")

    comptage = stocks.inventaire_physique(
        db,
        company=ctx["company"],
        count_date=date(2026, 6, 30),
        lignes=[{"reference": "ART001", "physical_quantity": "18"}],
        visumotif="Ecart de 10 % constate en inventaire physique (PV du 30/06)",
        user_id=ctx["user"].id,
    )
    assert comptage.status == "valide"
    ligne = comptage.lines[0]
    assert ligne.theoretical_quantity == Decimal("20.000")
    assert ligne.physical_quantity == Decimal("18.000")
    assert ligne.gap_quantity == Decimal("-2.000")
    assert ligne.unit_cost == Decimal("150.00")
    assert ligne.gap_value == Decimal("-300.00")
    assert comptage.total_ecart_valeur == Decimal("-300.00")

    # Le mouvement d'inventaire est comptabilise : la balance suit l'inventaire physique.
    mouvement = db.get(StockMovement, ligne.movement_id)
    assert mouvement.movement_type == "inventaire"
    assert mouvement.value == Decimal("-300.00")
    assert mouvement.entry_id is not None
    assert _solde_compte(db, ctx, "3111") == Decimal("2700.00")
    etat = stocks.etat_article(article)
    assert etat["quantity"] == Decimal("18.000")
    assert etat["value"] == Decimal("2700.00")
    assert _solde_compte(db, ctx, "3111") == etat["value"]  # critere de recette


def test_visa_obligatoire_au_dela_de_cinq_pourcent(db, ctx):
    """Ecart d'inventaire > 5 % de la valeur du stock : visa motive obligatoire."""
    article = _article(db, ctx)
    _entree(db, ctx, article, date(2026, 1, 10), "20", "150")  # 3 000 DH
    with pytest.raises(stocks.StockError, match="visa motive est obligatoire"):
        stocks.inventaire_physique(
            db,
            company=ctx["company"],
            count_date=date(2026, 6, 30),
            lignes=[{"reference": "ART001", "physical_quantity": "10"}],
            user_id=ctx["user"].id,
        )
    comptage = stocks.inventaire_physique(
        db,
        company=ctx["company"],
        count_date=date(2026, 6, 30),
        lignes=[{"reference": "ART001", "physical_quantity": "10"}],
        visumotif="Destruction de stock constatee (PV du 30/06)",
        user_id=ctx["user"].id,
    )
    assert comptage.total_ecart_valeur == Decimal("-1500.00")


def test_seuil_alerte_et_controles(db, ctx):
    """Seuil d'alerte : article en stock sous le seuil et controle correspondant."""
    article = _article(db, ctx, alert_threshold=Decimal("5"))
    _entree(db, ctx, article, date(2026, 1, 10), "3", "100")
    assert article.sous_seuil is True
    etat = stocks.etat_stocks(db, ctx["company"].id, au=date(2026, 12, 31))
    assert etat["nb_sous_seuil"] == 1
    assert etat["lignes"][0]["sous_seuil"] is True
    codes = {controle["code"] for controle in stocks.controles_stocks(db, ctx["company"].id)}
    assert "SOUS_SEUIL" in codes
    assert "MOVEMENT_NON_COMPTABILISE" in codes  # mouvement non comptabilise ici

    _entree(db, ctx, article, date(2026, 2, 10), "10", "100")
    assert article.sous_seuil is False


def test_mouvement_refuse_sur_periode_verrouillee(db, ctx):
    """P1.6 : aucun mouvement retroactif dans une periode verrouillee (trace)."""
    from app.models import AuditLog

    article = _article(db, ctx)
    verrouiller_periode(
        db, company_id=ctx["company"].id, year=2026, periode=6, motif="Inventaire mensuel"
    )
    with pytest.raises(PeriodLockedError, match="verrouillee"):
        _entree(db, ctx, article, date(2026, 6, 15), "5", "100")
    trace = db.execute(
        select(AuditLog).where(AuditLog.action == "PERIOD_LOCK_REJECTED")
    ).scalars().all()
    assert len(trace) == 1
    assert "mouvement de stock" in trace[0].payload_json
    _entree(db, ctx, article, date(2026, 7, 15), "5", "100")  # juillet : autorise


# ---------------------------------------------------------------------------
# Depreciations
# ---------------------------------------------------------------------------
def test_depreciation_puis_reprise_de_stock(db, ctx):
    """Depreciation (3911 / 61961) et reprise de l'exercice suivant."""
    article = _article(db, ctx)
    _entree(db, ctx, article, date(2026, 1, 10), "20", "150")  # 3 000 DH
    resultat = stocks.provisionner_stock(
        db,
        article,
        2026,
        inventory_value="2500",
        motif="Valeur d'inventaire constatee au 31/12 (obsolescence partielle)",
        user_id=ctx["user"].id,
    )
    assert resultat["dotation"] == Decimal("500.00")
    assert resultat["compte_provision"] == "3911"
    assert resultat["compte_dotation"] == "61961"
    lignes = {
        ligne.account_number: (ligne.debit, ligne.credit)
        for ligne in resultat["entry"].lines
    }
    assert lignes["61961"] == (Decimal("500.00"), Decimal("0.00"))
    assert lignes["3911"] == (Decimal("0.00"), Decimal("500.00"))
    with pytest.raises(stocks.StockError, match="existe deja"):
        stocks.provisionner_stock(
            db, article, 2026, inventory_value="2500", motif="Doublon"
        )

    etat = stocks.etat_provisions(db, ctx["company"].id, 2026)
    assert etat["total_provision"] == Decimal("500.00")
    assert etat["total_dotation"] == Decimal("500.00")

    # Exercice suivant : la valeur d'inventaire remonte -> reprise de 300 DH.
    db.add(
        FiscalYear(
            company_id=ctx["company"].id,
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            status="open",
        )
    )
    db.flush()
    reprise = stocks.provisionner_stock(
        db,
        article,
        2027,
        inventory_value="2800",
        motif="Valeur d'inventaire remontee au 31/12/2027",
        user_id=ctx["user"].id,
    )
    assert reprise["dotation"] == Decimal("-300.00")  # reprise
    lignes = {
        ligne.account_number: (ligne.debit, ligne.credit)
        for ligne in reprise["entry"].lines
    }
    assert lignes["3911"] == (Decimal("300.00"), Decimal("0.00"))
    assert lignes["61961"] == (Decimal("0.00"), Decimal("300.00"))
    assert _solde_compte(db, ctx, "3911") == Decimal("-200.00")
    etat = stocks.etat_provisions(db, ctx["company"].id, 2027)
    assert etat["total_reprise"] == Decimal("300.00")
    with pytest.raises(stocks.StockError, match="motif"):
        stocks.provisionner_stock(db, article, 2027, inventory_value="2700", motif="")



# ---------------------------------------------------------------------------
# Etats du module et regime intermittent
# ---------------------------------------------------------------------------
def test_etats_stocks_variation_et_inventaire(db, ctx):
    """Etat des stocks (reconcilie), variation de stocks et feuille d'inventaire."""
    article = _article(db, ctx)
    entree = _entree(db, ctx, article, date(2026, 1, 10), "20", "150")
    stocks.comptabiliser_mouvement(db, entree, user_id=ctx["user"].id)
    sortie = _sortie(db, ctx, article, date(2026, 3, 10), "5")
    stocks.comptabiliser_mouvement(db, sortie, user_id=ctx["user"].id)

    etat = stocks.etat_stocks(db, ctx["company"].id, au=date(2026, 12, 31))
    assert etat["nb_articles"] == 1
    ligne = etat["lignes"][0]
    assert ligne["quantity"] == Decimal("15.000")
    assert ligne["cmup"] == Decimal("150.00")
    assert ligne["value"] == Decimal("2250.00")
    assert ligne["valuation_method"] == "cmup"
    assert etat["total_valeur"] == etat["total_comptable"] == Decimal("2250.00")
    assert etat["conforme"] is True and etat["ecart"] == Decimal("0.00")
    assert stocks.controles_stocks(db, ctx["company"].id, 2026) == []

    variation = stocks.variation_stocks(db, ctx["company"].id, 2026)
    assert variation["total_initial"] == Decimal("0.00")
    assert variation["total_entrees"] == Decimal("3000.00")
    assert variation["total_sorties"] == Decimal("750.00")
    assert variation["total_final"] == Decimal("2250.00")
    assert variation["total_variation"] == Decimal("2250.00")
    ligne_variation = variation["lignes"][0]
    assert ligne_variation["entrees_quantity"] == Decimal("20.000")
    assert ligne_variation["sorties_quantity"] == Decimal("5.000")
    assert ligne_variation["final_quantity"] == Decimal("15.000")

    feuille = stocks.inventaire_valorise(db, ctx["company"].id, au=date(2026, 12, 31))
    assert feuille["lignes"][0]["theoretical_quantity"] == Decimal("15.000")
    assert feuille["total_valeur_theorique"] == Decimal("2250.00")


def test_constater_stock_final_regime_intermittent(db, ctx):
    """Regime intermittent : le stock final est constate a la cloture (3111 / 6114)."""
    article = _article(db, ctx)
    # Mouvements non comptabilises (regime intermittent : les achats vont en charges).
    _entree(db, ctx, article, date(2026, 1, 10), "20", "150")
    _sortie(db, ctx, article, date(2026, 3, 10), "5")
    assert _solde_compte(db, ctx, "3111") == Decimal("0.00")

    resultat = stocks.constater_stock_final(db, ctx["company"], 2026, user_id=ctx["user"].id)
    assert resultat["genere"] is True
    details = {detail["compte"]: detail for detail in resultat["details"]}
    assert details["3111"]["valeur_module"] == Decimal("2250.00")
    assert details["3111"]["solde_comptable"] == Decimal("0.00")
    assert details["3111"]["ecart"] == Decimal("2250.00")
    lignes = {
        ligne.account_number: (ligne.debit, ligne.credit)
        for ligne in resultat["entry"].lines
    }
    assert lignes["3111"] == (Decimal("2250.00"), Decimal("0.00"))
    assert lignes["6114"] == (Decimal("0.00"), Decimal("2250.00"))
    # Apres constatation : la balance est a l'etat de l'inventaire physique.
    assert _solde_compte(db, ctx, "3111") == Decimal("2250.00")
    etat = stocks.etat_stocks(db, ctx["company"].id, au=date(2026, 12, 31))
    assert etat["conforme"] is True
    # Deuxieme constatation : aucun ecart residuel.
    assert stocks.constater_stock_final(db, ctx["company"], 2026)["genere"] is False


def test_controles_detectent_cache_divergent_et_ecart_comptable(db, ctx):
    """Les controles signalent un cache de fiche divergent et un ecart comptable."""
    article = _article(db, ctx)
    entree = _entree(db, ctx, article, date(2026, 1, 10), "10", "100")
    stocks.comptabiliser_mouvement(db, entree, user_id=ctx["user"].id)

    # Alteration directe du cache (acces hors application) -> controle.
    article.quantity_on_hand = Decimal("99.000")
    db.flush()
    controles = stocks.controles_stocks(db, ctx["company"].id, 2026)
    codes = {controle["code"] for controle in controles}
    assert "CACHE_DIVERGENT" in codes
    assert "STOCK_NEGATIF" not in codes
    article.quantity_on_hand = Decimal("10.000")
    db.flush()

    # Ecart entre les fiches et la comptabilite (mouvement non comptabilise).
    _sortie(db, ctx, article, date(2026, 5, 10), "2")
    controles = stocks.controles_stocks(db, ctx["company"].id, 2026)
    codes = {controle["code"] for controle in controles}
    assert "ECART_INVENTAIRE_COMPTABILITE" in codes
    assert "MOVEMENT_NON_COMPTABILISE" in codes

