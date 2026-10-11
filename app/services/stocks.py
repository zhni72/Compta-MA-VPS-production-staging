"""Stocks et inventaire permanent (P1.3).

Gestion des articles en **quantite** et en **valeur** : fiches, mouvements
(entrees / sorties / ecarts d'inventaire), **valorisation CMUP ou FIFO**,
**depreciations** (prudence), inventaire physique et etats reglementaires.

References normatives
---------------------
- **CGNC titre II chapitre II (actif circulant — stocks)** : evaluation au **cout de
  revient** (cout d'acquisition + frais accessoires), methodes admises **CMUP** et
  **FIFO** (le **LIFO est proscrit**), application avec **permanence des methodes**.
- **CGNC titre V chapitre I** : tenue des comptes d'**inventaire permanent** en
  comptabilite generale (les comptes de stock sont mouvementes en permanence).
- **Prudence** : depreciation lorsque la **valeur d'inventaire** devient inferieure
  a la valeur comptable (`391x` / `61961`).
- **P1.6** : aucun mouvement retroactif en periode verrouillee.

Moteur de valorisation
----------------------
La quantite et la valeur d'un article sont **recalculees en rejouant ses
mouvements** (`value` est signee : + a l'entree, - a la sortie). Les colonnes
`quantity_on_hand`, `cmup` et `value_on_hand` de la fiche ne sont qu'un **cache**
de consultation, verifie par `controles_stocks` (`stock.cache_divergent`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.rates_ma import money
from app.models import (
    Account,
    Company,
    FiscalYear,
    StockCount,
    StockCountLine,
    StockItem,
    StockMovement,
    StockProvision,
)
from app.models.stock import (
    COUNT_STATUS_VALIDATED,
    MOVEMENT_COUNT,
    MOVEMENT_ENTRY,
    MOVEMENT_EXIT,
    MOVEMENT_TYPES,
    STOCK_REGIME_PERMANENT,
    STOCK_REGIMES,
    VALUATION_METHODS,
)
from app.services.accounting import (
    AccountingError,
    create_entry,
    ensure_period_open,
    get_fiscal_year,
    get_journal,
    validate_entry,
)
from app.services.closing import soldes_a_la_date
from app.services.period_locks import controler_periode

QTE = Decimal("0.001")  # 3 decimales (P1.3 : quantites)
MONTANT = Decimal("0.01")
SEUIL_ECART_INVENTAIRE = Decimal("5")  # 5 % (CDC § 3.3, controle bloquant n° 4)

# Compte de variation de stocks associe a un compte de stock (CGNC).
# 311x marchandises -> 6114 ; 312x matieres et fournitures -> 6124 ;
# 313x/314x produits en cours -> 7131 ; 315x produits finis -> 7132.
VARIATION_PAR_FAMILLE = {
    "311": "6114",
    "312": "6124",
    "313": "7131",
    "314": "7134",
    "315": "7132",
}
# Provision pour depreciation associee a un compte de stock (391x).
PROVISION_PAR_FAMILLE = {
    "311": "3911",
    "312": "3912",
    "313": "3913",
    "314": "3914",
    "315": "3915",
}
COMPTE_DOTATION_DEPRECIATION = "61961"  # D.E.P. pour depreciation des stocks


class StockError(AccountingError):
    """Erreur metier de gestion des stocks."""


def quantite(valeur: Decimal | str | float) -> Decimal:
    """Arrondit une quantite a 3 decimales."""
    return Decimal(str(valeur or 0)).quantize(QTE)


def _racine4(compte: str) -> str:
    """Racine a 4 chiffres d'un compte."""
    return str(compte).strip()[:4]


def compte_variation(stock_account: str) -> str:
    """Compte de variation de stocks associe a un compte de stock (CGNC)."""
    famille = _racine4(stock_account)[:3]
    return VARIATION_PAR_FAMILLE.get(famille, "6114")


def compte_provision(stock_account: str) -> str:
    """Compte de provision pour depreciation associe a un compte de stock (391x)."""
    famille = _racine4(stock_account)[:3]
    return PROVISION_PAR_FAMILLE.get(famille, "3911")


def _compte_existe(db: Session, compte: str | None) -> bool:
    """Vrai si le compte figure au plan comptable charge."""
    if not compte:
        return False
    return (
        db.execute(select(Account.number).where(Account.number == compte)).scalar_one_or_none()
        is not None
    )


def get_item(db: Session, company_id: int, reference: int | str) -> StockItem:
    """Fiche article par identifiant ou par reference."""
    requete = select(StockItem).where(StockItem.company_id == company_id)
    if isinstance(reference, int) or str(reference).isdigit():
        article = db.execute(requete.where(StockItem.id == int(reference))).scalar_one_or_none()
    else:
        article = db.execute(
            requete.where(StockItem.reference == str(reference))
        ).scalar_one_or_none()
    if article is None:
        raise StockError(f"Article {reference} introuvable")
    return article


def list_items(
    db: Session, company_id: int, *, sous_seuil: bool = False, actifs: bool = True
) -> list[StockItem]:
    """Articles du dossier (filtre optionnel sur le seuil d'alerte)."""
    requete = select(StockItem).where(StockItem.company_id == company_id)
    if actifs:
        requete = requete.where(StockItem.is_active.is_(True))
    articles = list(db.execute(requete.order_by(StockItem.reference)).scalars())
    if sous_seuil:
        articles = [article for article in articles if article.sous_seuil]
    return articles


def creer_article(
    db: Session,
    *,
    company: Company,
    reference: str,
    label: str,
    stock_account: str,
    unit: str = "U",
    family: str | None = None,
    purchase_account: str | None = None,
    sale_account: str | None = None,
    alert_threshold: Decimal | str | float = 0,
    valuation_method: str = "cmup",
    notes: str | None = None,
    user_id: int | None = None,
) -> StockItem:
    """Cree une fiche article (compte de stock 3xxx, methode de valorisation)."""
    if not reference or not reference.strip():
        raise StockError("La reference de l'article est obligatoire")
    if not label or not label.strip():
        raise StockError("La designation de l'article est obligatoire")
    if valuation_method not in VALUATION_METHODS:
        raise StockError(
            "Methode de valorisation invalide : le CGNC admet CMUP ou FIFO "
            "(le LIFO est proscrit)."
        )
    if str(stock_account)[:1] != "3":
        raise StockError(
            f"Compte {stock_account} invalide : un article est suivi par un compte de "
            "stock de classe 3 (actif circulant)."
        )
    if not _compte_existe(db, str(stock_account)):
        raise StockError(
            f"Compte {stock_account} absent du plan comptable : chargez le plan PCGE "
            "avant de creer un article."
        )
    if db.execute(
        select(StockItem).where(
            StockItem.company_id == company.id, StockItem.reference == reference.strip()
        )
    ).scalar_one_or_none() is not None:
        raise StockError(f"La reference {reference} existe deja pour ce dossier.")
    article = StockItem(
        company_id=company.id,
        reference=reference.strip(),
        label=label.strip(),
        unit=(unit or "U").strip(),
        family=family,
        stock_account=str(stock_account),
        purchase_account=purchase_account,
        sale_account=sale_account,
        alert_threshold=quantite(alert_threshold),
        valuation_method=valuation_method,
        notes=notes,
    )
    db.add(article)
    db.flush()
    compte_variation_article = compte_variation(article.stock_account)
    if not _compte_existe(db, compte_variation_article):
        log_action(
            db,
            action="STOCK_WARNING",
            entity="StockItem",
            entity_id=article.id,
            user_id=user_id,
            company_id=company.id,
            payload={
                "reference": article.reference,
                "avertissement": (
                    f"Compte de variation {compte_variation_article} absent du plan : "
                    "mouvement a valider avec l'expert-comptable."
                ),
            },
        )
    log_action(
        db,
        action="STOCK_ITEM_CREATED",
        entity="StockItem",
        entity_id=article.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "reference": article.reference,
            "compte_stock": article.stock_account,
            "methode": article.valuation_method,
        },
    )
    db.flush()
    return article


def changer_methode_valorisation(
    db: Session, article: StockItem, methode: str, *, user_id: int | None = None
) -> StockItem:
    """Change la methode de valorisation (permanence des methodes, CGNC).

    Le changement est **refuse** si l'article a deja des mouvements : il ne peut
    intervenir qu'avant le premier mouvement (un changement en cours d'exercice
    fausserait la valeur du stock et l'information annexe).
    """
    if methode not in VALUATION_METHODS:
        raise StockError("Methode invalide : CMUP ou FIFO (LIFO proscrit).")
    if article.movements:
        raise StockError(
            f"Article {article.reference} : methode inchangeable "
            f"({article.valuation_method}) car des mouvements existent "
            "(permanence des methodes, CGNC)."
        )
    ancienne = article.valuation_method
    article.valuation_method = methode
    log_action(
        db,
        action="STOCK_METHOD_CHANGED",
        entity="StockItem",
        entity_id=article.id,
        user_id=user_id,
        company_id=article.company_id,
        payload={"reference": article.reference, "avant": ancienne, "apres": methode},
    )
    db.flush()
    return article



# ---------------------------------------------------------------------------
# Moteur de valorisation (rejeu des mouvements)
# ---------------------------------------------------------------------------
def _mouvements(article: StockItem, *, jusqua: date | None = None) -> list[StockMovement]:
    """Mouvements de l'article dans l'ordre chronologique (id pour egalite de date)."""
    return sorted(
        (
            mouvement
            for mouvement in article.movements
            if jusqua is None or mouvement.movement_date <= jusqua
        ),
        key=lambda mouvement: (mouvement.movement_date, mouvement.id or 0),
    )


def etat_article(article: StockItem, *, jusqua: date | None = None) -> dict:
    """Quantite, valeur et cout moyen unitaire d'un article (rejeu des mouvements).

    `value` etant signee (+ entree, - sortie), le rejeu donne directement la valeur
    du stock : **Σ (quantite x cout unitaire) = valeur**, par construction.
    """
    mouvements = _mouvements(article, jusqua=jusqua)
    quantite_stock = Decimal("0")
    valeur_stock = Decimal("0")
    for mouvement in mouvements:
        quantite_stock = quantite(quantite_stock + mouvement.quantity)
        valeur_stock = money(valeur_stock + mouvement.value)
    cmup = (
        (valeur_stock / quantite_stock).quantize(Decimal("0.0001"))
        if quantite_stock > 0
        else Decimal("0")
    )
    return {
        "article": article,
        "quantity": quantite_stock,
        "value": valeur_stock,
        "cmup": cmup,
        "nb_mouvements": len(mouvements),
        "dernier_mouvement": mouvements[-1].movement_date if mouvements else None,
    }


def couches_fifo(article: StockItem, *, jusqua: date | None = None) -> list[dict]:
    """Couches FIFO **encore disponibles** apres rejeu complet des mouvements.

    Le rejeu est indispensable : une sortie anterieure a consomme les couches les
    plus anciennes, et c'est la file **restante** qui valorise la sortie suivante.
    """
    couches: list[dict] = []
    for mouvement in _mouvements(article, jusqua=jusqua):
        if mouvement.quantity > 0:
            couches.append(
                {
                    "movement_id": mouvement.id,
                    "date": mouvement.movement_date,
                    "reste": quantite(mouvement.quantity),
                    "valeur_initiale": money(mouvement.value),
                    "cout_unitaire": (
                        (mouvement.value / mouvement.quantity).quantize(Decimal("0.0001"))
                        if mouvement.quantity
                        else Decimal("0")
                    ),
                }
            )
        else:
            a_consommer = abs(mouvement.quantity)
            for couche in couches:
                if a_consommer <= 0:
                    break
                pris = min(couche["reste"], a_consommer)
                couche["reste"] = quantite(couche["reste"] - pris)
                a_consommer = quantite(a_consommer - pris)
    return [couche for couche in couches if couche["reste"] > 0]


def cout_fifo(
    article: StockItem, quantite_sortie: Decimal, *, jusqua: date | None = None
) -> dict:
    """Valorisation FIFO d'une sortie : consommation des couches les plus anciennes."""
    reste = quantite(quantite_sortie)
    if reste <= 0:
        raise StockError("La quantite a valoriser doit etre superieure a zero")
    valeur = Decimal("0")
    consommees: list[dict] = []
    for couche in couches_fifo(article, jusqua=jusqua):
        if reste <= 0:
            break
        pris = min(couche["reste"], reste)
        cout_unitaire = couche["cout_unitaire"]
        valeur_couche = money(pris * cout_unitaire)
        valeur = money(valeur + valeur_couche)
        consommees.append(
            {
                "movement_id": couche["movement_id"],
                "date": couche["date"],
                "quantite": quantite(pris),
                "cout_unitaire": cout_unitaire,
                "valeur": valeur_couche,
            }
        )
        reste = quantite(reste - pris)
    return {
        "valeur": valeur,
        "quantite_valorisee": quantite(quantite_sortie - max(reste, Decimal("0"))),
        "couches": consommees,
        "manquant": reste if reste > 0 else Decimal("0"),
    }


def cout_unitaire_sortie(
    article: StockItem, quantite_sortie: Decimal, *, jusqua: date | None = None
) -> Decimal:
    """Cout unitaire d'une sortie selon la methode de l'article (CMUP ou FIFO)."""
    if article.valuation_method == "fifo":
        resultat = cout_fifo(article, quantite_sortie, jusqua=jusqua)
        if resultat["quantite_valorisee"] <= 0:
            return Decimal("0")
        return (resultat["valeur"] / resultat["quantite_valorisee"]).quantize(
            Decimal("0.0001")
        )
    return etat_article(article, jusqua=jusqua)["cmup"]



# ---------------------------------------------------------------------------
# Mouvements de stock (entrees, sorties)
# ---------------------------------------------------------------------------
def _maj_cache(article: StockItem) -> dict:
    """Recalcule le cache de la fiche (quantite, CMUP, valeur) depuis les mouvements."""
    etat = etat_article(article)
    article.quantity_on_hand = etat["quantity"]
    article.cmup = money(etat["cmup"])
    article.value_on_hand = etat["value"]
    return etat


def enregistrer_mouvement(
    db: Session,
    *,
    article: StockItem,
    movement_date: date,
    movement_type: str,
    quantity: Decimal | str | float,
    reason: str,
    unit_cost: Decimal | str | float | None = None,
    label: str | None = None,
    reference: str | None = None,
    invoice_id: int | None = None,
    allow_negative: bool = False,
    user_id: int | None = None,
) -> StockMovement:
    """Enregistre un mouvement de stock valorise (entree ou sortie).

    - **entree** : `unit_cost` obligatoire (cout de revient, frais accessoires
      inclus) — le CMUP de l'article est recalcule apres l'entree ;
    - **sortie** : valorisee au **CMUP** ou en **FIFO** selon la fiche ; une sortie
      de valeur nulle est refusee (controle bloquant n° 2 du CDC) ;
    - **quantite negative** refusee sauf option explicite « stock negatif autorise » ;
    - **periode verrouillee** (P1.6) : mouvement retroactif refuse et trace.
    """
    if movement_type not in (MOVEMENT_ENTRY, MOVEMENT_EXIT):
        raise StockError(
            "Type de mouvement invalide : utiliser entree/sortie (les ecarts "
            "d'inventaire passent par l'inventaire physique)."
        )
    controler_periode(
        db,
        article.company_id,
        movement_date,
        user_id=user_id,
        operation=f"mouvement de stock ({reason})",
    )
    quantite_saisie = quantite(quantity)
    if quantite_saisie <= 0:
        raise StockError("La quantite du mouvement doit etre superieure a zero")
    etat = etat_article(article, jusqua=movement_date)
    if movement_type == MOVEMENT_ENTRY:
        if unit_cost is None:
            raise StockError(
                "Une entree de stock doit etre valorisee (cout unitaire obligatoire : "
                "cout d'acquisition + frais accessoires — CGNC)."
            )
        cout = money(unit_cost)
        if cout <= 0:
            raise StockError("Le cout unitaire d'une entree doit etre superieur a zero")
        valeur = money(quantite_saisie * cout)
        signe_quantite = quantite_saisie
    else:
        if quantite_saisie > etat["quantity"] and not allow_negative:
            raise StockError(
                f"Sortie de {quantite_saisie} {article.unit} impossible : stock "
                f"disponible {etat['quantity']} {article.unit} (stock negatif interdit)."
            )
        cout = cout_unitaire_sortie(article, quantite_saisie, jusqua=movement_date)
        valeur = money(quantite_saisie * cout)
        if valeur <= 0:
            raise StockError(
                f"Sortie non valorisee (0 DH) : verifiez les entrees de l'article "
                f"{article.reference} (aucun mouvement a zero sans justification)."
            )
        signe_quantite = -quantite_saisie
    mouvement = StockMovement(
        company_id=article.company_id,
        item_id=article.id,
        movement_date=movement_date,
        movement_type=movement_type,
        reason=reason,
        quantity=signe_quantite,
        unit_cost=(valeur / quantite_saisie).quantize(Decimal("0.0001")),
        value=-valeur if movement_type == MOVEMENT_EXIT else valeur,
        label=label,
        reference=reference,
        invoice_id=invoice_id,
        created_by=user_id,
    )
    db.add(mouvement)
    article.movements.append(mouvement)
    db.flush()
    _maj_cache(article)
    log_action(
        db,
        action="STOCK_MOVEMENT_RECORDED",
        entity="StockMovement",
        entity_id=mouvement.id,
        user_id=user_id,
        company_id=article.company_id,
        payload={
            "reference": article.reference,
            "type": movement_type,
            "motif": reason,
            "quantite": signe_quantite,
            "cout_unitaire": cout,
            "valeur": mouvement.value,
            "methode": article.valuation_method,
        },
    )
    return mouvement



def comptabiliser_mouvement(
    db: Session,
    mouvement: StockMovement,
    *,
    journal_code: str = "OD",
    user_id: int | None = None,
) -> dict:
    """Comptabilise un mouvement : **stock 3xxx** contre **variation (6114/6124/713x)**.

    Ecriture de l'inventaire permanent (CGNC titre V) ::

        entree : debit 3111 (valeur) / credit 6114 (variation)
        sortie : debit 6114 (variation) / credit 3111 (valeur)
    """
    if mouvement.entry_id is not None:
        raise StockError(
            f"Mouvement {mouvement.id} deja comptabilise (ecriture {mouvement.entry_id})."
        )
    article = db.get(StockItem, mouvement.item_id)
    if article is None:
        raise StockError("Article du mouvement introuvable")
    compte_stock = article.stock_account
    compte_variation_article = compte_variation(compte_stock)
    if not _compte_existe(db, compte_variation_article):
        raise StockError(
            f"Compte de variation {compte_variation_article} absent du plan comptable."
        )
    exercice = get_fiscal_year(db, article.company_id, mouvement.movement_date.year)
    ensure_period_open(exercice)
    journal = get_journal(db, article.company_id, journal_code)
    montant = money(abs(mouvement.value))
    entree = mouvement.value >= 0
    lignes = [
        {
            "account_number": compte_stock,
            "label": f"{'Entrée' if entree else 'Sortie'} stock {article.reference}",
            **({"debit": montant} if entree else {"credit": montant}),
        },
        {
            "account_number": compte_variation_article,
            "label": f"Variation de stocks - {article.label} ({article.reference})",
            **({"credit": montant} if entree else {"debit": montant}),
        },
    ]
    entry = create_entry(
        db,
        company_id=article.company_id,
        fiscal_year=exercice,
        journal=journal,
        entry_date=mouvement.movement_date,
        label=(
            f"{'Entrée' if entree else 'Sortie'} de stock {article.reference} "
            f"({mouvement.quantity} {article.unit})"
        ),
        reference=mouvement.reference or article.reference,
        source="stock_movement",
        source_id=mouvement.id,
        created_by=user_id,
        lines=lignes,
    )
    validate_entry(db, entry, user_id=user_id)
    mouvement.entry_id = entry.id
    db.flush()
    return {
        "mouvement": mouvement,
        "entry": entry,
        "entry_number": entry.entry_number,
        "compte_stock": compte_stock,
        "compte_variation": compte_variation_article,
        "montant": montant,
    }


def comptabiliser_mouvements(
    db: Session, company: Company, exercice: int, *, user_id: int | None = None
) -> list[dict]:
    """Comptabilise les mouvements non encore comptabilises d'un exercice."""
    debut, fin = date(exercice, 1, 1), date(exercice, 12, 31)
    mouvements = list(
        db.execute(
            select(StockMovement)
            .where(
                StockMovement.company_id == company.id,
                StockMovement.entry_id.is_(None),
                StockMovement.movement_date >= debut,
                StockMovement.movement_date <= fin,
            )
            .order_by(StockMovement.movement_date, StockMovement.id)
        ).scalars()
    )
    resultats: list[dict] = []
    for mouvement in mouvements:
        try:
            with db.begin_nested():
                operation = comptabiliser_mouvement(db, mouvement, user_id=user_id)
            resultats.append({**operation, "erreur": None})
        except AccountingError as exc:
            resultats.append({"mouvement": mouvement, "erreur": str(exc)})
    return resultats



# ---------------------------------------------------------------------------
# Inventaire physique (CGNC : au moins une fois par exercice)
# ---------------------------------------------------------------------------
def inventaire_physique(
    db: Session,
    *,
    company: Company,
    count_date: date,
    lignes: list[dict],
    label: str | None = None,
    note: str | None = None,
    visumotif: str | None = None,
    comptabiliser: bool = True,
    user_id: int | None = None,
) -> StockCount:
    """Enregistre un inventaire physique : ecarts valorises et ecritures de variation.

    ``lignes`` : ``[{"reference" (ou "item_id"), "physical_quantity"}]``.

    Controle bloquant n° 4 du CDC : un ecart global superieur a **5 %** de la valeur
    du stock exige un **visa** (motif saisi par un utilisateur habilite).
    """
    controler_periode(
        db, company.id, count_date, user_id=user_id, operation="inventaire physique"
    )
    if not lignes:
        raise StockError("Un inventaire doit comporter au moins une ligne comptee.")
    comptage = StockCount(
        company_id=company.id,
        count_date=count_date,
        status="brouillon",
        label=label or f"Inventaire du {count_date.strftime('%d/%m/%Y')}",
        note=note,
        created_by=user_id,
    )
    db.add(comptage)
    db.flush()
    valeur_stock_avant = money(
        sum(
            (
                etat_article(article, jusqua=count_date)["value"]
                for article in list_items(db, company.id)
            ),
            Decimal("0"),
        )
    )
    for ligne in lignes:
        article = get_item(db, company.id, ligne.get("reference") or ligne["item_id"])
        etat = etat_article(article, jusqua=count_date)
        physique = quantite(ligne["physical_quantity"])
        ecart = quantite(physique - etat["quantity"])
        cout = etat["cmup"]
        if cout <= 0:  # article epuise : valorisation au dernier cout d'entree
            entrees = [
                m for m in _mouvements(article, jusqua=count_date) if m.quantity > 0
            ]
            cout = entrees[-1].unit_cost if entrees else Decimal("0")
        comptage.lines.append(
            StockCountLine(
                item_id=article.id,
                theoretical_quantity=etat["quantity"],
                physical_quantity=physique,
                unit_cost=money(cout),
                gap_quantity=ecart,
                gap_value=money(ecart * cout),
            )
        )
    db.flush()
    ecart_total = money(sum((ligne.gap_value for ligne in comptage.lines), Decimal("0")))
    seuil = money(abs(valeur_stock_avant) * SEUIL_ECART_INVENTAIRE / Decimal("100"))
    if abs(ecart_total) > seuil and not visumotif:
        raise StockError(
            f"Ecart d'inventaire de {ecart_total} DH superieur a "
            f"{SEUIL_ECART_INVENTAIRE} % de la valeur du stock ({valeur_stock_avant} DH) : "
            "un visa motive est obligatoire (controle bloquant n° 4)."
        )
    for ligne in comptage.lines:
        if ligne.gap_quantity == 0 and ligne.gap_value == 0:
            continue
        article = db.get(StockItem, ligne.item_id)
        mouvement = StockMovement(
            company_id=company.id,
            item_id=article.id,
            movement_date=count_date,
            movement_type=MOVEMENT_COUNT,
            reason="inventaire",
            quantity=ligne.gap_quantity,
            unit_cost=ligne.unit_cost,
            value=ligne.gap_value,
            label=f"Ecart d'inventaire {article.reference}",
            reference=comptage.label,
            count_id=comptage.id,
            created_by=user_id,
        )
        db.add(mouvement)
        article.movements.append(mouvement)
        db.flush()
        ligne.movement_id = mouvement.id
        # Un ecart non valorise (article jamais valorise) n'a pas d'ecriture : il est
        # signale par les controles (aucun mouvement a 0 DH sans justification).
        if comptabiliser and ligne.gap_value != 0:
            with db.begin_nested():
                operation = comptabiliser_mouvement(db, mouvement, user_id=user_id)
            if comptage.entry_id is None:
                comptage.entry_id = operation["entry"].id
        _maj_cache(article)
        if ligne.gap_value == 0 and ligne.gap_quantity != 0:
            log_action(
                db,
                action="STOCK_WARNING",
                entity="StockCount",
                entity_id=comptage.id,
                user_id=user_id,
                company_id=company.id,
                payload={
                    "reference": article.reference,
                    "avertissement": (
                        f"Ecart d'inventaire de {ligne.gap_quantity} {article.unit} non "
                        "valorise (aucun cout connu pour cet article)."
                    ),
                },
            )
    comptage.status = COUNT_STATUS_VALIDATED
    log_action(
        db,
        action="STOCK_COUNT_VALIDATED",
        entity="StockCount",
        entity_id=comptage.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "date": count_date,
            "nb_lignes": len(comptage.lines),
            "nb_ecarts": len(comptage.ecarts),
            "ecart_valeur": ecart_total,
            "valeur_stock_avant": valeur_stock_avant,
            "visa": visumotif,
        },
    )
    db.flush()
    return comptage



def constater_stock_final(
    db: Session,
    company: Company,
    exercice: int,
    *,
    journal_code: str = "OD",
    user_id: int | None = None,
) -> dict:
    """Constatation du **stock final** et de la **variation** (regime intermittent).

    Aligne chaque compte de stock sur la valeur issue du module ::

        excedent : debit 3111 / credit 6114
        manquant : debit 6114 / credit 3111

    En **inventaire permanent**, les comptes sont deja mouvementes : l'ecart est
    normalement nul et tout ecart residuel est signale dans le resultat.
    """
    fin = date(exercice, 12, 31)
    valeurs_module: dict[str, Decimal] = {}
    for article in list_items(db, company.id, actifs=False):
        etat = etat_article(article, jusqua=fin)
        if etat["value"] == 0:
            continue
        valeurs_module[article.stock_account] = money(
            valeurs_module.get(article.stock_account, Decimal("0")) + etat["value"]
        )
    soldes = soldes_a_la_date(db, company.id, fin)
    lignes: list[dict] = []
    details: list[dict] = []
    for compte, valeur_module in sorted(valeurs_module.items()):
        solde_comptable = money(soldes.get(compte, Decimal("0")))
        ecart = money(valeur_module - solde_comptable)
        details.append(
            {
                "compte": compte,
                "valeur_module": valeur_module,
                "solde_comptable": solde_comptable,
                "ecart": ecart,
            }
        )
        if ecart == 0:
            continue
        excedent = ecart > 0
        lignes.append(
            {
                "account_number": compte,
                "label": f"Stock final {exercice} - compte {compte}",
                **({"debit": abs(ecart)} if excedent else {"credit": abs(ecart)}),
            }
        )
        lignes.append(
            {
                "account_number": compte_variation(compte),
                "label": f"Variation de stocks {exercice} - compte {compte}",
                **({"credit": abs(ecart)} if excedent else {"debit": abs(ecart)}),
            }
        )
    if not lignes:
        return {
            "genere": False,
            "exercice": exercice,
            "motif": "Aucun ecart entre le module de stocks et la comptabilite.",
            "details": details,
        }
    exercice_comptable = get_fiscal_year(db, company.id, exercice)
    ensure_period_open(exercice_comptable)
    journal = get_journal(db, company.id, journal_code)
    entry = create_entry(
        db,
        company_id=company.id,
        fiscal_year=exercice_comptable,
        journal=journal,
        entry_date=fin,
        label=f"Constatation du stock final {exercice} (variation de stocks)",
        reference=f"STOCK{exercice}",
        source="stock_closing",
        source_id=exercice_comptable.id,
        created_by=user_id,
        lines=lignes,
    )
    validate_entry(db, entry, user_id=user_id)
    log_action(
        db,
        action="STOCK_FINAL_RECORDED",
        entity="Entry",
        entity_id=entry.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "exercice": exercice,
            "entry_number": entry.entry_number,
            "details": details,
        },
    )
    db.flush()
    return {
        "genere": True,
        "exercice": exercice,
        "entry": entry,
        "entry_number": entry.entry_number,
        "details": details,
        "total_ecart": money(sum((detail["ecart"] for detail in details), Decimal("0"))),
    }



# ---------------------------------------------------------------------------
# Depreciation des stocks (prudence)
# ---------------------------------------------------------------------------
def provisionner_stock(
    db: Session,
    article: StockItem,
    exercice: int,
    *,
    inventory_value: Decimal | str,
    motif: str,
    journal_code: str = "OD",
    user_id: int | None = None,
) -> dict:
    """Deprecie un stock lorsque la **valeur d'inventaire** passe sous la valeur comptable.

    Ecriture de **prudence** (CGNC) ::

        dotation : debit 61961 (D.E.P. stocks) / credit 391x (provision)
        reprise  : debit 391x / credit 61961

    La provision est **cumulative** : seule la **variation** (dotation ou reprise) est
    comptabilisee, conformement au principe de non-compensation.
    """
    if not motif or not motif.strip():
        raise StockError("Une depreciation exige un motif (prudence, valeur d'inventaire).")
    if db.execute(
        select(StockProvision).where(
            StockProvision.item_id == article.id, StockProvision.exercice == exercice
        )
    ).scalar_one_or_none() is not None:
        raise StockError(
            f"Une depreciation existe deja pour {article.reference} en {exercice} "
            "(utiliser la dotation ou la reprise de l'exercice suivant)."
        )
    fin = date(exercice, 12, 31)
    etat = etat_article(article, jusqua=fin)
    book_value = etat["value"]
    valeur_inventaire = money(inventory_value)
    provision = money(max(Decimal("0"), book_value - valeur_inventaire))
    precedente = db.execute(
        select(StockProvision).where(
            StockProvision.item_id == article.id, StockProvision.exercice == exercice - 1
        )
    ).scalar_one_or_none()
    previous = money(precedente.provision) if precedente else money(0)
    dotation = money(provision - previous)
    if dotation == 0:
        raise StockError(
            f"Provision inchangee pour {article.reference} en {exercice} ({provision} DH) : "
            "aucune ecriture a passer."
        )
    compte_prov = compte_provision(article.stock_account)
    if not _compte_existe(db, compte_prov):
        raise StockError(f"Compte de provision {compte_prov} absent du plan comptable.")
    if not _compte_existe(db, COMPTE_DOTATION_DEPRECIATION):
        raise StockError(
            f"Compte de dotation {COMPTE_DOTATION_DEPRECIATION} absent du plan comptable."
        )
    ligne = StockProvision(
        company_id=article.company_id,
        item_id=article.id,
        exercice=exercice,
        book_value=book_value,
        inventory_value=valeur_inventaire,
        provision=provision,
        previous_provision=previous,
        motif=motif.strip(),
        created_by=user_id,
    )
    db.add(ligne)
    db.flush()
    exercice_comptable = get_fiscal_year(db, article.company_id, exercice)
    ensure_period_open(exercice_comptable)
    journal = get_journal(db, article.company_id, journal_code)
    augmentation = dotation > 0
    montant = abs(dotation)
    entry = create_entry(
        db,
        company_id=article.company_id,
        fiscal_year=exercice_comptable,
        journal=journal,
        entry_date=fin,
        label=(
            f"{'Depreciation' if augmentation else 'Reprise de depreciation'} du stock "
            f"{article.reference} ({exercice})"
        ),
        reference=article.reference,
        source="stock_provision",
        source_id=ligne.id,
        created_by=user_id,
        lines=[
            {
                "account_number": (
                    COMPTE_DOTATION_DEPRECIATION if augmentation else compte_prov
                ),
                "label": (
                    f"{'Depreciation' if augmentation else 'Reprise'} du stock "
                    f"{article.reference}"
                ),
                "debit": montant,
            },
            {
                "account_number": (
                    compte_prov if augmentation else COMPTE_DOTATION_DEPRECIATION
                ),
                "label": (
                    f"{'Provision' if augmentation else 'Reprise'} pour depreciation du "
                    f"stock {article.reference}"
                ),
                "credit": montant,
            },
        ],
    )
    validate_entry(db, entry, user_id=user_id)
    ligne.entry_id = entry.id
    db.flush()
    log_action(
        db,
        action="STOCK_PROVISION_RECORDED",
        entity="StockProvision",
        entity_id=ligne.id,
        user_id=user_id,
        company_id=article.company_id,
        payload={
            "reference": article.reference,
            "exercice": exercice,
            "valeur_comptable": book_value,
            "valeur_inventaire": valeur_inventaire,
            "provision": provision,
            "dotation": dotation,
            "compte": compte_prov,
            "entry_number": entry.entry_number,
        },
    )
    return {
        "provision": ligne,
        "dotation": dotation,
        "entry": entry,
        "entry_number": entry.entry_number,
        "compte_provision": compte_prov,
        "compte_dotation": COMPTE_DOTATION_DEPRECIATION,
    }



def etat_provisions(db: Session, company_id: int, exercice: int) -> dict:
    """Etat des depreciations de stocks de l'exercice (dotations et reprises)."""
    provisions = list(
        db.execute(
            select(StockProvision)
            .where(
                StockProvision.company_id == company_id,
                StockProvision.exercice == exercice,
            )
            .order_by(StockProvision.id)
        ).scalars()
    )
    lignes = []
    for ligne in provisions:
        article = db.get(StockItem, ligne.item_id)
        lignes.append(
            {
                "reference": article.reference if article else "?",
                "label": article.label if article else "?",
                "compte_stock": article.stock_account if article else "?",
                "compte_provision": (
                    compte_provision(article.stock_account) if article else "?"
                ),
                "book_value": money(ligne.book_value),
                "inventory_value": money(ligne.inventory_value),
                "previous_provision": money(ligne.previous_provision),
                "provision": money(ligne.provision),
                "dotation": money(ligne.dotation),
                "motif": ligne.motif,
                "entry_id": ligne.entry_id,
            }
        )
    return {
        "exercice": exercice,
        "lignes": lignes,
        "total_provision": money(
            sum((ligne["provision"] for ligne in lignes), Decimal("0"))
        ),
        "total_dotation": money(
            sum((ligne["dotation"] for ligne in lignes if ligne["dotation"] > 0), Decimal("0"))
        ),
        "total_reprise": money(
            -sum((ligne["dotation"] for ligne in lignes if ligne["dotation"] < 0), Decimal("0"))
        ),
    }


# ---------------------------------------------------------------------------
# Etats du module
# ---------------------------------------------------------------------------
def etat_stocks(
    db: Session,
    company_id: int,
    *,
    au: date | None = None,
    sous_seuil: bool = False,
) -> dict:
    """Etat de stock valorise (quantite, cout moyen, valeur) et reconciliation.

    Le total des valeurs issues des fiches est **compare aux comptes de stock** du
    grand livre : l'ecart eventuel est affiche (regime permanent).
    """
    articles = list_items(db, company_id, sous_seuil=sous_seuil, actifs=False)
    lignes: list[dict] = []
    valeur_totale = Decimal("0")
    for article in articles:
        etat = etat_article(article, jusqua=au)
        valeur_totale = money(valeur_totale + etat["value"])
        lignes.append(
            {
                "reference": article.reference,
                "label": article.label,
                "unit": article.unit,
                "family": article.family,
                "stock_account": article.stock_account,
                "valuation_method": article.valuation_method,
                "quantity": etat["quantity"],
                "cmup": money(etat["cmup"]),
                "value": etat["value"],
                "alert_threshold": article.alert_threshold,
                "sous_seuil": article.sous_seuil,
            }
        )
    jour = au or date.today()
    soldes = soldes_a_la_date(db, company_id, jour)
    comptes_stock = {ligne["stock_account"] for ligne in lignes}
    valeur_comptable = money(
        sum((soldes.get(compte, Decimal("0")) for compte in comptes_stock), Decimal("0"))
    )
    return {
        "au": jour,
        "lignes": lignes,
        "total_valeur": valeur_totale,
        "total_comptable": valeur_comptable,
        "ecart": money(valeur_totale - valeur_comptable),
        "nb_articles": len(lignes),
        "nb_sous_seuil": len([ligne for ligne in lignes if ligne["sous_seuil"]]),
        "conforme": money(valeur_totale - valeur_comptable) == 0,
    }


def inventaire_valorise(db: Session, company_id: int, *, au: date | None = None) -> dict:
    """Feuille d'inventaire physique (quantites theoriques a compter) pour saisie."""
    etat = etat_stocks(db, company_id, au=au)
    return {
        "au": etat["au"],
        "lignes": [
            {
                "reference": ligne["reference"],
                "label": ligne["label"],
                "unit": ligne["unit"],
                "stock_account": ligne["stock_account"],
                "theoretical_quantity": ligne["quantity"],
                "cmup": ligne["cmup"],
                "theoretical_value": ligne["value"],
            }
            for ligne in etat["lignes"]
        ],
        "total_valeur_theorique": etat["total_valeur"],
    }



def variation_stocks(db: Session, company_id: int, exercice: int) -> dict:
    """Variation de stocks de l'exercice : stock initial, mouvements, stock final."""
    debut = date(exercice, 1, 1)
    fin = date(exercice, 12, 31)
    lignes: list[dict] = []
    for article in list_items(db, company_id, actifs=False):
        quantite_initiale = Decimal("0")
        valeur_initiale = Decimal("0")
        for mouvement in _mouvements(article, jusqua=date(exercice - 1, 12, 31)):
            quantite_initiale = quantite(quantite_initiale + mouvement.quantity)
            valeur_initiale = money(valeur_initiale + mouvement.value)
        mouvements_exercice = [
            mouvement
            for mouvement in _mouvements(article, jusqua=fin)
            if mouvement.movement_date >= debut
        ]
        entrees = [m for m in mouvements_exercice if m.quantity > 0]
        sorties = [m for m in mouvements_exercice if m.quantity < 0]
        final = etat_article(article, jusqua=fin)
        if not mouvements_exercice and quantite_initiale == 0 and final["quantity"] == 0:
            continue
        lignes.append(
            {
                "reference": article.reference,
                "label": article.label,
                "stock_account": article.stock_account,
                "initial_quantity": quantite_initiale,
                "initial_value": valeur_initiale,
                "entrees_quantity": quantite(sum((m.quantity for m in entrees), Decimal("0"))),
                "entrees_value": money(sum((m.value for m in entrees), Decimal("0"))),
                "sorties_quantity": quantite(
                    sum((abs(m.quantity) for m in sorties), Decimal("0"))
                ),
                "sorties_value": money(sum((abs(m.value) for m in sorties), Decimal("0"))),
                "final_quantity": final["quantity"],
                "final_value": final["value"],
                "variation": money(final["value"] - valeur_initiale),
                "cmup": money(final["cmup"]),
            }
        )
    return {
        "exercice": exercice,
        "lignes": lignes,
        "total_initial": money(sum((ligne["initial_value"] for ligne in lignes), Decimal("0"))),
        "total_entrees": money(sum((ligne["entrees_value"] for ligne in lignes), Decimal("0"))),
        "total_sorties": money(sum((ligne["sorties_value"] for ligne in lignes), Decimal("0"))),
        "total_final": money(sum((ligne["final_value"] for ligne in lignes), Decimal("0"))),
        "total_variation": money(sum((ligne["variation"] for ligne in lignes), Decimal("0"))),
    }


def controles_stocks(
    db: Session, company_id: int, exercice: int | None = None
) -> list[dict]:
    """Controles de coherence du module stocks (l'application doit « parler »).

    Verifie : cache de fiche divergent, quantite negative, mouvements non
    comptabilises, articles sous seuil, ecart entre les fiches et la comptabilite,
    valorisation absente.
    """
    controles: list[dict] = []

    def ajouter(niveau: str, code: str, message: str, reference: str | None = None) -> None:
        controles.append(
            {
                "niveau": niveau,
                "code": code,
                "message": message,
                "reference": reference,
            }
        )

    for article in list_items(db, company_id, actifs=False):
        etat = etat_article(article)
        if etat["quantity"] < 0:
            ajouter(
                "bloquant",
                "STOCK_NEGATIF",
                f"Article {article.reference} : quantite negative ({etat['quantity']} "
                f"{article.unit}) — verifier les sorties saisies.",
                article.reference,
            )
        if (
            article.quantity_on_hand != etat["quantity"]
            or money(article.value_on_hand) != etat["value"]
        ):
            ajouter(
                "avertissement",
                "CACHE_DIVERGENT",
                f"Article {article.reference} : le cache de la fiche "
                f"({article.quantity_on_hand} / {article.value_on_hand} DH) differe des "
                f"mouvements ({etat['quantity']} / {etat['value']} DH) — recalculez la fiche.",
                article.reference,
            )
        if article.sous_seuil:
            ajouter(
                "avertissement",
                "SOUS_SEUIL",
                f"Article {article.reference} : stock {etat['quantity']} {article.unit} "
                f"au niveau du seuil d'alerte ({article.alert_threshold}).",
                article.reference,
            )
        mouvements_non_comptabilises = [
            mouvement for mouvement in article.movements if mouvement.entry_id is None
        ]
        if mouvements_non_comptabilises:
            ajouter(
                "avertissement",
                "MOVEMENT_NON_COMPTABILISE",
                f"Article {article.reference} : {len(mouvements_non_comptabilises)} "
                "mouvement(s) sans ecriture (inventaire permanent incomplet).",
                article.reference,
            )
    if exercice is not None:
        etat_global = etat_stocks(db, company_id, au=date(exercice, 12, 31))
        if etat_global["ecart"] != 0:
            ajouter(
                "avertissement",
                "ECART_INVENTAIRE_COMPTABILITE",
                f"Ecart de {etat_global['ecart']} DH entre les fiches de stock "
                f"({etat_global['total_valeur']} DH) et les comptes de stock "
                f"({etat_global['total_comptable']} DH) a la cloture {exercice} : "
                "constater le stock final ou comptabiliser les mouvements.",
            )
    return controles

