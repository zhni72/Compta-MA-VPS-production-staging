"""Cessation / cession d'activité : TVA de sortie et régularisations (P2.2).

Ce module couvre les **trois changements de situation** de l'entreprise et la
déclaration de TVA qui les accompagne :

| Événement | Régime TVA (annexe 1 RD V4.0) | Déclaration |
|---|---|---|
| **Cessation temporaire d'activité** | **3** — « déclaration TVA de cessation temporaire d'activité » | dans le **mois** qui suit la clôture du dernier exercice (**CGI art. 150 bis**) ; 2 exercices, renouvelable 1 |
| **Cession** de l'entreprise | **4** — « déclaration de cession ou cessation TVA » | **30 jours** (**CGI art. 114**) + déclaration de cession (art. 150-I : 45 jours) |
| **Cessation** définitive | **4** | **30 jours** (**CGI art. 114**) + déclaration de cessation (art. 150-I : 45 jours) |

Conformément à l'**annexe 1 « correspondance balise RD V4.0 »**, la déclaration de
régime **3** ou **4** porte `<regime>` = 3 ou 4 et `<periode>` = **1**.

Ce que calcule l'application
----------------------------
- la **TVA de la période de sortie** (collectée / déductible / nette) sur la période
  allant du **1ᵉʳ janvier de l'exercice** (ou du lendemain du dernier événement) à la
  **date d'effet** ;
- la **régularisation des déductions** exigée par l'art. 114 (renvoi aux
  **art. 101 à 105**) : pour chaque **bien amortissable** encore en service, la
  fraction de TVA à reverser est celle déjà calculée par le module P1.2
  (`assets.regularisation_tva_art106` : prorata des années restantes, durée
  paramétrable « meubles » / « immeubles », **art. 102 et 104-II-1°**) ;
- les **stocks** et autres biens : leur valeur est **affichée** et leur TVA de
  régularisation **saisie** (`montant_stocks`) — l'application ne devine aucun
  montant (avertissement `activite.regularisation_stocks_a_examiner`) ;
- le **total à payer** (TVA nette + régularisations), l'**échéance** (30 jours) et le
  **fichier EDI du relevé des déductions** au régime 3 ou 4.

L'application **ne clôture pas** l'activité d'elle-même : elle prépare la
déclaration, l'inscrit au registre `tax_declarations` et laisse l'utilisateur
déposer sur SIMPL (EDI/EFI) — aucune donnée fiscale n'est « présumée déposée».
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.rates_ma import money
from app.models import (
    DECLARATION_BROUILLON,
    DECLARATION_TVA,
    DELAI_CESSATION_TEMPORAIRE_MOIS,
    DELAI_DECLARATION_ART_150_JOURS,
    DELAI_DECLARATION_TVA_JOURS,
    PERIODE_REGIME_ACTIVITE,
    TYPE_CESSATION_TEMPORAIRE,
    ACTIVITY_TYPE_LABELS,
    ActivityEvent,
    Company,
    TaxDeclaration,
    regime_tva_pour_type,
)
from app.services.accounting import AccountingError, get_fiscal_year
from app.services.reporting import year_bounds
from app.services.vat import period_bounds, vat_return


class ActiviteError(AccountingError):
    """Erreur de gestion d'un événement de vie (cessation, cession)."""


# ---------------------------------------------------------------------------
# Evenements : creation et lecture
# ---------------------------------------------------------------------------
def creer_evenement(
    db: Session,
    company: Company,
    *,
    type: str,
    date_effet: date,
    motif: str | None = None,
    repreneur_nom: str | None = None,
    repreneur_fiscal_id: str | None = None,
    repreneur_ice: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> ActivityEvent:
    """Enregistre un **evenement de vie** (cessation temporaire, cession, cessation).

    Regles de fond :

    - le **type** fixe le **regime TVA** de la declaration (3 ou 4) et la `periode`
      (**1** pour ces regimes, annexe 1 RD V4.0) ;
    - l'exercice de la **date d'effet** doit exister dans le dossier ;
    - une **cessation temporaire** exige un **motif** (CGI art. 150 bis : la
      declaration indique « notamment les motifs justifiant la cessation ») ;
    - une **cession** est nominative : le **nom du repreneur** est exige ;
    - deux evenements ne peuvent pas porter la **meme date d'effet**, et aucun
      evenement ne peut etre anterieur a un evenement deja enregistre (la chronologie
      des declarations serait incoherente).
    """
    try:
        regime = regime_tva_pour_type(type)
    except ValueError as exc:
        raise ActiviteError(str(exc)) from exc
    get_fiscal_year(db, company.id, date_effet.year)  # leve si l'exercice est absent
    if type == TYPE_CESSATION_TEMPORAIRE and not (motif or "").strip():
        raise ActiviteError(
            "Une cessation temporaire d'activité exige un motif (CGI art. 150 bis : "
            "la déclaration indique les motifs justifiant la cessation)."
        )
    if type == "cession" and not (repreneur_nom or "").strip():
        raise ActiviteError(
            "Une cession exige l'identification du repreneur (nom ou raison sociale)."
        )
    existants = list_evenements(db, company.id)
    if any(evenement.date_effet == date_effet for evenement in existants):
        raise ActiviteError(
            f"Un événement est déjà enregistré au {date_effet.isoformat()} : "
            "corrigez sa fiche plutôt que d'en créer un second à la même date."
        )
    if existants and date_effet < max(e.date_effet for e in existants):
        raise ActiviteError(
            "La date d'effet est antérieure à un événement déjà enregistré : "
            "saisissez les événements dans l'ordre chronologique."
        )
    evenement = ActivityEvent(
        company_id=company.id,
        type=type,
        date_effet=date_effet,
        regime_tva=regime,
        periode=PERIODE_REGIME_ACTIVITE,
        motif=(motif or "").strip() or None,
        repreneur_nom=(repreneur_nom or "").strip() or None,
        repreneur_fiscal_id=(repreneur_fiscal_id or "").strip() or None,
        repreneur_ice=(repreneur_ice or "").strip() or None,
        notes=(notes or "").strip() or None,
        created_by=user_id,
    )
    db.add(evenement)
    db.flush()
    log_action(
        db,
        action="ACTIVITY_EVENT_CREATED",
        entity="ActivityEvent",
        entity_id=evenement.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "type": evenement.type,
            "date_effet": evenement.date_effet.isoformat(),
            "regime_tva": evenement.regime_tva,
            "periode": evenement.periode,
            "echeance_tva": echeance_tva(evenement).isoformat(),
        },
    )
    return evenement


def list_evenements(db: Session, company_id: int, *, annee: int | None = None) -> list[ActivityEvent]:
    """Evenements du dossier (filtres par exercice de la date d'effet)."""
    requete = select(ActivityEvent).where(ActivityEvent.company_id == company_id)
    if annee is not None:
        requete = requete.where(
            ActivityEvent.date_effet >= year_bounds(annee)[0],
            ActivityEvent.date_effet <= year_bounds(annee)[1],
        )
    return list(
        db.execute(requete.order_by(ActivityEvent.date_effet, ActivityEvent.id)).scalars()
    )


def get_evenement(db: Session, company_id: int, reference: int | str) -> ActivityEvent:
    """Evenement par identifiant (404 applicatif si absent du dossier)."""
    evenement = db.get(ActivityEvent, int(reference))
    if evenement is None or evenement.company_id != company_id:
        raise ActiviteError(f"Événement d'activité {reference} introuvable dans ce dossier.")
    return evenement


def dernier_evenement(db: Session, company_id: int) -> ActivityEvent | None:
    """Dernier evenement enregistre (None si l'entreprise est en activite normale)."""
    evenements = list_evenements(db, company_id)
    return evenements[-1] if evenements else None


# ---------------------------------------------------------------------------
# Echeances legales et periode de la declaration de sortie
# ---------------------------------------------------------------------------
def echeance_tva(evenement: ActivityEvent) -> date:
    """Echeance de la declaration de TVA de sortie : **date d'effet + 30 jours**.

    CGI art. 114 : le redevable fournit dans les **trente (30) jours** qui suivent
    la date de cession ou de cessation la declaration de liquidation de la taxe et
    de regularisation des deductions ; la taxe due est exigible dans ce delai.
    """
    return evenement.date_effet + timedelta(days=DELAI_DECLARATION_TVA_JOURS)


def echeance_declaration_art_150(evenement: ActivityEvent) -> date:
    """Echeance de la declaration de changement (cessation/cession) : **+ 45 jours**."""
    return evenement.date_effet + timedelta(days=DELAI_DECLARATION_ART_150_JOURS)


def echeance_cessation_temporaire(evenement: ActivityEvent) -> date:
    """Echeance de la declaration de cessation temporaire (CGI art. 150 bis).

    La declaration est souscrite **dans le mois qui suit la cloture du dernier
    exercice** d'activite (fin de mois, pour rester prudente sur la date limite).
    """
    cloture = year_bounds(evenement.date_effet.year)[1]
    mois_suivant = cloture.month + DELAI_CESSATION_TEMPORAIRE_MOIS
    annee = cloture.year + (mois_suivant - 1) // 12
    mois = (mois_suivant - 1) % 12 + 1
    return period_bounds(annee, month=mois)[1]


def delais(evenement: ActivityEvent) -> dict:
    """Echeances, regime et references applicables a un evenement."""
    return {
        "regime_tva": evenement.regime_tva,
        "periode": evenement.periode,
        "echeance_tva": echeance_tva(evenement),
        "echeance_declaration_art_150": echeance_declaration_art_150(evenement),
        "echeance_cessation_temporaire": (
            echeance_cessation_temporaire(evenement)
            if evenement.type == TYPE_CESSATION_TEMPORAIRE
            else None
        ),
        "delai_tva_jours": DELAI_DECLARATION_TVA_JOURS,
        "reference_tva": "CGI art. 114 (déclaration de cession ou de cessation)",
        "reference_changement": "CGI art. 150-I (45 jours)",
        "reference_cessation_temporaire": "CGI art. 150 bis (mois suivant la clôture)",
        "reference_regime": (
            "Annexe 1 EDI Simpl-TVA « correspondance balise RD V4.0 » : "
            "régime 3 (cessation temporaire) / 4 (cession ou cessation), période 1"
        ),
    }


def periode_declaration(
    db: Session, company_id: int, evenement: ActivityEvent
) -> tuple[date, date]:
    """Periode de la declaration de sortie : du debut d'activite a la date d'effet.

    Le debut est le **1ᵉʳ janvier** de l'exercice de l'evenement, ou le **lendemain
    du dernier evenement anterieur** (pour ne declarer qu'une fois chaque periode).
    """
    date_from = year_bounds(evenement.date_effet.year)[0]
    precedents = [
        autre.date_effet
        for autre in list_evenements(db, company_id)
        if autre.id != evenement.id and autre.date_effet < evenement.date_effet
    ]
    if precedents:
        date_from = max(date_from, max(precedents) + timedelta(days=1))
    return date_from, evenement.date_effet


# ---------------------------------------------------------------------------
# Regularisation des deductions (CGI art. 114 -> art. 101 a 105)
# ---------------------------------------------------------------------------
def regularisation_deductions(
    db: Session,
    company: Company,
    evenement: ActivityEvent,
    *,
    montant_stocks: Decimal | int | float | str | None = None,
) -> dict:
    """Regularisation de la TVA deduite exigee pour une cession ou une cessation.

    **Immobilisations** : pour chaque bien amortissable encore en service a la date
    d'effet, le module P1.2 calcule la fraction de TVA a reverser (prorata des annees
    restantes, duree parametrable ; **CGI art. 102 et 104-II-1°**, renvoi de
    l'**art. 114** aux articles 101 a 105).

    **Stocks et autres biens** : la valeur des stocks est **affichee** et la TVA a
    regulariser est **saisie** (`montant_stocks`) — aucun taux n'est devine
    (avertissement `activite.regularisation_stocks_a_examiner`).
    """
    from app.services import assets  # noqa: PLC0415 - import local (anti-cycle)

    lignes: list[dict] = []
    total = Decimal("0")
    for bien in assets.list_assets(db, company.id):
        if bien.disposal_date is not None and bien.disposal_date <= evenement.date_effet:
            continue  # deja sorti de l'actif : regularise lors de la cession du bien
        calcul = assets.regularisation_tva_art106(bien, evenement.date_effet)
        if not calcul["applicable"]:
            continue
        lignes.append(
            {
                "code": bien.code,
                "label": bien.label,
                "compte": bien.account_number,
                "tva_montant": money(bien.tva_montant),
                "annees_utilisees": calcul["annees_utilisees"],
                "annees_restantes": calcul["annees_restantes"],
                "montant": calcul["montant"],
            }
        )
        total = money(total + calcul["montant"])
    stocks = money(montant_stocks) if montant_stocks is not None else None
    return {
        "lignes_immobilisations": lignes,
        "total_immobilisations": total,
        "montant_stocks": stocks,
        "montant_stocks_a_saisir": stocks is None,
        "total": money(total + (stocks or Decimal("0"))),
        "references": (
            "CGI art. 114 (renvoi aux art. 101 à 105) ; art. 102 et 104-II-1° "
            "(biens amortissables : 5 ans meubles / 10 ans immeubles, paramétrable)"
        ),
        "avertissement": (
            "Durée de régularisation des biens amortissables et TVA sur stocks à "
            "confirmer par l'expert-comptable (CDC, ambiguïtés A5 et A23 : le CDC cite "
            "« art. 106 », qui traite des EXCLUSIONS du droit à déduction)."
        ),
    }


# ---------------------------------------------------------------------------
# Declaration de TVA de sortie (regimes 3 et 4)
# ---------------------------------------------------------------------------
def declaration_tva_sortie(
    db: Session,
    company: Company,
    evenement: ActivityEvent,
    *,
    montant_stocks: Decimal | int | float | str | None = None,
) -> dict:
    """Prepare la **declaration de TVA** de l'evenement (regime 3 ou 4, periode 1).

    Contenu : TVA de la **periode de sortie** (collectee, deductible, nette),
    **regularisation des deductions**, **total a payer**, credit reportable,
    **echeances** (30 jours art. 114 ; 45 jours art. 150 ; mois suivant la cloture
    pour une cessation temporaire) et **controles**.
    """
    date_from, date_to = periode_declaration(db, company.id, evenement)
    tva = vat_return(db, company.id, date_from, date_to)
    regularisation = regularisation_deductions(
        db, company, evenement, montant_stocks=montant_stocks
    )
    declaration = {
        "evenement_id": evenement.id,
        "annonce": evenement.type_libelle,
        "annee": evenement.date_effet.year,
        "regime": evenement.regime_tva,
        "periode": evenement.periode,
        "date_from": date_from,
        "date_to": date_to,
        "tva": tva,
        "regularisation": regularisation,
        "tva_collectee": tva["tva_collectee"],
        "tva_deductible": tva["tva_deductible"],
        "tva_nette": tva["tva_nette"],
        "tva_a_payer": tva["tva_a_payer"],
        "regularisation_totale": regularisation["total"],
        "total_a_payer": money(tva["tva_a_payer"] + regularisation["total"]),
        "credit_a_reporter": tva["credit_tva_a_reporter"],
        "delais": delais(evenement),
    }
    declaration["controles"] = controles_activite(
        db, company, evenement, declaration=declaration
    )
    return declaration


def controles_bloquants(controles: list[dict]) -> list[dict]:
    """Controles bloquants (interdisent le depot de la declaration de sortie)."""
    return [controle for controle in controles if controle["niveau"] == "bloquant"]


def controles_activite(
    db: Session,
    company: Company,
    evenement: ActivityEvent,
    *,
    declaration: dict | None = None,
) -> list[dict]:
    """Controles d'un evenement de vie (avant preparation et avant depot).

    Bloquants : `activite.motif_absent` (cessation temporaire, art. 150 bis) et
    `activite.echeance_tva_depassee` (30 jours, art. 114). Avertissements :
    `activite.repreneur_absent`, `activite.regularisation_stocks_a_examiner`,
    `activite.tva_non_declaree`, `activite.ecritures_apres_effet`.
    """
    from app.services.reporting import movements  # noqa: PLC0415 - import local

    controles: list[dict] = []

    def ajouter(code: str, niveau: str, message: str) -> None:
        controles.append({"code": code, "niveau": niveau, "message": message})

    if evenement.type == TYPE_CESSATION_TEMPORAIRE and not (evenement.motif or "").strip():
        ajouter(
            "activite.motif_absent",
            "bloquant",
            "Cessation temporaire sans motif : la déclaration exige les motifs "
            "justifiant la cessation (CGI art. 150 bis).",
        )
    if evenement.type == "cession" and not (evenement.repreneur_nom or "").strip():
        ajouter(
            "activite.repreneur_absent",
            "avertissement",
            "Cession sans identification du repreneur : la transmission de la taxe "
            "due sur les encaissements doit être documentée (CGI art. 114).",
        )
    declaration = declaration or declaration_tva_sortie(db, company, evenement)
    if declaration["regularisation"]["montant_stocks_a_saisir"]:
        ajouter(
            "activite.regularisation_stocks_a_examiner",
            "avertissement",
            "TVA à régulariser sur les stocks et biens non amortissables : montant à "
            "saisir par l'expert-comptable (aucun taux n'est deviné ; CGI art. 114, "
            "renvoi aux articles 101 à 105).",
        )
    registre = declaration_registre(db, company.id, evenement)
    if registre is None:
        ajouter(
            "activite.tva_non_declaree",
            "avertissement",
            f"Déclaration TVA de {evenement.type_libelle} non enregistrée au registre "
            f"(régime {evenement.regime_tva}, échéance "
            f"{echeance_tva(evenement).isoformat()}).",
        )
    elif date.today() > echeance_tva(evenement) and registre.accuse_le is None:
        ajouter(
            "activite.echeance_tva_depassee",
            "bloquant",
            "Échéance de 30 jours dépassée (CGI art. 114) : la déclaration TVA de "
            f"cession/cessation devait être déposée avant le "
            f"{echeance_tva(evenement).isoformat()} — régularisez sans délai.",
        )
    jour_suivant = evenement.date_effet + timedelta(days=1)
    post_effet = movements(db, company.id, jour_suivant, year_bounds(2100)[1])
    if post_effet:
        ajouter(
            "activite.ecritures_apres_effet",
            "avertissement",
            f"{len(post_effet)} compte(s) mouvementé(s) après la date d'effet "
            f"({evenement.date_effet.isoformat()}) : vérifiez que l'activité n'a pas "
            "repris (la déclaration de sortie ne couvre que la période antérieure).",
        )
    ajouter(
        "activite.recap",
        "information",
        f"{evenement.type_libelle} au {evenement.date_effet.isoformat()} — régime TVA "
        f"{evenement.regime_tva} (période {evenement.periode}) : TVA de la période "
        f"{declaration['date_from'].isoformat()} → {declaration['date_to'].isoformat()} "
        f"= {declaration['tva_nette']} DH, régularisations "
        f"{declaration['regularisation_totale']} DH, total à payer "
        f"{declaration['total_a_payer']} DH (échéance "
        f"{echeance_tva(evenement).isoformat()}).",
    )
    return controles


# ---------------------------------------------------------------------------
# Registre des declarations (tax_declarations) et fichier EDI
# ---------------------------------------------------------------------------
def declaration_registre(
    db: Session, company_id: int, evenement: ActivityEvent
) -> TaxDeclaration | None:
    """Declaration TVA de l'evenement au registre (periode = exercice, regime = 3|4)."""
    return db.execute(
        select(TaxDeclaration).where(
            TaxDeclaration.company_id == company_id,
            TaxDeclaration.type == DECLARATION_TVA,
            TaxDeclaration.periode == str(evenement.date_effet.year),
            TaxDeclaration.regime == str(evenement.regime_tva),
        )
    ).scalar_one_or_none()


def enregistrer_declaration_tva(
    db: Session,
    company: Company,
    evenement: ActivityEvent,
    *,
    declaration: dict | None = None,
    mode_depot: str = "EDI",
    user_id: int | None = None,
) -> TaxDeclaration:
    """Inscrit la **declaration TVA de sortie** au registre (`tax_declarations`).

    La declaration est **brouillon** ; une declaration deja deposee est **figee**
    (aucune regeneration silencieuse). L'evenement est relie a sa declaration.
    """
    declaration = declaration or declaration_tva_sortie(db, company, evenement)
    registre = declaration_registre(db, company.id, evenement)
    if registre is not None and registre.statut != DECLARATION_BROUILLON:
        raise ActiviteError(
            f"La déclaration TVA {registre.periode} (régime {registre.regime}) est déjà "
            f"« {registre.statut_libelle} » : elle ne peut plus être régénérée."
        )
    if registre is None:
        registre = TaxDeclaration(
            company_id=company.id,
            fiscal_year_id=get_fiscal_year(db, company.id, evenement.date_effet.year).id,
            type=DECLARATION_TVA,
            periode=str(evenement.date_effet.year),
            regime=str(evenement.regime_tva),
            mode_depot=mode_depot,
            statut=DECLARATION_BROUILLON,
        )
        db.add(registre)
        db.flush()
    registre.regime = str(evenement.regime_tva)
    registre.mode_depot = mode_depot
    registre.montant = declaration["total_a_payer"]
    registre.nb_lignes = len(declaration["tva"]["detail"])
    registre.notes = (
        f"{evenement.type_libelle} au {evenement.date_effet.isoformat()} — "
        f"régime {evenement.regime_tva} / période {evenement.periode} : TVA "
        f"{declaration['date_from'].isoformat()} → {declaration['date_to'].isoformat()} "
        f"= {declaration['tva_nette']} DH, régularisations "
        f"{declaration['regularisation_totale']} DH, total "
        f"{declaration['total_a_payer']} DH, échéance "
        f"{echeance_tva(evenement).isoformat()}."
    )
    evenement.declaration_id = registre.id
    db.flush()
    log_action(
        db,
        action="ACTIVITY_TVA_RECORDED",
        entity="TaxDeclaration",
        entity_id=registre.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "evenement_id": evenement.id,
            "type_evenement": evenement.type,
            "regime": registre.regime,
            "periode": registre.periode,
            "total_a_payer": str(registre.montant),
        },
    )
    return registre


# ---------------------------------------------------------------------------
# Fichier EDI du releve des deductions au regime 3 ou 4
# ---------------------------------------------------------------------------
def construire_rd_sortie(
    db: Session,
    company: Company,
    evenement: ActivityEvent,
    *,
    include_zero_vat: bool = False,
    tx_unit: str = "percent",
    prorata: Decimal | int | float | str = "1",
    base_periode: str | None = None,
    max_lignes: int | None = None,
) -> dict:
    """Prepare le **releve des deductions EDI** de la declaration de sortie.

    Le fichier porte le **regime** de l'evenement (**3** ou **4**) et la **periode
    `1`**, conformement a l'annexe 1 « correspondance balise RD V4.0 » : c'est le
    meme fichier que le releve mensuel/trimestriel, transmis avec la declaration de
    cession ou de cessation.
    """
    from app.services import edi_tva  # noqa: PLC0415 - import local (anti-cycle)

    date_from, date_to = periode_declaration(db, company.id, evenement)
    taux_prorata = Decimal(str(prorata))
    releve = edi_tva.collect_rd_lines(
        db,
        company,
        date_from,
        date_to,
        include_zero_vat=include_zero_vat,
        prorata=taux_prorata,
        base_periode=base_periode or edi_tva.BASE_PERIODE_DEFAUT,
    )
    xml = edi_tva.build_rd_xml(
        identifiant_fiscal=company.fiscal_id or "",
        annee=evenement.date_effet.year,
        periode=evenement.periode,
        regime=evenement.regime_tva,
        lignes=releve["lignes"],
        tx_unit=tx_unit,
        declarant_nom=company.name,
        inclure_prorata=taux_prorata != Decimal("1"),
        max_lignes=max_lignes,
    )
    return {
        "annee": evenement.date_effet.year,
        "periode": evenement.periode,
        "regime": evenement.regime_tva,
        "date_from": date_from,
        "date_to": date_to,
        "xml": xml,
        "nom_fichier": edi_tva.xml_filename(
            evenement.date_effet.year, evenement.periode, evenement.regime_tva
        ),
        "taille": len(xml.encode("utf-8")),
        "releve": releve,
        "references": (
            "Annexe 1 EDI Simpl-TVA « correspondance balise RD V4.0 » : régime 3 "
            "(cessation temporaire) / 4 (cession ou cessation), période 1"
        ),
    }


def situation(db: Session, company: Company, *, annee: int | None = None) -> dict:
    """Situation de l'activite : evenements, declaration de sortie et registre.

    Point d'entree unique de l'API et de l'ecran (aucune ecriture) : il restitue la
    chronologie des evenements, la **declaration TVA de sortie** du dernier evenement
    (TVA, regularisations, total, echeances, controles) et l'etat du **registre**.
    """
    evenements = list_evenements(db, company.id, annee=annee)
    courant = evenements[-1] if evenements else None
    declaration = declaration_tva_sortie(db, company, courant) if courant else None
    return {
        "annee": annee or (courant.date_effet.year if courant else date.today().year),
        "evenements": evenements,
        "evenement": courant,
        "declaration": declaration,
        "registre": declaration_registre(db, company.id, courant) if courant else None,
        "en_activite": courant is None,
        "types": ACTIVITY_TYPE_LABELS,
        "references": {
            "evenements": "CGI art. 114 (TVA) et art. 150-I (45 jours)",
            "cessation_temporaire": "CGI art. 150 bis (2 exercices, renouvelable 1)",
            "regime_tva": "Annexe 1 RD V4.0 : régimes 3 et 4, période 1",
            "regularisation": "CGI art. 114 (renvoi art. 101 à 105), art. 102 et 104-II-1°",
        },
    }


def soumettre_declaration(
    db: Session,
    registre: TaxDeclaration,
    *,
    jour: date | None = None,
    accuse_le: date | None = None,
    motif_rejet: str | None = None,
    user_id: int | None = None,
) -> TaxDeclaration:
    """Enregistre le **depot** (ou l'accuse de reception) de la declaration TVA."""
    from app.models import DECLARATION_ACCEPTEE, DECLARATION_REJETEE, DECLARATION_SOUMISE

    jour_fourni = jour is not None
    jour = jour or date.today()
    if registre.statut in (DECLARATION_ACCEPTEE, DECLARATION_REJETEE):
        raise ActiviteError(
            f"La déclaration {registre.type} {registre.periode} est déjà "
            f"« {registre.statut_libelle} » : aucun nouveau dépôt possible."
        )
    if accuse_le is not None:
        registre.statut = DECLARATION_ACCEPTEE
        registre.accuse_le = accuse_le
    elif motif_rejet:
        registre.statut = DECLARATION_REJETEE
        registre.motif_rejet = motif_rejet
    else:
        registre.statut = DECLARATION_SOUMISE
    if jour_fourni or registre.soumise_le is None:
        registre.soumise_le = jour
    db.flush()
    log_action(
        db,
        action="ACTIVITY_TVA_SUBMITTED",
        entity="TaxDeclaration",
        entity_id=registre.id,
        user_id=user_id,
        company_id=registre.company_id,
        payload={
            "periode": registre.periode,
            "regime": registre.regime,
            "statut": registre.statut,
            "accuse_le": accuse_le.isoformat() if accuse_le else None,
        },
    )
    return registre