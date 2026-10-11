"""Assembleur de la liasse fiscale EDI Simpl-IS (P2.1 — etape 2).

Construit la liasse d'un exercice **a partir des donnees de l'application** :
balance definitive, immobilisations (J2), stocks (J3), frais de personnel / DTS
(J6), resultat fiscal et IS / cotisation minimale (etape 1), provisions, creances
et dettes.

Sources de verite
-----------------
- **Structure et codes legaux** : lus dans les **XSD officiels** de la DGI
  (`referentiels/liasse/*.xsd`) — racine `Liasse`, entete `modele/id`,
  `resultatFiscal`, `groupeValeursTableau` / `ValeursTableau` (tableau),
  `ValeurCellule` (`cellule/codeEdi`, `valeur`, `numeroLigne`), `extraFieldvaleurs`.
  Les `tableau/id` et `cellule/codeEdi` sont des **enumerations fermees** : un code
  absent du schema est **refuse** (`liasse.code_hors_schema`), jamais devine.
- **Correspondance `codeEdi` <-> rubrique comptable** : referentiel **editable**
  `codification_liasse.csv` (voir `referentiels/liasse/LISEZ-MOI.md`). Le XSD ne
  porte **aucun libelle** et l'annexe officielle « Codification des cellules »
  **n'est pas fournie** : l'application ne compose donc aucune cellule dont
  l'origine n'est pas decrite dans le referentiel (ambiguite **A22** du CDC).

Livrables de l'etape 2
----------------------
- `construire_liasse()` : liasse en memoire (entete, tableaux, cellules, controles) ;
- `enregistrer_liasse()` : persistance dans `liasse_tables` / `liasse_cells` et
  **registre `tax_declarations`** (type `LIASSE`, statut brouillon) ;
- `etat_de_saisie_efi_liasse()` / `efi_liasse_csv()` : **EFI assiste par tableau**
  (etat de saisie avec `codeEdi`, libelle et valeur) tant que le fichier EDI
  n'est pas valide par le schema ;
- `reconciliation_liasse_balance()` : controle « **Σ liasses = balance** ».
"""

from __future__ import annotations

import csv
import hashlib
import io
import unicodedata
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.core.rates_ma import money
from app.models import (
    DECLARATION_ACCEPTEE,
    DECLARATION_BROUILLON,
    DECLARATION_REJETEE,
    DECLARATION_SOUMISE,
    DEPOT_EFI,
    DEPOT_MODES,
    Company,
    LiasseCell,
    LiasseTableau,
    TaxDeclaration,
)
from app.services.accounting import AccountingError, get_fiscal_year
from app.services.reporting import movements, year_bounds

# --- Modeles officiels (nom = nom du fichier XSD sans extension) -------------
MODELE_COMPTABLE_SIMPLIFIE = "liasse_modele_comptable simplifié"
MODELE_NORMAL = "liasse_modele_normal"
MODELE_ASSURANCES = "liasse_modele_Assurances"
MODELE_ETABLISSEMENTS_CREDIT = "liasse_modele_établissements de crédit"
MODELES_LIASSE = (
    MODELE_COMPTABLE_SIMPLIFIE,
    MODELE_NORMAL,
    MODELE_ASSURANCES,
    MODELE_ETABLISSEMENTS_CREDIT,
)
MODELE_PAR_DEFAUT = MODELE_COMPTABLE_SIMPLIFIE
MODELE_LABELS = {
    MODELE_COMPTABLE_SIMPLIFIE: "Liasse comptable simplifiée (cible PME)",
    MODELE_NORMAL: "Liasse comptable normale",
    MODELE_ASSURANCES: "Liasse des assurances",
    MODELE_ETABLISSEMENTS_CREDIT: "Liasse des établissements de crédit",
}
RACINE_XML = "Liasse"  # element racine declare par les schemas Simpl-IS
TYPE_DECLARATION = "LIASSE"

# --- Alias des modeles (saisie utilisateur : « simplifié », « normal »...) ---
MODELES_ALIAS = {
    "liasse_modele_comptable simplifie": MODELE_COMPTABLE_SIMPLIFIE,
    "comptable simplifie": MODELE_COMPTABLE_SIMPLIFIE,
    "simplifie": MODELE_COMPTABLE_SIMPLIFIE,
    "simplified": MODELE_COMPTABLE_SIMPLIFIE,
    "liasse_modele_normal": MODELE_NORMAL,
    "normal": MODELE_NORMAL,
    "liasse_modele_assurances": MODELE_ASSURANCES,
    "assurances": MODELE_ASSURANCES,
    "assurance": MODELE_ASSURANCES,
    "liasse_modele_etablissements de credit": MODELE_ETABLISSEMENTS_CREDIT,
    "etablissements de credit": MODELE_ETABLISSEMENTS_CREDIT,
    "etablissement de credit": MODELE_ETABLISSEMENTS_CREDIT,
}


def normaliser_modele(nom: str) -> str:
    """Nom de modele normalise (minuscules, sans accents ni espaces doubles)."""
    decompose = unicodedata.normalize("NFKD", (nom or "").strip().lower())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(sans_accents.split())


def resoudre_modele(nom: str) -> str:
    """Nom de fichier XSD du modele a partir d'un nom ou d'un alias usuel."""
    if nom in MODELES_LIASSE:
        return nom
    alias = MODELES_ALIAS.get(normaliser_modele(nom))
    if alias is None:
        raise LiasseError(
            f"Modèle de liasse « {nom} » inconnu (valeurs admises : "
            f"{', '.join(MODELES_LIASSE)}, ou les alias "
            f"{', '.join(sorted(set(MODELES_ALIAS)))})."
        )
    return alias

# --- Colonnes du referentiel de codification --------------------------------
COLONNES_CODIFICATION = (
    "modele",
    "tableau_id",
    "tableau_libelle",
    "code_edi",
    "rubrique",
    "libelle",
    "numero_ligne",
    "extra_field",
    "origine",
)

MAX_XML_BYTES = 1_000_000  # limite de format des teleservices DGI (comme la DTS)

_XS = "{http://www.w3.org/2001/XMLSchema}"

# --- Catalogue des rubriques (documentation et verification du referentiel) --
# Rubriques dynamiques : un prefixe + un element de la comptabilite.
PREFIXES_RUBRIQUES = {
    "solde:": "solde (débit − crédit) d'un compte de la balance, ex. `solde:3421`",
    "racine:": "cumul des comptes d'une racine (2 ou 3 chiffres), ex. `racine:44`",
    "classe:": "cumul d'une classe de comptes (1 à 7), ex. `classe:6`",
}
# Rubriques fixes (calculees par les modules) : cle -> libelle.
RUBRIQUES_FIXES = {
    "total_produits": "Total des produits (classe 7)",
    "total_charges": "Total des charges (classe 6)",
    "resultat_comptable": "Résultat net comptable (CPC)",
    "resultat_avant_impot": "Résultat avant impôt (hors comptes 67x)",
    "chiffre_affaires": "Chiffre d'affaires (HT)",
    "total_reintegrations": "Réintégrations fiscales (CGI art. 11)",
    "total_deductions": "Déductions fiscales",
    "report_deficitaire": "Report déficitaire utilisé (CGI art. 114)",
    "resultat_fiscal": "Résultat fiscal",
    "is_theorique": "IS théorique",
    "cotisation_minimale": "Cotisation minimale (CGI art. 144)",
    "impot_du": "Impôt dû (le plus élevé de l'IS et de la CM)",
    "acomptes_verses": "Acomptes d'IS versés (compte 3453)",
    "solde_a_payer": "Solde d'IS à payer",
    "immo:brut": "Immobilisations — valeur brute (J2)",
    "immo:amortissements": "Immobilisations — amortissements cumulés (J2)",
    "immo:vnc": "Immobilisations — valeur nette comptable (J2)",
    "immo:brut_comptable": "Immobilisations — brut au grand livre (J2)",
    "immo:amortissements_comptables": "Immobilisations — amortissements au grand livre (J2)",
    "immo:dotations": "Dotations de l'exercice (plan d'amortissement, J2)",
    "immo:amortissements_cumules_plan": "Amortissements cumulés du plan (J2)",
    "immo:cessions_valeur": "Cessions — valeur d'origine (J2)",
    "immo:cessions_vnc": "Cessions — valeur nette comptable (J2)",
    "immo:cessions_prix": "Cessions — prix de cession (J2)",
    "immo:cessions_resultat": "Cessions — plus ou moins-value (J2)",
    "immo:regularisation_tva": "Cessions — régularisation de TVA (art. 106)",
    "stock:valeur": "Stocks — valeur des fiches (J3)",
    "stock:comptable": "Stocks — valeur au grand livre (J3)",
    "stock:ecart": "Stocks — écart fiches / comptabilité (J3)",
    "stock:provisions": "Stocks — dépréciations constatées (J3)",
    "stock:dotations_provisions": "Stocks — dotations aux dépréciations (J3)",
    "stock:reprises_provisions": "Stocks — reprises de dépréciations (J3)",
    "stock:initial": "Stocks — stock initial (J3)",
    "stock:final": "Stocks — stock final (J3)",
    "stock:entrees": "Stocks — entrées (J3)",
    "stock:sorties": "Stocks — sorties (J3)",
    "stock:variation": "Stocks — variation de l'exercice (J3)",
    "personnel:effectif": "Effectif déclaré à la DTS (J6)",
    "personnel:permanent_effectif": "Effectif permanent (J6)",
    "personnel:occasionnel_effectif": "Effectif occasionnel (J6)",
    "personnel:stagiaires_effectif": "Stagiaires (J6)",
    "personnel:brut_imposable": "Personnel — rémunérations brutes imposables (J6)",
    "personnel:cotisations_sociales": "Personnel — cotisations sociales salariales (J6)",
    "personnel:cnss_total": "Personnel — CNSS/AMO salarial + patronal (J6)",
    "personnel:ir_retenu": "Personnel — IR retenu à la source (J6)",
    "personnel:net_a_payer": "Personnel — net à payer (J6)",
    "personnel:cout_employeur": "Personnel — coût employeur (J6)",
    "personnel:brut_permanent": "Personnel permanent — brut imposable (J6)",
    "personnel:brut_occasionnel": "Personnel occasionnel — brut (J6)",
    "personnel:brut_stagiaires": "Stagiaires — brut (J6)",
}


def rubrique_documentee(specification: str) -> bool:
    """La rubrique appartient-elle au catalogue documente ?

    Verifie la **forme** de la specification (`-` initial admis) sans acceder a la
    comptabilite : c'est le controle du referentiel de codification (outil) et non
    la verification de disponibilite, faite a la construction de la liasse.
    """
    cle = (specification or "").strip().lstrip("-+").strip()
    if cle in RUBRIQUES_FIXES:
        return True
    return any(
        cle.startswith(prefixe) and len(cle) > len(prefixe)
        for prefixe in PREFIXES_RUBRIQUES
    )


class LiasseError(AccountingError):
    """Erreur de construction de la liasse (schema absent, referentiel invalide)."""


# ---------------------------------------------------------------------------
# Contrat des schemas officiels (XSD)
# ---------------------------------------------------------------------------
def xsds_disponibles(*, xsd_dir: Path | None = None) -> list[str]:
    """Modeles disponibles dans le dossier des XSD (`LIASSE_XSD_DIR`)."""
    dossier = Path(xsd_dir or settings.liasse_racine)
    if not dossier.is_dir():
        return []
    return sorted(chemin.stem for chemin in dossier.glob("liasse_modele_*.xsd"))


@lru_cache(maxsize=16)
def _contrat(modele: str, dossier: str) -> dict:
    """Lit le contrat d'un modele dans son XSD (cache par (modele, dossier))."""
    chemin = Path(dossier) / f"{modele}.xsd"
    if not chemin.is_file():
        raise LiasseError(
            f"Schéma « {modele} » introuvable ({chemin}) : dépôt impossible en EDI. "
            "Renseignez LIASSE_XSD_DIR (dossier des XSD officiels DGI) ou utilisez "
            "le mode EFI assisté."
        )
    try:
        arbre = etree.parse(str(chemin))
    except etree.XMLSyntaxError as exc:  # pragma: no cover - schema corrompu
        raise LiasseError(f"Schéma illisible « {chemin} » : {exc}") from exc

    enumerations: dict[str, list[str]] = {}
    for element in arbre.iter(f"{_XS}element"):
        nom = element.get("name")
        if nom not in ("id", "codeEdi", "code"):
            continue
        valeurs = [
            enumeration.get("value")
            for enumeration in element.iter(f"{_XS}enumeration")
            if enumeration.get("value") is not None
        ]
        if valeurs:
            enumerations.setdefault(nom, []).extend(valeurs)

    racine = next(
        (
            element.get("name")
            for element in arbre.getroot()
            if element.tag == f"{_XS}element" and element.get("name") == RACINE_XML
        ),
        RACINE_XML,
    )
    modele_id = next(
        (
            element.get("fixed")
            for element in arbre.iter(f"{_XS}element")
            if element.get("name") == "id" and element.get("fixed") is not None
        ),
        None,
    )
    types = {
        element.get("name"): restriction.get("base")
        for element in arbre.iter(f"{_XS}element")
        if element.get("name") in ("valeur", "numeroLigne")
        for restriction in element.iter(f"{_XS}restriction")
    }
    tableaux = sorted({int(valeur) for valeur in enumerations.get("id", [])})
    codes = sorted(set(enumerations.get("codeEdi", [])))
    return {
        "modele": modele,
        "libelle": MODELE_LABELS.get(modele, modele),
        "fichier": str(chemin),
        "racine": racine,
        "modele_id": int(modele_id) if modele_id else None,
        "tableaux": tableaux,
        "codes": codes,
        "codes_ensemble": frozenset(codes),
        "extra_fields": sorted(set(enumerations.get("code", []))),
        "type_valeur": types.get("valeur"),
        "type_numero_ligne": types.get("numeroLigne"),
    }


def contrat_modele(
    modele: str = MODELE_PAR_DEFAUT, *, xsd_dir: Path | None = None
) -> dict:
    """Contrat du modele : tableaux et `codeEdi` legaux, entete, types (XSD)."""
    dossier = str(Path(xsd_dir or settings.liasse_racine))
    return _contrat(resoudre_modele(modele), dossier)


# ---------------------------------------------------------------------------
# Referentiel de codification (`codeEdi` <-> rubrique comptable)
# ---------------------------------------------------------------------------
def _ligne_codification(brut: dict, numero: int) -> dict:
    """Valide une ligne du referentiel et normalise ses types."""
    modele = (brut.get("modele") or "").strip()
    code_edi = (brut.get("code_edi") or "").strip()
    rubrique = (brut.get("rubrique") or "").strip()
    if not modele or not code_edi or not rubrique:
        raise LiasseError(
            f"Référentiel de codification, ligne {numero} : « modele », « code_edi » "
            "et « rubrique » sont obligatoires."
        )
    try:
        tableau_id = int((brut.get("tableau_id") or "").strip())
    except ValueError as exc:
        raise LiasseError(
            f"Référentiel de codification, ligne {numero} : « tableau_id » invalide "
            f"({brut.get('tableau_id')!r})."
        ) from exc
    numero_brut = (brut.get("numero_ligne") or "").strip()
    try:
        numero_ligne = int(numero_brut) if numero_brut else None
    except ValueError as exc:
        raise LiasseError(
            f"Référentiel de codification, ligne {numero} : « numero_ligne » invalide "
            f"({numero_brut!r})."
        ) from exc
    return {
        "modele": modele,
        "tableau_id": tableau_id,
        "tableau_libelle": (brut.get("tableau_libelle") or "").strip() or None,
        "code_edi": code_edi,
        "rubrique": rubrique,
        "libelle": (brut.get("libelle") or "").strip() or None,
        "numero_ligne": numero_ligne,
        "extra_field": (brut.get("extra_field") or "").strip() or None,
        "origine": (brut.get("origine") or "").strip() or None,
    }


def charger_codification(
    *, chemin: Path | None = None, modele: str | None = None
) -> list[dict]:
    """Lignes du referentiel de codification (filtrees par modele si fourni)."""
    fichier = Path(chemin or settings.liasse_codification)
    if not fichier.is_file():
        raise LiasseError(
            f"Référentiel de codification introuvable ({fichier}) : aucun `codeEdi` "
            "n'est deviné par l'application. Renseignez `codification_liasse.csv` "
            "(voir referentiels/liasse/LISEZ-MOI.md)."
        )
    with fichier.open("r", encoding="utf-8", newline="") as flux:
        lecteur = csv.DictReader(flux)
        colonnes = lecteur.fieldnames or []
        manquantes = [nom for nom in COLONNES_CODIFICATION if nom not in colonnes]
        if manquantes:
            raise LiasseError(
                f"Référentiel de codification {fichier} : colonnes manquantes "
                f"{', '.join(manquantes)}."
            )
        lignes = [
            _ligne_codification(brut, numero)
            for numero, brut in enumerate(lecteur, start=2)
        ]
    if modele is not None:
        lignes = [ligne for ligne in lignes if ligne["modele"] == modele]
    return lignes


def tableaux_codification(lignes: list[dict]) -> list[dict]:
    """Regroupe le referentiel par tableau (ordre d'apparition conserve)."""
    tableaux: dict[int, dict] = {}
    for ligne in lignes:
        tableau = tableaux.setdefault(
            ligne["tableau_id"],
            {
                "tableau_id": ligne["tableau_id"],
                "libelle": ligne["tableau_libelle"],
                "extra_field": ligne["extra_field"],
                "cellules": [],
            },
        )
        if tableau["libelle"] is None:
            tableau["libelle"] = ligne["tableau_libelle"]
        if tableau["extra_field"] is None:
            tableau["extra_field"] = ligne["extra_field"]
        tableau["cellules"].append(ligne)
    return [tableaux[cle] for cle in sorted(tableaux)]


# ---------------------------------------------------------------------------
# Rubriques alimentees par l'application
# ---------------------------------------------------------------------------
def _rubrique(valeur: object, libelle: str, source: str, *, texte: bool = False) -> dict:
    """Une rubrique : valeur, libelle, origine de la valeur et nature."""
    return {
        "valeur": valeur,
        "libelle": libelle,
        "source": source,
        "type": "texte" if texte else "montant",
    }


def _rubriques_balance(db: Session, company_id: int, annee: int) -> dict:
    """Soldes par compte, cumuls par racine (2-3 chiffres) et par classe."""
    date_from, date_to = year_bounds(annee)
    rubriques: dict[str, dict] = {}
    racines: dict[str, Decimal] = {}
    classes: dict[int, Decimal] = {}
    for ligne in movements(db, company_id, date_from, date_to):
        numero = ligne["account_number"]
        rubriques[f"solde:{numero}"] = _rubrique(
            ligne["solde"],
            ligne["label"],
            f"balance {annee} — solde du compte {numero} (débit − crédit)",
        )
        for taille in (2, 3):
            if len(numero) >= taille:
                prefixe = numero[:taille]
                racines[prefixe] = money(racines.get(prefixe, Decimal("0")) + ligne["solde"])
        classe = int(ligne["account_class"])
        classes[classe] = money(classes.get(classe, Decimal("0")) + ligne["solde"])
    for prefixe, montant in racines.items():
        rubriques[f"racine:{prefixe}"] = _rubrique(
            montant,
            f"Cumul des comptes {prefixe}…",
            f"balance {annee} — cumul de la racine {prefixe}",
        )
    for classe, montant in classes.items():
        rubriques[f"classe:{classe}"] = _rubrique(
            montant,
            f"Cumul de la classe {classe}",
            f"balance {annee} — cumul de la classe {classe}",
        )
    return rubriques


def _rubriques_fiscales(db: Session, company: Company, annee: int) -> dict:
    """Resultat fiscal, IS et cotisation minimale (etape 1)."""
    from app.services import fiscal_liasse  # noqa: PLC0415 - import local

    dossier = fiscal_liasse.dossier_is(db, company, annee)
    calcul = dossier["calcul"]
    balance = dossier["balance"]
    source = f"résultat fiscal {annee} (J7 étape 1)"
    return {
        "total_produits": _rubrique(
            balance["total_produits"], "Total des produits", source
        ),
        "total_charges": _rubrique(balance["total_charges"], "Total des charges", source),
        "resultat_comptable": _rubrique(
            calcul["resultat_comptable"], "Résultat net comptable", source
        ),
        "resultat_avant_impot": _rubrique(
            calcul["resultat_avant_impot"], "Résultat avant impôt", source
        ),
        "chiffre_affaires": _rubrique(
            calcul["chiffre_affaires_ht"], "Chiffre d'affaires (HT)", source
        ),
        "total_reintegrations": _rubrique(
            calcul["total_reintegrations"], "Réintégrations fiscales", source
        ),
        "total_deductions": _rubrique(
            calcul["total_deductions"], "Déductions fiscales", source
        ),
        "report_deficitaire": _rubrique(
            calcul["report_deficitaire_utilise"], "Report déficitaire utilisé", source
        ),
        "resultat_fiscal": _rubrique(
            calcul["resultat_fiscal"], "Résultat fiscal", source
        ),
        "is_theorique": _rubrique(calcul["is_theorique"], "IS théorique", source),
        "cotisation_minimale": _rubrique(
            calcul["cotisation_minimale"], "Cotisation minimale", source
        ),
        "impot_du": _rubrique(calcul["impot_du"], "Impôt dû (IS ou CM)", source),
        "acomptes_verses": _rubrique(
            calcul["acomptes_verses"], "Acomptes d'IS versés", source
        ),
        "solde_a_payer": _rubrique(calcul["solde_a_payer"], "Solde d'IS à payer", source),
    }


def _rubriques_immobilisations(db: Session, company: Company, annee: int) -> dict:
    """Immobilisations : brut, amortissements, VNC, dotations et cessions (J2)."""
    from app.services import assets  # noqa: PLC0415 - import local (anti-cycle)

    source = f"immobilisations {annee} (J2)"
    etat = assets.etat_immobilisations(db, company.id, annee)
    rubriques = {
        "immo:brut": _rubrique(etat["total_brut"], "Immobilisations — valeur brute", source),
        "immo:amortissements": _rubrique(
            etat["total_amortissements"], "Immobilisations — amortissements cumulés", source
        ),
        "immo:vnc": _rubrique(etat["total_vnc"], "Immobilisations — valeur nette", source),
        "immo:brut_comptable": _rubrique(
            etat["comptabilite"]["brut"], "Immobilisations — brut au grand livre", source
        ),
        "immo:amortissements_comptables": _rubrique(
            etat["comptabilite"]["amortissements"],
            "Immobilisations — amortissements au grand livre",
            source,
        ),
    }
    dotations = assets.amortissements_deductibles(db, company.id, annee)
    rubriques.update(
        {
            "immo:dotations": _rubrique(
                dotations["total_dotation"], "Dotations de l'exercice (plan)", source
            ),
            "immo:amortissements_cumules_plan": _rubrique(
                dotations["total_cumul"], "Amortissements cumulés (plan)", source
            ),
        }
    )
    cessions = assets.tableau_cessions(db, company.id, annee)
    rubriques.update(
        {
            "immo:cessions_valeur": _rubrique(
                cessions["total_valeur_origine"], "Cessions — valeur d'origine", source
            ),
            "immo:cessions_vnc": _rubrique(
                cessions["total_vnc"], "Cessions — valeur nette comptable", source
            ),
            "immo:cessions_prix": _rubrique(
                cessions["total_prix"], "Cessions — prix de cession", source
            ),
            "immo:cessions_resultat": _rubrique(
                cessions["total_resultat"], "Cessions — résultat (plus/moins-value)", source
            ),
            "immo:regularisation_tva": _rubrique(
                cessions["total_regularisation"],
                "Cessions — régularisation de TVA (art. 106)",
                source,
            ),
        }
    )
    return rubriques


def _rubriques_stocks(db: Session, company: Company, annee: int) -> dict:
    """Stocks : valeur, provisions, variation et régularisations (J3)."""
    from app.services import stocks  # noqa: PLC0415 - import local (anti-cycle)

    source = f"stocks {annee} (J3)"
    etat = stocks.etat_stocks(db, company.id, au=year_bounds(annee)[1])
    provisions = stocks.etat_provisions(db, company.id, annee)
    variation = stocks.variation_stocks(db, company.id, annee)
    return {
        "stock:valeur": _rubrique(etat["total_valeur"], "Stocks — valeur des fiches", source),
        "stock:comptable": _rubrique(
            etat["total_comptable"], "Stocks — valeur au grand livre", source
        ),
        "stock:ecart": _rubrique(
            etat["ecart"], "Stocks — écart fiches / comptabilité", source
        ),
        "stock:provisions": _rubrique(
            provisions["total_provision"], "Stocks — dépréciations constatées", source
        ),
        "stock:dotations_provisions": _rubrique(
            provisions["total_dotation"], "Stocks — dotations aux dépréciations", source
        ),
        "stock:reprises_provisions": _rubrique(
            provisions["total_reprise"], "Stocks — reprises de dépréciations", source
        ),
        "stock:initial": _rubrique(variation["total_initial"], "Stocks — stock initial", source),
        "stock:final": _rubrique(variation["total_final"], "Stocks — stock final", source),
        "stock:entrees": _rubrique(variation["total_entrees"], "Stocks — entrées", source),
        "stock:sorties": _rubrique(variation["total_sorties"], "Stocks — sorties", source),
        "stock:variation": _rubrique(
            variation["total_variation"], "Stocks — variation de l'exercice", source
        ),
    }


def date_dernier_jour(annee: int) -> "date":
    """Dernier jour de l'exercice (cloture)."""
    return year_bounds(annee)[1]


def _rubriques_personnel(db: Session, company: Company, annee: int) -> dict:
    """Frais de personnel et effectifs issus de la DTS « 9421 » (J6)."""
    from app.services.edi_dts import construire_dts  # noqa: PLC0415 - import local

    modele = construire_dts(db, company, annee)
    totaux = modele["totaux"]
    edi = modele["totaux_edi"]
    source = f"DTS « 9421 » {annee} (J6)"
    return {
        "personnel:effectif": _rubrique(
            Decimal(totaux["nb_salaries"]), "Effectif déclaré à la DTS", source
        ),
        "personnel:permanent_effectif": _rubrique(
            Decimal(len(modele["personnel_permanent"])), "Effectif permanent", source
        ),
        "personnel:occasionnel_effectif": _rubrique(
            Decimal(len(modele["personnel_occasionnel"])),
            "Effectif occasionnel",
            source,
        ),
        "personnel:stagiaires_effectif": _rubrique(
            Decimal(len(modele["stagiaires"])), "Stagiaires", source
        ),
        "personnel:brut_imposable": _rubrique(
            totaux["brut_imposable"], "Personnel — rémunérations brutes imposables", source
        ),
        "personnel:cotisations_sociales": _rubrique(
            totaux["cotisations_sociales"], "Personnel — cotisations sociales (part salariale)", source
        ),
        "personnel:cnss_total": _rubrique(
            totaux["cnss_total"], "Personnel — cotisations CNSS/AMO (salarial + patronal)", source
        ),
        "personnel:ir_retenu": _rubrique(
            totaux["ir_retenu"], "Personnel — IR retenu à la source", source
        ),
        "personnel:net_a_payer": _rubrique(
            totaux["net_a_payer"], "Personnel — net à payer", source
        ),
        "personnel:cout_employeur": _rubrique(
            totaux["cout_employeur"], "Personnel — coût employeur", source
        ),
        "personnel:brut_permanent": _rubrique(
            edi["totalMtRevenuBrutImposablePP"],
            "Personnel permanent — brut imposable",
            source,
        ),
        "personnel:brut_occasionnel": _rubrique(
            edi["totalMtBrutSommesPO"], "Personnel occasionnel — brut", source
        ),
        "personnel:brut_stagiaires": _rubrique(
            edi["totalMtBrutTraitSalaireSTG"], "Stagiaires — brut", source
        ),
    }


def rubriques_liasse(db: Session, company: Company, annee: int) -> dict:
    """Toutes les valeurs mobilisables par la liasse d'un exercice.

    Retourne `{"rubriques": {...}, "indisponibles": [...]}` : une source absente
    (pas d'immobilisation, pas de bulletin de paie, exercice sans écriture…) **ne
    bloque pas** la liasse — elle est simplement signalée, et les cellules qui en
    dépendent restent sans valeur (`liasse.rubrique_sans_valeur`).
    """
    rubriques = _rubriques_balance(db, company.id, annee)
    indisponibles: list[dict] = []
    for nom, fabrique in (
        ("résultat fiscal (J7 étape 1)", _rubriques_fiscales),
        ("immobilisations (J2)", _rubriques_immobilisations),
        ("stocks (J3)", _rubriques_stocks),
        ("personnel / DTS (J6)", _rubriques_personnel),
    ):
        try:
            rubriques.update(fabrique(db, company, annee))
        except Exception as exc:  # noqa: BLE001 - une source absente n'est pas fatale
            indisponibles.append({"source": nom, "message": str(exc)})
    return {"rubriques": rubriques, "indisponibles": indisponibles}


def _format_valeur(valeur: object) -> str:
    """Valeur telle qu'elle sera ecrite dans le fichier (`valeur` = chaîne)."""
    if isinstance(valeur, Decimal):
        return f"{valeur:.2f}"
    if hasattr(valeur, "isoformat"):
        return valeur.isoformat()
    return str(valeur)


def _valeur_cellule(specification: str, rubriques: dict) -> tuple[object, str | None]:
    """Resout une specification de rubrique (`-solde:3481` = solde inverse).

    Retourne `(valeur, probleme)` : `probleme` vaut `"inconnue"` (spec absente du
    catalogue), `"sans_valeur"` (rubrique connue mais non alimentee) ou `None`.
    """
    specification = (specification or "").strip()
    negation = specification.startswith("-")
    cle = specification.lstrip("-+").strip()
    rubrique = rubriques.get(cle)
    if rubrique is None:
        # Rubrique du catalogue mais source indisponible (pas de paie, pas de stock…)
        # ou specification hors catalogue (erreur de referentiel) : jamais devine.
        return None, ("sans_valeur" if rubrique_documentee(cle) else "inconnue")
    valeur = rubrique["valeur"]
    if valeur is None:
        return None, "sans_valeur"
    if negation and rubrique["type"] == "montant":
        valeur = money(-Decimal(str(valeur)))
    return valeur, None


def construire_liasse(
    db: Session,
    company: Company,
    annee: int,
    *,
    modele: str = MODELE_PAR_DEFAUT,
    codification: list[dict] | None = None,
    xsd_dir: Path | None = None,
) -> dict:
    """Assemble la liasse d'un exercice a partir de la balance et des modules.

    Chaque cellule provient **exclusivement** du referentiel de codification :
    aucune correspondance `codeEdi` <-> rubrique n'est devinee. Les codes sont
    controles contre les **enumerations du XSD** du modele ; un schema absent ne
    bloque que le depot **EDI** (l'EFI assiste reste possible) et il est signale
    par `liasse.schema_absent`.
    """
    get_fiscal_year(db, company.id, annee)  # leve si l'exercice n'existe pas
    modele_resolu = resoudre_modele(modele)  # leve si le modele est inconnu
    contrat: dict | None
    try:
        contrat = contrat_modele(modele_resolu, xsd_dir=xsd_dir)
    except LiasseError:
        contrat = None
    lignes = (
        codification
        if codification is not None
        else charger_codification(modele=modele_resolu)
    )
    valeurs = rubriques_liasse(db, company, annee)
    rubriques = valeurs["rubriques"]
    tableaux: list[dict] = []
    sans_valeur: list[dict] = []
    inconnues: list[dict] = []
    hors_schema: list[dict] = []
    for tableau in tableaux_codification(lignes):
        cellules: list[dict] = []
        for ligne in tableau["cellules"]:
            valeur, probleme = _valeur_cellule(ligne["rubrique"], rubriques)
            cle = (ligne["rubrique"] or "").lstrip("-+").strip()
            if probleme == "inconnue":
                inconnues.append(
                    {
                        "tableau_id": ligne["tableau_id"],
                        "code_edi": ligne["code_edi"],
                        "rubrique": ligne["rubrique"],
                    }
                )
                continue
            if probleme == "sans_valeur":
                sans_valeur.append(
                    {
                        "tableau_id": ligne["tableau_id"],
                        "code_edi": ligne["code_edi"],
                        "rubrique": ligne["rubrique"],
                    }
                )
                continue
            rubrique = rubriques[cle]
            libelle = ligne["libelle"] or rubrique["libelle"]
            cellules.append(
                {
                    "tableau_id": ligne["tableau_id"],
                    "code_edi": ligne["code_edi"],
                    "rubrique": ligne["rubrique"],
                    "libelle": libelle,
                    "valeur": _format_valeur(valeur),
                    "valeur_numerique": (
                        money(Decimal(str(valeur)))
                        if rubrique["type"] == "montant"
                        else None
                    ),
                    "numero_ligne": ligne["numero_ligne"],
                    "extra_field": ligne["extra_field"] or tableau["extra_field"],
                    "source": (
                        f"{rubrique['source']} | référentiel de codification"
                        + (f" : {ligne['origine']}" if ligne["origine"] else "")
                    ),
                }
            )
        if cellules or tableau["libelle"]:
            tableaux.append(
                {
                    "tableau_id": tableau["tableau_id"],
                    "libelle": tableau["libelle"],
                    "extra_field": tableau["extra_field"],
                    "cellules": cellules,
                }
            )
    if contrat is not None:
        for tableau in tableaux:
            if tableau["tableau_id"] not in contrat["tableaux"]:
                hors_schema.append(
                    {
                        "tableau_id": tableau["tableau_id"],
                        "code_edi": None,
                        "motif": "tableau absent de l'énumération du schéma",
                    }
                )
            for cellule in tableau["cellules"]:
                if cellule["code_edi"] not in contrat["codes_ensemble"]:
                    hors_schema.append(
                        {
                            "tableau_id": tableau["tableau_id"],
                            "code_edi": cellule["code_edi"],
                            "rubrique": cellule["rubrique"],
                            "motif": "codeEdi absent de l'énumération du schéma",
                        }
                    )
    return {
        "annee": annee,
        "modele": modele_resolu,
        "libelle_modele": (contrat or {}).get(
            "libelle", MODELE_LABELS.get(modele_resolu, modele_resolu)
        ),
        "modele_id": (contrat or {}).get("modele_id"),
        "racine": (contrat or {}).get("racine", RACINE_XML),
        "schema": (contrat or {}).get("fichier"),
        "entete": {
            "identifiantFiscal": company.fiscal_id,
            "exerciceFiscalDu": year_bounds(annee)[0].isoformat(),
            "exerciceFiscalAu": year_bounds(annee)[1].isoformat(),
            "raisonSociale": company.name,
            "ice": company.ice,
        },
        "tableaux": tableaux,
        "nb_tableaux": len(tableaux),
        "nb_cellules": sum(len(tableau["cellules"]) for tableau in tableaux),
        "total_numerique": money(
            sum(
                (
                    cellule["valeur_numerique"]
                    for tableau in tableaux
                    for cellule in tableau["cellules"]
                    if cellule["valeur_numerique"] is not None
                ),
                Decimal("0"),
            )
        ),
        "rubriques_disponibles": len(rubriques),
        "sources_indisponibles": valeurs["indisponibles"],
        "cellules_sans_valeur": sans_valeur,
        "cellules_rubrique_inconnue": inconnues,
        "cellules_hors_schema": hors_schema,
        "resultat_fiscal": (rubriques.get("resultat_fiscal") or {}).get("valeur"),
        "impot_du": (rubriques.get("impot_du") or {}).get("valeur"),
        "contrat": contrat,
    }


def controles_liasse(
    db: Session, company: Company, annee: int, liasse: dict
) -> list[dict]:
    """Controles avant depot de la liasse (CDC § 4.1 et § 6.5).

    Bloquants : `liasse.schema_absent`, `liasse.code_hors_schema`,
    `liasse.tableau_hors_schema`, `liasse.rubrique_inconnue`, plus les bloquants du
    **dossier fiscal** (exercice non clos P1.6, balance déséquilibrée). Avertissements :
    `liasse.codification_absente`, `liasse.rubrique_sans_valeur`,
    `liasse.sources_indisponibles`.
    """
    from app.services import fiscal_liasse  # noqa: PLC0415 - import local

    controles: list[dict] = []

    def ajouter(code: str, niveau: str, message: str) -> None:
        controles.append({"code": code, "niveau": niveau, "message": message})

    contrat = liasse.get("contrat")
    if contrat is None:
        ajouter(
            "liasse.schema_absent",
            "bloquant",
            "Schéma XSD du modèle introuvable : le dépôt EDI est impossible (les "
            "codes ne peuvent pas être vérifiés). Renseignez LIASSE_XSD_DIR ou "
            "utilisez le mode EFI assisté.",
        )
    if liasse["cellules_hors_schema"]:
        details = " ; ".join(
            f"tableau {item['tableau_id']}"
            + (f" / code {item['code_edi']}" if item.get("code_edi") else "")
            for item in liasse["cellules_hors_schema"]
        )
        ajouter(
            "liasse.code_hors_schema",
            "bloquant",
            f"{len(liasse['cellules_hors_schema'])} élément(s) du référentiel de "
            f"codification hors schéma ({details}) : corrigez la codification "
            "(voir referentiels/liasse/LISEZ-MOI.md).",
        )
    if liasse["cellules_rubrique_inconnue"]:
        details = " ; ".join(
            f"code {item['code_edi']} → {item['rubrique']}"
            for item in liasse["cellules_rubrique_inconnue"]
        )
        ajouter(
            "liasse.rubrique_inconnue",
            "bloquant",
            f"{len(liasse['cellules_rubrique_inconnue'])} rubrique(s) inconnue(s) du "
            f"catalogue ({details}) : la valeur n'est jamais devinée.",
        )
    if liasse["cellules_sans_valeur"]:
        ajouter(
            "liasse.rubrique_sans_valeur",
            "avertissement",
            f"{len(liasse['cellules_sans_valeur'])} cellule(s) du référentiel sans "
            "valeur disponible : source absente (immobilisations, stocks, paie…) — "
            "à compléter en EFI ou à saisir manuellement.",
        )
    if liasse["nb_cellules"] == 0:
        ajouter(
            "liasse.codification_absente",
            "avertissement",
            f"Aucune cellule alimentée pour le modèle « {liasse['modele']} » : le "
            "référentiel de codification ne décrit encore aucune correspondance "
            "`codeEdi` ↔ rubrique (annexe DGI « Codification des cellules » non "
            "fournie — ambiguïté A22).",
        )
    elif contrat is not None:
        ajouter(
            "liasse.recap",
            "information",
            f"Liasse {annee} ({liasse['libelle_modele']}) : {liasse['nb_tableaux']} "
            f"tableau(x), {liasse['nb_cellules']} cellule(s) alimentée(s), "
            f"{liasse['rubriques_disponibles']} rubrique(s) disponible(s) — "
            f"schéma {contrat['modele']} (id {contrat['modele_id']}, "
            f"{len(contrat['tableaux'])} tableaux, {len(contrat['codes'])} codes).",
        )
    if liasse["sources_indisponibles"]:
        ajouter(
            "liasse.sources_indisponibles",
            "avertissement",
            "Sources non mobilisables pour cette liasse : "
            + " ; ".join(
                f"{item['source']} ({item['message'][:120]})"
                for item in liasse["sources_indisponibles"]
            )
            + ".",
        )
    reconciliation = reconciliation_liasse_balance(db, company.id, annee, liasse)
    if reconciliation["ecarts"]:
        ajouter(
            "liasse.reconciliation_balance",
            "bloquant",
            f"{len(reconciliation['ecarts'])} cellule(s) ne concordent plus avec la "
            "balance (Σ liasses ≠ balance) : reconstruisez la liasse sur la balance "
            "définitive — écarts "
            + " ; ".join(
                f"compte {item['compte']} (liasse {item['valeur_liasse']} / "
                f"balance {item['valeur_balance']})"
                for item in reconciliation["ecarts"][:5]
            )
            + ".",
        )
    controles.extend(fiscal_liasse.controles_fiscaux(db, company, annee))
    return controles


def controles_bloquants(controles: list[dict]) -> list[dict]:
    """Controles bloquants (interdisent le depot de la liasse)."""
    return [controle for controle in controles if controle["niveau"] == "bloquant"]


def reconciliation_liasse_balance(
    db: Session, company_id: int, annee: int, liasse: dict
) -> dict:
    """Controle « **Σ liasses = balance** » des cellules issues de la balance.

    Chaque cellule dont la rubrique est un `solde:<compte>` (ou son inverse
    `-solde:<compte>`) est rapprochee du **solde du compte au grand livre** : tout
    ecart signale une valeur figee, une double affectation ou une balance modifiee
    apres construction de la liasse.
    """
    date_from, date_to = year_bounds(annee)
    soldes = {
        ligne["account_number"]: ligne["solde"]
        for ligne in movements(db, company_id, date_from, date_to)
    }
    lignes: list[dict] = []
    ecarts: list[dict] = []
    for tableau in liasse["tableaux"]:
        for cellule in tableau["cellules"]:
            specification = (cellule.get("rubrique") or "").strip()
            negation = specification.startswith("-")
            cle = specification.lstrip("-+").strip()
            if not cle.startswith("solde:"):
                continue
            compte = cle.split(":", 1)[1]
            attendu = soldes.get(compte)
            if attendu is None:
                continue
            if negation:
                attendu = money(-attendu)
            ecart = money((cellule.get("valeur_numerique") or Decimal("0")) - attendu)
            ligne = {
                "tableau_id": tableau["tableau_id"],
                "code_edi": cellule["code_edi"],
                "compte": compte,
                "valeur_liasse": cellule.get("valeur_numerique"),
                "valeur_balance": attendu,
                "ecart": ecart,
            }
            lignes.append(ligne)
            if ecart != 0:
                ecarts.append(ligne)
    return {
        "annee": annee,
        "lignes": lignes,
        "ecarts": ecarts,
        "nb_rapprochements": len(lignes),
        "conforme": not ecarts,
    }


# ---------------------------------------------------------------------------
# EFI assiste par tableau
# ---------------------------------------------------------------------------
def etat_de_saisie_efi_liasse(liasse: dict) -> list[dict]:
    """**EFI assiste** : une feuille par tableau, une ligne par cellule.

    Les cellules du referentiel **sans valeur disponible** sont presentes avec
    `etat = "a_completer"` (elles restent a saisir sur le teleservice SIMPL ou a
    alimenter par une rubrique) ; les autres portent leur valeur (`etat = "valeur"`).
    """
    sans_valeur = liasse.get("cellules_sans_valeur", [])
    feuilles: list[dict] = []
    for tableau in liasse["tableaux"]:
        lignes = [
            {
                "tableau_id": tableau["tableau_id"],
                "code_edi": cellule["code_edi"],
                "libelle": cellule["libelle"],
                "rubrique": cellule["rubrique"],
                "valeur": cellule["valeur"],
                "numero_ligne": cellule["numero_ligne"],
                "extra_field": cellule["extra_field"],
                "etat": "valeur",
                "source": cellule["source"],
            }
            for cellule in tableau["cellules"]
        ]
        lignes.extend(
            {
                "tableau_id": tableau["tableau_id"],
                "code_edi": cellule["code_edi"],
                "libelle": None,
                "rubrique": cellule["rubrique"],
                "valeur": None,
                "numero_ligne": None,
                "extra_field": None,
                "etat": "a_completer",
                "source": "référentiel de codification (source sans valeur)",
            }
            for cellule in sans_valeur
            if cellule["tableau_id"] == tableau["tableau_id"]
        )
        feuilles.append(
            {
                "onglet": f"Tableau {tableau['tableau_id']}",
                "tableau_id": tableau["tableau_id"],
                "libelle": tableau["libelle"],
                "extra_field": tableau["extra_field"],
                "lignes": lignes,
                "nb_lignes": len(lignes),
                "nb_a_completer": len([ligne for ligne in lignes if ligne["etat"] == "a_completer"]),
            }
        )
    return feuilles


def efi_liasse_csv(liasse: dict) -> bytes:
    """Export de l'**etat de saisie EFI** (CSV `;`, UTF-8 avec BOM pour Excel)."""
    tampon = io.StringIO()
    writer = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "modele",
            "tableau_id",
            "tableau_libelle",
            "code_edi",
            "libelle",
            "valeur",
            "numero_ligne",
            "extra_field",
            "etat",
            "origine",
        ]
    )
    for feuille in etat_de_saisie_efi_liasse(liasse):
        for ligne in feuille["lignes"]:
            writer.writerow(
                [
                    liasse["modele"],
                    ligne["tableau_id"],
                    feuille["libelle"] or "",
                    ligne["code_edi"],
                    ligne["libelle"] or "",
                    ligne["valeur"] or "",
                    "" if ligne["numero_ligne"] is None else ligne["numero_ligne"],
                    ligne["extra_field"] or "",
                    ligne["etat"],
                    ligne["source"] or "",
                ]
            )
    return tampon.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Fichier XML EDI (structure du schema officiel)
# ---------------------------------------------------------------------------
def xml_filename(company: Company, annee: int) -> str:
    """Nom du fichier de liasse : `LIASSE_<IF>_<exercice>.xml` (deterministe)."""
    identifiant = (company.fiscal_id or "IF").strip() or "IF"
    return f"LIASSE_{identifiant}_{annee}.xml"


def _balise(nom: str, valeur: object, *, niveau: int) -> str:
    """Balise XML indentee (la valeur est echappee)."""
    return f"{'  ' * niveau}<{nom}>{escape(str(valeur))}</{nom}>"


def _cellule_xml(cellule: dict, *, niveau: int = 4) -> list[str]:
    """`ValeurCellule` : `cellule/codeEdi`, `valeur` et `numeroLigne` (optionnel)."""
    return [
        "  " * niveau + "<ValeurCellule>",
        "  " * (niveau + 1) + "<cellule>",
        _balise("codeEdi", cellule["code_edi"], niveau=niveau + 2),
        "  " * (niveau + 1) + "</cellule>",
        _balise("valeur", cellule["valeur"], niveau=niveau + 1),
        *(
            [_balise("numeroLigne", cellule["numero_ligne"], niveau=niveau + 1)]
            if cellule.get("numero_ligne") is not None
            else []
        ),
        "  " * niveau + "</ValeurCellule>",
    ]


def build_liasse_xml(liasse: dict, *, forcer: bool = False) -> str:
    """Genere le fichier **XML EDI** de la liasse (structure du schema Simpl-IS).

    Structure : racine **`Liasse`** → `modele/id` (valeur **fixee par le XSD**, lue
    dans le contrat) → `resultatFiscal` (`identifiantFiscal`, `exerciceFiscalDu`,
    `exerciceFiscalAu`) → `groupeValeursTableau` → `ValeursTableau` → `tableau/id` →
    `groupeValeurs` → `ValeurCellule` (`cellule/codeEdi`, `valeur`, `numeroLigne`) →
    `extraFieldvaleurs`.

    Deux exigences du schema sont respectees strictement :

    - **au moins une `ValeurCellule` par tableau** : les tableaux sans cellule sont
      **omis** du fichier (ils restent visibles dans l'EFI assiste) ;
    - **au moins un tableau renseigne** : un document vide est **refuse**.

    Le bloc `extraFieldvaleurs` est emis **vide** : la semantique des `extraField`
    (code et valeur attendus) depend de l'annexe « Codification des cellules »
    **non fournie** (ambiguite A22) — aucune valeur n'est inventee, la saisie se fait
    sur le teleservice (mode EFI).
    """
    contrat = liasse.get("contrat")
    if contrat is None or liasse.get("modele_id") is None:
        raise LiasseError(
            "Schéma XSD du modèle indisponible : le fichier EDI ne peut pas être "
            "produit (l'`id` du modèle et les codes légaux sont lus dans le schéma). "
            "Utilisez l'EFI assisté ou renseignez `LIASSE_XSD_DIR`."
        )
    identifiant = (liasse["entete"].get("identifiantFiscal") or "").strip()
    if not identifiant:
        raise LiasseError(
            "Identifiant fiscal du déclarant absent : le fichier EDI serait rejeté."
        )
    tableaux = [tableau for tableau in liasse["tableaux"] if tableau["cellules"]]
    if not tableaux:
        raise LiasseError(
            "Aucune cellule renseignée : le schéma exige au moins un tableau avec une "
            "`ValeurCellule` — complétez le référentiel de codification (annexe DGI, "
            "ambiguïté A22) ou saisissez la liasse en EFI assisté."
        )
    lignes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<{liasse['racine']}>",
        "  <modele>",
        _balise("id", liasse["modele_id"], niveau=2),
        "  </modele>",
        "  <resultatFiscal>",
        _balise("identifiantFiscal", identifiant, niveau=2),
        _balise("exerciceFiscalDu", liasse["entete"]["exerciceFiscalDu"], niveau=2),
        _balise("exerciceFiscalAu", liasse["entete"]["exerciceFiscalAu"], niveau=2),
        "  </resultatFiscal>",
        "  <groupeValeursTableau>",
    ]
    for tableau in tableaux:
        lignes.extend(
            [
                "    <ValeursTableau>",
                "      <tableau>",
                _balise("id", tableau["tableau_id"], niveau=4),
                "      </tableau>",
                "      <groupeValeurs>",
            ]
        )
        for cellule in tableau["cellules"]:
            lignes.extend(_cellule_xml(cellule, niveau=4))
        lignes.extend(
            [
                "      </groupeValeurs>",
                "      <extraFieldvaleurs>",
                "      </extraFieldvaleurs>",
                "    </ValeursTableau>",
            ]
        )
    lignes.extend(["  </groupeValeursTableau>", f"</{liasse['racine']}>"])
    xml = "\n".join(lignes) + "\n"
    controle_taille(xml)
    return xml


def controle_taille(xml: str) -> int:
    """Verifie la taille du fichier (limite de format des teleservices DGI)."""
    taille = len(xml.encode("utf-8"))
    if taille > MAX_XML_BYTES:
        raise LiasseError(
            f"Fichier de liasse de {taille} octets : au-delà de la limite de "
            f"{MAX_XML_BYTES} octets acceptée par le téléservice. Contactez la DGI "
            "ou réduisez le nombre de cellules."
        )
    return taille
def valider_xsd(
    xml: str, *, modele: str | None = None, xsd_dir: Path | None = None
) -> dict:
    """Valide le fichier contre le **schéma XSD officiel** du modèle (lxml).

    Retourne `{"valide": True|False|None, "message", "erreurs", "schema"}` :

    - `True` : le document est **conforme** au schéma (et l'application ne dit
      jamais conforme sans cette preuve) ;
    - `False` : **refusé** — la liste des écarts (ligne, message) est fournie ;
    - `None` : schéma **introuvable** (`LIASSE_XSD_DIR`), donc validation
      **impossible** : le fichier n'est **ni conforme ni refusé**.

    Un fichier XML illisible (erreur de syntaxe) est également **refusé**.
    """
    modele_resolu = resoudre_modele(modele or MODELE_PAR_DEFAUT)
    chemin = Path(settings.liasse_racine) if xsd_dir is None else Path(xsd_dir)
    schema_path = chemin / f"{modele_resolu}.xsd"
    if not schema_path.is_file():
        return {
            "valide": None,
            "message": (
                f"Schéma « {modele_resolu} » introuvable ({schema_path}) : validation "
                "impossible. Le fichier n'est pas déclaré conforme pour autant."
            ),
            "erreurs": [],
            "schema": str(schema_path),
        }
    try:
        schema = etree.XMLSchema(etree.parse(str(schema_path)))
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError) as exc:
        raise LiasseError(f"Schéma XSD illisible « {schema_path} » : {exc}") from exc
    try:
        document = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        return {
            "valide": False,
            "message": f"Fichier XML illisible : {exc}",
            "erreurs": [{"ligne": exc.lineno, "message": str(exc)}],
            "schema": str(schema_path),
        }
    if schema.validate(document):
        return {
            "valide": True,
            "message": f"Fichier conforme au schéma {schema_path.name}.",
            "erreurs": [],
            "schema": str(schema_path),
        }
    erreurs = [
        {"ligne": erreur.line, "message": erreur.message}
        for erreur in list(schema.error_log)[:10]
    ]
    details = " ; ".join(f"ligne {item['ligne']} : {item['message']}" for item in erreurs)
    return {
        "valide": False,
        "message": f"Écarts au schéma XSD : {details}",
        "erreurs": erreurs,
        "schema": str(schema_path),
    }


def produire_liasse_xml(
    db: Session,
    company: Company,
    annee: int,
    *,
    modele: str = MODELE_PAR_DEFAUT,
    codification: list[dict] | None = None,
    xsd_dir: Path | None = None,
    forcer: bool = False,
) -> dict:
    """Construit la liasse, **la contrôle**, produit le XML et le **valide par XSD**.

    Regle de verite : le fichier n'est produit que si **aucun contrôle bloquant**
    ne subsiste et que le schéma le **valide** ; sinon une `LiasseError` est levée
    avec le détail (`forcer=True` n'existe que pour les tests et les reprises
    assistées, il ne rend jamais un fichier « conforme »).
    """
    liasse = construire_liasse(
        db, company, annee, modele=modele, codification=codification, xsd_dir=xsd_dir
    )
    controles = controles_liasse(db, company, annee, liasse)
    bloquants = controles_bloquants(controles)
    if bloquants and not forcer:
        raise LiasseError(
            "Liasse refusée avant dépôt : "
            + " ; ".join(f"{item['code']} — {item['message']}" for item in bloquants[:4])
        )
    xml = build_liasse_xml(liasse, forcer=forcer)
    validation = valider_xsd(xml, modele=liasse["modele"], xsd_dir=xsd_dir)
    if validation["valide"] is not True and not forcer:
        raise LiasseError(
            "Fichier refusé par le schéma XSD (jamais présumé conforme) : "
            + validation["message"]
        )
    return {
        "annee": annee,
        "modele": liasse["modele"],
        "libelle_modele": liasse["libelle_modele"],
        "xml": xml,
        "nom_fichier": xml_filename(company, annee),
        "taille": len(xml.encode("utf-8")),
        "validation": validation,
        "liasse": liasse,
        "controles": controles,
        "bloquants": bloquants,
    }


# ---------------------------------------------------------------------------
# Persistance : liasse_tables / liasse_cells + registre tax_declarations
# ---------------------------------------------------------------------------
def declaration_liasse(
    db: Session, company_id: int, annee: int
) -> TaxDeclaration | None:
    """Declaration de liasse de l'exercice (None si absente)."""
    return db.execute(
        select(TaxDeclaration).where(
            TaxDeclaration.company_id == company_id,
            TaxDeclaration.type == TYPE_DECLARATION,
            TaxDeclaration.periode == str(annee),
        )
    ).scalar_one_or_none()


def enregistrer_liasse(
    db: Session,
    company: Company,
    liasse: dict,
    *,
    mode_depot: str = DEPOT_EFI,
    xml: str | None = None,
    validation: dict | None = None,
    user_id: int | None = None,
) -> TaxDeclaration:
    """Enregistre la liasse : tableaux, cellules et **registre des declarations**.

    La declaration est **brouillon** tant qu'elle n'est pas deposee ; une
    declaration deja soumise (ou acceptee) est **figee** : la regeneration est
    refusee. Les tableaux et cellules de l'exercice sont remplaces (idempotence :
    rejouer la construction ne duplique rien). Lorsqu'un fichier est fourni, son
    nom, sa taille et son **empreinte SHA-256** sont conserves (preuve du fichier
    depose), ainsi que le **resultat de la validation XSD** dans les notes.
    """
    exercice = get_fiscal_year(db, company.id, liasse["annee"])
    if mode_depot not in DEPOT_MODES:
        raise LiasseError(
            f"Mode de dépôt « {mode_depot} » inconnu (valeurs admises : "
            f"{', '.join(DEPOT_MODES)})."
        )
    declaration = declaration_liasse(db, company.id, liasse["annee"])
    if declaration is not None and declaration.statut != DECLARATION_BROUILLON:
        raise LiasseError(
            f"La déclaration LIASSE {liasse['annee']} est déjà "
            f"« {declaration.statut_libelle} » : elle ne peut plus être régénérée "
            "(une déclaration déposée est figée)."
        )
    if declaration is None:
        declaration = TaxDeclaration(
            company_id=company.id,
            fiscal_year_id=exercice.id,
            type=TYPE_DECLARATION,
            periode=str(liasse["annee"]),
            regime=liasse["modele"],
            mode_depot=mode_depot,
            statut=DECLARATION_BROUILLON,
        )
        db.add(declaration)
        db.flush()
    declaration.regime = liasse["modele"]
    declaration.mode_depot = mode_depot
    declaration.fiscal_year_id = exercice.id
    declaration.nb_lignes = liasse["nb_cellules"]
    impot_du = liasse.get("impot_du")
    declaration.montant = (
        money(Decimal(str(impot_du))) if impot_du is not None else money(0)
    )
    declaration.notes = (
        f"Liasse {liasse['libelle_modele']} — {liasse['nb_tableaux']} tableau(x), "
        f"{liasse['nb_cellules']} cellule(s) alimentée(s)."
    )
    if xml is not None:
        contenu = xml.encode("utf-8")
        declaration.fichier_nom = xml_filename(company, liasse["annee"])
        declaration.fichier_hash = hashlib.sha256(contenu).hexdigest()
        declaration.fichier_taille = len(contenu)
    etat_validation = (
        {True: "conforme au schéma XSD", False: "REFUSÉ par le schéma XSD"}.get(
            validation["valide"] if validation else None,
            "validation XSD non réalisée",
        )
    )
    declaration.notes = f"{declaration.notes} Validation XSD : {etat_validation}."

    # Remplacement des tableaux/cellules de l'exercice (suppression explicite : les
    # cles etrangeres ne sont pas garanties par tous les SGBD).
    anciens = (
        db.execute(
            select(LiasseTableau.id).where(LiasseTableau.declaration_id == declaration.id)
        )
        .scalars()
        .all()
    )
    if anciens:
        db.execute(delete(LiasseCell).where(LiasseCell.liasse_table_id.in_(list(anciens))))
        db.execute(
            delete(LiasseTableau).where(LiasseTableau.declaration_id == declaration.id)
        )
        db.flush()

    for ordre, tableau in enumerate(liasse["tableaux"], start=1):
        entete = LiasseTableau(
            declaration_id=declaration.id,
            modele=liasse["modele"],
            tableau_id=tableau["tableau_id"],
            libelle=tableau["libelle"],
            extra_field=tableau["extra_field"],
            ordre=ordre,
        )
        db.add(entete)
        db.flush()
        for cellule in tableau["cellules"]:
            db.add(
                LiasseCell(
                    liasse_table_id=entete.id,
                    declaration_id=declaration.id,
                    tableau_id=tableau["tableau_id"],
                    code_edi=cellule["code_edi"],
                    rubrique=cellule["rubrique"],
                    libelle=cellule["libelle"],
                    valeur=cellule["valeur"],
                    valeur_numerique=cellule["valeur_numerique"],
                    numero_ligne=cellule["numero_ligne"],
                    extra_field=cellule["extra_field"],
                    source=cellule["source"],
                )
            )
    db.flush()
    log_action(
        db,
        action="LIASSE_RECORDED",
        entity="TaxDeclaration",
        entity_id=declaration.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "periode": declaration.periode,
            "modele": liasse["modele"],
            "mode_depot": mode_depot,
            "nb_tableaux": liasse["nb_tableaux"],
            "nb_cellules": liasse["nb_cellules"],
            "impot_du": str(declaration.montant),
            "fichier": declaration.fichier_nom,
            "hash": declaration.fichier_hash,
            "validation": (validation or {}).get("valide"),
        },
    )
    return declaration


def liasse_enregistree(db: Session, company_id: int, annee: int) -> dict:
    """Relit la liasse persistee d'un exercice (telle qu'utilisee par l'EFI)."""
    declaration = declaration_liasse(db, company_id, annee)
    if declaration is None:
        return {"annee": annee, "declaration": None, "tableaux": [], "nb_cellules": 0}
    tableaux: list[dict] = []
    for entete in db.execute(
        select(LiasseTableau)
        .where(LiasseTableau.declaration_id == declaration.id)
        .order_by(LiasseTableau.ordre, LiasseTableau.id)
    ).scalars():
        cellules = [
            {
                "tableau_id": cellule.tableau_id,
                "code_edi": cellule.code_edi,
                "rubrique": cellule.rubrique,
                "libelle": cellule.libelle,
                "valeur": cellule.valeur,
                "valeur_numerique": cellule.valeur_numerique,
                "numero_ligne": cellule.numero_ligne,
                "extra_field": cellule.extra_field,
                "source": cellule.source,
            }
            for cellule in db.execute(
                select(LiasseCell)
                .where(LiasseCell.liasse_table_id == entete.id)
                .order_by(LiasseCell.id)
            ).scalars()
        ]
        tableaux.append(
            {
                "tableau_id": entete.tableau_id,
                "libelle": entete.libelle,
                "extra_field": entete.extra_field,
                "cellules": cellules,
            }
        )
    return {
        "annee": annee,
        "declaration": declaration,
        "modele": declaration.regime,
        "tableaux": tableaux,
        "nb_tableaux": len(tableaux),
        "nb_cellules": sum(len(tableau["cellules"]) for tableau in tableaux),
    }


# ---------------------------------------------------------------------------
# Depot et accuse de reception (registre `tax_declarations`)
# ---------------------------------------------------------------------------
def soumettre_declaration(
    db: Session,
    declaration: TaxDeclaration,
    *,
    jour: date | None = None,
    accuse_le: date | None = None,
    motif_rejet: str | None = None,
    user_id: int | None = None,
) -> TaxDeclaration:
    """Enregistre le depot de la liasse (ou l'**accuse de reception** de la DGI).

    `accuse_le` renseigne : declaration **acceptee** ; `motif_rejet` renseigne :
    declaration **rejetee** (motif conserve pour la correction) ; sinon elle est
    **soumise** (accuse en attente). Une declaration acceptee ou rejetee est
    **definitive** : aucun nouveau depot. La **date de dépôt** initiale est
    conservee lorsque l'accuse de reception est enregistre ensuite.
    """
    jour_fourni = jour is not None
    jour = jour or date.today()
    if declaration.statut in (DECLARATION_ACCEPTEE, DECLARATION_REJETEE):
        raise LiasseError(
            f"La déclaration {declaration.type} {declaration.periode} est déjà "
            f"« {declaration.statut_libelle} » : aucun nouveau dépôt possible."
        )
    if accuse_le is not None:
        declaration.statut = DECLARATION_ACCEPTEE
        declaration.accuse_le = accuse_le
    elif motif_rejet:
        declaration.statut = DECLARATION_REJETEE
        declaration.motif_rejet = motif_rejet
    else:
        declaration.statut = DECLARATION_SOUMISE
    if jour_fourni or declaration.soumise_le is None:
        declaration.soumise_le = jour
    db.flush()
    log_action(
        db,
        action="LIASSE_SUBMITTED",
        entity="TaxDeclaration",
        entity_id=declaration.id,
        user_id=user_id,
        company_id=declaration.company_id,
        payload={
            "periode": declaration.periode,
            "statut": declaration.statut,
            "accuse_le": accuse_le.isoformat() if accuse_le else None,
            "motif_rejet": motif_rejet,
            "fichier": declaration.fichier_nom,
            "hash": declaration.fichier_hash,
        },
    )
    return declaration


def list_declarations(
    db: Session, company_id: int, *, type_declaration: str = TYPE_DECLARATION
) -> list[TaxDeclaration]:
    """Registre des declarations d'un dossier (liasse par defaut)."""
    return list(
        db.execute(
            select(TaxDeclaration)
            .where(
                TaxDeclaration.company_id == company_id,
                TaxDeclaration.type == type_declaration,
            )
            .order_by(TaxDeclaration.periode.desc())
        )
        .scalars()
        .all()
    )


def dossier_liasse(
    db: Session,
    company: Company,
    annee: int,
    *,
    modele: str = MODELE_PAR_DEFAUT,
    codification: list[dict] | None = None,
) -> dict:
    """Dossier de liasse d'un exercice : calcul fiscal, liasse, contrôles, registre.

    Point d'entree unique de l'API et de l'ecran : il n'**echoue pas** lorsque le
    schema, le referentiel ou une source manquent — les anomalies sont retournees
    comme **contrôles** (`liasse.schema_absent`, `liasse.codification_absente`…),
    et le fichier EDI reste refusé tant qu'un bloquant subsiste.
    """
    from app.services import fiscal_liasse  # noqa: PLC0415 - import local

    liasse = construire_liasse(db, company, annee, modele=modele, codification=codification)
    controles = controles_liasse(db, company, annee, liasse)
    return {
        "annee": annee,
        "modele": liasse["modele"],
        "libelle_modele": liasse["libelle_modele"],
        "liasse": liasse,
        "controles": controles,
        "bloquants": controles_bloquants(controles),
        "fiscal": fiscal_liasse.dossier_is(db, company, annee),
        "efi": etat_de_saisie_efi_liasse(liasse),
        "declarations": list_declarations(db, company.id),
        "declaration": declaration_liasse(db, company.id, annee),
        "reconciliation": reconciliation_liasse_balance(db, company.id, annee, liasse),
    }