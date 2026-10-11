"""Declaration des traitements et salaires - DTS « 9421 » (P1.4).

Produit la **declaration annuelle des traitements et salaires** deposee sur les
teleservices **SIMPL** de la DGI, dans les deux modes prevus par le guide :

- **EDI** : fichier **XML** genere par le logiciel (`build_dts_xml`), depose tel quel ;
- **EFI** : **etat de saisie** pour la saisie assistee en ligne
  (`etat_de_saisie_efi`), onglet par onglet.

References
----------
- **Guide DGI « Declaration des traitements et salaries » (9421)** : formulaire en
  onglets — *personnel permanent* et *salaries beneficiant de l'exoneration*
  (art. 57-20° du CGI) ; documents scannes a zipper avant insertion.
- **CGI / LF 2026** : IR retenu a la source (bareme historisé de `rates_ma`),
  deduction pour charges de famille, frais professionnels, exoneration des
  nouveaux recrutements (36 mois).
- **CNSS / AMO 2026** : parts salariale et patronale, plafond de 6 000 DH.

⚠️ **Avertissement trace (CDC § 8, ecart n° 6 et ambiguite A7)** : le **XSD du
fichier DTS n'est pas disponible** dans le referentiel fourni. La structure XML
produite ici reprend l'organisation du formulaire (declarant, personnel
permanent, salaries exoneres, totaux) mais **n'a pas pu etre validee contre le
schema officiel** : elle est explicitement signalee comme **a confronter au XSD**
dans `modele["avertissements"]`. Des que le schema est obtenu, le renseigner
dans `settings.dts_xsd_path` : la validation XSD s'active alors automatiquement
(`valider_xsd`). En attendant, le **mode EFI assiste** reste utilisable.

Regle de verite
---------------
La declaration est **deduite des bulletins valides** de l'exercice : le total
declare est **reconcilie** avec les bulletins **et** avec la comptabilite
(soldes des comptes 617x), conformement au critere « Σ bulletins = ecriture =
declaration » du CDC § 3.4.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.core.rates_ma import money
from app.models import Company, Employee, TaxDeclaration
from app.models.declaration import (
    DECLARATION_BROUILLON,
    DECLARATION_DTS,
    DECLARATION_SOUMISE,
    DEPOT_EDI,
    DEPOT_EFI,
    DEPOT_MODES,
)
from app.services.accounting import AccountingError
from app.services.payroll import (
    _bulletins_annee,
    cumuls_salarie,
    etat_cotisations,
)
from app.services.reporting import movements, year_bounds

MODE_DTS = (DEPOT_EDI, DEPOT_EFI)
RACINES_CHARGES_PERSONNEL = ("617",)
MAX_XML_BYTES = 1_000_000  # limite de format des teleservices (comme la TVA RD)

# ---------------------------------------------------------------------------
# Modele EDI officiel V5.1 : categories de personnel et racine du fichier
# ---------------------------------------------------------------------------
# L'exemple officiel (`EDI_DTS_Exemples_V5.1.xml`) distingue **trois listes** :
# personnel permanent (PP), personnel occasionnel (PO) et stagiaires (STG). La
# correspondance avec les types de contrat est **une hypothese de travail** a
# confirmer par l'expert-comptable (voir CDC § 9.14, ambiguite A17).
CATEGORIE_PERMANENT = "PP"
CATEGORIE_OCCASIONNEL = "PO"
CATEGORIE_STAGIAIRE = "STG"
CONTRATS_PERMANENTS = ("cdi", "cdd")
CONTRATS_OCCASIONNELS = ("anapec", "interim")
CONTRATS_STAGIAIRES = ("stage", "apprentissage")
CATEGORIE_LABELS = {
    CATEGORIE_PERMANENT: "Personnel permanent",
    CATEGORIE_OCCASIONNEL: "Personnel occasionnel",
    CATEGORIE_STAGIAIRE: "Stagiaires",
}
RACINE_XML = "TraitementEtSalaire"
SCHEMA_XML = "traitementSalaire.xsd"
ESPACE_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def categorie_personnel(employe: Employee) -> str:
    """Categorie de la DTS (PP / PO / STG) deduite du type de contrat."""
    contrat = (employe.type_contrat or "cdi").lower()
    if contrat in CONTRATS_STAGIAIRES:
        return CATEGORIE_STAGIAIRE
    if contrat in CONTRATS_OCCASIONNELS:
        return CATEGORIE_OCCASIONNEL
    return CATEGORIE_PERMANENT


def nom_et_prenom(nom_complet: str | None) -> tuple[str, str]:
    """Separe nom et prenom (le formulaire 9421 les demande distinctement).

    Le modele interne ne porte qu'un champ `nom` : le premier mot est considere
    comme le **nom** et le reste comme le **prenom** (hypothese a confirmer, voir
    CDC § 9.14, ambiguite A18).
    """
    morceaux = str(nom_complet or "").strip().split(maxsplit=1)
    if not morceaux:
        return "", ""
    if len(morceaux) == 1:
        return morceaux[0], ""
    return morceaux[0], morceaux[1]


class DtsError(AccountingError):
    """Erreur de preparation ou de generation de la DTS « 9421 »."""


# ---------------------------------------------------------------------------
# Modele de declaration (donnees de la DTS)
# ---------------------------------------------------------------------------
def _salarie_dts(db: Session, employe: Employee, annee: int) -> dict:
    """Ligne « salarie » de la DTS : identite, cumuls annuels et IR retenu."""
    cumuls = cumuls_salarie(db, employe.company_id, employe.id, annee)
    nom, prenom = nom_et_prenom(employe.nom)
    return {
        "matricule": employe.matricule,
        "nom": nom,
        "prenom": prenom,
        "nom_complet": employe.nom,
        "categorie": categorie_personnel(employe),
        "cin": employe.cin,
        "numero_cnss": employe.cnss,
        "situation_familiale": employe.situation_familiale,
        "personnes_a_charge": employe.personnes_a_charge,
        "date_entree": employe.date_entree,
        "date_sortie": employe.date_sortie,
        "fonction": employe.fonction,
        "adresse": employe.adresse,
        "exonere_art_57_20": bool(employe.exoneration_art_57_20),
        "brut_imposable": cumuls["brut"],
        "cotisations_sociales": cumuls["cotisations"],
        "ir_retenu": cumuls["ir"],
        "net_a_payer": cumuls["net"],
        "cout_employeur": cumuls["cout_employeur"],
        "mois": sorted(cumuls["mois"]),
    }


def construire_dts(
    db: Session, company: Company, annee: int, *, mode: str = DEPOT_EDI
) -> dict:
    """Construit la DTS d'un exercice a partir des bulletins valides.

    Retourne le **modele declaratif** (declarant, personnel permanent, salaries
    exoneres art. 57-20°, cotisations, totaux) et les **controles** : coherence
    des identifiants, reconciliation avec la comptabilite (comptes `617x`) et
    avertissement sur l'absence de XSD officiel (ecart n° 6).
    """
    if mode not in DEPOT_MODES:
        raise DtsError(
            f"Mode de dépôt « {mode} » inconnu (valeurs admises : "
            f"{', '.join(DEPOT_MODES)})."
        )
    bulletins = _bulletins_annee(db, company.id, annee)
    if not bulletins:
        raise DtsError(
            f"Aucun bulletin de paie pour l'exercice {annee} : la DTS « 9421 » ne "
            "peut pas être préparée (préparez et validez la paie)."
        )
    employes: dict[int, Employee] = {}
    for bulletin in bulletins:
        employe = db.get(Employee, bulletin.employee_id)
        if employe is not None:
            employes.setdefault(employe.id, employe)
    salaries = [
        _salarie_dts(db, employe, annee)
        for employe in sorted(employes.values(), key=lambda item: item.matricule)
    ]
    permanents = [s for s in salaries if s["categorie"] == CATEGORIE_PERMANENT]
    occasionnels = [s for s in salaries if s["categorie"] == CATEGORIE_OCCASIONNEL]
    stagiaires = [s for s in salaries if s["categorie"] == CATEGORIE_STAGIAIRE]
    exoneres = [s for s in salaries if s["exonere_art_57_20"]]
    cotisations = etat_cotisations(db, company.id, annee)

    def total(lignes: list[dict], cle: str) -> Decimal:
        return money(sum((ligne[cle] for ligne in lignes), Decimal("0")))

    modele = {
        "type": DECLARATION_DTS,
        "annee": annee,
        "mode": mode,
        "periode": str(annee),
        "declarant": {
            "identifiant_fiscal": company.fiscal_id,
            "nom": company.name,
            "ice": company.ice,
            "numero_cnss": company.cnss_number,
            "rc": company.rc,
            "adresse": company.address,
            "ville": company.city,
        },
        # Listes officielles de la declaration (onglets du formulaire 9421)
        "personnel_permanent": permanents,
        "personnel_occasionnel": occasionnels,
        "stagiaires": stagiaires,
        # Vue interne : salaries beneficiant de l'exoneration art. 57-20°
        "salaries_exoneres": exoneres,
        "cotisations": cotisations["totaux"],
        "totaux": {
            "nb_salaries": len(salaries),
            "brut_imposable": total(salaries, "brut_imposable"),
            "cotisations_sociales": total(salaries, "cotisations_sociales"),
            "ir_retenu": total(salaries, "ir_retenu"),
            "net_a_payer": total(salaries, "net_a_payer"),
            "cnss_total": cotisations["totaux"]["total_cnss"],
            "cout_employeur": total(salaries, "cout_employeur"),
        },
        # Totaux **normalises** du modele EDI V5.1 (balises du fichier officiel)
        "totaux_edi": {
            "totalMtRevenuBrutImposablePP": total(permanents, "brut_imposable"),
            "totalMtRevenuNetImposablePP": total(permanents, "net_a_payer"),
            "totalMtTotalDeductionPP": total(permanents, "cotisations_sociales"),
            "totalMtIrPrelevePP": total(permanents, "ir_retenu"),
            "totalMtBrutSommesPO": total(occasionnels, "brut_imposable"),
            "totalIrPrelevePO": total(occasionnels, "ir_retenu"),
            "totalMtBrutTraitSalaireSTG": total(stagiaires, "brut_imposable"),
            "totalMtBrutIndemnitesSTG": money(0),
            "totalMtRetenuesSTG": total(stagiaires, "cotisations_sociales"),
            "totalMtRevenuNetImpSTG": total(stagiaires, "net_a_payer"),
            "totalSommePayeRTS": total(salaries, "net_a_payer"),
            "totalmtAnuuelRevenuSalarial": total(salaries, "brut_imposable"),
            "totalmtAbondement": money(0),
            "montantPermanent": total(permanents, "ir_retenu"),
            "montantOccasionnel": total(occasionnels, "ir_retenu"),
            "montantStagiaire": total(stagiaires, "ir_retenu"),
        },
    }
    modele["controles"] = _controles_dts(db, company, annee, modele)
    return modele


def _comptabilite_personnel(db: Session, company_id: int, annee: int) -> Decimal:
    """Charges de personnel comptabilisees (racines 617x) sur l'exercice."""
    date_from, date_to = year_bounds(annee)
    total = Decimal("0")
    for ligne in movements(db, company_id, date_from, date_to):
        if ligne["account_number"][:3] in RACINES_CHARGES_PERSONNEL:
            total += ligne["solde"]
    return money(total)


def _controles_dts(
    db: Session, company: Company, annee: int, modele: dict
) -> list[dict]:
    """Controles avant depot : identifiants et reconciliation avec la comptabilite."""
    controles: list[dict] = []

    def ajouter(code: str, niveau: str, message: str) -> None:
        controles.append({"code": code, "niveau": niveau, "message": message})

    if not (company.fiscal_id or "").strip():
        ajouter(
            "dts.if_manquant",
            "bloquant",
            "Identifiant fiscal (IF) du déclarant manquant : la DTS ne peut pas "
            "être déposée.",
        )
    if not (company.ice or "").strip():
        ajouter(
            "dts.ice_manquant",
            "avertissement",
            "ICE de l'employeur non renseigné (fiche Société).",
        )
    if not (company.cnss_number or "").strip():
        ajouter(
            "dts.cnss_societe_manquant",
            "avertissement",
            "N° CNSS de l'employeur non renseigné (fiche Société).",
        )
    for salarie in modele["personnel_permanent"] + modele["salaries_exoneres"]:
        if not (salarie["numero_cnss"] or "").strip():
            ajouter(
                "dts.cnss_salarie_manquant",
                "bloquant",
                f"{salarie['matricule']} {salarie['nom']} : n° CNSS manquant — "
                "la déclaration est refusée (contrôle bloquant n° 6 du CDC § 3.4).",
            )
        if not (salarie["cin"] or "").strip():
            ajouter(
                "dts.cin_manquante",
                "avertissement",
                f"{salarie['matricule']} {salarie['nom']} : CIN non renseignée.",
            )
    comptable = _comptabilite_personnel(db, company.id, annee)
    cout = money(modele["totaux"]["cout_employeur"])
    if comptable != cout:
        ajouter(
            "dts.reconciliation_comptable",
            "avertissement",
            f"Charges de personnel comptabilisées (617x) : {comptable} DH contre "
            f"coût employeur des bulletins {cout} DH — écart "
            f"{money(comptable - cout)} DH à justifier (paie non validée, "
            "écritures manuelles, charges d'un autre exercice).",
        )
    else:
        ajouter(
            "dts.reconciliation_comptable",
            "information",
            f"Réconciliation : Σ bulletins (coût employeur {cout} DH) = comptes "
            "617x de l'exercice.",
        )
    if modele["mode"] == DEPOT_EDI:
        ajouter(
            "dts.schema_absent",
            "avertissement",
            "Schéma XSD de la DTS (`traitementSalaire.xsd`) non fourni par la DGI "
            "(écart n° 6) : le fichier XML suit le modèle officiel V5.1 (exemple du "
            "référentiel) mais **ne peut pas être validé** par l'application. "
            "Renseignez `DTS_XSD_PATH` dès réception du schéma ; à défaut, utilisez "
            "le mode EFI assisté.",
        )
    for salarie in modele["personnel_permanent"] + modele["personnel_occasionnel"] + modele["stagiaires"]:
        if not salarie["prenom"]:
            ajouter(
                "dts.prenom_incomplet",
                "avertissement",
                f"{salarie['matricule']} : le nom saisi ne permet pas d'extraire un "
                "prénom (le formulaire 9421 demande nom et prénom séparés) — "
                "saisissez « NOM Prénom » dans la fiche salarié.",
            )
    ajouter(
        "dts.recap",
        "information",
        f"DTS {annee} : {modele['totaux']['nb_salaries']} salarié(s), brut "
        f"{modele['totaux']['brut_imposable']} DH, IR retenu "
        f"{modele['totaux']['ir_retenu']} DH, CNSS/AMO "
        f"{modele['totaux']['cnss_total']} DH.",
    )
    return controles


def controles_bloquants(controles: list[dict]) -> list[dict]:
    """Controles bloquants de la DTS (interdisent la generation du fichier)."""
    return [controle for controle in controles if controle["niveau"] == "bloquant"]


# ---------------------------------------------------------------------------
# Fichier XML EDI (mode « EDI »)
# ---------------------------------------------------------------------------
def xml_filename(company: Company, annee: int) -> str:
    """Nom du fichier DTS : `DTS_<IF>_<exercice>.xml` (deterministe)."""
    identifiant = (company.fiscal_id or "IF").strip() or "IF"
    return f"DTS_{identifiant}_{annee}.xml"


def _balise(nom: str, valeur: object, *, niveau: int = 1, montant: bool = False) -> str:
    """Balise XML indentee ; les montants sont ecrits a 2 decimales (point)."""
    if valeur is None or valeur == "":
        return ""
    if montant:
        texte = f"{Decimal(str(valeur)):.2f}"
    elif isinstance(valeur, date):
        texte = valeur.isoformat()
    else:
        texte = str(valeur)
    return f"{'  ' * niveau}<{nom}>{escape(texte)}</{nom}>"


def _salarie_xml(salarie: dict, *, niveau: int = 3) -> list[str]:
    """Balises d'un salarie dans sa liste (modele officiel : nom et prenom separes).

    Les montants individuels reprennent le vocabulaire des totaux officiels ; leur
    nom exact devra etre confirme sur l'annexe « correspondance balise /
    declaration » du referentiel DGI (voir CDC § 9.14, ambiguite A19).
    """
    return [
        _balise("nom", salarie["nom"], niveau=niveau),
        _balise("prenom", salarie["prenom"], niveau=niveau),
        _balise("adressePersonnelle", salarie.get("adresse"), niveau=niveau),
        _balise("numCNI", salarie.get("cin"), niveau=niveau),
        _balise("numCE", salarie.get("numero_cnss"), niveau=niveau),
        _balise("matricule", salarie.get("matricule"), niveau=niveau),
        _balise(
            "montantRevenuBrutImposable",
            salarie["brut_imposable"],
            niveau=niveau,
            montant=True,
        ),
        _balise(
            "montantRetenues",
            salarie["cotisations_sociales"],
            niveau=niveau,
            montant=True,
        ),
        _balise("montantIrPreleve", salarie["ir_retenu"], niveau=niveau, montant=True),
        _balise(
            "montantRevenuNetImposable",
            salarie["net_a_payer"],
            niveau=niveau,
            montant=True,
        ),
    ]


def controle_taille(xml: str) -> int:
    """Verifie la taille du fichier (limite de format des teleservices DGI)."""
    taille = len(xml.encode("utf-8"))
    if taille > MAX_XML_BYTES:
        raise DtsError(
            f"Fichier DTS de {taille} octets : au-delà de la limite de "
            f"{MAX_XML_BYTES} octets acceptée par le téléservice. Fractionnez la "
            "déclaration ou contactez la DGI."
        )
    return taille


def valider_xsd(xml: str) -> dict:
    """Valide le fichier contre le **XSD officiel** s'il est disponible.

    `settings.dts_xsd_path` : chemin du schéma fourni par la DGI. Tant que le
    schéma n'est pas renseigné, la fonction retourne `valide=None` avec un
    **avertissement explicite** (écart n° 6) : l'application ne déclare jamais
    conforme un fichier qu'elle n'a pas pu valider.
    """
    chemin = getattr(settings, "dts_xsd_path", None)
    if not chemin or not str(chemin).strip():
        return {
            "valide": None,
            "message": (
                "Schéma XSD de la DTS non disponible (écart n° 6) : validation "
                "impossible. Renseignez `DTS_XSD_PATH` dès réception du schéma "
                "officiel de la DGI."
            ),
        }
    try:  # pragma: no cover - depend de la fourniture du schema par la DGI
        from lxml import etree

        schema = etree.XMLSchema(etree.parse(str(chemin)))
        document = etree.fromstring(xml.encode("utf-8"))
        if schema.validate(document):
            return {"valide": True, "message": f"Fichier conforme à {chemin}."}
        details = " ; ".join(
            f"ligne {erreur.line} : {erreur.message}"
            for erreur in list(schema.error_log)[:5]
        )
        return {"valide": False, "message": f"Écarts au schéma XSD : {details}"}
    except Exception as exc:  # pragma: no cover - schema illisible
        raise DtsError(f"Validation XSD impossible ({chemin}) : {exc}") from exc


def build_dts_xml(modele: dict, *, forcer: bool = False) -> str:
    """Genere le fichier **XML EDI** de la DTS « 9421 » (modele officiel V5.1).

    Structure reprise de l'**exemple officiel** du referentiel DGI
    (`EDI_DTS_Exemples_V5.1.xml`) : racine **`TraitementEtSalaire`**, schema
    `traitementSalaire.xsd` (**sans namespace**), informations du declarant en
    **balises plates**, totaux **normalises** (`totalMt…PP`, `…PO`, `…STG`) et
    **trois listes de personnel** (`listPersonnelPermanent`,
    `listPersonnelOccasionnel`, `listStagiaires`).

    Le XSD officiel (`traitementSalaire.xsd`) n'etant pas fourni par la DGI, la
    generation reste refusee tant qu'un **controle bloquant** subsiste (n° CNSS
    manquant, IF absent) ; `valider_xsd()` realise le controle de conformite des
    que le schema est renseigne (`DTS_XSD_PATH`).
    """
    bloquants = controles_bloquants(modele.get("controles", []))
    if bloquants and not forcer:
        raise DtsError(
            "Génération du fichier DTS refusée — contrôles bloquants : "
            + " | ".join(controle["message"] for controle in bloquants)
        )
    declarant = modele["declarant"]
    totaux_edi = modele["totaux_edi"]
    lignes: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lignes.append(
        f'<{RACINE_XML} xmlns:xsi="{ESPACE_XSI}" '
        f'xsi:noNamespaceSchemaLocation="{SCHEMA_XML}">'
    )
    # Identite du declarant : balises PLATES (aucun element <declarant>)
    lignes.extend(
        [
            _balise("identifiantFiscal", declarant["identifiant_fiscal"], niveau=1),
            _balise("nom", None, niveau=1),
            _balise("prenom", None, niveau=1),
            _balise("raisonSociale", declarant["nom"], niveau=1),
            _balise("exerciceFiscalDu", f"{modele['annee']}-01-01", niveau=1),
            _balise("exerciceFiscalAu", f"{modele['annee']}-12-31", niveau=1),
            _balise("annee", modele["annee"], niveau=1),
            _balise("adresse", declarant.get("adresse"), niveau=1),
            _balise("numeroCNSS", declarant.get("numero_cnss"), niveau=1),
            _balise("numeroRC", declarant.get("rc"), niveau=1),
            _balise("effectifTotal", totaux_edi.get("effectifTotal"), niveau=1),
            _balise(
                "nbrPersoPermanent", len(modele["personnel_permanent"]), niveau=1
            ),
            _balise(
                "nbrPersoOccasionnel", len(modele["personnel_occasionnel"]), niveau=1
            ),
            _balise("nbrStagiaires", len(modele["stagiaires"]), niveau=1),
        ]
    )
    # Totaux normalises du modele officiel
    lignes.extend(
        _balise(cle, totaux_edi[cle], niveau=1, montant=True)
        for cle in (
            "totalMtRevenuBrutImposablePP",
            "totalMtRevenuNetImposablePP",
            "totalMtTotalDeductionPP",
            "totalMtIrPrelevePP",
            "totalMtBrutSommesPO",
            "totalIrPrelevePO",
            "totalMtBrutTraitSalaireSTG",
            "totalMtBrutIndemnitesSTG",
            "totalMtRetenuesSTG",
            "totalMtRevenuNetImpSTG",
            "totalSommePayeRTS",
            "totalmtAnuuelRevenuSalarial",
            "totalmtAbondement",
            "montantPermanent",
            "montantOccasionnel",
            "montantStagiaire",
        )
    )
    # Trois listes de personnel (onglets du formulaire 9421)
    for nom_liste, nom_element, cle in (
        ("listPersonnelPermanent", "PersonnelPermanent", "personnel_permanent"),
        ("listPersonnelOccasionnel", "PersonnelOccasionnel", "personnel_occasionnel"),
        ("listStagiaires", "Stagiaire", "stagiaires"),
    ):
        lignes.append(f"  <{nom_liste}>")
        for salarie in modele[cle]:
            lignes.append(f"    <{nom_element}>")
            lignes.extend(_salarie_xml(salarie, niveau=3))
            lignes.append(f"    </{nom_element}>")
        lignes.append(f"  </{nom_liste}>")
    lignes.append(f"</{RACINE_XML}>")
    xml = "\n".join(ligne for ligne in lignes if ligne) + "\n"
    controle_taille(xml)
    return xml


def etat_de_saisie_efi(modele: dict) -> list[dict]:
    """**Etat de saisie EFI** : une ligne par salarie, prete a recopier en ligne.

    Reprend les **trois onglets** du formulaire 9421 (personnel permanent,
    personnel occasionnel, stagiaires) : le comptable saisit les champs du
    formulaire a partir de cet etat quand le fichier EDI n'est pas utilise.
    """
    lignes: list[dict] = []
    for onglet, salaries in (
        ("personnel permanent", modele["personnel_permanent"]),
        ("personnel occasionnel", modele["personnel_occasionnel"]),
        ("stagiaires", modele["stagiaires"]),
    ):
        for salarie in salaries:
            lignes.append(
                {
                    "onglet": onglet,
                    "categorie": salarie["categorie"],
                    "matricule": salarie["matricule"],
                    "nom": salarie["nom"],
                    "prenom": salarie["prenom"],
                    "cin": salarie["cin"],
                    "numero_cnss": salarie["numero_cnss"],
                    "situation_familiale": salarie["situation_familiale"],
                    "personnes_a_charge": salarie["personnes_a_charge"],
                    "date_entree": salarie["date_entree"],
                    "fonction": salarie["fonction"],
                    "exonere_art_57_20": salarie["exonere_art_57_20"],
                    "brut_imposable": salarie["brut_imposable"],
                    "cotisations_sociales": salarie["cotisations_sociales"],
                    "ir_retenu": salarie["ir_retenu"],
                    "net_a_payer": salarie["net_a_payer"],
                }
            )
    return lignes


# ---------------------------------------------------------------------------
# Registre des declarations (`tax_declarations`)
# ---------------------------------------------------------------------------
def declaration_par_periode(
    db: Session, company_id: int, type_declaration: str, periode: str
) -> TaxDeclaration | None:
    """Declaration d'un type et d'une periode (None si absente)."""
    return db.execute(
        select(TaxDeclaration).where(
            TaxDeclaration.company_id == company_id,
            TaxDeclaration.type == type_declaration,
            TaxDeclaration.periode == periode,
        )
    ).scalar_one_or_none()


def enregistrer_declaration(
    db: Session,
    company: Company,
    modele: dict,
    *,
    xml: str | None = None,
    user_id: int | None = None,
) -> TaxDeclaration:
    """Enregistre la DTS dans le **registre des declarations** (statut brouillon).

    Le fichier produit est conserve avec son nom, sa taille et son **empreinte
    SHA-256** : l'empreinte permet de prouver plus tard que le fichier depose est
    bien celui genere par l'application.
    """
    periode = modele["periode"]
    existante = declaration_par_periode(db, company.id, modele["type"], periode)
    if existante is not None and existante.statut != DECLARATION_BROUILLON:
        raise DtsError(
            f"La déclaration {modele['type']} {periode} est déjà "
            f"« {existante.statut_libelle} » : elle ne peut plus être régénérée "
            "(une déclaration déposée est figée)."
        )
    declaration = existante or TaxDeclaration(
        company_id=company.id, type=modele["type"], periode=periode
    )
    declaration.regime = modele["mode"]
    declaration.mode_depot = modele["mode"]
    declaration.statut = DECLARATION_BROUILLON
    declaration.montant = modele["totaux"]["ir_retenu"]
    declaration.nb_lignes = modele["totaux"]["nb_salaries"]
    declaration.deposant = modele["declarant"]["nom"]
    declaration.notes = (
        "DTS « 9421 » générée depuis les bulletins de paie "
        f"({modele['totaux']['nb_salaries']} salarié(s))."
    )
    if xml is not None:
        contenu = xml.encode("utf-8")
        declaration.fichier_nom = xml_filename(company, modele["annee"])
        declaration.fichier_hash = hashlib.sha256(contenu).hexdigest()
        declaration.fichier_taille = len(contenu)
    db.add(declaration)
    db.flush()
    log_action(
        db,
        action="DTS_RECORDED",
        entity="TaxDeclaration",
        entity_id=declaration.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "periode": periode,
            "mode": modele["mode"],
            "montant_ir": str(declaration.montant),
            "nb_salaries": declaration.nb_lignes,
            "fichier": declaration.fichier_nom,
            "hash": declaration.fichier_hash,
        },
    )
    return declaration


def soumettre_declaration(
    db: Session,
    declaration: TaxDeclaration,
    *,
    jour: date | None = None,
    accuse_le: date | None = None,
    motif_rejet: str | None = None,
    user_id: int | None = None,
) -> TaxDeclaration:
    """Enregistre le depot (ou l'accuse de reception) dans le registre.

    `accuse_le` renseigne : declaration **acceptee** ; `motif_rejet` renseigne :
    declaration **rejetee** (motif conserve pour la correction) ; sinon elle est
    **soumise** (accuse en attente).
    """
    jour = jour or date.today()
    if declaration.statut in ("acceptee", "rejetee"):
        raise DtsError(
            f"La déclaration {declaration.type} {declaration.periode} est déjà "
            f"« {declaration.statut_libelle} » : aucun nouveau dépôt possible."
        )
    if accuse_le is not None:
        declaration.statut = "acceptee"
        declaration.accuse_le = accuse_le
    elif motif_rejet:
        declaration.statut = "rejetee"
        declaration.motif_rejet = motif_rejet
    else:
        declaration.statut = DECLARATION_SOUMISE
    declaration.soumise_le = jour
    db.flush()
    log_action(
        db,
        action="DTS_SUBMITTED",
        entity="TaxDeclaration",
        entity_id=declaration.id,
        user_id=user_id,
        company_id=declaration.company_id,
        payload={
            "periode": declaration.periode,
            "statut": declaration.statut,
            "accuse_le": accuse_le.isoformat() if accuse_le else None,
            "motif_rejet": motif_rejet,
        },
    )
    return declaration


def list_declarations(
    db: Session, company_id: int, *, type_declaration: str | None = None
) -> list[TaxDeclaration]:
    """Registre des declarations d'un dossier (filtre par type si fourni)."""
    requete = select(TaxDeclaration).where(TaxDeclaration.company_id == company_id)
    if type_declaration:
        requete = requete.where(TaxDeclaration.type == type_declaration)
    return list(
        db.execute(requete.order_by(TaxDeclaration.periode.desc())).scalars().all()
    )


def pdf_bordereau_dts(modele: dict) -> bytes:
    """Fiche recapitulative de la DTS « 9421 » (bordereau du fichier depose).

    Reprend le declarant, le detail par salarie, les cotisations et les totaux,
    et **rappelle l'avertissement sur le XSD** : le document accompagne le
    fichier depose et sert de piece justificative interne.
    """
    from app.services.pdf import (  # noqa: PLC0415 - import local (anti-cycle)
        Colonne,
        Document,
        Tableau,
        rendre_pdf,
    )

    declarant = modele["declarant"]
    totaux = modele["totaux"]
    lignes = []
    for onglet, salaries in (
        ("permanent (PP)", modele["personnel_permanent"]),
        ("occasionnel (PO)", modele["personnel_occasionnel"]),
        ("stagiaires (STG)", modele["stagiaires"]),
    ):
        for salarie in salaries:
            lignes.append(
                [
                    onglet,
                    salarie["matricule"],
                    f"{salarie['nom']} {salarie['prenom']}".strip()[:28],
                    str(salarie["numero_cnss"] or "-"),
                    f"{salarie['brut_imposable']:.2f}",
                    f"{salarie['ir_retenu']:.2f}",
                    f"{salarie['net_a_payer']:.2f}",
                ]
            )
    tableaux = [
        Tableau(
            titre="Declarant",
            colonnes=(
                Colonne("Element", largeur=90),
                Colonne("Valeur", largeur=70, alignement="right"),
            ),
            lignes=[
                ["Societe", declarant["nom"]],
                ["Identifiant fiscal (IF)", str(declarant["identifiant_fiscal"] or "-")],
                ["ICE", str(declarant["ice"] or "-")],
                ["N° CNSS employeur", str(declarant["numero_cnss"] or "-")],
                ["Registre de commerce", str(declarant["rc"] or "-")],
                ["Adresse", f"{declarant['adresse'] or '-'} {declarant['ville'] or ''}"],
                ["Exercice declare", str(modele["annee"])],
                ["Mode de depot", modele["mode"]],
            ],
        ),
        Tableau(
            titre="Salaries declares",
            colonnes=(
                Colonne("Onglet", largeur=22),
                Colonne("Matricule", largeur=22),
                Colonne("Nom", largeur=48),
                Colonne("N° CNSS", largeur=28),
                Colonne("Brut", largeur=24, alignement="right"),
                Colonne("IR", largeur=22, alignement="right"),
                Colonne("Net", largeur=24, alignement="right"),
            ),
            lignes=lignes or [["-", "-", "aucun salarie", "-", "0,00", "0,00", "0,00"]],
            total=[
                "Total",
                "",
                f"{totaux['nb_salaries']} salarie(s)",
                "",
                f"{totaux['brut_imposable']:.2f}",
                f"{totaux['ir_retenu']:.2f}",
                f"{totaux['net_a_payer']:.2f}",
            ],
        ),
        Tableau(
            titre="Cotisations sociales et impots retenus",
            colonnes=(
                Colonne("Nature", largeur=95),
                Colonne("Montant", largeur=65, alignement="right"),
            ),
            lignes=[
                ["CNSS part salariale", f"{modele['cotisations']['cnss_salariale']:.2f} DH"],
                ["AMO part salariale", f"{modele['cotisations']['amo_salariale']:.2f} DH"],
                ["CNSS part patronale", f"{modele['cotisations']['cnss_patronale']:.2f} DH"],
                ["AMO part patronale", f"{modele['cotisations']['amo_patronale']:.2f} DH"],
                [
                    "Prestations familiales",
                    f"{modele['cotisations']['prestations_familiales']:.2f} DH",
                ],
                [
                    "Taxe de formation professionnelle",
                    f"{modele['cotisations']['taxe_formation']:.2f} DH",
                ],
                ["Total CNSS / AMO a verser", f"{totaux['cnss_total']:.2f} DH"],
                ["IR retenu a la source (a verser)", f"{totaux['ir_retenu']:.2f} DH"],
                ["Cout employeur total", f"{totaux['cout_employeur']:.2f} DH"],
            ],
        ),
    ]
    avertissement = next(
        (
            controle["message"]
            for controle in modele.get("controles", [])
            if controle["code"] == "dts.schema_absent"
        ),
        None,
    )
    document = Document(
        titre=f"DECLARATION DES TRAITEMENTS ET SALAIRES (9421) - {modele['annee']}",
        sous_titre=(
            "Fiche recapitulative du fichier transmis aux teleservices SIMPL (DGI) "
            "- modele EDI V5.1"
        ),
        entete=[
            f"{declarant['nom']} - IF {declarant['identifiant_fiscal'] or '-'} "
            f"- ICE {declarant['ice'] or '-'}",
            f"Exercice {modele['annee']} - mode {modele['mode']} "
            f"- fichier {xml_filename_preview(declarant, modele['annee'])}",
        ],
        tableaux=tableaux,
        pied=(
            "Document genere par Compta MA - declaration deduite des bulletins de "
            "paie valides."
        ),
        filigrane="PROVISOIRE" if avertissement else None,
    )
    return rendre_pdf(document)


def xml_filename_preview(declarant: dict, annee: int) -> str:
    """Nom de fichier attendu (apercu) a partir du declarant du modele."""
    identifiant = (declarant.get("identifiant_fiscal") or "IF").strip() or "IF"
    return f"DTS_{identifiant}_{annee}.xml"
