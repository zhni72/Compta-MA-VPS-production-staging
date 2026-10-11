"""Paie, bulletins, cotisations et ecritures comptables (P1.4).

Cycle de paie mensuel : **fiches salaries** et contrats, **calcul** des
bulletins (brut, IR, CNSS/AMO salariales, charges patronales, net), **ecriture
globale de paie**, **paiement** du net, **DTS « 9421 »** (module `edi_dts`) et
**etats** (livre de paie, journal de paie, recapitulatif annuel, cotisations).

References normatives
---------------------
- **CGI / LF 2026** : retenue a la source sur traitements et salaires
  (art. 57 et suivants) ; **bareme IR progressif** avec **deduction pour charges
  de famille** ; frais professionnels (35 % / 25 % plafonnes) ; exoneration des
  nouveaux recrutements (art. 57-20°, onglet dedie du formulaire 9421).
- **CNSS / AMO 2026** : part salariale (4,48 % plafonnee a 6 000 DH + 2,26 %
  AMO) et part patronale (8,98 % + 4,11 % AMO + 6,40 % prestations familiales
  + 1,60 % taxe de formation professionnelle).
- **CGNC / PCGE** (comptes verifies dans `plan_comptable_cgnc.csv`) :
  `61711` appointements · `61712` primes · `61713` indemnites et avantages ·
  `61741` cotisations de securite sociale · `61742` retraite · `61743` mutuelle ·
  `61744` prestations familiales · `61761` assurances groupe · `61768` autres
  charges sociales (taxe de formation) · **`4432` remunerations dues au
  personnel** (dette du net a payer) · `4434` oppositions · `4441` CNSS ·
  `4443` caisses de retraite · `4445` mutuelles · `4448` autres organismes
  sociaux · `4452` Etat - impots et taxes (IR retenu a la source) ·
  `3431` avances et acomptes au personnel (regularisation des avances).
- **P1.6** : aucune saisie ni recalcul retroactif sur une periode verrouillee ;
  ecriture de paie forcement **equilibree**.
- **Loi 09-08 (CNDP)** : CIN, n° CNSS et situation de famille sont des donnees
  personnelles (journalisation, conservation 10 ans).

Regle de verite
---------------
Le bulletin est **recalcule** a partir du contrat en vigueur et des variables de
la periode ; l'ecriture de paie est **deduite des bulletins** (aucun montant
n'est saisi a la main), et la DTS est **reconciliee** avec les deux.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.rates_ma import (
    QUOTITE_CESSIBLE_AVERTISSEMENT,
    BaremeIndisponible,
    bareme_paie,
    compute_cnss,
    compute_ir_monthly,
    frais_professionnels_mensuels,
    money,
)
from app.models import (
    ENTRY_STATUS_VALIDATED,
    Company,
    Employee,
    Entry,
    EntryLine,
    PayContract,
    PayrollRun,
    Payslip,
    PayslipLine,
)
from app.models.payroll import (
    CONTRAT_LABELS,
    CONTRATS,
    PAIEMENTS_PAIE,
    PAIEMENT_PAIE_LABELS,
    PAYROLL_STATUS_DRAFT,
    PAYROLL_STATUS_PAID,
    PAYROLL_STATUS_VALIDATED,
    RUBRIQUE_AMO,
    RUBRIQUE_ASSURANCE_GROUPE,
    RUBRIQUE_AVANCES,
    RUBRIQUE_AVANTAGES,
    RUBRIQUE_CNSS,
    RUBRIQUE_HEURES_SUP,
    RUBRIQUE_INDEMNITES,
    RUBRIQUE_IR,
    RUBRIQUE_LABELS,
    RUBRIQUE_MUTUELLE,
    RUBRIQUE_NET,
    RUBRIQUE_OPPOSITIONS,
    RUBRIQUE_PRIMES,
    RUBRIQUE_RETRAITE,
    RUBRIQUE_SALAIRE_BASE,
    SITUATIONS_FAMILIALES,
    SITUATION_LABELS,
)
from app.services.accounting import (
    AccountingError,
    create_entry,
    get_fiscal_year,
    get_journal,
    validate_entry,
)
from app.services.vat import period_bounds

# ---------------------------------------------------------------------------
# Comptes PCGE de la paie (verifies dans le plan comptable de reference)
# ---------------------------------------------------------------------------
COMPTE_SALAIRE_BASE = "61711"
COMPTE_PRIMES = "61712"
COMPTE_INDEMNITES = "61713"
COMPTE_CNSS_PATRONALE = "61741"
COMPTE_PRESTATIONS_FAMILIALES = "61744"
COMPTE_ASSURANCE_GROUPE = "61761"
# La taxe de formation professionnelle (1,60 %) n'a pas de compte dedie dans le
# plan : elle est rattachee a « autres charges sociales diverses » (61768).
COMPTE_TAXE_FORMATION = "61768"
COMPTE_NET_A_PAYER = "4432"  # remunerations dues au personnel (dette)
COMPTE_AVANCES = "3431"  # avances et acomptes au personnel (regularisation)
COMPTE_OPPOSITIONS = "4434"  # oppositions sur salaires
COMPTE_CNSS = "4441"  # Caisse Nationale de la Securite Sociale
COMPTE_RETRAITE = "4443"  # caisses de retraite
COMPTE_MUTUELLE = "4445"  # mutuelles
COMPTE_AUTRES_ORGANISMES = "4448"  # autres organismes sociaux (assurance groupe)
COMPTE_IR = "4452"  # Etat - impots, taxes et assimiles (IR retenu a la source)
COMPTE_BANQUE = "5141"
COMPTE_CAISSE = "5161"

JOURNAL_PAIE = "OD"  # operations diverses (aucun journal « paie » dans le plan)
SOURCE_ECRITURE = "payroll"


class PayrollError(AccountingError):
    """Erreur de paie (donnee manquante, controle bloquant, periode verrouillee)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def valider_periode(periode: str) -> tuple[int, int]:
    """Valide une periode de paie `AAAA-MM` et retourne (annee, mois)."""
    texte = str(periode or "").strip()
    if (
        len(texte) != 7
        or texte[4] != "-"
        or not texte[:4].isdigit()
        or not texte[5:].isdigit()
    ):
        raise PayrollError(
            f"Période de paie « {periode} » invalide : format attendu AAAA-MM "
            "(exemple 2026-01)."
        )
    annee, mois = int(texte[:4]), int(texte[5:])
    if not 1 <= mois <= 12:
        raise PayrollError(f"Mois invalide dans la période « {periode} ».")
    try:
        bareme_paie(annee)  # refuse un exercice sans bareme parametre
    except BaremeIndisponible as exc:
        raise PayrollError(str(exc)) from exc
    return annee, mois


def bornes_periode(periode: str) -> tuple[date, date]:
    """Premier et dernier jour de la periode de paie."""
    annee, mois = valider_periode(periode)
    return period_bounds(annee, month=mois)


def date_paie_defaut(periode: str) -> date:
    """Date de paie par defaut : dernier jour du mois de la periode."""
    return bornes_periode(periode)[1]


# ---------------------------------------------------------------------------
# Fiches salaries et contrats
# ---------------------------------------------------------------------------
def creer_employe(
    db: Session,
    *,
    company: Company,
    matricule: str,
    nom: str,
    date_entree: date,
    cin: str | None = None,
    cnss: str | None = None,
    situation_familiale: str = "celibataire",
    enfants: int = 0,
    type_contrat: str = "cdi",
    fonction: str | None = None,
    adresse: str | None = None,
    rib: str | None = None,
    banque: str | None = None,
    mode_paiement: str = "virement",
    exoneration_art_57_20: bool = False,
    exoneration_fin: date | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> Employee:
    """Cree une fiche salarie (matricule unique par dossier)."""
    matricule = str(matricule or "").strip()
    if not matricule:
        raise PayrollError("Le matricule du salarié est obligatoire.")
    if situation_familiale not in SITUATIONS_FAMILIALES:
        raise PayrollError(
            f"Situation de famille « {situation_familiale} » inconnue "
            f"(valeurs admises : {', '.join(SITUATIONS_FAMILIALES)})."
        )
    if type_contrat not in CONTRATS:
        raise PayrollError(
            f"Type de contrat « {type_contrat} » inconnu "
            f"(valeurs admises : {', '.join(CONTRATS)})."
        )
    if mode_paiement not in PAIEMENTS_PAIE:
        raise PayrollError(
            f"Mode de paiement « {mode_paiement} » inconnu "
            f"(valeurs admises : {', '.join(PAIEMENTS_PAIE)})."
        )
    if int(enfants or 0) < 0:
        raise PayrollError("Le nombre d'enfants ne peut pas être négatif.")
    existant = db.execute(
        select(Employee).where(
            Employee.company_id == company.id, Employee.matricule == matricule
        )
    ).scalar_one_or_none()
    if existant is not None:
        raise PayrollError(
            f"Le matricule « {matricule} » existe déjà dans ce dossier "
            f"({existant.nom})."
        )
    employe = Employee(
        company_id=company.id,
        matricule=matricule,
        nom=nom.strip(),
        cin=cin,
        cnss=cnss,
        situation_familiale=situation_familiale,
        enfants=int(enfants or 0),
        date_entree=date_entree,
        type_contrat=type_contrat,
        fonction=fonction,
        adresse=adresse,
        rib=rib,
        banque=banque,
        mode_paiement=mode_paiement,
        exoneration_art_57_20=exoneration_art_57_20,
        exoneration_fin=exoneration_fin,
        notes=notes,
    )
    db.add(employe)
    db.flush()
    log_action(
        db,
        action="PAYROLL_EMPLOYEE_CREATED",
        entity="Employee",
        entity_id=employe.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "matricule": matricule,
            "nom": nom,
            "type_contrat": type_contrat,
            "situation_familiale": situation_familiale,
            "enfants": int(enfants or 0),
        },
    )
    return employe


def get_employe(db: Session, company_id: int, reference: int | str) -> Employee:
    """Fiche salarie par identifiant ou matricule (cloisonnee par societe)."""
    requete = select(Employee).where(Employee.company_id == company_id)
    if isinstance(reference, int) or str(reference).isdigit():
        employe = db.execute(
            requete.where(Employee.id == int(reference))
        ).scalar_one_or_none()
    else:
        employe = db.execute(
            requete.where(Employee.matricule == str(reference))
        ).scalar_one_or_none()
    if employe is None:
        raise PayrollError(f"Salarié « {reference} » introuvable dans ce dossier.")
    return employe


def list_employes(
    db: Session, company_id: int, *, actifs_seulement: bool = True
) -> list[Employee]:
    """Liste des salaries (actifs par defaut), tries par matricule."""
    requete = select(Employee).where(Employee.company_id == company_id)
    if actifs_seulement:
        requete = requete.where(Employee.actif.is_(True))
    return list(db.execute(requete.order_by(Employee.matricule)).scalars().all())


def ajouter_contrat(
    db: Session,
    employee: Employee,
    *,
    salaire_base: Decimal | str,
    date_effet: date,
    prime_transport: Decimal | str = "0",
    prime_logement: Decimal | str = "0",
    autres_primes: Decimal | str = "0",
    indemnite_representation: Decimal | str = "0",
    avantages_nature: Decimal | str = "0",
    taux_retraite: Decimal | str = "0",
    taux_mutuelle: Decimal | str = "0",
    taux_assurance_groupe: Decimal | str = "0",
    mode_paiement: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> PayContract:
    """Ajoute un element contractuel (date d'effet) : historisation des montants."""
    base = money(Decimal(str(salaire_base or "0")))
    if base <= 0:
        raise PayrollError("Le salaire de base doit être supérieur à zéro.")
    contrat = PayContract(
        employee_id=employee.id,
        salaire_base=base,
        prime_transport=money(Decimal(str(prime_transport or "0"))),
        prime_logement=money(Decimal(str(prime_logement or "0"))),
        autres_primes=money(Decimal(str(autres_primes or "0"))),
        indemnite_representation=money(Decimal(str(indemnite_representation or "0"))),
        avantages_nature=money(Decimal(str(avantages_nature or "0"))),
        taux_retraite=Decimal(str(taux_retraite or "0")),
        taux_mutuelle=Decimal(str(taux_mutuelle or "0")),
        taux_assurance_groupe=Decimal(str(taux_assurance_groupe or "0")),
        date_effet=date_effet,
        mode_paiement=mode_paiement or employee.mode_paiement,
        notes=notes,
    )
    db.add(contrat)
    db.flush()
    log_action(
        db,
        action="PAYROLL_CONTRACT_ADDED",
        entity="PayContract",
        entity_id=contrat.id,
        user_id=user_id,
        company_id=employee.company_id,
        payload={
            "matricule": employee.matricule,
            "salaire_base": str(base),
            "date_effet": date_effet.isoformat(),
        },
    )
    return contrat


def contrat_a(employee: Employee, jour: date) -> PayContract:
    """Contrat en vigueur a une date donnee (dernier effet anterieur ou egal)."""
    contrats = [
        contrat for contrat in employee.contrats if contrat.date_effet <= jour
    ]
    if not contrats:
        raise PayrollError(
            f"Aucun contrat en vigueur au {jour.strftime('%d/%m/%Y')} pour "
            f"{employee.matricule} ({employee.nom}) : saisissez la rémunération "
            "contractuelle avant de préparer la paie."
        )
    return max(contrats, key=lambda contrat: contrat.date_effet)


# ---------------------------------------------------------------------------
# Calcul du bulletin (moteur de paie)
# ---------------------------------------------------------------------------
def _ligne(
    code: str,
    libelle: str,
    *,
    base: Decimal | str = "0",
    taux: Decimal | str | None = None,
    gain: Decimal | str = "0",
    retenue: Decimal | str = "0",
    compte: str | None = None,
) -> dict:
    """Rubrique de bulletin (une ligne du detail et de l'ecriture)."""
    return {
        "code": code,
        "libelle": libelle,
        "base": money(Decimal(str(base or "0"))),
        "taux": None if taux is None else Decimal(str(taux)),
        "gain": money(Decimal(str(gain or "0"))),
        "retenue": money(Decimal(str(retenue or "0"))),
        "compte": compte,
    }


def calculer_bulletin(
    db: Session,
    *,
    employee: Employee,
    periode: str,
    contrat: PayContract | None = None,
    variables: dict | None = None,
) -> dict:
    """Calcule un bulletin (sans ecriture) : totaux, cout employeur, rubriques.

    Methode (guide DTS « 9421 », CGI art. 57) : brut imposable -> cotisations
    obligatoires -> frais professionnels -> net imposable -> **IR par le barème
    de l'exercice** (déduction charges de famille) -> net à payer. Taux et
    barèmes viennent de `rates_ma` (**historisés**, jamais codés en dur).
    """
    annee, _mois = valider_periode(periode)
    _debut, fin = bornes_periode(periode)
    variables = dict(variables or {})
    contrat = contrat or contrat_a(employee, fin)

    base = money(contrat.salaire_base)
    primes = money(
        contrat.autres_primes + Decimal(str(variables.get("primes", "0") or "0"))
    )
    indemnites = money(
        contrat.prime_transport
        + contrat.prime_logement
        + contrat.indemnite_representation
    )
    avantages = money(contrat.avantages_nature)
    heures_sup = money(Decimal(str(variables.get("heures_sup", "0") or "0")))
    jours_absence = Decimal(str(variables.get("jours_absence", "0") or "0"))
    absences = money(base / Decimal("30") * jours_absence) if jours_absence else money(0)
    brut_imposable = money(base + primes + indemnites + avantages + heures_sup - absences)
    if brut_imposable <= 0:
        raise PayrollError(
            f"Bulletin de {employee.matricule} ({periode}) : le brut imposable "
            f"({brut_imposable} DH) doit être positif."
        )

    # CNSS / AMO (barème de l'exercice) puis retraite, mutuelle, assurance.
    # `annee` est transmise explicitement : la paie utilise le barème historisé
    # de son exercice (jamais les taux 2026 par defaut).
    cotisations = compute_cnss(brut_imposable, annee)
    cnss_salariale = cotisations["employee_social"]
    amo_salariale = cotisations["employee_amo"]
    # Taux contractuels exprimés en POURCENTAGE (3.00 = 3 %).
    retraite = money(brut_imposable * contrat.taux_retraite / Decimal("100"))
    mutuelle = money(brut_imposable * contrat.taux_mutuelle / Decimal("100"))
    assurance = money(brut_imposable * contrat.taux_assurance_groupe / Decimal("100"))
    cotisations_salariales = money(
        cnss_salariale + amo_salariale + retraite + mutuelle + assurance
    )

    # Net imposable : cotisations obligatoires (CNSS/AMO) et retraite deduites,
    # frais professionnels plafonnes (bareme de l'exercice) ; mutuelle et
    # assurance groupe non deduites (choix prudent documente au CDC § 9.13).
    frais = frais_professionnels_mensuels(brut_imposable, annee)
    deductible = money(cnss_salariale + amo_salariale + retraite)
    net_imposable = money(brut_imposable - deductible - frais)
    personnes = employee.personnes_a_charge
    exonere = bool(employee.exoneration_art_57_20) and (
        employee.exoneration_fin is None or fin <= employee.exoneration_fin
    )
    ir = money(0) if exonere else compute_ir_monthly(net_imposable, personnes, annee)

    avances = money(Decimal(str(variables.get("avances", "0") or "0")))
    oppositions = money(Decimal(str(variables.get("oppositions", "0") or "0")))
    net_avant_retenues = money(brut_imposable - cotisations_salariales - ir)
    if oppositions > net_avant_retenues:
        raise PayrollError(
            f"Bulletin de {employee.matricule} ({periode}) : l'opposition "
            f"({oppositions} DH) excède le net saisissable ({net_avant_retenues} DH)."
        )
    net = money(net_avant_retenues - avances - oppositions)
    if net < 0:
        raise PayrollError(
            f"Bulletin de {employee.matricule} ({periode}) : le net à payer "
            f"({net} DH) est négatif (avances {avances} DH)."
        )

    resultat = {
        "employee_id": employee.id,
        "matricule": employee.matricule,
        "nom": employee.nom,
        "periode": periode,
        "date_paie": fin,
        "annee": annee,
        "personnes_a_charge": personnes,
        "exonere_art_57_20": exonere,
        "brut": brut_imposable,
        "brut_imposable": brut_imposable,
        "frais_professionnels": frais,
        "base_cnss": cotisations["assiette_plafonnee"],
        "net_imposable": net_imposable,
        "cnss_salariale": cnss_salariale,
        "amo_salariale": amo_salariale,
        "retraite": retraite,
        "mutuelle": mutuelle,
        "assurance_groupe": assurance,
        "cotisations_salariales": cotisations_salariales,
        "ir": ir,
        "avances": avances,
        "oppositions": oppositions,
        "net": net,
        "contrat_id": contrat.id,
        "salaire_base": base,
        "primes": primes,
        "indemnites": indemnites,
        "avantages": avantages,
        "heures_sup": heures_sup,
        "absences": absences,
        "taux_retraite": contrat.taux_retraite,
        "taux_mutuelle": contrat.taux_mutuelle,
        "taux_assurance_groupe": contrat.taux_assurance_groupe,
        "assiette_cnss": cotisations["assiette_plafonnee"],
    }
    resultat.update(_charges_patronales(cotisations, brut_imposable))
    resultat["rubriques"] = rubriques_bulletin(resultat)
    return resultat


def _charges_patronales(cotisations: dict, brut_imposable: Decimal) -> dict:
    """Charges patronales (CNSS, AMO, prestations familiales, formation) et cout."""
    cout = money(
        brut_imposable
        + cotisations["employer_social"]
        + cotisations["employer_amo"]
        + cotisations["employer_family"]
        + cotisations["employer_tfp"]
    )
    return {
        "cnss_patronale": cotisations["employer_social"],
        "amo_patronale": cotisations["employer_amo"],
        "prestations_familiales": cotisations["employer_family"],
        "taxe_formation": cotisations["employer_tfp"],
        "total_patronal": cotisations["total_employer"],
        "cout_employeur": cout,
    }


def rubriques_bulletin(bulletin: dict) -> list[dict]:
    """Detail du bulletin (rubriques : libelle, base, taux, gain, retenue, compte).

    Chaque rubrique porte le **compte PCGE** qui la recevra dans l'ecriture de
    paie : le bulletin et la comptabilite sont donc reconcilies rubrique par
    rubrique (aucun montant n'est ressaisi a la main).
    """
    rubriques = [
        _ligne(
            RUBRIQUE_SALAIRE_BASE,
            RUBRIQUE_LABELS[RUBRIQUE_SALAIRE_BASE],
            base=bulletin["salaire_base"],
            gain=bulletin["salaire_base"],
            compte=COMPTE_SALAIRE_BASE,
        )
    ]
    if bulletin.get("primes"):
        rubriques.append(
            _ligne(
                RUBRIQUE_PRIMES,
                RUBRIQUE_LABELS[RUBRIQUE_PRIMES],
                gain=bulletin["primes"],
                compte=COMPTE_PRIMES,
            )
        )
    if bulletin.get("indemnites"):
        rubriques.append(
            _ligne(
                RUBRIQUE_INDEMNITES,
                RUBRIQUE_LABELS[RUBRIQUE_INDEMNITES],
                gain=bulletin["indemnites"],
                compte=COMPTE_INDEMNITES,
            )
        )
    if bulletin.get("avantages"):
        rubriques.append(
            _ligne(
                RUBRIQUE_AVANTAGES,
                RUBRIQUE_LABELS[RUBRIQUE_AVANTAGES],
                gain=bulletin["avantages"],
                compte=COMPTE_INDEMNITES,
            )
        )
    if bulletin.get("heures_sup"):
        rubriques.append(
            _ligne(
                RUBRIQUE_HEURES_SUP,
                RUBRIQUE_LABELS[RUBRIQUE_HEURES_SUP],
                gain=bulletin["heures_sup"],
                compte=COMPTE_SALAIRE_BASE,
            )
        )
    if bulletin.get("absences"):
        rubriques.append(
            _ligne(
                "145",
                "Absences non payées",
                base=bulletin["salaire_base"],
                retenue=bulletin["absences"],
            )
        )
    rubriques.extend(
        [
            _ligne(
                RUBRIQUE_CNSS,
                RUBRIQUE_LABELS[RUBRIQUE_CNSS],
                base=bulletin["base_cnss"],
                taux="4.48",
                retenue=bulletin["cnss_salariale"],
                compte=COMPTE_CNSS,
            ),
            _ligne(
                RUBRIQUE_AMO,
                RUBRIQUE_LABELS[RUBRIQUE_AMO],
                base=bulletin["brut_imposable"],
                taux="2.26",
                retenue=bulletin["amo_salariale"],
                compte=COMPTE_CNSS,
            ),
        ]
    )
    if bulletin.get("retraite"):
        rubriques.append(
            _ligne(
                RUBRIQUE_RETRAITE,
                RUBRIQUE_LABELS[RUBRIQUE_RETRAITE],
                base=bulletin["brut_imposable"],
                taux=bulletin.get("taux_retraite"),
                retenue=bulletin["retraite"],
                compte=COMPTE_RETRAITE,
            )
        )
    if bulletin.get("mutuelle"):
        rubriques.append(
            _ligne(
                RUBRIQUE_MUTUELLE,
                RUBRIQUE_LABELS[RUBRIQUE_MUTUELLE],
                base=bulletin["brut_imposable"],
                taux=bulletin.get("taux_mutuelle"),
                retenue=bulletin["mutuelle"],
                compte=COMPTE_MUTUELLE,
            )
        )
    if bulletin.get("assurance_groupe"):
        rubriques.append(
            _ligne(
                RUBRIQUE_ASSURANCE_GROUPE,
                RUBRIQUE_LABELS[RUBRIQUE_ASSURANCE_GROUPE],
                base=bulletin["brut_imposable"],
                taux=bulletin.get("taux_assurance_groupe"),
                retenue=bulletin["assurance_groupe"],
                compte=COMPTE_AUTRES_ORGANISMES,
            )
        )
    rubriques.append(
        _ligne(
            RUBRIQUE_IR,
            RUBRIQUE_LABELS[RUBRIQUE_IR],
            base=bulletin["net_imposable"],
            retenue=bulletin["ir"],
            compte=COMPTE_IR,
        )
    )
    if bulletin.get("avances"):
        rubriques.append(
            _ligne(
                RUBRIQUE_AVANCES,
                RUBRIQUE_LABELS[RUBRIQUE_AVANCES],
                retenue=bulletin["avances"],
                compte=COMPTE_AVANCES,
            )
        )
    if bulletin.get("oppositions"):
        rubriques.append(
            _ligne(
                RUBRIQUE_OPPOSITIONS,
                RUBRIQUE_LABELS[RUBRIQUE_OPPOSITIONS],
                retenue=bulletin["oppositions"],
                compte=COMPTE_OPPOSITIONS,
            )
        )
    return rubriques


# ---------------------------------------------------------------------------
# Cycle de paie : preparation, validation (ecriture), paiement
# ---------------------------------------------------------------------------
def get_run(db: Session, company_id: int, periode: str) -> PayrollRun | None:
    """Cycle de paie d'une periode (None si aucun)."""
    return db.execute(
        select(PayrollRun).where(
            PayrollRun.company_id == company_id, PayrollRun.periode == periode
        )
    ).scalar_one_or_none()


def preparer_paie(
    db: Session,
    company: Company,
    periode: str,
    *,
    variables: dict[str, dict] | None = None,
    date_paie: date | None = None,
    employes: list[Employee] | None = None,
    user_id: int | None = None,
) -> PayrollRun:
    """Prepare (calcule) la paie d'une periode : bulletins en **brouillon**.

    Le calcul est **refait** a chaque appel tant que le cycle est en brouillon
    (saisie des variables, corrections) ; un cycle valide ou paye est fige
    (aucun recalcul retroactif - P1.6). `variables` est indexe par matricule.
    """
    _annee, _mois = valider_periode(periode)
    debut, fin = bornes_periode(periode)
    jour_paie = date_paie or fin
    variables = dict(variables or {})
    run = get_run(db, company.id, periode)
    if run is not None and run.statut != PAYROLL_STATUS_DRAFT:
        raise PayrollError(
            f"La paie {periode} est « {run.statut_libelle} » : elle ne peut plus "
            "être recalculée (nouvelle période ou déverrouillage requis)."
        )
    if run is None:
        run = PayrollRun(
            company_id=company.id,
            periode=periode,
            date_paie=jour_paie,
            statut=PAYROLL_STATUS_DRAFT,
            created_by=user_id,
        )
        db.add(run)
        db.flush()
    else:
        for ancien in list(run.bulletins):
            db.delete(ancien)
        db.flush()
        run.date_paie = jour_paie

    salaries = employes if employes is not None else list_employes(db, company.id)
    retenus: list[Employee] = []
    for employe in salaries:
        if employe.date_entree > fin:
            continue
        if employe.date_sortie is not None and employe.date_sortie < debut:
            continue
        calcul = calculer_bulletin(
            db,
            employee=employe,
            periode=periode,
            variables=variables.get(employe.matricule) or {},
        )
        db.add(_bulletin_depuis_calcul(company, run, employe, calcul, jour_paie))
        db.flush()
        retenus.append(employe)
    if not retenus:
        raise PayrollError(
            f"Aucun salarié actif sur la période {periode} : vérifiez les dates "
            "d'entrée/sortie et les contrats de rémunération."
        )
    db.flush()
    _maj_totaux(db, run)
    log_action(
        db,
        action="PAYROLL_PREPARED",
        entity="PayrollRun",
        entity_id=run.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "periode": periode,
            "nb_bulletins": len(retenus),
            "total_brut": str(run.total_brut),
            "total_net": str(run.total_net),
        },
    )
    return run


def _bulletin_depuis_calcul(
    company: Company,
    run: PayrollRun,
    employe: Employee,
    calcul: dict,
    jour_paie: date,
) -> Payslip:
    """Enregistre le bulletin et ses rubriques (detail + comptes PCGE)."""
    bulletin = Payslip(
        company_id=company.id,
        run_id=run.id,
        employee_id=employe.id,
        periode=run.periode,
        date_paie=jour_paie,
        brut=calcul["brut_imposable"],
        brut_imposable=calcul["brut_imposable"],
        frais_professionnels=calcul["frais_professionnels"],
        base_cnss=calcul["assiette_cnss"],
        net_imposable=calcul["net_imposable"],
        personnes_a_charge=calcul["personnes_a_charge"],
        cnss_salariale=calcul["cnss_salariale"],
        amo_salariale=calcul["amo_salariale"],
        retraite=calcul["retraite"],
        mutuelle=calcul["mutuelle"],
        assurance_groupe=calcul["assurance_groupe"],
        cotisations_salariales=calcul["cotisations_salariales"],
        ir=calcul["ir"],
        avances=calcul["avances"],
        oppositions=calcul["oppositions"],
        net=calcul["net"],
        cnss_patronale=calcul["cnss_patronale"],
        amo_patronale=calcul["amo_patronale"],
        prestations_familiales=calcul["prestations_familiales"],
        taxe_formation=calcul["taxe_formation"],
        cout_employeur=calcul["cout_employeur"],
    )
    bulletin.lignes = [
        PayslipLine(
            ordre=ordre,
            code=rubrique["code"],
            libelle=rubrique["libelle"],
            base=rubrique["base"],
            taux=rubrique["taux"],
            gain=rubrique["gain"],
            retenue=rubrique["retenue"],
            compte=rubrique["compte"],
        )
        for ordre, rubrique in enumerate(calcul["rubriques"], start=1)
    ]
    return bulletin


def _maj_totaux(db: Session, run: PayrollRun) -> None:
    """Recalcule les totaux du cycle depuis les bulletins (aucun cumul stocke)."""
    bulletins = db.execute(select(Payslip).where(Payslip.run_id == run.id)).scalars()
    brut = cotisations = ir = net = employeur = Decimal("0")
    for bulletin in bulletins:
        brut += bulletin.brut_imposable
        cotisations += bulletin.cotisations_salariales
        ir += bulletin.ir
        net += bulletin.net
        employeur += bulletin.cout_employeur
    run.total_brut = money(brut)
    run.total_cotisations = money(cotisations)
    run.total_ir = money(ir)
    run.total_net = money(net)
    run.total_employeur = money(employeur)
    db.flush()


def lignes_ecriture_paie(bulletins: list[Payslip]) -> list[dict]:
    """Ecriture globale de paie deduite des bulletins (equilibre garanti).

    - **debit** : remunerations (61711/61712/61713) et charges patronales
      (61741 CNSS + AMO, 61744 prestations familiales, 61768 taxe de formation) ;
    - **credit** : `4441` CNSS (parts salariale **et** patronale, prestations et
      formation), `4443` retraite, `4445` mutuelle, `4448` assurance groupe,
      `4452` IR retenu a la source, `4434` oppositions, `3431` avances
      regularisees et **`4432` net a payer** au personnel.
    """
    debits: dict[str, Decimal] = {}
    credits: dict[str, Decimal] = {}
    libelles: dict[str, str] = {}
    total_net = Decimal("0")
    total_patronal_cnss = Decimal("0")
    total_prestations = Decimal("0")
    total_formation = Decimal("0")

    def cumul(comptes: dict[str, Decimal], compte: str, montant: Decimal) -> None:
        if montant:
            comptes[compte] = money(comptes.get(compte, Decimal("0")) + montant)

    for bulletin in bulletins:
        for ligne in bulletin.lignes:
            if ligne.gain:
                if ligne.compte:
                    cumul(debits, ligne.compte, ligne.gain)
                    libelles[ligne.compte] = ligne.libelle
                else:  # pragma: no cover - toute rubrique de gain porte un compte
                    cumul(debits, COMPTE_SALAIRE_BASE, ligne.gain)
            if ligne.retenue:
                if ligne.compte:
                    cumul(credits, ligne.compte, ligne.retenue)
                    libelles[ligne.compte] = ligne.libelle
                else:
                    # Retenue sans contrepartie (absences non payees) : elle
                    # diminue le debit des appointements.
                    cumul(debits, COMPTE_SALAIRE_BASE, -ligne.retenue)
        total_net += bulletin.net
        total_patronal_cnss += bulletin.cnss_patronale + bulletin.amo_patronale
        total_prestations += bulletin.prestations_familiales
        total_formation += bulletin.taxe_formation

    cumul(debits, COMPTE_CNSS_PATRONALE, total_patronal_cnss)
    libelles[COMPTE_CNSS_PATRONALE] = "Cotations patronales CNSS/AMO"
    cumul(debits, COMPTE_PRESTATIONS_FAMILIALES, total_prestations)
    libelles[COMPTE_PRESTATIONS_FAMILIALES] = "Prestations familiales (patronales)"
    cumul(debits, COMPTE_TAXE_FORMATION, total_formation)
    libelles[COMPTE_TAXE_FORMATION] = "Taxe de formation professionnelle"
    # Les charges patronales CNSS, prestations familiales et formation sont
    # reversees au meme organisme que les parts salariales (4441).
    cumul(credits, COMPTE_CNSS, total_patronal_cnss + total_prestations + total_formation)
    libelles[COMPTE_CNSS] = "CNSS / AMO (parts salariale et patronale)"
    cumul(credits, COMPTE_NET_A_PAYER, total_net)
    libelles[COMPTE_NET_A_PAYER] = "Rémunérations dues au personnel"

    lignes = [
        {
            "account_number": compte,
            "debit": montant,
            "label": libelles.get(compte, "Paie"),
        }
        for compte, montant in sorted(debits.items())
        if montant
    ] + [
        {
            "account_number": compte,
            "credit": montant,
            "label": libelles.get(compte, "Paie"),
        }
        for compte, montant in sorted(credits.items())
        if montant
    ]
    total_debit = money(sum((ligne["debit"] for ligne in lignes if "debit" in ligne), Decimal("0")))
    total_credit = money(
        sum((ligne["credit"] for ligne in lignes if "credit" in ligne), Decimal("0"))
    )
    if total_debit != total_credit:
        raise PayrollError(
            "Écriture de paie déséquilibrée : débit "
            f"{total_debit} DH contre crédit {total_credit} DH — l'écriture est "
            "refusée (contrôle bloquant n° 4 du CDC § 3.4)."
        )
    return lignes


def valider_paie(
    db: Session, run: PayrollRun, *, user_id: int | None = None
) -> Entry:
    """Valide la paie : genere l'**ecriture globale** et fige les bulletins.

    L'ecriture est **deduite des bulletins** (aucune saisie manuelle) et doit
    etre **equilibree** ; elle est refusee si la periode est verrouillee (P1.6).
    """
    if run.statut == PAYROLL_STATUS_VALIDATED:
        raise PayrollError(f"La paie {run.periode} est déjà validée.")
    if run.statut == PAYROLL_STATUS_PAID:
        raise PayrollError(f"La paie {run.periode} est déjà payée : elle est figée.")
    bulletins = list_bulletins(db, run)
    if not bulletins:
        raise PayrollError(
            f"Paie {run.periode} : aucun bulletin à comptabiliser (préparez la paie "
            "avant de la valider)."
        )
    # Cible fonctionnelle (audit J9, A2) : le module Paie est l'**unique source**
    # des ecritures de paie. Une ecriture de paie d'une autre origine sur la
    # periode (numerotation « PAIE » ou comptes de dette de paie mouvementes)
    # doit d'abord etre regularisee : sinon la charge serait comptabilisee deux
    # fois. Une **OD legitime** en 617x (regularisation, provision...) reste
    # autorisee : elle est seulement signalee.
    doublon = controle_doublon_paie(db, run.company_id, run.periode)
    if doublon["bloquants"]:
        details = " ; ".join(
            f"{entree['numero']} du {entree['date']} "
            f"(pièce {entree['reference'] or '-'}, {entree['motif']})"
            for entree in doublon["bloquants"][:5]
        )
        raise PayrollError(
            f"Paie {run.periode} : écriture(s) de paie déjà comptabilisée(s) hors du "
            f"module ({len(doublon['bloquants'])} : {details}). Le module Paie est "
            "l'unique source des écritures de paie : régularisez ces écritures "
            "(contre-écriture ou réinitialisation contrôlée) avant de valider."
        )
    exercice = get_fiscal_year(db, run.company_id, run.annee)
    journal = get_journal(db, run.company_id, JOURNAL_PAIE)
    ecriture = create_entry(
        db,
        company_id=run.company_id,
        fiscal_year=exercice,
        journal=journal,
        entry_date=run.date_paie,
        label=f"Paie {run.periode} - {len(bulletins)} bulletin(s)",
        lines=lignes_ecriture_paie(bulletins),
        reference=f"PAIE {run.periode}",
        source=SOURCE_ECRITURE,
        source_id=run.id,
        created_by=user_id,
        validate=True,
    )
    for bulletin in bulletins:
        bulletin.entry_id = ecriture.id
    run.entry_id = ecriture.id
    run.statut = PAYROLL_STATUS_VALIDATED
    db.flush()
    log_action(
        db,
        action="PAYROLL_VALIDATED",
        entity="PayrollRun",
        entity_id=run.id,
        user_id=user_id,
        company_id=run.company_id,
        payload={
            "periode": run.periode,
            "ecriture": ecriture.entry_number,
            "total_brut": str(run.total_brut),
            "total_net": str(run.total_net),
            "total_ir": str(run.total_ir),
            "cout_employeur": str(run.total_employeur),
        },
    )
    return ecriture


def payer_paie(
    db: Session,
    run: PayrollRun,
    *,
    date_paiement: date | None = None,
    mode: str | None = None,
    user_id: int | None = None,
) -> Entry:
    """Regle le net a payer : `4432` -> banque (`5141`) ou caisse (`5161`)."""
    if run.statut == PAYROLL_STATUS_DRAFT:
        raise PayrollError(
            f"Paie {run.periode} : validez la paie (écriture) avant de la payer."
        )
    if run.statut == PAYROLL_STATUS_PAID:
        raise PayrollError(f"La paie {run.periode} est déjà payée.")
    mode_paiement = mode or run.mode_paiement
    if mode_paiement not in PAIEMENTS_PAIE:
        raise PayrollError(
            f"Mode de paiement « {mode_paiement} » inconnu "
            f"(valeurs admises : {', '.join(PAIEMENTS_PAIE)})."
        )
    jour = date_paiement or run.date_paie
    tresorerie = COMPTE_CAISSE if mode_paiement == "especes" else COMPTE_BANQUE
    journal = get_journal(db, run.company_id, "CA" if mode_paiement == "especes" else "BQ")
    exercice = get_fiscal_year(db, run.company_id, jour.year)
    montant = money(run.total_net)
    if montant <= 0:
        raise PayrollError(
            f"Paie {run.periode} : le net à payer ({montant} DH) doit être positif."
        )
    ecriture = create_entry(
        db,
        company_id=run.company_id,
        fiscal_year=exercice,
        journal=journal,
        entry_date=jour,
        label=f"Règlement des salaires {run.periode}",
        lines=[
            {
                "account_number": COMPTE_NET_A_PAYER,
                "debit": montant,
                "label": f"Règlement salaires {run.periode}",
            },
            {
                "account_number": tresorerie,
                "credit": montant,
                "label": f"Règlement salaires {run.periode}",
            },
        ],
        reference=f"PAIE {run.periode}",
        source=SOURCE_ECRITURE,
        source_id=run.id,
        created_by=user_id,
        validate=True,
    )
    run.paiement_entry_id = ecriture.id
    run.mode_paiement = mode_paiement
    run.date_paiement = jour
    run.statut = PAYROLL_STATUS_PAID
    db.flush()
    log_action(
        db,
        action="PAYROLL_PAID",
        entity="PayrollRun",
        entity_id=run.id,
        user_id=user_id,
        company_id=run.company_id,
        payload={
            "periode": run.periode,
            "mode": mode_paiement,
            "montant": str(montant),
            "ecriture": ecriture.entry_number,
        },
    )
    return ecriture


def list_bulletins(db: Session, run: PayrollRun) -> list[Payslip]:
    """Bulletins du cycle de paie, tries par matricule."""
    bulletins = db.execute(
        select(Payslip)
        .join(Employee, Employee.id == Payslip.employee_id)
        .where(Payslip.run_id == run.id)
        .order_by(Employee.matricule)
    ).scalars()
    return list(bulletins)


def bulletins_periode(
    db: Session, company_id: int, periode: str
) -> list[Payslip]:
    """Bulletins d'une periode (toutes versions confondues : un seul cycle)."""
    return list(
        db.execute(
            select(Payslip)
            .join(Employee, Employee.id == Payslip.employee_id)
            .where(Payslip.company_id == company_id, Payslip.periode == periode)
            .order_by(Employee.matricule)
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Controles de coherence de la paie
# ---------------------------------------------------------------------------
def ecritures_paie_hors_module(
    db: Session, company_id: int, periode: str
) -> list[dict]:
    """Charges de personnel (617x) comptabilisees sur la periode **hors module**.

    Sert a l'inventaire et a l'affichage : liste des ecritures de charge de
    personnel d'une autre origine (import, saisie manuelle) sur la periode.
    Le **garde-fou** de comptabilisation est `controle_doublon_paie()`, qui
    distingue un **doublon reel** (ecriture de paie) d'une **OD legitime** en 617x.
    """
    debut, fin = bornes_periode(periode)
    lignes = db.execute(
        select(Entry, EntryLine.account_number)
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .where(
            Entry.company_id == company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
            Entry.entry_date >= debut,
            Entry.entry_date <= fin,
            Entry.source != SOURCE_ECRITURE,
            EntryLine.account_number.like("617%"),
        )
        .order_by(Entry.entry_date, Entry.id)
    ).all()
    resultat: dict[int, dict] = {}
    for entree, _compte in lignes:
        resultat.setdefault(
            entree.id,
            {
                "entry_id": entree.id,
                "numero": entree.entry_number,
                "date": str(entree.entry_date),
                "reference": entree.reference,
                "source": entree.source,
                "libelle": entree.label,
            },
        )
    return list(resultat.values())


# Comptes de **dettes de paie** : une ecriture qui les mouvemente est une
# ecriture de paie (et non une simple OD de charge).
COMPTES_DETTES_PAIE: tuple[str, ...] = (
    COMPTE_NET_A_PAYER,       # 4432 remunerations dues au personnel
    "4434",                   # oppositions sur salaires
    COMPTE_CNSS,              # 4441
    COMPTE_RETRAITE,          # 4443
    COMPTE_MUTUELLE,          # 4445
    COMPTE_AUTRES_ORGANISMES,  # 4448
    COMPTE_IR,                # 4452 IR retenu a la source
)
# Numerotation des ecritures de paie de l'application (« PAIE 2026-01 ») et du
# jeu de donnees de recette (« PAIE26-01 »).
MOTIF_REFERENCE_PAIE = re.compile(r"^PAIE", re.IGNORECASE)


def controle_doublon_paie(db: Session, company_id: int, periode: str) -> dict:
    """Distingue un **doublon reel de paie** d'une **OD legitime** en 617x (P1).

    Defaut corrige (audit J9, A2) : la paie du module etait comptabilisee en plus
    d'ecritures de paie **synthetiques** du jeu de donnees. Le premier garde-fou
    interdisait *toute* ecriture de charge de personnel hors module, ce qui
    bloquait aussi des **OD parfaitement legitimes** (regularisations, provisions,
    avantages en nature...).

    Regle retenue :
    - **bloquant** (doublon reel) : l'ecriture hors module porte la **numerotation
      de paie** (`ref` commencant par « PAIE ») **ou** mouvemente un **compte de
      dette de paie** (`4432`, `443x`, `444x`, `4452`) : c'est une ecriture de paie ;
    - **avertissement** (non bloquant) : charges de personnel `617x` sans
      numerotation de paie ni dette de paie : OD legitime, signalee a
      l'utilisateur mais autorisee.
    """
    debut, fin = bornes_periode(periode)
    ecritures = db.execute(
        select(Entry)
        .where(
            Entry.company_id == company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
            Entry.entry_date >= debut,
            Entry.entry_date <= fin,
            Entry.source != SOURCE_ECRITURE,
        )
        .order_by(Entry.entry_date, Entry.id)
    ).scalars().all()

    bloquants: list[dict] = []
    avertissements: list[dict] = []
    for entree in ecritures:
        comptes = {ligne.account_number for ligne in entree.lines}
        charges = {compte for compte in comptes if compte.startswith("617")}
        if not charges:
            continue
        dettes = sorted(compte for compte in comptes if compte.startswith(COMPTES_DETTES_PAIE))
        reference_paie = MOTIF_REFERENCE_PAIE.match(entree.reference or "") is not None
        constat = {
            "entry_id": entree.id,
            "numero": entree.entry_number,
            "date": str(entree.entry_date),
            "reference": entree.reference,
            "source": entree.source,
            "libelle": entree.label,
            "comptes_charges": sorted(charges),
            "comptes_dettes_paie": dettes,
        }
        if reference_paie or dettes:
            constat["motif"] = (
                f"numerotation de paie « {entree.reference} »"
                if reference_paie
                else f"comptes de dette de paie {dettes}"
            )
            bloquants.append(constat)
        else:
            constat["motif"] = (
                "charges de personnel 617x hors module, sans numerotation de paie ni "
                "dette de paie : OD legitime (a verifier par le comptable)"
            )
            avertissements.append(constat)
    return {"periode": periode, "bloquants": bloquants, "avertissements": avertissements}


def controles_paie(db: Session, company_id: int, periode: str) -> list[dict]:
    """Controles de la paie d'une periode (CDC § 3.4).

    Bloquants : net négatif, **Σ bulletins ≠ écriture**, **n° CNSS manquant**,
    écriture déséquilibrée, période verrouillée. Avertissements : opposition
    supérieure au tiers du net (quotité cessible à vérifier), CIN manquante.
    """
    controles: list[dict] = []

    def ajouter(code: str, niveau: str, message: str) -> None:
        controles.append({"code": code, "niveau": niveau, "message": message})

    run = get_run(db, company_id, periode)
    if run is None:
        ajouter(
            "paie.absente",
            "information",
            f"Aucune paie préparée pour la période {periode}.",
        )
        return controles
    bulletins = list_bulletins(db, run)
    if not bulletins:
        ajouter(
            "paie.aucun_bulletin",
            "bloquant",
            f"Paie {periode} : aucun bulletin (préparez la paie).",
        )
        return controles

    total_brut = money(sum((b.brut_imposable for b in bulletins), Decimal("0")))
    total_net = money(sum((b.net for b in bulletins), Decimal("0")))
    total_ir = money(sum((b.ir for b in bulletins), Decimal("0")))
    if total_brut != money(run.total_brut) or total_net != money(run.total_net):
        ajouter(
            "paie.cumul_divergent",
            "bloquant",
            f"Paie {periode} : totaux du cycle (brut {run.total_brut}, net "
            f"{run.total_net}) différents de la somme des bulletins (brut "
            f"{total_brut}, net {total_net}).",
        )

    for bulletin in bulletins:
        employe = db.get(Employee, bulletin.employee_id)
        nom = (
            f"{employe.matricule} {employe.nom}"
            if employe is not None
            else str(bulletin.employee_id)
        )
        if employe is not None and not (employe.cnss or "").strip():
            ajouter(
                "paie.cnss_manquant",
                "bloquant",
                f"{nom} : n° CNSS manquant — la DTS « 9421 » serait refusée "
                "(renseignez la fiche salarié).",
            )
        if employe is not None and not (employe.cin or "").strip():
            ajouter(
                "paie.cin_manquant",
                "avertissement",
                f"{nom} : CIN non renseignée (pièce d'identité à archiver).",
            )
        if bulletin.net < 0:
            ajouter(
                "paie.net_negatif",
                "bloquant",
                f"{nom} : net à payer négatif ({bulletin.net} DH).",
            )
        seuil_opposition = money(bulletin.net * QUOTITE_CESSIBLE_AVERTISSEMENT)
        if bulletin.oppositions and bulletin.oppositions > seuil_opposition:
            ajouter(
                "paie.opposition_quotite",
                "avertissement",
                f"{nom} : opposition ({bulletin.oppositions} DH) supérieure au "
                f"tiers du net ({seuil_opposition} DH) — vérifiez la quotité "
                "cessible applicable (Code de procédure civile).",
            )

    # Ecriture de paie : equilibre et reconciliation avec les bulletins.
    if run.entry_id is not None:
        ecriture = db.get(Entry, run.entry_id)
        if ecriture is not None:
            debit = money(sum((ligne.debit for ligne in ecriture.lines), Decimal("0")))
            credit = money(sum((ligne.credit for ligne in ecriture.lines), Decimal("0")))
            if debit != credit:
                ajouter(
                    "paie.ecriture_desequilibree",
                    "bloquant",
                    f"Écriture de paie {ecriture.entry_number} déséquilibrée : "
                    f"débit {debit} DH contre crédit {credit} DH.",
                )
            # Le debit de l'ecriture = brut + charges patronales = cout employeur.
            if debit != money(run.total_employeur):
                ajouter(
                    "paie.ecriture_divergente",
                    "bloquant",
                    f"Écriture de paie {ecriture.entry_number} : débit {debit} DH "
                    f"contre coût employeur des bulletins {run.total_employeur} DH.",
                )
    if run.statut == PAYROLL_STATUS_DRAFT:
        from app.services.period_locks import est_verrouillee

        if est_verrouillee(db, company_id, run.date_paie):
            ajouter(
                "paie.periode_verrouillee",
                "bloquant",
                f"Période {periode} verrouillée : la paie ne peut pas être "
                "validée (déverrouillage motivé requis — P1.6).",
            )
    ajouter(
        "paie.recap",
        "information",
        f"Paie {periode} : {run.statut_libelle} — brut {total_brut} DH, "
        f"IR {total_ir} DH, net {total_net} DH, coût employeur "
        f"{run.total_employeur} DH.",
    )
    return controles


def bulletin_dict(db: Session, company: Company, payslip: Payslip) -> dict:
    """Bulletin au format attendu par le PDF de paie (P1.1, interface inchangee)."""
    employe = db.get(Employee, payslip.employee_id)
    return {
        "periode": payslip.periode,
        "societe": {
            "nom": company.name,
            "ice": company.ice,
            "fiscal_id": company.fiscal_id,
            "cnss_number": company.cnss_number,
        },
        "salarie": {
            "matricule": employe.matricule if employe else "",
            "nom": employe.nom if employe else "",
            "cnss": employe.cnss if employe else None,
            "situation": employe.situation_familiale if employe else "",
            "enfants": employe.enfants if employe else 0,
            "date_entree": employe.date_entree if employe else None,
        },
        "lignes": [
            {
                "libelle": ligne.libelle,
                "base": ligne.base or None,
                "taux": ligne.taux,
                "gain": ligne.gain or None,
                "retenue": ligne.retenue or None,
            }
            for ligne in sorted(payslip.lignes, key=lambda item: item.ordre)
        ],
        "totaux": {
            "brut": payslip.brut_imposable,
            "cotisations": payslip.cotisations_salariales,
            "ir": payslip.ir,
            "net": payslip.net,
        },
    }


# ---------------------------------------------------------------------------
# Etats de paie (journal, livre, cotisations, recapitulatif annuel)
# ---------------------------------------------------------------------------
def journal_de_paie(db: Session, company_id: int, periode: str) -> dict:
    """Journal de paie d'une periode : bulletins, totaux et cumuls par rubrique."""
    run = get_run(db, company_id, periode)
    if run is None:
        return {
            "periode": periode,
            "run_id": None,
            "statut": None,
            "bulletins": [],
            "totaux": {},
            "rubriques": [],
        }
    bulletins = list_bulletins(db, run)
    rubriques: dict[str, dict] = {}
    for bulletin in bulletins:
        for ligne in bulletin.lignes:
            cumul = rubriques.setdefault(
                ligne.code,
                {
                    "code": ligne.code,
                    "libelle": ligne.libelle,
                    "gains": Decimal("0"),
                    "retenues": Decimal("0"),
                },
            )
            cumul["gains"] += ligne.gain
            cumul["retenues"] += ligne.retenue
    lignes_bulletins = []
    for bulletin in bulletins:
        employe = db.get(Employee, bulletin.employee_id)
        lignes_bulletins.append(
            {
                "payslip_id": bulletin.id,
                "employee_id": bulletin.employee_id,
                "matricule": employe.matricule if employe else "",
                "nom": employe.nom if employe else "",
                "brut": bulletin.brut_imposable,
                "cotisations": bulletin.cotisations_salariales,
                "ir": bulletin.ir,
                "net": bulletin.net,
                "cout_employeur": bulletin.cout_employeur,
            }
        )
    return {
        "periode": periode,
        "run_id": run.id,
        "statut": run.statut,
        "statut_libelle": run.statut_libelle,
        "date_paie": run.date_paie,
        "entry_id": run.entry_id,
        "paiement_entry_id": run.paiement_entry_id,
        "bulletins": lignes_bulletins,
        "totaux": {
            "brut": run.total_brut,
            "cotisations": run.total_cotisations,
            "ir": run.total_ir,
            "net": run.total_net,
            "cout_employeur": run.total_employeur,
        },
        "rubriques": [
            {
                "code": cumul["code"],
                "libelle": cumul["libelle"],
                "gains": money(cumul["gains"]),
                "retenues": money(cumul["retenues"]),
            }
            for cumul in rubriques.values()
        ],
    }


def _bulletins_annee(db: Session, company_id: int, annee: int) -> list[Payslip]:
    """Bulletins d'un exercice (toutes periodes), tries par matricule puis mois."""
    return list(
        db.execute(
            select(Payslip)
            .join(Employee, Employee.id == Payslip.employee_id)
            .where(
                Payslip.company_id == company_id,
                Payslip.periode.like(f"{annee}-%"),
            )
            .order_by(Employee.matricule, Payslip.periode)
        ).scalars()
    )


def livre_de_paie(db: Session, company_id: int, annee: int) -> dict:
    """Livre de paie annuel : cumuls mensuels par salarie (brut, IR, net, cout)."""
    bulletins = _bulletins_annee(db, company_id, annee)
    salaries: dict[int, dict] = {}
    mois_ouverts: set[str] = set()
    for bulletin in bulletins:
        employe = db.get(Employee, bulletin.employee_id)
        ligne = salaries.setdefault(
            bulletin.employee_id,
            {
                "employee_id": bulletin.employee_id,
                "matricule": employe.matricule if employe else "",
                "nom": employe.nom if employe else "",
                "cnss": employe.cnss if employe else None,
                "mois": {},
                "brut": Decimal("0"),
                "cotisations": Decimal("0"),
                "ir": Decimal("0"),
                "net": Decimal("0"),
                "cout_employeur": Decimal("0"),
            },
        )
        ligne["mois"][bulletin.periode] = {
            "brut": bulletin.brut_imposable,
            "cotisations": bulletin.cotisations_salariales,
            "ir": bulletin.ir,
            "net": bulletin.net,
            "cout_employeur": bulletin.cout_employeur,
        }
        ligne["brut"] += bulletin.brut_imposable
        ligne["cotisations"] += bulletin.cotisations_salariales
        ligne["ir"] += bulletin.ir
        ligne["net"] += bulletin.net
        ligne["cout_employeur"] += bulletin.cout_employeur
        mois_ouverts.add(bulletin.periode)
    lignes = []
    for ligne in salaries.values():
        for cle in ("brut", "cotisations", "ir", "net", "cout_employeur"):
            ligne[cle] = money(ligne[cle])
        lignes.append(ligne)
    lignes.sort(key=lambda item: item["matricule"])
    return {
        "annee": annee,
        "periodes": sorted(mois_ouverts),
        "salaries": lignes,
        "totaux": {
            cle: money(sum((ligne[cle] for ligne in lignes), Decimal("0")))
            for cle in ("brut", "cotisations", "ir", "net", "cout_employeur")
        },
    }


CLES_COTISATIONS = (
    "cnss_salariale",
    "amo_salariale",
    "cnss_patronale",
    "amo_patronale",
    "prestations_familiales",
    "taxe_formation",
    "ir",
    "net",
)


def etat_cotisations(db: Session, company_id: int, annee: int) -> dict:
    """Etat des cotisations et de l'IR retenu, mois par mois (CNSS / DGI)."""
    bulletins = _bulletins_annee(db, company_id, annee)
    mois: dict[str, dict] = {}
    for bulletin in bulletins:
        cumul = mois.setdefault(
            bulletin.periode,
            {
                "periode": bulletin.periode,
                "brut": Decimal("0"),
                "cnss_salariale": Decimal("0"),
                "amo_salariale": Decimal("0"),
                "cnss_patronale": Decimal("0"),
                "amo_patronale": Decimal("0"),
                "prestations_familiales": Decimal("0"),
                "taxe_formation": Decimal("0"),
                "ir": Decimal("0"),
                "net": Decimal("0"),
            },
        )
        cumul["brut"] += bulletin.brut_imposable
        for cle in CLES_COTISATIONS:
            cumul[cle] += getattr(bulletin, cle)
    lignes = []
    for cumul in sorted(mois.values(), key=lambda item: item["periode"]):
        for cle in list(cumul):
            if cle != "periode":
                cumul[cle] = money(cumul[cle])
        cumul["total_cnss"] = money(
            cumul["cnss_salariale"]
            + cumul["amo_salariale"]
            + cumul["cnss_patronale"]
            + cumul["amo_patronale"]
            + cumul["prestations_familiales"]
            + cumul["taxe_formation"]
        )
        lignes.append(cumul)
    return {
        "annee": annee,
        "lignes": lignes,
        "totaux": {
            cle: money(sum((ligne[cle] for ligne in lignes), Decimal("0")))
            for cle in ("brut", *CLES_COTISATIONS, "total_cnss")
        },
    }


def recapitulatif_annuel(db: Session, company_id: int, annee: int) -> dict:
    """Recapitulatif annuel par salarie (cumuls, cout employeur) et cotisations."""
    livre = livre_de_paie(db, company_id, annee)
    return {
        "annee": annee,
        "salaries": livre["salaries"],
        "periodes": livre["periodes"],
        "totaux_salaires": livre["totaux"],
        "cotisations": etat_cotisations(db, company_id, annee),
        "nb_salaries": len(livre["salaries"]),
        "nb_periodes": len(livre["periodes"]),
    }


def cumuls_salarie(db: Session, company_id: int, employee_id: int, annee: int) -> dict:
    """Cumuls annuels d'un salarie (attestation de salaire, controle de la DTS)."""
    for ligne in livre_de_paie(db, company_id, annee)["salaries"]:
        if ligne["employee_id"] == employee_id:
            return ligne
    raise PayrollError(
        f"Aucun bulletin pour le salarié {employee_id} sur l'exercice {annee}."
    )
