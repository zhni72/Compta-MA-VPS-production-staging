"""Resultat fiscal, IS / cotisation minimale et controles (J7 — P2.1, etape 1).

Premier etage du module **IS & liasse fiscale EDI** : determiner le **resultat
fiscal** a partir du resultat comptable (reintegrations et deductions), comparer
l'**IS** et la **cotisation minimale**, gerer le **report deficitaire** et les
**acomptes**, puis controler la coherence avant toute production de liasse.

References normatives
---------------------
- **CGI art. 11** : charges non deductibles (amendes et penalites, provisions non
  dedu ctibles, etc.) — a **reintegrer** au resultat comptable.
- **CGI art. 114** : **report deficitaire** sur les exercices suivants (la duree
  et les conditions doivent etre confirmees : voir CDC § 9.14, ambiguite A21).
- **CGI art. 144** : **cotisation minimale** due lorsque son montant est
  **superieur** a l'IS ; les **acomptes** verses (compte **3453**) et les credits
  d'impot viennent en deduction du solde.
- **CGNC** : charges d'impot sur les resultats (`6701` impots sur les benefices,
  `6705` imposition minimale annuelle, `6708` rappels et degrevements) —
  **l'impot sur les resultats n'est pas deductible du resultat fiscal** : il est
  donc exclu du resultat « avant impot ».
- **P1.6** : l'IS et la liasse ne se deposent que sur un **exercice clos**.

Regle de verite
---------------
Le resultat comptable vient de la balance (aucune saisie) ; les reintegrations
**detectees automatiquement** sont des **propositions** (comptes non deductibles
par nature) et toute reintegration complementaire est **saisie avec son motif** :
le calcul est integralement reproductible.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rates_ma import (
    compute_cotisation_minimale,
    compute_is,
    is_rates,
    money,
)
from app.models import Company, FiscalYear
from app.services.accounting import AccountingError, get_fiscal_year
from app.services.reporting import income_statement, movements, year_bounds

# ---------------------------------------------------------------------------
# Comptes CGNC utilises
# ---------------------------------------------------------------------------
RACINE_IMPOTS_RESULTATS = "67"  # 6701 / 6705 / 6708 : impot sur les resultats
COMPTE_ACOMPTES_IS = "3453"  # Acomptes sur impots sur les resultats
RACINE_CHIFFRE_AFFAIRES = "71"  # ventes de marchandises et produits
COMPTE_TVA_COLLECTEE = "4455"  # TVA collectee (figure comptable CA TTC)
CATEGORIE_IS_SOCIETE = "standard"  # societes : taux de droit commun (CGI art. 19)

# Assiette de la cotisation minimale (CGI 2025 art. 144-I-B, rappel art. 9-I) :
# produits **hors TVA** — chiffre d'affaires (71x), autres produits
# d'exploitation (75x), produits financiers (76x) et subventions/dons (74x/77x).
# Le compte de TVA collectee (4455) n'entre **jamais** dans la base : la loi
# exclut explicitement la TVA (CM-1 V7B).
RACINES_ASSIETTE_CM = ("71", "74", "75", "76", "77")

# ---------------------------------------------------------------------------
# Catalogue des reintegrations / deductions (parametrable)
# ---------------------------------------------------------------------------
# Chaque rubrique porte sa **reference CGI** ; les `comptes` listes permettent la
# **detection automatique** depuis la balance (le comptable reste maitre du
# montant a reintegrer). Les `codeEdi` de la liasse seront rattaches a l'etape 2
# (depuis les enumerations des XSD officiels).
CATALOGUE_REINTEGRATIONS: tuple[dict, ...] = (
    {
        "code": "AMENDES_PENALITES",
        "libelle": "Amendes, pénalités et majorations non déductibles",
        "reference": "CGI art. 11",
        "comptes": ("6581", "6582", "6583", "65831", "65833"),
    },
    {
        "code": "PROVISIONS_NON_DEDUCTIBLES",
        "libelle": "Provisions non déductibles (risques, charges, dépréciations)",
        "reference": "CGI art. 11",
        "comptes": ("6195", "6196", "6197", "1515", "1555"),
    },
    {
        "code": "CHARGES_NON_JUSTIFIEES",
        "libelle": "Charges non justifiées ou sans contrepartie",
        "reference": "CGI art. 11",
        "comptes": (),
    },
    {
        "code": "DEDUCTIONS_DISPROPORTIONNEES",
        "libelle": "Rémunérations et avantages excessifs (disproportionnés)",
        "reference": "CGI art. 11",
        "comptes": (),
    },
)
CATALOGUE_DEDUCTIONS: tuple[dict, ...] = (
    {
        "code": "PRODUITS_EXONERES",
        "libelle": "Produits exonérés ou bénéficiant d'un régime particulier",
        "reference": "CGI art. 6 à 8",
        "comptes": (),
    },
    {
        "code": "REPRISES_PROVISIONS_TAXABLES",
        "libelle": "Reprises de provisions antérieurement réintégrées",
        "reference": "CGI art. 11",
        "comptes": (),
    },
    {
        "code": "DEDUCTIONS_FISCALES_SPECIALES",
        "libelle": "Déductions fiscales spéciales (investissements, etc.)",
        "reference": "CGI (texte au cas par cas)",
        "comptes": (),
    },
)
CATALOGUE_REINTEGRATIONS_PAR_CODE = {
    rubrique["code"]: rubrique for rubrique in CATALOGUE_REINTEGRATIONS
}
CATALOGUE_DEDUCTIONS_PAR_CODE = {
    rubrique["code"]: rubrique for rubrique in CATALOGUE_DEDUCTIONS
}
# Duree du report deficitaire : **non codee en dur** (CGI art. 114, ambiguite A21).
DUREE_REPORT_DEFICITAIRE = None


class FiscalError(AccountingError):
    """Erreur du calcul fiscal (exercice absent, montant invalide, controle)."""


# ---------------------------------------------------------------------------
# Resultat comptable et charges non deductibles detectees
# ---------------------------------------------------------------------------
def resultat_avant_impot(db: Session, company_id: int, annee: int) -> dict:
    """Resultat comptable de l'exercice, **hors impot sur les resultats**.

    Le compte de produits et charges (CPC) inclut les comptes `67x` (impots sur
    les resultats). Pour le calcul fiscal, on retablit le resultat **avant
    impot** : l'IS et la cotisation minimale **ne sont pas deductibles**
    (CGI art. 11) — les exclure evite une double prise en compte.
    """
    date_from, date_to = year_bounds(annee)
    cpc = income_statement(db, company_id, date_from, date_to)
    impots = money(
        sum(
            (
                ligne["solde"]
                for ligne in movements(db, company_id, date_from, date_to)
                if ligne["account_number"][:2] == RACINE_IMPOTS_RESULTATS
            ),
            Decimal("0"),
        )
    )
    return {
        "annee": annee,
        "date_from": date_from,
        "date_to": date_to,
        "total_produits": cpc["total_produits"],
        "total_charges": cpc["total_charges"],
        "resultat_comptable": cpc["resultat"],
        "impots_resultats_comptabilises": impots,
        "resultat_avant_impot": money(cpc["resultat"] + impots),
        "nature_resultat": cpc["nature_resultat"],
    }


def charges_non_deductibles(db: Session, company_id: int, annee: int) -> list[dict]:
    """**Propositions** de reintegration detectees dans la balance (CGI art. 11).

    Chaque ligne correspond a une rubrique du catalogue : le montant propose est
    la somme des **comptes non deductibles par nature** (amendes et penalites,
    provisions non deductibles...). Le comptable reste maitre du montant retenu.
    """
    date_from, date_to = year_bounds(annee)
    soldes = {
        ligne["account_number"]: ligne["solde"]
        for ligne in movements(db, company_id, date_from, date_to)
    }
    propositions: list[dict] = []
    for rubrique in CATALOGUE_REINTEGRATIONS:
        detail = [
            {"compte": compte, "montant": money(soldes.get(compte, Decimal("0")))}
            for compte in rubrique["comptes"]
            if soldes.get(compte)
        ]
        montant = money(sum((ligne["montant"] for ligne in detail), Decimal("0")))
        if montant:
            propositions.append(
                {
                    "code": rubrique["code"],
                    "libelle": rubrique["libelle"],
                    "reference": rubrique["reference"],
                    "montant": montant,
                    "detail": detail,
                }
            )
    return propositions


def chiffre_affaires(db: Session, company_id: int, annee: int) -> dict:
    """Chiffre d'affaires HT, TVA collectee et **CA TTC** (figure comptable).

    Grandeur **informationnelle uniquement** : depuis la correction V7B, la
    cotisation minimale n'est plus assise sur le CA TTC mais sur les produits
    **hors TVA** (CGI art. 144-I-B) — voir `assiette_cotisation_minimale`.
    Le CA HT vient des comptes `71x` (soldes crediteurs inverses) et la TVA
    collectee du compte `4455`.
    """
    date_from, date_to = year_bounds(annee)
    ca_ht = Decimal("0")
    tva = Decimal("0")
    for ligne in movements(db, company_id, date_from, date_to):
        numero = ligne["account_number"]
        if numero[:2] == RACINE_CHIFFRE_AFFAIRES:
            ca_ht += -ligne["solde"]  # produit : solde crediteur
        elif numero == COMPTE_TVA_COLLECTEE:
            tva += -ligne["solde"]
    ca_ht = money(ca_ht)
    tva = money(tva)
    return {
        "annee": annee,
        "chiffre_affaires_ht": ca_ht,
        "tva_collectee": tva,
        "chiffre_affaires_ttc": money(ca_ht + tva),
    }


def assiette_cotisation_minimale(db: Session, company_id: int, annee: int) -> dict:
    """Base de la cotisation minimale : produits **hors TVA** (CGI art. 144-I-B).

    Somme les soldes crediteurs inverses des comptes de produits des categories
    visees par l'article 144-I-B du CGI (rappel de l'article 9-I) :

    - `71x` : chiffre d'affaires (art. 9-I-A-1°) ;
    - `75x` : autres produits d'exploitation (art. 9-I-A-5°) ;
    - `76x` : produits financiers (art. 9-I-B) ;
    - `74x` / `77x` : subventions et dons (art. 9-I-A-4°, art. 9-I-C-2°/4°).

    Aucun compte de TVA n'entre dans la base : la loi assied la cotisation
    minimale sur le montant **hors taxe sur la valeur ajoutee** (CM-1/CM-2 V7B).
    """
    date_from, date_to = year_bounds(annee)
    detail = {racine: money(0) for racine in RACINES_ASSIETTE_CM}
    for ligne in movements(db, company_id, date_from, date_to):
        racine = ligne["account_number"][:2]
        if racine in detail:
            detail[racine] = money(detail[racine] + (-ligne["solde"]))  # produit
    base = money(sum((detail[racine] for racine in RACINES_ASSIETTE_CM), Decimal("0")))
    return {
        "annee": annee,
        "detail": detail,
        "base_hors_tva": base,
    }


def montant_acomptes(db: Session, company_id: int, annee: int) -> Decimal:
    """Acomptes d'IS verses sur l'exercice (compte `3453`, solde debiteur)."""
    date_from, date_to = year_bounds(annee)
    total = Decimal("0")
    for ligne in movements(db, company_id, date_from, date_to):
        if ligne["account_number"].startswith(COMPTE_ACOMPTES_IS):
            total += ligne["solde"]
    return money(total)


def _montant(valeur: Decimal | int | float | str | None, libelle: str) -> Decimal:
    """Convertit un montant saisi et refuse une valeur negative."""
    try:
        montant = money(Decimal(str(valeur or "0")))
    except Exception as exc:  # noqa: BLE001 - conversion volontairement toleree
        raise FiscalError(f"Montant invalide pour « {libelle} » : {valeur}") from exc
    if montant < 0:
        raise FiscalError(f"Le montant « {libelle} » ne peut pas être négatif.")
    return montant


# ---------------------------------------------------------------------------
# Resultat fiscal, IS et cotisation minimale
# ---------------------------------------------------------------------------
def _detail_reintegrations(
    db: Session, company_id: int, annee: int, saisies: dict[str, object],
    detection_automatique: bool
) -> tuple[list[dict], list[dict]]:
    """Detail des reintegrations (saisies + propositions detectees).

    Les **propositions** sont toujours retournees (information du comptable et
    des controles) ; `detection_automatique` decide seulement si elles sont
    **retenues** dans le calcul lorsqu'aucun montant n'est saisi.
    """
    propositions = charges_non_deductibles(db, company_id, annee)
    propositions_par_code = (
        {p["code"]: p for p in propositions} if detection_automatique else {}
    )
    detail: list[dict] = []
    for rubrique in CATALOGUE_REINTEGRATIONS:
        montant = _montant(saisies.get(rubrique["code"], "0"), rubrique["libelle"])
        origine = "saisie" if montant else ""
        if not montant:
            proposition = propositions_par_code.get(rubrique["code"])
            if proposition:
                montant = proposition["montant"]
                origine = "détection automatique"
        if montant:
            detail.append(
                {
                    "code": rubrique["code"],
                    "libelle": rubrique["libelle"],
                    "reference": rubrique["reference"],
                    "montant": montant,
                    "origine": origine,
                }
            )
    for code, montant_saisi in saisies.items():
        if code in CATALOGUE_REINTEGRATIONS_PAR_CODE:
            continue
        montant = _montant(montant_saisi, f"réintégration {code}")
        if montant:
            detail.append(
                {
                    "code": code,
                    "libelle": f"Réintégration saisie ({code})",
                    "reference": "CGI art. 11",
                    "montant": montant,
                    "origine": "saisie",
                }
            )
    return detail, propositions


def _detail_deductions(saisies: dict[str, object]) -> list[dict]:
    """Detail des deductions saisies (hors report deficitaire)."""
    detail: list[dict] = []
    for rubrique in CATALOGUE_DEDUCTIONS:
        montant = _montant(saisies.get(rubrique["code"], "0"), rubrique["libelle"])
        if montant:
            detail.append(
                {
                    "code": rubrique["code"],
                    "libelle": rubrique["libelle"],
                    "reference": rubrique["reference"],
                    "montant": montant,
                    "origine": "saisie",
                }
            )
    return detail


def date_debut_activite(db: Session, company: Company) -> date | None:
    """Date de **debut d'activite** retenue pour l'exoneration de cotisation minimale.

    Ordre de priorite (aucune valeur inventee) :
    1. `date_debut_exploitation` (saisie dans la fiche societe) ;
    2. `date_constitution` ;
    3. a defaut, le **debut du premier exercice** ouvert au dossier.
    """
    if company.date_debut_exploitation is not None:
        return company.date_debut_exploitation
    if company.date_constitution is not None:
        return company.date_constitution
    premier = db.execute(
        select(FiscalYear)
        .where(FiscalYear.company_id == company.id)
        .order_by(FiscalYear.year)
    ).scalars().first()
    return None if premier is None else premier.start_date


def _mois_depuis(debut: date, annee: int) -> int:
    """Nombre de mois ecoules de ``debut`` jusqu'a la fin de l'exercice ``annee``."""
    if annee < debut.year:
        return 0
    return (annee - debut.year) * 12 + (12 - debut.month + 1)


def mois_activite_effectif(db: Session, company: Company, annee: int) -> int:
    """Nombre de **mois d'activite cumules** a la fin de l'exercice (>= 1).

    Calcule depuis les dates reelles de la societe : c'est cette duree qui
    determine l'**exoneration de cotisation minimale** des 36 premiers mois
    (CGNC / CGI art. 144-I-C-1°). Un exercice posterieur au debut d'activite
    majore le compteur d'autant.
    """
    debut = date_debut_activite(db, company)
    if debut is None:
        # Dossier sans date ni exercice anterieur : activite reputee nouvelle.
        return 1
    return max(1, _mois_depuis(debut, annee))


def exoneration_cotisation_minimale(db: Session, company: Company, annee: int) -> dict:
    """Etat de l'exoneration de cotisation minimale pour un exercice.

    Exoneration des **36 premiers mois d'activite** (CGI art. 144-I-C-1°),
    **cessant a l'expiration des 60 mois suivant la constitution** : la fenetre
    d'exoneration se termine au plus tard a la date la plus proche entre
    (debut d'activite + 36 mois) et (constitution + 60 mois) (CM-3 V7B).

    Retourne : `mois_activite`, `exoneree`, `date_debut_activite`,
    `fin_exoneration` (fenetre retenue), `duree_exoneration_mois`,
    `butee_constitution_mois`, `fin_butee_constitution`.
    """
    from app.core.rates_ma import COTISATION_MINIMALE_BY_YEAR

    parametres = COTISATION_MINIMALE_BY_YEAR.get(int(annee))
    duree = int(parametres["exemption_months"]) if parametres else 36
    butee = (
        int(parametres["exemption_butee_months"])
        if parametres is not None and parametres.get("exemption_butee_months") is not None
        else 60
    )
    debut = date_debut_activite(db, company)
    mois = mois_activite_effectif(db, company, annee)
    fin = None
    if debut is not None:
        mois_fin = debut.month - 1 + duree
        fin = date(debut.year + mois_fin // 12, mois_fin % 12 + 1, 1)
    # Butee maximale : 60 mois apres la constitution (CGI art. 144-I-C-1°).
    fin_butee = None
    if company.date_constitution is not None:
        mois_fin = company.date_constitution.month - 1 + butee
        fin_butee = date(
            company.date_constitution.year + mois_fin // 12,
            mois_fin % 12 + 1,
            1,
        )
        if fin is None or fin_butee < fin:
            fin = fin_butee
    exoneree = mois < duree
    if exoneree and fin_butee is not None and date(annee, 12, 31) >= fin_butee:
        # Exercice entierement apres la butee : exoneration epuisee.
        exoneree = False
    return {
        "exercice": annee,
        "date_debut_activite": debut,
        "duree_exoneration_mois": duree,
        "mois_activite": mois,
        "exoneree": exoneree,
        "fin_exoneration": fin,
        "butee_constitution_mois": butee,
        "fin_butee_constitution": fin_butee,
    }


def calculer_is(
    db: Session,
    company: Company,
    annee: int,
    *,
    reintegrations: dict[str, object] | None = None,
    deductions: dict[str, object] | None = None,
    report_deficitaire: object = "0",
    credits_impot: object = "0",
    acomptes: object | None = None,
    mois_activite: int | None = None,
    detection_automatique: bool = True,
) -> dict:
    """Calcule le **resultat fiscal**, l'**IS**, la **cotisation minimale** et le solde.

    - **resultat fiscal** = resultat avant impot + reintegrations - deductions
      - report deficitaire utilise (CGI art. 11 et 114) ;
    - **IS** : `compute_is` (taux de l'exercice, jamais code en dur) ;
    - **cotisation minimale** : `compute_cotisation_minimale` sur l'assiette
      **hors TVA** des produits (CGI art. 144-I-B, voir
      `assiette_cotisation_minimale`), **due meme en cas de deficit** ;
    - **impot du** = le plus eleve des deux (CGI art. 144) ; les **acomptes**
      (`3453`) et les **credits d'impot** viennent en deduction du solde ;
    - les reintegrations non saisies sont **proposees** par detection automatique
      (comptes non deductibles par nature) et signalees comme telles.
    """
    exercice = get_fiscal_year(db, company.id, annee)
    base = resultat_avant_impot(db, company.id, annee)
    detail_reintegrations, propositions = _detail_reintegrations(
        db, company.id, annee, dict(reintegrations or {}), detection_automatique
    )
    detail_deductions = _detail_deductions(dict(deductions or {}))
    total_reintegrations = money(
        sum((ligne["montant"] for ligne in detail_reintegrations), Decimal("0"))
    )
    total_deductions = money(
        sum((ligne["montant"] for ligne in detail_deductions), Decimal("0"))
    )
    resultat_avant_report = money(
        base["resultat_avant_impot"] + total_reintegrations - total_deductions
    )
    report_disponible = _montant(report_deficitaire, "report déficitaire")
    report_utilise = money(
        min(report_disponible, resultat_avant_report)
        if resultat_avant_report > 0
        else Decimal("0")
    )
    resultat_fiscal = money(resultat_avant_report - report_utilise)
    deficit_constate = money(-resultat_fiscal) if resultat_fiscal < 0 else money(0)

    is_theorique = (
        compute_is(resultat_fiscal, CATEGORIE_IS_SOCIETE, annee=annee)
        if resultat_fiscal > 0
        else money(0)
    )
    affaires = chiffre_affaires(db, company.id, annee)
    # Assiette de la CM : produits **hors TVA** (CGI art. 144-I-B) — la TVA
    # collectee (4455) n'y entre pas (correction CM-1/CM-2 V7B).
    assiette_cm = assiette_cotisation_minimale(db, company.id, annee)
    # Nombre de mois d'activite : calcule depuis les **dates reelles** de la
    # societe (constitution / debut d'exploitation), sauf saisie explicite.
    exoneration = exoneration_cotisation_minimale(db, company, annee)
    mois = exoneration["mois_activite"] if mois_activite is None else int(mois_activite)
    # La CM est due des que l'exoneration est epuisee : 36 mois d'activite OU
    # butee des 60 mois depuis la constitution (CGI art. 144-I-C-1°). Un nombre
    # de mois refletant cet epuisement est transmis au bareme (la saisie
    # explicite des mois prime, comme precedemment).
    mois_cm = mois
    if (
        mois_activite is None
        and not exoneration["exoneree"]
        and mois <= exoneration["duree_exoneration_mois"]
    ):
        mois_cm = exoneration["duree_exoneration_mois"] + 1
    cotisation_minimale = compute_cotisation_minimale(
        assiette_cm["base_hors_tva"], months_of_activity=mois_cm, annee=annee
    )
    cotisation_minimale_due = (
        cotisation_minimale if cotisation_minimale > is_theorique else money(0)
    )
    impot_du = money(max(is_theorique, cotisation_minimale))
    acomptes_verses = (
        montant_acomptes(db, company.id, annee)
        if acomptes is None
        else _montant(acomptes, "acomptes versés")
    )
    credits = _montant(credits_impot, "crédits d'impôt")
    total_credits = money(acomptes_verses + credits)
    solde = money(impot_du - total_credits)
    return {
        "annee": annee,
        "exercice_id": exercice.id,
        "statut_exercice": exercice.status,
        "resultat_comptable": base["resultat_comptable"],
        "impots_resultats_comptabilises": base["impots_resultats_comptabilises"],
        "resultat_avant_impot": base["resultat_avant_impot"],
        "detail_reintegrations": detail_reintegrations,
        "total_reintegrations": total_reintegrations,
        "detail_deductions": detail_deductions,
        "total_deductions": total_deductions,
        "resultat_avant_report": resultat_avant_report,
        "report_deficitaire_disponible": report_disponible,
        "report_deficitaire_utilise": report_utilise,
        "report_deficitaire_restant": money(report_disponible - report_utilise),
        "resultat_fiscal": resultat_fiscal,
        "deficit_constate": deficit_constate,
        "nature_resultat_fiscal": "benefice" if resultat_fiscal >= 0 else "deficit",
        "is_theorique": is_theorique,
        "chiffre_affaires_ht": affaires["chiffre_affaires_ht"],
        "tva_collectee": affaires["tva_collectee"],
        "chiffre_affaires_ttc": affaires["chiffre_affaires_ttc"],
        "base_cotisation_minimale": assiette_cm["base_hors_tva"],
        "detail_base_cotisation_minimale": assiette_cm["detail"],
        "cotisation_minimale": cotisation_minimale,
        "cotisation_minimale_due": cotisation_minimale_due,
        "mois_activite": mois,
        "exoneration_cotisation_minimale": {
            "exoneree": exoneration["exoneree"],
            "date_debut_activite": exoneration["date_debut_activite"],
            "fin_exoneration": exoneration["fin_exoneration"],
            "duree_exoneration_mois": exoneration["duree_exoneration_mois"],
            "butee_constitution_mois": exoneration["butee_constitution_mois"],
            "fin_butee_constitution": exoneration["fin_butee_constitution"],
            "source": (
                "saisie"
                if mois_activite is not None
                else "dates reelles de la societe (constitution / debut d'exploitation)"
            ),
        },
        "taux_is_exercice": str(is_rates(annee)["standard"]),
        "impot_du": impot_du,
        "acomptes_verses": acomptes_verses,
        "credits_impot": credits,
        "total_credits": total_credits,
        "solde_a_payer": money(solde if solde > 0 else 0),
        "excedent_a_reporter": money(-solde if solde < 0 else 0),
        "taux_effectif": (
            money(impot_du / resultat_fiscal * 100) if resultat_fiscal > 0 else None
        ),
        "propositions_reintegration": propositions,
    }


def reconciliation_balance(db: Session, company_id: int, annee: int) -> dict:
    """Controle prepare pour la liasse : la balance est-elle exploitable ?

    Verifie l'**equilibre de la partie double** (somme des soldes nulle) et
    retourne les totaux par classe, les produits, les charges et le resultat : ce
    sont les montants que l'etape 2 reconciliera **tableau par tableau**
    (« Σ liasses = balance »).
    """
    date_from, date_to = year_bounds(annee)
    lignes = movements(db, company_id, date_from, date_to)
    classes: dict[int, Decimal] = {}
    for ligne in lignes:
        classe = int(ligne["account_class"])
        classes[classe] = money(classes.get(classe, Decimal("0")) + ligne["solde"])
    ecart = money(sum(classes.values(), Decimal("0")))
    cpc = income_statement(db, company_id, date_from, date_to)
    return {
        "annee": annee,
        "classes": dict(sorted(classes.items())),
        "total_soldes": ecart,
        "equilibre": ecart == 0,
        "total_produits": cpc["total_produits"],
        "total_charges": cpc["total_charges"],
        "resultat": cpc["resultat"],
        "nb_lignes": len(lignes),
        "pret_pour_liasse": ecart == 0 and bool(lignes),
    }


def controles_fiscaux(
    db: Session, company: Company, annee: int, *, calcul: dict | None = None
) -> list[dict]:
    """Controles avant declaration IS / liasse (CDC § 4.1).

    Bloquants : **exercice non clos** (comptes definitifs exiges, P1.6) et
    **balance desequilibree**. Avertissements : charges non deductibles detectees
    non reintegrees (CGI art. 11), **cotisation minimale superieure a l'IS**
    (CGI art. 144), deficit a reporter (CGI art. 114), solde d'impot.
    """
    controles: list[dict] = []

    def ajouter(code: str, niveau: str, message: str) -> None:
        controles.append({"code": code, "niveau": niveau, "message": message})

    exercice = get_fiscal_year(db, company.id, annee)
    if exercice.status not in ("closed", "locked"):
        ajouter(
            "fiscal.exercice_non_clos",
            "bloquant",
            f"Exercice {annee} en statut « {exercice.status} » : la déclaration de "
            "résultat et la liasse exigent des comptes définitifs. Clôturez "
            "l'exercice (écran Exercices) avant de déposer.",
        )
    balance = reconciliation_balance(db, company.id, annee)
    if not balance["equilibre"]:
        ajouter(
            "fiscal.balance_desequilibree",
            "bloquant",
            f"Balance déséquilibrée ({annee}) : somme des soldes "
            f"{balance['total_soldes']} DH (doit être nulle).",
        )
    if not balance["nb_lignes"]:
        ajouter(
            "fiscal.exercice_sans_ecriture",
            "bloquant",
            f"Aucun mouvement comptable sur l'exercice {annee} : déclaration "
            "impossible.",
        )
    calcul = calcul or calculer_is(db, company, annee)
    non_reintegrees = [
        proposition
        for proposition in calcul["propositions_reintegration"]
        if not any(
            ligne["code"] == proposition["code"]
            for ligne in calcul["detail_reintegrations"]
        )
    ]
    if non_reintegrees:
        ajouter(
            "fiscal.reintegrations_a_examiner",
            "avertissement",
            "Charges non déductibles détectées (CGI art. 11) non réintégrées : "
            + " ; ".join(f"{p['libelle']} ({p['montant']} DH)" for p in non_reintegrees)
            + ".",
        )
    if calcul["cotisation_minimale_due"]:
        ajouter(
            "fiscal.cotisation_minimale_due",
            "avertissement",
            f"Cotisation minimale ({calcul['cotisation_minimale']} DH) supérieure à "
            f"l'IS ({calcul['is_theorique']} DH) : c'est elle qui est due "
            "(CGI art. 144), y compris en cas de déficit.",
        )
    if calcul["deficit_constate"]:
        ajouter(
            "fiscal.deficit_reportable",
            "avertissement",
            f"Déficit fiscal de {calcul['deficit_constate']} DH : report sur les "
            "exercices suivants (CGI art. 114) — durée et conditions à confirmer "
            "(CDC § 9.14, ambiguïté A21).",
        )
    if calcul["solde_a_payer"]:
        ajouter(
            "fiscal.solde_a_payer",
            "information",
            f"Solde d'IS à payer : {calcul['solde_a_payer']} DH (impôt dû "
            f"{calcul['impot_du']} DH - acomptes et crédits "
            f"{calcul['total_credits']} DH).",
        )
    if calcul["excedent_a_reporter"]:
        ajouter(
            "fiscal.excedent_acomptes",
            "information",
            f"Excédent d'acomptes de {calcul['excedent_a_reporter']} DH "
            "(imputable sur les acomptes suivants ou à restituer).",
        )
    ajouter(
        "fiscal.recap",
        "information",
        f"Exercice {annee} : résultat avant impôt {calcul['resultat_avant_impot']} DH, "
        f"réintégrations {calcul['total_reintegrations']} DH, déductions "
        f"{calcul['total_deductions']} DH, résultat fiscal "
        f"{calcul['resultat_fiscal']} DH, IS {calcul['is_theorique']} DH, "
        f"cotisation minimale {calcul['cotisation_minimale']} DH, impôt dû "
        f"{calcul['impot_du']} DH.",
    )
    return controles


def controles_bloquants(controles: list[dict]) -> list[dict]:
    """Controles bloquants (interdisent la declaration et la liasse)."""
    return [controle for controle in controles if controle["niveau"] == "bloquant"]


def dossier_is(db: Session, company: Company, annee: int, **parametres: object) -> dict:
    """Dossier fiscal complet d'un exercice : calcul, balance et controles.

    Point d'entree unique pour l'API, l'ecran et l'etape 2 (assembleur de
    liasse) : le calcul est **reproductible** (memes saisies, meme resultat).
    """
    calcul = calculer_is(db, company, annee, **parametres)
    return {
        "annee": annee,
        "calcul": calcul,
        "balance": reconciliation_balance(db, company.id, annee),
        "controles": controles_fiscaux(db, company, annee, calcul=calcul),
    }

