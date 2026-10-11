"""Immobilisations et amortissements (P1.2).

Cycle de vie complet : **acquisition -> mise en service -> dotations -> cession /
mise au rebut**, avec la TVA d'immobilisation au **34551** et les
**regularisations de TVA (CGI art. 106)**.

References normatives
---------------------
- **CGNC — plan comptable, titre II chapitre I (actif immobilise)** : trois
  categories (non-valeurs `21x`, corporelles et incorporelles `22x`/`23x`,
  financieres `24x`) ; l'**amortissement** est la constatation systematique et
  irreversible de la depreciation liee au temps ; la **VNC** = valeur d'entree -
  amortissements cumules.
- **CGI art. 10** : amortissements fiscalement deductibles, **prorata temporis** a
  compter de la mise en service, duree d'utilisation, **amortissement degressif**
  avec coefficient multiplicateur **parametrable** (jamais code en dur :
  ambiguite A4 du CDC).
- **CGI art. 106** : **regularisation de la TVA** ayant greve une immobilisation
  lorsqu'une cession ou une mise au rebut intervient avant la fin de la periode de
  regularisation, par **fractions egales** (duree parametrable : ambiguite A5).

Regles structurelles
--------------------
- les **fiches** (`assets`) portent le plan d'amortissement ; les **ecritures**
  restent la seule source de verite comptable ;
- une dotation n'existe que si son **ecriture est validee** (6193x / 283x) ;
- toute sortie d'actif **solde** le compte 2xxx et son compte 283x ;
- un bien **cede ou mis au rebut ne peut plus etre amorti** ;
- la **VNC ne descend jamais sous la valeur residuelle** (derniere annuite
  plafonnee, jamais d'amortissement negatif).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.core.numbering import next_document_number
from app.core.rates_ma import money
from app.models import (
    Account,
    Asset,
    AssetDepreciationLine,
    AssetEvent,
    Company,
    Entry,
    EntryLine,
    FiscalYear,
    Invoice,
    InvoiceLine,
)
from app.models.asset import (
    ASSET_EVENT_ACQUISITION,
    ASSET_EVENT_CESSION,
    ASSET_EVENT_DOTATION,
    ASSET_EVENT_REBUT,
    ASSET_EVENT_REGULARISATION,
    ASSET_METHOD_DEGRESSIF,
    ASSET_METHOD_LINEAIRE,
    ASSET_METHODS,
    ASSET_STATUS_CELE,
    ASSET_STATUS_EN_SERVICE,
    ASSET_STATUS_REBUTE,
)
from app.services.accounting import (
    AccountingError,
    create_entry,
    ensure_period_open,
    get_fiscal_year,
    get_journal,
    validate_entry,
)
from app.services.reporting import movements

# ---------------------------------------------------------------------------
# Comptes PCGE : correspondances structurelles (verifiees sur le plan de reference)
# ---------------------------------------------------------------------------
# Familles amortissables : non-valeurs (21x), incorporelles (22x), corporelles (23x).
FAMILLES_AMORTISSABLES = ("21", "22", "23")
# Familles non amortissables par nature : immobilisations financieres (provisions 29x).
FAMILLES_FINANCIERES = ("24", "25", "26", "27")
# Immobilisations en cours (239x) : amortissement a compter de la mise en service.
PREFIXE_EN_COURS = "239"
# Repli documente si le compte de dotation derive est absent du plan (ex. 2130 :
# l'amortissement 2813 existe mais la dotation 61913 est absente) : la famille
# fournit alors son compte generique, avec avertissement.
REPLI_DOTATION = {"21": "61911", "22": "61928", "23": "61938"}
# Immeubles : duree de regularisation de la TVA plus longue (CGI art. 106).
FAMILLES_IMMEUBLES = ("231", "232")


def racine4(account_number: str) -> str:
    """Racine a 4 chiffres d'un compte (ex. 23321 -> 2332)."""
    return str(account_number).strip()[:4]


def est_immeuble(account_number: str) -> bool:
    """Vrai pour un terrain ou une construction (regularisation art. 106 longue)."""
    return racine4(account_number)[:3] in FAMILLES_IMMEUBLES


def compte_vna(account_number: str) -> str:
    """Compte de VNA des immobilisations cedees (6512 incorporelles / 6513 corporelles)."""
    return (
        settings.compte_vna_cession_incorporelle
        if racine4(account_number)[:2] in ("21", "22")
        else settings.compte_vna_cession_corporelle
    )


def compte_produit_cession(account_number: str) -> str:
    """Compte de produit de cession (7512 incorporelles / 7513 corporelles)."""
    return (
        settings.compte_produit_cession_incorporelle
        if racine4(account_number)[:2] in ("21", "22")
        else settings.compte_produit_cession_corporelle
    )


def comptes_amortissement(account_number: str) -> dict:
    """Comptes (amortissement 28x, dotation 619x) derives d'un compte d'immobilisation.

    Le PCGE est **structure** : les deux derniers chiffres du compte d'actif
    identifient le poste, d'ou par construction ``amortissement = "28" + poste`` et
    ``dotation = "619" + poste`` — ex. ``2332`` -> ``2833`` / ``61933``,
    ``2340`` -> ``2834`` / ``61934``, ``2220`` -> ``2822`` / ``61922``.

    Retourne ``{"amortissement", "dotation", "amortissable", "motif"}`` ; ``motif``
    explique les cas non amortissables (immobilisation financiere, bien en cours).
    """
    numero = racine4(account_number)
    famille = numero[:2]
    if numero[:3] == PREFIXE_EN_COURS:
        return {
            "amortissement": None,
            "dotation": None,
            "amortissable": False,
            "motif": (
                "Immobilisation en cours (239x) : amortissement a compter de la mise "
                "en service ; transferer d'abord le bien vers son compte definitif."
            ),
        }
    if famille in FAMILLES_FINANCIERES:
        return {
            "amortissement": None,
            "dotation": None,
            "amortissable": False,
            "motif": (
                "Immobilisation financiere : pas d'amortissement (depreciation "
                "eventuelle par provisions, comptes 29x / 6194x)."
            ),
        }
    if famille not in FAMILLES_AMORTISSABLES:
        return {
            "amortissement": None,
            "dotation": None,
            "amortissable": False,
            "motif": f"Compte {numero} hors des familles amortissables du CGNC.",
        }
    poste = numero[1:3]
    return {
        "amortissement": f"28{poste}",
        "dotation": f"619{poste}",
        "amortissable": True,
        "motif": None,
    }


def _compte_existe(db: Session, compte: str | None) -> bool:
    """Vrai si le compte figure au plan comptable charge."""
    if not compte:
        return False
    return (
        db.execute(
            select(Account.number).where(Account.number == compte)
        ).scalar_one_or_none()
        is not None
    )



def comptes_immobilisation(db: Session, account_number: str) -> dict:
    """Comptes d'amortissement/dotation **verifies dans le plan**, avec avertissement.

    Complete `comptes_amortissement` en controlant l'existence des comptes derives :
    si le compte de **dotation** derive est absent du plan (cas rare, ex. 2130 ->
    ``61913``), le compte generique de la famille est utilise et un **avertissement**
    est retourne — aucune donnee comptable n'est inventee silencieusement.
    """
    resultat = comptes_amortissement(account_number)
    resultat["avertissement"] = None
    if not resultat["amortissable"]:
        return resultat
    numero = racine4(account_number)
    famille = numero[:2]
    if not _compte_existe(db, resultat["amortissement"]):
        resultat["amortissable"] = False
        resultat["avertissement"] = (
            f"Compte d'amortissement {resultat['amortissement']} absent du plan : "
            "verifier le plan comptable avant de constater une dotation."
        )
        return resultat
    if not _compte_existe(db, resultat["dotation"]):
        repli = REPLI_DOTATION.get(famille)
        resultat["dotation"] = repli
        resultat["avertissement"] = (
            f"Compte de dotation derive 619{numero[1:3]} absent du plan : repli sur "
            f"{repli} (compte generique de la famille) — a valider par "
            "l'expert-comptable."
        )
    return resultat


def coefficient_degressif(duree_annees: int) -> Decimal:
    """Coefficient multiplicateur du degressif selon la duree (CGI art. 10).

    Le coefficient est **parametrable** (jamais code en dur) : voir
    `settings.coefficient_degressif_*` (ambiguite A4 du CDC — a confirmer sur
    l'edition 2026 du CGI).
    """
    if duree_annees <= 4:
        return Decimal(str(settings.coefficient_degressif_court))
    if duree_annees <= 6:
        return Decimal(str(settings.coefficient_degressif_moyen))
    return Decimal(str(settings.coefficient_degressif_long))


def fraction_premiere_annee(asset: Asset) -> Decimal:
    """Fraction de la premiere annuite (prorata temporis fiscal, CGI art. 10).

    Convention retenue : **mois entiers a partir du mois de mise en service**
    (mise en service en octobre -> 3/12). La convention « annee pleine »
    (amortissement comptable) s'obtient en positionnant ``prorata_temporis = False``
    sur la fiche.
    """
    if asset.service_date is None:
        return Decimal("1")
    mois_restants = Decimal(13 - asset.service_date.month)
    return mois_restants / Decimal("12")


# ---------------------------------------------------------------------------
# Sanity checks et lecture des fiches
# ---------------------------------------------------------------------------
def get_asset(db: Session, company_id: int, reference: int | str) -> Asset:
    """Fiche d'immobilisation par identifiant ou par code (IM202600001)."""
    stmt = select(Asset).where(Asset.company_id == company_id)
    if isinstance(reference, int) or str(reference).isdigit():
        asset = db.execute(stmt.where(Asset.id == int(reference))).scalar_one_or_none()
    else:
        asset = db.execute(stmt.where(Asset.code == str(reference))).scalar_one_or_none()
    if asset is None:
        raise AccountingError(f"Immobilisation {reference} introuvable")
    return asset


def list_assets(
    db: Session, company_id: int, *, statut: str | None = None, exercice: int | None = None
) -> list[Asset]:
    """Fiches d'immobilisations, filtrees par statut et/ou exercice de mise en service."""
    stmt = select(Asset).where(Asset.company_id == company_id)
    if statut:
        stmt = stmt.where(Asset.statut == statut)
    if exercice is not None:
        stmt = stmt.where(Asset.acquisition_date <= date(exercice, 12, 31))
    return list(db.execute(stmt.order_by(Asset.account_number, Asset.code)).scalars())


def amortissements_cumules(
    asset: Asset, *, jusqua_annee: int | None = None, realisees: bool = True
) -> Decimal:
    """Amortissements cumules d'une fiche (CGNC : le cumul vient des dotations).

    - ``realisees = True`` (defaut) : seules les dotations **comptabilisees** ;
    - ``jusqua_annee`` : limite aux exercices jusqu'a cette annee incluse.
    """
    total = Decimal("0")
    for ligne in asset.depreciation_lines:
        if jusqua_annee is not None and ligne.exercice > jusqua_annee:
            continue
        if realisees and not ligne.is_constatee:
            continue
        total += ligne.annuite
    return money(total)


def valeur_nette_comptable(asset: Asset, *, jusqua_annee: int | None = None) -> Decimal:
    """VNC = valeur d'origine - amortissements cumules (CGNC, titre II chapitre I)."""
    return money(asset.valeur_origine - amortissements_cumules(asset, jusqua_annee=jusqua_annee))


def dotation_constatee(asset: Asset, exercice: int) -> AssetDepreciationLine | None:
    """Ligne de plan **comptabilisee** d'un exercice (None si non constatee)."""
    for ligne in asset.depreciation_lines:
        if ligne.exercice == exercice and ligne.is_constatee:
            return ligne
    return None



# ---------------------------------------------------------------------------
# Fiche d'immobilisation (acquisition)
# ---------------------------------------------------------------------------
def _verifier_fiche(
    *,
    label: str,
    account_number: str,
    acquisition_date: date,
    service_date: date | None,
    valeur_origine: Decimal,
    valeur_residuelle: Decimal,
    duree_annees: int,
    mode: str,
    amortissable: bool,
) -> None:
    """Controles bloquants d'une fiche (CDC § 3.2, P1.2)."""
    if not label or not label.strip():
        raise AccountingError("Le libelle de l'immobilisation est obligatoire")
    if str(account_number)[:1] != "2":
        raise AccountingError(
            f"Compte {account_number} invalide : une immobilisation est portee par un "
            "compte de classe 2 (actif immobilise)."
        )
    if valeur_origine <= 0:
        raise AccountingError("La valeur d'origine doit etre superieure a zero")
    if valeur_residuelle < 0:
        raise AccountingError("La valeur residuelle ne peut pas etre negative")
    if valeur_residuelle >= valeur_origine:
        raise AccountingError(
            "La valeur residuelle doit etre strictement inferieure a la valeur "
            f"d'origine ({valeur_origine})."
        )
    if service_date is not None and service_date < acquisition_date:
        raise AccountingError(
            "La date de mise en service ne peut pas preceder la date d'acquisition "
            f"({acquisition_date})."
        )
    if mode not in ASSET_METHODS:
        raise AccountingError(
            f"Mode d'amortissement invalide : {mode} "
            f"(attendu : {', '.join(ASSET_METHODS)})"
        )
    if amortissable and duree_annees <= 0:
        raise AccountingError(
            "La duree d'amortissement doit etre superieure a zero pour une "
            "immobilisation amortissable."
        )
    if not amortissable and mode == ASSET_METHOD_DEGRESSIF:
        raise AccountingError(
            "Un amortissement degressif exige un compte d'immobilisation amortissable."
        )


def _journal_et_exercice(db: Session, company_id: int, jour: date, journal_code: str):
    """Journal et exercice comptable d'une date donnee (avec controle d'ouverture)."""
    exercice = get_fiscal_year(db, company_id, jour.year)
    ensure_period_open(exercice)
    return get_journal(db, company_id, journal_code), exercice


def _ecriture_acquisition(
    db: Session,
    asset: Asset,
    *,
    compte_contrepartie: str,
    journal_code: str = "OD",
    user_id: int | None = None,
) -> Entry:
    """Ecriture d'acquisition : 2xxx + 34551 (si TVA) / fournisseur ou banque.

    La TVA d'immobilisation est logee au **34551** (CGNC / CGI) et jamais au 34552 :
    elle conditionne l'assiette des regularisations de l'art. 106.
    """
    journal, exercice = _journal_et_exercice(
        db, asset.company_id, asset.acquisition_date, journal_code
    )
    lignes: list[dict] = [
        {
            "account_number": asset.account_number,
            "label": f"Acquisition - {asset.label}",
            "debit": money(asset.valeur_origine),
        }
    ]
    if asset.tva_montant > 0:
        lignes.append(
            {
                "account_number": asset.tva_compte,
                "label": f"TVA recuperable sur immobilisation {asset.code}",
                "debit": money(asset.tva_montant),
            }
        )
    lignes.append(
        {
            "account_number": compte_contrepartie,
            "label": f"Acquisition immobilisation {asset.code}",
            "credit": money(asset.valeur_origine + asset.tva_montant),
        }
    )
    entry = create_entry(
        db,
        company_id=asset.company_id,
        fiscal_year=exercice,
        journal=journal,
        entry_date=asset.acquisition_date,
        label=f"Acquisition immobilisation {asset.code} - {asset.label}",
        reference=asset.code,
        source="asset_acquisition",
        source_id=asset.id,
        created_by=user_id,
        lines=lignes,
    )
    validate_entry(db, entry, user_id=user_id)
    return entry



def creer_immobilisation(
    db: Session,
    *,
    company: Company,
    label: str,
    account_number: str,
    acquisition_date: date,
    valeur_origine: Decimal | str,
    duree_annees: int = 0,
    service_date: date | None = None,
    mode: str = ASSET_METHOD_LINEAIRE,
    coefficient: Decimal | str | None = None,
    valeur_residuelle: Decimal | str = 0,
    prorata_temporis: bool | None = None,
    tva_montant: Decimal | str = 0,
    tva_compte: str | None = None,
    third_party_id: int | None = None,
    invoice_id: int | None = None,
    code: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
    comptabiliser: bool = False,
    compte_contrepartie: str | None = None,
    journal_code: str = "OD",
    compte_amortissement: str | None = None,
    compte_dotation: str | None = None,
) -> Asset:
    """Cree une fiche d'immobilisation (et, si demande, son ecriture d'acquisition).

    ``comptabiliser = True`` produit l'ecriture d'acquisition (2xxx + 34551) : elle
    est inutile lorsque la facture d'achat a deja comptabilise l'immobilisation
    (cas courant : la fiche est alors rattachee a la facture par ``invoice_id``).

    ``compte_amortissement`` / ``compte_dotation`` permettent de forcer les comptes
    derives du PCGE (cas des comptes non derives par la structure du plan).
    """
    info = comptes_immobilisation(db, account_number)
    montant_origine = money(valeur_origine)
    montant_residuel = money(valeur_residuelle)
    coefficient_final = coefficient
    if mode == ASSET_METHOD_DEGRESSIF and coefficient_final is None:
        coefficient_final = coefficient_degressif(int(duree_annees or 0))
    _verifier_fiche(
        label=label,
        account_number=account_number,
        acquisition_date=acquisition_date,
        service_date=service_date,
        valeur_origine=montant_origine,
        valeur_residuelle=montant_residuel,
        duree_annees=int(duree_annees or 0),
        mode=mode,
        amortissable=info["amortissable"],
    )
    if not _compte_existe(db, str(account_number)):
        raise AccountingError(
            f"Compte {account_number} absent du plan comptable : chargez le plan PCGE "
            "(outil tools/charger_plan_comptable.py) avant de creer une fiche."
        )
    asset = Asset(
        company_id=company.id,
        code=code
        or next_document_number(db, company.id, "IMMOBILISATION", acquisition_date.year),
        label=label.strip(),
        account_number=str(account_number),
        third_party_id=third_party_id,
        invoice_id=invoice_id,
        acquisition_date=acquisition_date,
        service_date=service_date,
        valeur_origine=montant_origine,
        valeur_residuelle=montant_residuel,
        duree_annees=int(duree_annees or 0),
        mode=mode,
        coefficient=coefficient_final,
        prorata_temporis=(
            settings.immo_prorata_temporis
            if prorata_temporis is None
            else prorata_temporis
        ),
        tva_montant=money(tva_montant),
        tva_compte=tva_compte or settings.vat_deductible_asset_account,
        notes=notes,
        created_by=user_id,
    )
    db.add(asset)
    db.flush()

    avertissements: list[str] = []
    if info["avertissement"]:
        avertissements.append(info["avertissement"])
    if compte_amortissement or compte_dotation:
        avertissements.append(
            "Comptes d'amortissement/dotation forces manuellement : "
            f"{compte_amortissement or info['amortissement']} / "
            f"{compte_dotation or info['dotation']}."
        )
    evenement = AssetEvent(
        asset_id=asset.id,
        event_type=ASSET_EVENT_ACQUISITION,
        event_date=acquisition_date,
        montant=montant_origine,
        motif=f"Acquisition au compte {asset.account_number}",
    )
    db.add(evenement)
    db.flush()
    if comptabiliser:
        if not compte_contrepartie:
            raise AccountingError(
                "Comptabilisation de l'acquisition demandee sans compte de "
                "contrepartie (fournisseur 4411 ou banque 5141)."
            )
        entry = _ecriture_acquisition(
            db,
            asset,
            compte_contrepartie=compte_contrepartie,
            journal_code=journal_code,
            user_id=user_id,
        )
        evenement.entry_id = entry.id
        db.flush()
    for avertissement in avertissements:
        log_action(
            db,
            action="ASSET_WARNING",
            entity="Asset",
            entity_id=asset.id,
            user_id=user_id,
            company_id=company.id,
            payload={"code": asset.code, "avertissement": avertissement},
        )
    log_action(
        db,
        action="ASSET_CREATED",
        entity="Asset",
        entity_id=asset.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "code": asset.code,
            "compte": asset.account_number,
            "valeur_origine": montant_origine,
            "duree_annees": asset.duree_annees,
            "mode": asset.mode,
        },
    )
    db.flush()
    return asset



# ---------------------------------------------------------------------------
# Plan d'amortissement (lineaire / degressif, prorata temporis)
# ---------------------------------------------------------------------------
def plan_amortissement(asset: Asset, *, jusqua: int | None = None) -> list[dict]:
    """Plan d'amortissement projete : annuite, cumul et VNC par exercice.

    Regles appliquees (CGNC / CGI art. 10) :
    - base amortissable = valeur d'origine - valeur residuelle ;
    - **prorata temporis** la premiere annee (mois entiers depuis le mois de mise en
      service), desactivable sur la fiche (``prorata_temporis = False``) ;
    - **lineaire** : annuite constante = base / duree ;
    - **degressif** : taux = (1 / duree) x coefficient applique a la **VNC**, avec
      **bascule en lineaire** des que le taux lineaire sur la duree restante devient
      plus favorable ;
    - la **derniere annuite est plafonnee** : la VNC ne descend jamais sous la valeur
      residuelle et les arrondis sont absorbes (Σ cumul + VNC = valeur d'origine).

    ``jusqua`` limite le plan a un exercice donne (plan « realise » a date).
    """
    info = comptes_amortissement(asset.account_number)
    if not info["amortissable"] or asset.service_date is None:
        return []
    base = money(asset.valeur_origine - asset.valeur_residuelle)
    if base <= 0 or asset.duree_annees <= 0:
        return []
    fraction = (
        fraction_premiere_annee(asset) if asset.prorata_temporis else Decimal("1")
    )
    coefficient = asset.coefficient or coefficient_degressif(asset.duree_annees)
    lignes: list[dict] = []
    cumul = Decimal("0")
    annee = asset.service_date.year
    index = 0
    # duree + 1 exercices au maximum : la premiere annuite est partielle (prorata).
    while cumul < base and index <= asset.duree_annees:
        if asset.mode == ASSET_METHOD_DEGRESSIF:
            restantes = asset.duree_annees - index
            taux_lineaire = (
                Decimal("1") / Decimal(restantes) if restantes > 0 else Decimal("1")
            )
            taux_degressif = (Decimal("1") / Decimal(asset.duree_annees)) * coefficient
            taux = max(taux_degressif, taux_lineaire)
            annuite = (base - cumul) * taux
        else:
            annuite = base / Decimal(asset.duree_annees)
        if index == 0:
            annuite = annuite * fraction
        annuite = money(annuite)
        restant = money(base - cumul)
        if annuite > restant:
            annuite = restant
        if annuite <= 0:
            break
        cumul = money(cumul + annuite)
        lignes.append(
            {
                "exercice": annee,
                "base": base,
                "annuite": annuite,
                "cumul": cumul,
                "vnc": money(asset.valeur_origine - cumul),
                "constatee": False,
                "entry_id": None,
            }
        )
        annee += 1
        index += 1
    if lignes and lignes[-1]["cumul"] != base:
        ecart = money(base - lignes[-1]["cumul"])
        lignes[-1]["annuite"] = money(lignes[-1]["annuite"] + ecart)
        lignes[-1]["cumul"] = base
        lignes[-1]["vnc"] = money(asset.valeur_origine - base)
    for ligne in lignes:
        realisee = dotation_constatee(asset, ligne["exercice"])
        if realisee is not None:
            ligne["constatee"] = True
            ligne["entry_id"] = realisee.entry_id
            ligne["annuite"] = realisee.annuite
            ligne["cumul"] = realisee.cumul
            ligne["vnc"] = realisee.vnc
    if jusqua is not None:
        return [ligne for ligne in lignes if ligne["exercice"] <= jusqua]
    return lignes


def dotation_exercice(asset: Asset, exercice: int) -> Decimal:
    """Annuite theorique d'un exercice (0 si le bien n'est pas amortissable cette annee)."""
    for ligne in plan_amortissement(asset):
        if ligne["exercice"] == exercice:
            return money(ligne["annuite"])
    return money(0)



# ---------------------------------------------------------------------------
# Dotations aux amortissements (6193x / 283x)
# ---------------------------------------------------------------------------
def comptabiliser_dotation(
    db: Session,
    asset: Asset,
    exercice: int,
    *,
    user_id: int | None = None,
    journal_code: str = "OD",
    date_ecriture: date | None = None,
) -> dict:
    """Constata la dotation d'un exercice : ecriture **6193x / 283x** + ligne de plan.

    Refuse (controles bloquants) : un bien **deja cede ou mis au rebut**, une
    dotation **deja constatee** pour le meme exercice, un exercice **clos ou
    verrouille**, une immobilisation **non amortissable** (financiere, en cours) et
    un bien **deja totalement amorti**.

    Retourne le detail de l'operation (annuite, cumul, VNC, ecriture).
    """
    info = comptes_immobilisation(db, asset.account_number)
    if not info["amortissable"]:
        raise AccountingError(
            f"Immobilisation {asset.code} non amortissable : {info['motif']}"
        )
    if asset.is_disposed:
        raise AccountingError(
            f"Immobilisation {asset.code} deja sortie de l'actif "
            f"({asset.statut} le {asset.disposal_date}) : aucun amortissement possible."
        )
    if asset.service_date is None:
        raise AccountingError(
            f"Immobilisation {asset.code} sans date de mise en service : "
            "l'amortissement demarre a la mise en service (CGI art. 10)."
        )
    if asset.service_date.year > exercice:
        raise AccountingError(
            f"Immobilisation {asset.code} mise en service en "
            f"{asset.service_date.year} : aucune dotation avant cet exercice."
        )
    existante = dotation_constatee(asset, exercice)
    if existante is not None:
        raise AccountingError(
            f"Dotation {exercice} deja constatee pour {asset.code} "
            f"(ecriture n° {existante.entry_id})."
        )
    annuite = dotation_exercice(asset, exercice)
    if annuite <= 0:
        raise AccountingError(
            f"Immobilisation {asset.code} entierement amortie : aucune dotation a "
            f"constater pour {exercice}."
        )
    exercice_comptable = get_fiscal_year(db, asset.company_id, exercice)
    ensure_period_open(exercice_comptable)
    journal = get_journal(db, asset.company_id, journal_code)
    jour = date_ecriture or exercice_comptable.end_date
    entry = create_entry(
        db,
        company_id=asset.company_id,
        fiscal_year=exercice_comptable,
        journal=journal,
        entry_date=jour,
        label=f"Dotation amortissement {exercice} - {asset.label}",
        reference=asset.code,
        source="asset_dotation",
        source_id=asset.id,
        created_by=user_id,
        lines=[
            {
                "account_number": info["dotation"],
                "label": f"Dotation {exercice} - {asset.label}",
                "debit": annuite,
            },
            {
                "account_number": info["amortissement"],
                "label": f"Amortissement {exercice} - {asset.label}",
                "credit": annuite,
            },
        ],
    )
    validate_entry(db, entry, user_id=user_id)
    cumul = money(amortissements_cumules(asset, realisees=True) + annuite)
    ligne = AssetDepreciationLine(
        exercice=exercice,
        base=money(asset.valeur_origine - asset.valeur_residuelle),
        annuite=annuite,
        cumul=cumul,
        vnc=money(asset.valeur_origine - cumul),
        entry_id=entry.id,
    )
    asset.depreciation_lines.append(ligne)
    asset.events.append(
        AssetEvent(
            event_type=ASSET_EVENT_DOTATION,
            event_date=jour,
            montant=annuite,
            entry_id=entry.id,
            motif=f"Dotation {exercice} ({info['dotation']} / {info['amortissement']})",
        )
    )
    log_action(
        db,
        action="ASSET_DEPRECIATION_POSTED",
        entity="Asset",
        entity_id=asset.id,
        user_id=user_id,
        company_id=asset.company_id,
        payload={
            "code": asset.code,
            "exercice": exercice,
            "annuite": annuite,
            "cumul": cumul,
            "entry_number": entry.entry_number,
        },
    )
    db.flush()
    return {
        "asset": asset,
        "exercice": exercice,
        "annuite": annuite,
        "cumul": cumul,
        "vnc": money(asset.valeur_origine - cumul),
        "compte_dotation": info["dotation"],
        "compte_amortissement": info["amortissement"],
        "entry": entry,
        "entry_number": entry.entry_number,
    }


def comptabiliser_dotations(
    db: Session,
    company: Company,
    exercice: int,
    *,
    user_id: int | None = None,
    journal_code: str = "OD",
) -> list[dict]:
    """Constata les dotations de **toutes** les immobilisations en service.

    Chaque fiche est traitee independamment : une erreur (bien cede, dotation deja
    constatee...) n'interrompt pas le traitement des autres fiches et est retournee
    dans le resultat (``erreur``), ce qui permet un ecran de traitement en masse.
    """
    resultats: list[dict] = []
    for asset in list_assets(db, company.id):
        if asset.statut != ASSET_STATUS_EN_SERVICE or asset.service_date is None:
            continue
        try:
            # SAVEPOINT par fiche : une erreur est isolee, les autres fiches passent.
            with db.begin_nested():
                operation = comptabiliser_dotation(
                    db, asset, exercice, user_id=user_id, journal_code=journal_code
                )
            resultats.append({**operation, "erreur": None})
        except AccountingError as exc:
            resultats.append({"asset": asset, "exercice": exercice, "erreur": str(exc)})
    return resultats



# ---------------------------------------------------------------------------
# Regularisation de la TVA (CGI art. 106)
# ---------------------------------------------------------------------------
def regularisation_tva_art106(asset: Asset, date_sortie: date) -> dict:
    """Regularisation de la TVA d'une immobilisation sortie de l'actif (CGI art. 106).

    Principe : lorsqu'une immobilisation ayant ouvert droit a deduction est cedee ou
    mise au rebut **avant la fin de la periode de regularisation**, la TVA deduite est
    regularisee **par fractions egales** pour les annees restantes ::

        fraction annuelle   = TVA deduite / duree de regularisation
        montant a reverser  = TVA deduite x annees restantes / duree

    La duree est **parametrable** (``settings.regularisation_tva_annees_meubles`` = 5,
    ``..._immeubles`` = 10) et **reste a confirmer** : ambiguite **A5** du CDC.
    """
    duree = (
        settings.regularisation_tva_annees_immeubles
        if est_immeuble(asset.account_number)
        else settings.regularisation_tva_annees_meubles
    )
    debut = asset.service_date or asset.acquisition_date
    resultat = {
        "applicable": False,
        "annees_regularisation": duree,
        "annees_utilisees": 0,
        "annees_restantes": 0,
        "montant": money(0),
        "compte_charge": settings.compte_regularisation_tva,
        "compte_tva": asset.tva_compte,
        "motif": None,
        "avertissement": (
            "Duree de regularisation (5 ans meubles / 10 ans immeubles) et base a "
            "confirmer aupres de l'expert-comptable (CDC, ambiguite A5)."
        ),
    }
    if asset.tva_montant <= 0:
        resultat["motif"] = "Aucune TVA deductible rattachee a la fiche."
        return resultat
    annees_utilisees = max(0, date_sortie.year - debut.year)
    if annees_utilisees >= duree:
        resultat["annees_utilisees"] = duree
        resultat["motif"] = (
            f"Periode de regularisation de {duree} ans achevee : aucune TVA a reverser."
        )
        return resultat
    restantes = duree - annees_utilisees
    resultat.update(
        {
            "applicable": True,
            "annees_utilisees": annees_utilisees,
            "annees_restantes": restantes,
            "montant": money(asset.tva_montant * Decimal(restantes) / Decimal(duree)),
        }
    )
    return resultat



# ---------------------------------------------------------------------------
# Cession et mise au rebut (sortie d'actif)
# ---------------------------------------------------------------------------
def _sortir_actif(
    db: Session,
    asset: Asset,
    *,
    type_sortie: str,
    date_sortie: date,
    prix: Decimal | str = 0,
    tva_taux: Decimal | str = 0,
    compte_encaissement: str | None = None,
    regulariser_tva: bool = True,
    motif: str | None = None,
    user_id: int | None = None,
    journal_code: str = "OD",
) -> dict:
    """Ecriture complete de sortie d'actif (cession ou mise au rebut).

    Ecriture produite (CGNC) ::

        Debit  3481/3421/5141 (creance ou encaissement)  prix TTC     (cession)
        Debit  28xx (amortissements cumules)             cumul
        Debit  6513/6512 (VNA)                           valeur d'origine - cumul
        Debit  compte de regularisation TVA              regularisation art. 106
        Credit 2xxx (valeur d'origine)
        Credit 7513/7512 (produit de cession HT)                       (cession)
        Credit 4455 (TVA sur cession, le cas echeant)                  (cession)
        Credit 34551 (regularisation art. 106)
    """
    if asset.is_disposed:
        raise AccountingError(
            f"Immobilisation {asset.code} deja sortie de l'actif le "
            f"{asset.disposal_date} ({asset.statut})."
        )
    if date_sortie < asset.acquisition_date:
        raise AccountingError(
            f"La date de sortie ({date_sortie}) ne peut pas preceder la date "
            f"d'acquisition ({asset.acquisition_date})."
        )
    montant_prix = money(prix)
    if type_sortie == ASSET_EVENT_CESSION and montant_prix <= 0 and not motif:
        raise AccountingError(
            "Une cession exige un prix de cession (utiliser la mise au rebut pour une "
            "sortie sans contrepartie)."
        )
    if type_sortie == ASSET_EVENT_REBUT and not motif:
        raise AccountingError(
            "La mise au rebut exige un motif (justificatif de sortie de l'actif)."
        )
    info = comptes_immobilisation(db, asset.account_number)
    compte_vna_actif = compte_vna(asset.account_number)
    if not _compte_existe(db, compte_vna_actif):
        raise AccountingError(
            f"Compte de VNA {compte_vna_actif} absent du plan comptable."
        )
    exercice = get_fiscal_year(db, asset.company_id, date_sortie.year)
    ensure_period_open(exercice)
    journal = get_journal(db, asset.company_id, journal_code)

    cumul = amortissements_cumules(asset, realisees=True)
    vnc = money(asset.valeur_origine - cumul)
    taux = Decimal(str(tva_taux or 0))
    if taux > 0:
        produit_ht = money((montant_prix * Decimal("100")) / (Decimal("100") + taux))
        tva_cession = money(montant_prix - produit_ht)
    else:
        produit_ht = money(montant_prix)
        tva_cession = money(0)
    regularisation = (
        regularisation_tva_art106(asset, date_sortie)
        if regulariser_tva
        else {
            "applicable": False,
            "montant": money(0),
            "annees_restantes": 0,
            "annees_regularisation": 0,
            "motif": "Regularisation non demandee.",
        }
    )
    montant_regularisation = (
        regularisation["montant"] if regularisation["applicable"] else money(0)
    )

    libelle_sortie = (
        f"Cession immobilisation {asset.code} - {asset.label}"
        if type_sortie == ASSET_EVENT_CESSION
        else f"Mise au rebut {asset.code} - {asset.label}"
    )
    lignes: list[dict] = []
    if montant_prix > 0:
        lignes.append(
            {
                "account_number": compte_encaissement or settings.compte_cession_a_recevoir,
                "label": libelle_sortie,
                "debit": montant_prix,
            }
        )
    if cumul > 0:
        lignes.append(
            {
                "account_number": info["amortissement"],
                "label": f"Reprise des amortissements {asset.code}",
                "debit": money(cumul),
            }
        )
    if vnc > 0:
        lignes.append(
            {
                "account_number": compte_vna_actif,
                "label": f"VNA {asset.code} - {asset.label}",
                "debit": vnc,
            }
        )
    if montant_regularisation > 0:
        lignes.append(
            {
                "account_number": regularisation["compte_charge"],
                "label": (
                    f"Regularisation TVA art. 106 "
                    f"({regularisation['annees_restantes']} an(s)) - {asset.code}"
                ),
                "debit": montant_regularisation,
            }
        )
    lignes.append(
        {
            "account_number": asset.account_number,
            "label": f"Sortie - {asset.label}",
            "credit": money(asset.valeur_origine),
        }
    )
    if produit_ht > 0:
        lignes.append(
            {
                "account_number": compte_produit_cession(asset.account_number),
                "label": f"Produit de cession {asset.code}",
                "credit": produit_ht,
            }
        )
    if tva_cession > 0:
        lignes.append(
            {
                "account_number": settings.vat_collected_account,
                "label": f"TVA sur cession {asset.code} ({taux.normalize()} %)",
                "credit": tva_cession,
            }
        )
    if montant_regularisation > 0:
        lignes.append(
            {
                "account_number": asset.tva_compte,
                "label": f"Regularisation TVA art. 106 - {asset.code}",
                "credit": montant_regularisation,
            }
        )


    entry = create_entry(
        db,
        company_id=asset.company_id,
        fiscal_year=exercice,
        journal=journal,
        entry_date=date_sortie,
        label=libelle_sortie,
        reference=asset.code,
        source=f"asset_{type_sortie}",
        source_id=asset.id,
        created_by=user_id,
        lines=lignes,
    )
    validate_entry(db, entry, user_id=user_id)
    asset.statut = (
        ASSET_STATUS_CELE if type_sortie == ASSET_EVENT_CESSION else ASSET_STATUS_REBUTE
    )
    asset.disposal_date = date_sortie
    asset.disposal_price = montant_prix if type_sortie == ASSET_EVENT_CESSION else None
    asset.disposal_reason = motif
    asset.events.append(
        AssetEvent(
            event_type=type_sortie,
            event_date=date_sortie,
            montant=montant_prix,
            entry_id=entry.id,
            motif=motif,
        )
    )
    if montant_regularisation > 0:
        asset.events.append(
            AssetEvent(
                event_type=ASSET_EVENT_REGULARISATION,
                event_date=date_sortie,
                montant=montant_regularisation,
                entry_id=entry.id,
                motif=(
                    f"Regularisation TVA art. 106 : "
                    f"{regularisation['annees_restantes']}/"
                    f"{regularisation['annees_regularisation']} an(s)"
                ),
            )
        )
    log_action(
        db,
        action="ASSET_DISPOSED",
        entity="Asset",
        entity_id=asset.id,
        user_id=user_id,
        company_id=asset.company_id,
        payload={
            "code": asset.code,
            "type": type_sortie,
            "date": date_sortie,
            "vnc": vnc,
            "prix": montant_prix,
            "resultat": money(produit_ht - vnc),
            "regularisation_tva": montant_regularisation,
            "entry_number": entry.entry_number,
        },
    )
    db.flush()
    return {
        "asset": asset,
        "type": type_sortie,
        "date": date_sortie,
        "valeur_origine": money(asset.valeur_origine),
        "cumul": cumul,
        "vnc": vnc,
        "prix": montant_prix,
        "produit_ht": produit_ht,
        "tva_cession": tva_cession,
        "resultat_cession": money(produit_ht - vnc),
        "regularisation": regularisation,
        "comptes": {
            "vna": compte_vna_actif,
            "produit": compte_produit_cession(asset.account_number),
            "amortissement": info["amortissement"],
        },
        "entry": entry,
        "entry_number": entry.entry_number,
    }


def ceder_immobilisation(
    db: Session,
    asset: Asset,
    *,
    date_cession: date,
    prix: Decimal | str,
    tva_taux: Decimal | str = 0,
    compte_encaissement: str | None = None,
    regulariser_tva: bool = True,
    motif: str | None = None,
    user_id: int | None = None,
    journal_code: str = "OD",
) -> dict:
    """Cede une immobilisation : produit, sortie d'actif et regularisation art. 106."""
    return _sortir_actif(
        db,
        asset,
        type_sortie=ASSET_EVENT_CESSION,
        date_sortie=date_cession,
        prix=prix,
        tva_taux=tva_taux,
        compte_encaissement=compte_encaissement,
        regulariser_tva=regulariser_tva,
        motif=motif,
        user_id=user_id,
        journal_code=journal_code,
    )


def mettre_au_rebut(
    db: Session,
    asset: Asset,
    *,
    date_rebut: date,
    motif: str,
    regulariser_tva: bool = True,
    user_id: int | None = None,
    journal_code: str = "OD",
) -> dict:
    """Met une immobilisation au rebut (sortie d'actif sans contrepartie)."""
    return _sortir_actif(
        db,
        asset,
        type_sortie=ASSET_EVENT_REBUT,
        date_sortie=date_rebut,
        prix=0,
        regulariser_tva=regulariser_tva,
        motif=motif,
        user_id=user_id,
        journal_code=journal_code,
    )



# ---------------------------------------------------------------------------
# Etats du module (immobilisations, amortissements, cessions)
# ---------------------------------------------------------------------------
def soldes_immobilisations_comptables(
    db: Session, company_id: int, exercice: int
) -> dict:
    """Soldes comptables des comptes 2xxx et 28x a la cloture de l'exercice.

    S'appuie sur `closing.soldes_a_la_date`, qui applique la **regle anti double
    comptage** : depuis la correction de l'ecart 9 (ecritures d'a-nouveaux generees
    a la cloture), un cumul depuis l'origine compterait deux fois les reports.
    """
    from app.services.closing import soldes_a_la_date

    soldes = soldes_a_la_date(db, company_id, date(exercice, 12, 31))
    brut = money(
        sum(
            (
                valeur
                for compte, valeur in soldes.items()
                if compte[:1] == "2"
                and not compte.startswith("28")
                and not compte.startswith("29")
            ),
            Decimal("0"),
        )
    )
    amortissements = money(
        -sum(
            (valeur for compte, valeur in soldes.items() if compte.startswith("28")),
            Decimal("0"),
        )
    )
    return {
        "brut": brut,
        "amortissements": amortissements,
        "vnc": money(brut - amortissements),
        "detail": [
            {"account_number": compte, "solde": valeur}
            for compte, valeur in sorted(soldes.items())
            if compte[:1] == "2" and not compte.startswith("29")
        ],
    }


def etat_immobilisations(db: Session, company_id: int, exercice: int) -> dict:
    """Etat des immobilisations : **brut / amortissements / VNC par poste** (CGNC).

    Le tableau vient des **fiches** (hors biens sortis) et il est **reconcilie** avec
    la comptabilite : l'ecart eventuel est affiche — aucun montant n'est presente
    comme juste s'il diverge du grand livre.
    """
    fiches = list_assets(db, company_id, exercice=exercice)
    postes: dict[str, dict] = {}
    for asset in fiches:
        if asset.disposal_date is not None and asset.disposal_date.year <= exercice:
            continue
        cle = racine4(asset.account_number)
        libelle = db.execute(
            select(Account.label).where(Account.number == cle)
        ).scalar_one_or_none()
        poste = postes.setdefault(
            cle,
            {
                "compte": cle,
                "libelle": libelle or "Compte d'immobilisation",
                "brut": Decimal("0"),
                "amortissements": Decimal("0"),
                "vnc": Decimal("0"),
                "biens": [],
            },
        )
        cumul = amortissements_cumules(asset, jusqua_annee=exercice, realisees=True)
        poste["brut"] = money(poste["brut"] + asset.valeur_origine)
        poste["amortissements"] = money(poste["amortissements"] + cumul)
        poste["vnc"] = money(poste["brut"] - poste["amortissements"])
        poste["biens"].append(
            {
                "code": asset.code,
                "label": asset.label,
                "date_acquisition": asset.acquisition_date,
                "valeur_origine": money(asset.valeur_origine),
                "amortissements": cumul,
                "vnc": money(asset.valeur_origine - cumul),
            }
        )
    total_brut = money(sum((p["brut"] for p in postes.values()), Decimal("0")))
    total_amortissements = money(
        sum((p["amortissements"] for p in postes.values()), Decimal("0"))
    )
    comptable = soldes_immobilisations_comptables(db, company_id, exercice)
    return {
        "exercice": exercice,
        "postes": sorted(postes.values(), key=lambda p: p["compte"]),
        "total_brut": total_brut,
        "total_amortissements": total_amortissements,
        "total_vnc": money(total_brut - total_amortissements),
        "comptabilite": comptable,
        "ecarts": {
            "brut": money(total_brut - comptable["brut"]),
            "amortissements": money(total_amortissements - comptable["amortissements"]),
        },
    }



def tableau_cessions(db: Session, company_id: int, exercice: int) -> dict:
    """Tableau des cessions et mises au rebut de l'exercice (plus/moins-value)."""
    lignes: list[dict] = []
    for asset in list_assets(db, company_id):
        if asset.disposal_date is None or asset.disposal_date.year != exercice:
            continue
        cumul = amortissements_cumules(asset, jusqua_annee=exercice, realisees=True)
        vnc = money(asset.valeur_origine - cumul)
        prix = money(asset.disposal_price or 0)
        regularisation = Decimal("0")
        for evenement in asset.events:
            if (
                evenement.event_type == ASSET_EVENT_REGULARISATION
                and evenement.event_date.year == exercice
            ):
                regularisation = money(regularisation + evenement.montant)
        lignes.append(
            {
                "code": asset.code,
                "label": asset.label,
                "compte": asset.account_number,
                "type": asset.statut,
                "date_sortie": asset.disposal_date,
                "valeur_origine": money(asset.valeur_origine),
                "amortissements": cumul,
                "vnc": vnc,
                "prix": prix,
                "resultat": money(prix - vnc),
                "regularisation_tva": regularisation,
                "motif": asset.disposal_reason,
            }
        )
    lignes.sort(key=lambda ligne: (ligne["date_sortie"], ligne["code"]))
    return {
        "exercice": exercice,
        "lignes": lignes,
        "total_valeur_origine": money(
            sum((l["valeur_origine"] for l in lignes), Decimal("0"))
        ),
        "total_vnc": money(sum((l["vnc"] for l in lignes), Decimal("0"))),
        "total_prix": money(sum((l["prix"] for l in lignes), Decimal("0"))),
        "total_resultat": money(sum((l["resultat"] for l in lignes), Decimal("0"))),
        "total_regularisation": money(
            sum((l["regularisation_tva"] for l in lignes), Decimal("0"))
        ),
    }


def amortissements_deductibles(db: Session, company_id: int, exercice: int) -> dict:
    """Etat des amortissements de l'exercice (fiscalement deductible, CGI art. 10).

    La dotation affichee est celle **comptabilisee** lorsque la dotation a ete
    constatee, sinon la dotation **theorique** du plan (colonne « constatee »).
    """
    lignes: list[dict] = []
    for asset in list_assets(db, company_id, exercice=exercice):
        if asset.disposal_date is not None and asset.disposal_date.year < exercice:
            continue
        plan = plan_amortissement(asset)
        dotation = next((l for l in plan if l["exercice"] == exercice), None)
        if dotation is None:
            continue
        cumul = amortissements_cumules(asset, jusqua_annee=exercice, realisees=True)
        lignes.append(
            {
                "code": asset.code,
                "label": asset.label,
                "compte": asset.account_number,
                "mode": asset.mode,
                "duree_annees": asset.duree_annees,
                "base": dotation["base"],
                "dotation": dotation["annuite"],
                "constatee": dotation["constatee"],
                "cumul": cumul,
                "vnc": money(asset.valeur_origine - cumul),
                "valeur_origine": money(asset.valeur_origine),
            }
        )
    return {
        "exercice": exercice,
        "lignes": lignes,
        "total_dotation": money(sum((l["dotation"] for l in lignes), Decimal("0"))),
        "total_cumul": money(sum((l["cumul"] for l in lignes), Decimal("0"))),
        "total_vnc": money(sum((l["vnc"] for l in lignes), Decimal("0"))),
        "total_valeur_origine": money(
            sum((l["valeur_origine"] for l in lignes), Decimal("0"))
        ),
        "nb_non_constatees": len([l for l in lignes if not l["constatee"]]),
    }



# ---------------------------------------------------------------------------
# Controles de coherence (l'application doit « parler »)
# ---------------------------------------------------------------------------
def controles_immobilisations(
    db: Session, company_id: int, exercice: int | None = None
) -> list[dict]:
    """Controles de coherence du module P1.2, affiches dans l'interface et l'API.

    Trois natures de constats :

    1. **controles bloquants** (donnee incomplete empechant une operation) :
       immobilisation amortissable sans duree ou sans mise en service, sortie sans
       motif, cession sans prix ;
    2. **controles de conformite TVA** : TVA d'immobilisation logee au **34552**
       alors que la piece porte un compte de classe 2 — elle doit etre au **34551**
       (elle conditionne l'assiette des regularisations art. 106) ;
    3. **controles de coherence** : ecart entre les fiches et la comptabilite,
       dotation de l'exercice de cession non constatee (VNC survaluee).
    """
    controles: list[dict] = []

    def ajouter(
        niveau: str, code: str, message: str, asset: Asset | None = None
    ) -> None:
        controles.append(
            {
                "niveau": niveau,
                "code": code,
                "message": message,
                "asset_code": asset.code if asset is not None else None,
            }
        )

    for asset in list_assets(db, company_id):
        info = comptes_immobilisation(db, asset.account_number)
        if info["avertissement"]:
            ajouter(
                "avertissement",
                "COMPTES_DERIVES",
                f"{asset.code} : {info['avertissement']}",
                asset,
            )
        if asset.statut == ASSET_STATUS_EN_SERVICE and info["amortissable"]:
            if asset.service_date is None:
                ajouter(
                    "bloquant",
                    "SANS_MISE_EN_SERVICE",
                    f"Immobilisation {asset.code} ({asset.label}) : aucune date de "
                    "mise en service, donc aucune dotation possible (CGI art. 10).",
                    asset,
                )
            if asset.duree_annees <= 0:
                ajouter(
                    "bloquant",
                    "DUREE_NULLE",
                    f"Immobilisation {asset.code} : duree d'amortissement nulle alors "
                    "que le compte est amortissable.",
                    asset,
                )
        if (
            asset.duree_annees > 0
            and not info["amortissable"]
            and asset.statut == ASSET_STATUS_EN_SERVICE
        ):
            ajouter(
                "avertissement",
                "DUREE_SUR_NON_AMORTISSABLE",
                f"Immobilisation {asset.code} : une duree d'amortissement est saisie "
                f"alors que le bien n'est pas amortissable. {info['motif']}",
                asset,
            )
        if asset.statut == ASSET_STATUS_REBUTE and not asset.disposal_reason:
            ajouter(
                "bloquant",
                "REBUT_SANS_MOTIF",
                f"Immobilisation {asset.code} : mise au rebut sans motif "
                "(justificatif de sortie obligatoire).",
                asset,
            )
        if (
            asset.statut == ASSET_STATUS_CELE
            and not asset.disposal_reason
            and (asset.disposal_price is None or asset.disposal_price <= 0)
        ):
            ajouter(
                "bloquant",
                "CESSION_SANS_PRIX",
                f"Immobilisation {asset.code} : cession sans prix ni motif (utiliser "
                "la mise au rebut pour une sortie sans contrepartie).",
                asset,
            )
        if (
            exercice is not None
            and asset.disposal_date is not None
            and asset.disposal_date.year == exercice
            and info["amortissable"]
            and dotation_constatee(asset, exercice) is None
        ):
            ajouter(
                "avertissement",
                "DOTATION_ANNEE_CESSION",
                f"Immobilisation {asset.code} cedee en {exercice} sans dotation "
                f"constatee pour {exercice} : la VNC de cession serait survaluee.",
                asset,
            )

    controles.extend(_controles_tva_immobilisation(db, company_id))

    if exercice is not None:
        etat = etat_immobilisations(db, company_id, exercice)
        for cle, libelle in (
            ("brut", "valeurs brutes"),
            ("amortissements", "amortissements"),
        ):
            ecart = etat["ecarts"][cle]
            if ecart != 0:
                controles.append(
                    {
                        "niveau": "avertissement",
                        "code": "ECART_FICHES_COMPTABILITE",
                        "message": (
                            f"Ecart de {ecart} DH sur les {libelle} entre les fiches "
                            f"d'immobilisation et la comptabilite ({exercice}) : "
                            "verifier les immobilisations acquises ou cedees hors "
                            "fiches."
                        ),
                        "asset_code": None,
                    }
                )
    return controles



def _controles_tva_immobilisation(db: Session, company_id: int) -> list[dict]:
    """TVA d'immobilisation logee au 34552 alors que la piece porte un compte 2xxx.

    La TVA sur immobilisation doit etre au **34551** (CGNC / CGI art. 106) : une TVA
    d'immobilisation dans le 34552 fausse la presentation du bilan et l'assiette des
    regularisations.
    """
    controles: list[dict] = []
    lignes = db.execute(
        select(Entry.entry_number, Entry.source, Entry.source_id, EntryLine.debit)
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .where(
            Entry.company_id == company_id,
            EntryLine.account_number == settings.vat_deductible_charge_account,
        )
    ).all()
    for numero, source, source_id, montant in lignes:
        if source != "invoice" or source_id is None:
            continue
        facture = db.get(Invoice, source_id)
        if facture is None:
            continue
        comptes_immo = [
            ligne.account_number
            for ligne in db.execute(
                select(InvoiceLine).where(InvoiceLine.invoice_id == facture.id)
            ).scalars()
            if ligne.account_number and str(ligne.account_number).startswith("2")
        ]
        if comptes_immo:
            controles.append(
                {
                    "niveau": "bloquant",
                    "code": "TVA_34552_SUR_IMMOBILISATION",
                    "message": (
                        f"Ecriture {numero} : TVA de {money(montant)} DH logee au "
                        f"{settings.vat_deductible_charge_account} alors que la facture "
                        f"{facture.number or facture.id} porte l'immobilisation "
                        f"{', '.join(comptes_immo)} : elle doit etre au "
                        f"{settings.vat_deductible_asset_account} (CGNC / CGI art. 106)."
                    ),
                    "asset_code": None,
                }
            )
    return controles

