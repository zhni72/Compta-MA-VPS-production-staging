"""Baremes fiscaux et sociaux marocains - exercice 2026.

ATTENTION : ces valeurs sont celles de la Loi de Finances 2026. Elles sont
regroupees ici pour etre facilement auditees et mises a jour, et elles sont
egalement historisees en base (table `vat_rates`) pour les taux de TVA.
Toute mise a jour annuelle doit passer par un examen de ce module.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MONEY_Q = Decimal("0.01")


def money(value: Decimal | int | float | str) -> Decimal:
    """Arrondit un montant en dirhams a 2 decimales (arrondi commercial)."""
    return Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# TVA 2026 : deux taux seulement (7 % et 14 % supprimes au 01/01/2026)
# ---------------------------------------------------------------------------
VAT_RATES_2026: list[dict] = [
    {
        "code": "TVA20",
        "rate": Decimal("20.00"),
        "label": "TVA 20 % - taux normal",
        "valid_from": "2026-01-01",
        "is_deductible": True,
    },
    {
        "code": "TVA10",
        "rate": Decimal("10.00"),
        "label": "TVA 10 % - taux reduit (eau, transport, restauration, banques)",
        "valid_from": "2026-01-01",
        "is_deductible": True,
    },
    {
        "code": "TVA0",
        "rate": Decimal("0.00"),
        "label": "Exonere / export / produits de base",
        "valid_from": "2026-01-01",
        "is_deductible": False,
    },
]

VAT_DECLARATION_THRESHOLD = Decimal("1000000")  # CA >= 1 M MAD => regime mensuel

# ---------------------------------------------------------------------------
# IR 2026 : bareme progressif annuel (tranche haute, taux, somme a deduire)
# ---------------------------------------------------------------------------
IR_BRACKETS_2026: list[tuple[Decimal, Decimal, Decimal]] = [
    (Decimal("40000"), Decimal("0.00"), Decimal("0")),
    (Decimal("60000"), Decimal("0.10"), Decimal("4000")),
    (Decimal("80000"), Decimal("0.20"), Decimal("10000")),
    (Decimal("100000"), Decimal("0.30"), Decimal("18000")),
    (Decimal("180000"), Decimal("0.34"), Decimal("22000")),
    (Decimal("Infinity"), Decimal("0.37"), Decimal("27400")),
]

IR_PROFESSIONAL_EXPENSES_2026 = {
    "gross_threshold": Decimal("78000"),
    "rate_below": Decimal("0.35"),
    "cap_below": Decimal("30000"),
    "rate_above": Decimal("0.25"),
    "cap_above": Decimal("35000"),
}

# Frais professionnels 2025 — CGI 2025 art. 59-I-A (p. 95-96), valides par
# P1B V6 : 35 % du revenu brut annuel imposable jusqu'a 78 000 DH, 25 % au-dela,
# deduction annuelle plafonnee a **35 000 DH**. Le plafond de la tranche basse
# (30 000 DH, arithmetiquement sans impact : 35 % x 78 000 = 27 300 < 30 000)
# est conserve a l'identique du jeu 2026 (declaration documentaire V6 § 6.6).
IR_PROFESSIONAL_EXPENSES_2025 = {
    "gross_threshold": Decimal("78000"),
    "rate_below": Decimal("0.35"),
    "cap_below": Decimal("35000"),
    "rate_above": Decimal("0.25"),
    "cap_above": Decimal("35000"),
}
IR_FAMILY_DEDUCTION = Decimal("600")  # par personne a charge
IR_FAMILY_MAX_PERSONS = 6

# ---------------------------------------------------------------------------
# IR 2025 (loi de finances 2025) : bareme applicable a l'exercice 2025.
# Deduction pour charges de famille de **500 DH** par personne (6 au maximum).
# Source : bareme IR 2025 (CGI art. 73, version 2025) — valeurs fournies au
# projet ; a confirmer par l'expert-comptable (statut « documente (a confirmer) »).
# ---------------------------------------------------------------------------
IR_BRACKETS_2025: list[tuple[Decimal, Decimal, Decimal]] = [
    (Decimal("40000"), Decimal("0.00"), Decimal("0")),
    (Decimal("60000"), Decimal("0.10"), Decimal("4000")),
    (Decimal("80000"), Decimal("0.20"), Decimal("10000")),
    (Decimal("100000"), Decimal("0.30"), Decimal("18000")),
    (Decimal("180000"), Decimal("0.34"), Decimal("22000")),
    (Decimal("Infinity"), Decimal("0.37"), Decimal("27400")),
]
IR_FAMILY_DEDUCTION_BY_YEAR: dict[int, Decimal] = {
    2025: Decimal("500"),
    2026: IR_FAMILY_DEDUCTION,
}

# ---------------------------------------------------------------------------
# Paie (P1.4) : baremes mensuels de la retenue a la source (DGI)
# ---------------------------------------------------------------------------
# Methode officielle (guide DTS « 9421 » / CGI art. 57 et suivants) :
#   1. salaire brut mensuel
#   2. - cotisations sociales obligatoires (CNSS / AMO, part salariale)
#   3. - frais professionnels (35 % plafonnes, 25 % au-dela du seuil annuel)
#   4. = net imposable mensuel -> annualise (x 12)
#   5. IR annuel (bareme progressif) - deduction pour charges de famille
#   6. / 12 = IR mensuel retenu a la source
IR_MONTHS = 12
# Quotite cessible (oppositions sur salaires) : la fraction legale insaisissable
# n'est PAS fixee par le CDC et n'est donc **pas codee en dur** : la limite
# bloquante appliquee est le net a payer ; au-dela du tiers, un avertissement
# invite a verifier la quotite applicable (Code de procedure civile).
QUOTITE_CESSIBLE_AVERTISSEMENT = Decimal("0.333333")

# Baremes de paie **histories par exercice** : un exercice absent de ce
# registre est refuse (aucun bareme n'est devine - regle permanente n° 2).
# Le registre est defini **apres** les constantes CNSS/AMO (voir plus bas).


class BaremeIndisponible(ValueError):
    """Aucun bareme de paie n'est parametre pour l'exercice demande."""


def bareme_paie(annee: int) -> dict[str, object]:
    """Bareme de paie applicable a un exercice (IR, CNSS/AMO, plafonds).

    Le bareme est **historisé** : demander un exercice non parametre leve une
    erreur explicite plutot que d'appliquer un bareme de l'annee precedente.
    """
    bareme = BAREMES_PAIE.get(int(annee))
    if bareme is None:
        connus = ", ".join(str(an) for an in sorted(BAREMES_PAIE))
        raise BaremeIndisponible(
            f"Aucun barème de paie n'est paramétré pour l'exercice {annee} "
            f"(exercices disponibles : {connus}). Mettez à jour "
            "`app/core/rates_ma.py` (barème IR/CNSS de la loi de finances) avant "
            "de calculer la paie."
        )
    return bareme


def deduction_charges_famille(
    personnes_a_charge: int, annee: int = 2026
) -> Decimal:
    """Deduction annuelle pour charges de famille (600 DH par personne, max 6)."""
    bareme = bareme_paie(annee)
    personnes = max(0, min(int(personnes_a_charge), int(bareme["max_personnes"])))
    return money(personnes * Decimal(str(bareme["deduction_famille"])))


def frais_professionnels_mensuels(
    brut_mensuel: Decimal | int | float | str, annee: int = 2026
) -> Decimal:
    """Frais professionnels mensuels (35 % / 25 % plafonnes, CGI art. 59)."""
    return money(
        compute_professional_expenses(Decimal(str(brut_mensuel)) * IR_MONTHS, annee)
        / IR_MONTHS
    )


def compute_ir_monthly(
    net_imposable_mensuel: Decimal | int | float | str,
    personnes_a_charge: int = 0,
    annee: int = 2026,
) -> Decimal:
    """IR mensuel retenu a la source (methode de l'annualisation, DGI).

    Le bareme est celui de l'exercice demande (`bareme_paie`) : aucun taux
    n'est code en dur dans le calcul de la paie (controle bloquant n° 2 du
    CDC § 3.4).
    """
    bareme_paie(annee)  # refuse un exercice non parametre
    net = Decimal(str(net_imposable_mensuel))
    if net <= 0:
        return money(0)
    ir_annuel = compute_ir_annual(net * IR_MONTHS, annee)
    deduction = deduction_charges_famille(personnes_a_charge, annee)
    ir_net = ir_annuel - deduction
    if ir_net <= 0:
        return money(0)
    return money(ir_net / IR_MONTHS)


def parametres_paie_manquants(annee: int) -> list[str]:
    """Parametres de paie **non figes** pour un exercice (aucune hypothese).

    Utilise par la simulation P1B et par l'ecran des referentiels : un exercice
    dont les cotisations sociales ne sont pas documentees ne peut pas donner de
    cout employeur fiable (regle permanente : aucun taux devine).
    """
    bareme = BAREMES_PAIE.get(int(annee))
    if bareme is None:
        return ["bareme de paie non parametre"]
    manquants: list[str] = []
    if bareme.get("frais_professionnels") is None:
        manquants.append("frais professionnels (CGI art. 59, version de l'exercice)")
    if bareme.get("cnss") is None:
        manquants.append("CNSS / AMO (taux et plafonds de l'exercice)")
    return manquants


# ---------------------------------------------------------------------------
# CNSS / AMO 2026
# ---------------------------------------------------------------------------
CNSS_2026 = {
    "ceiling_social": Decimal("6000"),  # plafond prestations sociales
    "employee_social": Decimal("0.0448"),
    "employer_social": Decimal("0.0898"),
    "employee_amo": Decimal("0.0226"),
    "employer_amo": Decimal("0.0411"),
    "employer_family": Decimal("0.0640"),
    "employer_tfp": Decimal("0.0160"),
    "total_employee": Decimal("0.0674"),
    "total_employer": Decimal("0.2109"),
}

# CNSS / AMO 2025 — valides par P1B V6 et V7A-CORR. Cotisations sociales
# (4,48 % / 8,98 % avec plafond 6 000 DH/mois) et prestations familiales
# (6,40 %) : dahir 1-72-184 art. 19-20 + fiche institutionnelle CNSS. AMO
# secteur prive : **2,26 % salarie / 4,11 % employeur** (4,52 % a parts egales
# + 1,85 % employeur, decret 2-14-707, BO 6314 p. 4770-4771 — V7A-CORR),
# assiette brute **sans plafond**. TFP : 1,60 % employeur (decret 2-73-633
# art. 3 modifie). Valeurs identiques au jeu 2026 (aucune inversion de taux).
CNSS_2025 = {
    "ceiling_social": Decimal("6000"),  # plafond prestations sociales
    "employee_social": Decimal("0.0448"),
    "employer_social": Decimal("0.0898"),
    "employee_amo": Decimal("0.0226"),
    "employer_amo": Decimal("0.0411"),
    "employer_family": Decimal("0.0640"),
    "employer_tfp": Decimal("0.0160"),
    "total_employee": Decimal("0.0674"),
    "total_employer": Decimal("0.2109"),
}

# ---------------------------------------------------------------------------
# IS : registre **historisé par exercice** (aucun taux devine)
# ---------------------------------------------------------------------------
# Chaque exercice porte son propre jeu de taux (source : loi de finances de
# l'annee). Un exercice absent du registre est **refuse** : l'application
# n'applique jamais le taux d'une autre annee (exigence de la recette J9/P1 :
# le recalcul d'un exercice se fait « avec le taux applicable a l'exercice »).
IS_RATES_2026 = {
    "standard": Decimal("0.20"),       # BNF < 100 M MAD
    "large_company": Decimal("0.35"),  # BNF > 100 M MAD
    "financial": Decimal("0.40"),      # banques, assurances, BAM, CDG
    "cfc": Decimal("0.20"),            # Casablanca Finance City / ZAI
}
IS_RATES_BY_YEAR: dict[int, dict[str, Decimal]] = {
    # IS 2025 : grille **transitoire** de convergence (CGI 2025 — LF 2023-2025)
    # validee par P1B V6 (`P1B_REFERENTIELS_PAIE_2025_V6_LOCAL.md`, CGI 2025
    # p. 470-472). Le taux de droit commun reste 20 % ; les societes dont le
    # benefice net fiscal est inferieur ou egal a 300 000 DH relevent de 17,5 %
    # en 2025. Taux specifiques 2025 **corriges en V7B** : 31,25 % >= 100 M DH
    # (grandes entreprises, art. 247-XXXVII), 39,25 % etablissements de credit /
    # assurances / BAM / CDG, 18,75 % Casablanca Finance City / ZAI.
    2025: {
        "standard": Decimal("0.20"),        # BNF < 100 M MAD (droit commun)
        "small_profit": Decimal("0.175"),   # BNF <= 300 000 MAD (2025)
        "large_company": Decimal("0.3125"),  # BNF >= 100 M MAD (31,25 % en 2025)
        "financial": Decimal("0.3925"),      # banques, assurances, BAM, CDG (39,25 % en 2025)
        "cfc": Decimal("0.1875"),            # Casablanca Finance City / ZAI (18,75 % en 2025)
    },
    2026: IS_RATES_2026,
}
DERNIER_EXERCICE_IS = max(IS_RATES_BY_YEAR)
IS_LARGE_COMPANY_THRESHOLD = Decimal("100000000")
# Seuil du taux transitoire **par exercice** (les exercices sans entree n'ont pas
# de taux reduit : ils restent au taux de droit commun).
IS_SMALL_PROFIT_THRESHOLD_BY_YEAR: dict[int, Decimal] = {
    2025: Decimal("300000"),
}
IS_SMALL_PROFIT_THRESHOLD_2025 = IS_SMALL_PROFIT_THRESHOLD_BY_YEAR[2025]
COTISATION_MINIMALE_2026 = {
    "rate": Decimal("0.0025"),
    "minimum": Decimal("3000"),
    "exemption_months": 36,
    "exemption_butee_months": 60,
}
# Cotisation minimale 2025 : 0,25 % des produits **hors TVA** (CGI 2025
# art. 144-I-B), plancher 3 000 DH, exoneration des 36 premiers mois d'activite
# **cessant a l'expiration des 60 mois suivant la constitution** (art.
# 144-I-C-1°) — arbitrage P1B V7A conserve par V7B (aucune valeur modifiee).
COTISATION_MINIMALE_2025 = {
    "rate": Decimal("0.0025"),
    "minimum": Decimal("3000"),
    "exemption_months": 36,
    "exemption_butee_months": 60,
}
COTISATION_MINIMALE_BY_YEAR: dict[int, dict[str, object]] = {
    2025: COTISATION_MINIMALE_2025,
    2026: COTISATION_MINIMALE_2026,
}

# ---------------------------------------------------------------------------
# Sources des referentiels fiscaux (exigence P1B v2) : chaque taux, plafond et
# base est rattache a sa **source reglementaire ou officielle**, et chaque
# grandeur non encore fournie est listee comme telle — aucune hypothese.
# ---------------------------------------------------------------------------
SOURCES_REFERENTIELS: dict[int, list[dict[str, str]]] = {
    2026: [
        {
            "element": "IS — taux standard (< 100 M DH de benefice net fiscal)",
            "valeur": "20 %",
            "base": "benefice net fiscal",
            "source": "CGI (edition 2026 fournie au projet), convergence LF — tableau IS",
            "statut": "documente",
        },
        {
            "element": "IS — taux grandes entreprises (> 100 M DH)",
            "valeur": "35 %",
            "base": "benefice net fiscal",
            "source": "CGI (edition 2026 fournie au projet)",
            "statut": "documente",
        },
        {
            "element": "IS — etablissements de credit / assurances / CFC",
            "valeur": "40 % / 20 %",
            "base": "benefice net fiscal",
            "source": "CGI (edition 2026 fournie au projet)",
            "statut": "documente",
        },
        {
            "element": "Cotisation minimale — taux et plancher",
            "valeur": "0,25 % des produits hors TVA ; plancher 3 000 DH",
            "base": "produits hors TVA (CGI art. 144-I-B : CA, autres produits "
            "d'exploitation, produits financiers, subventions et dons)",
            "source": "CGI art. 144 (edition 2026 fournie au projet)",
            "statut": "documente",
        },
        {
            "element": "Cotisation minimale — exoneration",
            "valeur": "36 mois d'activite, butee 60 mois depuis la constitution",
            "base": "duree d'activite (dates reelles de la societe)",
            "source": "CGI art. 144-I-C-1° (36 premiers mois, cesse au plus tard "
            "60 mois apres la constitution)",
            "statut": "documente",
        },
        {
            "element": "IR — bareme mensuel (annualisation DGI)",
            "valeur": "bareme progressif 6 tranches (0 % a 37 %)",
            "base": "net imposable mensuel",
            "source": "CGI art. 73 (bareme IR 2026) — `BAREMES_PAIE[2026]`",
            "statut": "documente",
        },
        {
            "element": "Frais professionnels",
            "valeur": "35 % plafonne 2 500 DH/mois jusqu'a 55 000 DH, 25 % au-dela",
            "base": "brut imposable",
            "source": "CGI art. 59 (edition 2026 fournie au projet)",
            "statut": "documente",
        },
        {
            "element": "CNSS — part salariale / patronale, plafond",
            "valeur": "4,48 % / 8,98 % — plafond 6 000 DH/mois",
            "base": "salaire brut plafonne",
            "source": "CNSS (regime general) — `CNSS_2026` ; a re-confirmer par le client",
            "statut": "documente (a confirmer)",
        },
        {
            "element": "AMO — part salariale / patronale",
            "valeur": "2,26 % / 4,11 %",
            "base": "salaire brut (sans plafond)",
            "source": "AMO (couverture medicale obligatoire) — `CNSS_2026`",
            "statut": "documente (a confirmer)",
        },
        {
            "element": "Prestations familiales / taxe de formation professionnelle",
            "valeur": "6,40 % / 1,60 % (part patronale)",
            "base": "salaire brut",
            "source": "CNSS / TFP — reglementation 2026 fournie au projet",
            "statut": "documente",
        },
    ],
    2025: [
        {
            "element": "IS 2025 — grille transitoire (convergence LF 2023-2025)",
            "valeur": "17,5 % si benefice net fiscal <= 300 000 DH ; 20 % au-dela "
            "(< 100 M DH) ; **31,25 %** >= 100 M DH ; **39,25 %** etablissements de "
            "credit / assurances ; **18,75 %** CFC/ZAI",
            "base": "benefice net fiscal 2025",
            "source": "CGI 2025 art. 247-XXXVII (tableau IS) p. 470-472 — P1B V6",
            "statut": "documente (a confirmer)",
        },
        {
            "element": "IR 2025 — bareme mensuel",
            "valeur": "bareme progressif 6 tranches (0 % jusqu'a 40 000 DH, 10/20/30/34/37 %) — "
            "deduction familiale 500 DH par personne (6 max)",
            "base": "net imposable mensuel 2025",
            "source": "CGI 2025 art. 73-I p. 117 ; LF 2025 art. 8 (BO 7362 p. 2983) ; "
            "Note DGI 736 p. 13 — `BAREMES_PAIE[2025]`",
            "statut": "documente (a confirmer)",
        },
        {
            "element": "Frais professionnels 2025",
            "valeur": "35 % jusqu'a 78 000 DH de brut annuel, 25 % au-dela ; "
            "deduction plafonnee a 35 000 DH",
            "base": "brut imposable 2025",
            "source": "CGI 2025 art. 59-I-A p. 95-96 — `IR_PROFESSIONAL_EXPENSES_2025`",
            "statut": "documente",
        },
        {
            "element": "CNSS / AMO 2025 — taux et plafond",
            "valeur": "CNSS 4,48 % / 8,98 % (plafond 6 000 DH/mois) ; "
            "AMO 2,26 % / 4,11 % (sans plafond)",
            "base": "salaire brut 2025",
            "source": "dahir 1-72-184 art. 19-20 + fiche CNSS ; AMO decret 2-14-707 "
            "(BO 6314 p. 4770-4771) — `CNSS_2025` (P1B V6 / V7A-CORR)",
            "statut": "documente (a confirmer)",
        },
        {
            "element": "Prestations familiales / TFP 2025 (part patronale)",
            "valeur": "6,40 % / 1,60 %",
            "base": "salaire brut 2025",
            "source": "CNSS (PF) : dahir 1-72-184 art. 20 + fiche CNSS ; "
            "TFP : decret 2-73-633 art. 3 modifie — `CNSS_2025`",
            "statut": "documente",
        },
        {
            "element": "Cotisation minimale 2025 — taux, plancher, exoneration",
            "valeur": "0,25 % des produits hors TVA ; plancher 3 000 DH ; "
            "exoneration 36 mois d'activite (butee 60 mois depuis la constitution)",
            "base": "produits hors TVA 2025 (CGI art. 144-I-B : CA 71x, autres "
            "produits d'exploitation 75x, produits financiers 76x, subventions "
            "et dons 74x/77x)",
            "source": "CGI 2025 art. 144 p. 263-265 — arbitrage P1B V7A",
            "statut": "documente (a confirmer)",
        },
    ],
}


def sources_referentiel(annee: int) -> list[dict[str, str]]:
    """Sources documentees du referentiel fiscal d'un exercice (vide si inconnu)."""
    return SOURCES_REFERENTIELS.get(int(annee), [])


def referentiel_complet(annee: int) -> bool:
    """Vrai si **toutes** les sources de l'exercice sont documentees (aucune a fournir)."""
    entrees = sources_referentiel(annee)
    return bool(entrees) and all(entree["statut"].startswith("documente") for entree in entrees)
CSS_2026: list[tuple[Decimal, Decimal, Decimal]] = [
    (Decimal("5000000"), Decimal("0.015"), Decimal("1000000")),
    (Decimal("10000000"), Decimal("0.025"), Decimal("5000000")),
    (Decimal("40000000"), Decimal("0.035"), Decimal("10000000")),
    (Decimal("Infinity"), Decimal("0.05"), Decimal("40000000")),
]

# ---------------------------------------------------------------------------
# Registre des baremes de paie (P1.4) : un jeu complet par exercice
# ---------------------------------------------------------------------------
# Chaque exercice reunit le bareme IR, les frais professionnels, la deduction
# pour charges de famille et les taux CNSS/AMO applicables. La paie refuse de
# calculer un exercice absent de ce registre (aucun taux devine).
BAREMES_PAIE: dict[int, dict[str, object]] = {
    # Paie 2025 : bareme IR 2025, deduction familiale 500 DH et — depuis la
    # correction V7B — **frais professionnels** (CGI 2025 art. 59) et
    # **cotisations CNSS/AMO 2025** (dahir 1-72-184, fiche CNSS, decret
    # 2-14-707) documentes par P1B V6 / V7A-CORR : la paie 2025 est calculable
    # avec ses propres taux (aucun taux 2026 applique par defaut).
    2025: {
        "ir_brackets": IR_BRACKETS_2025,
        "frais_professionnels": IR_PROFESSIONAL_EXPENSES_2025,
        "deduction_famille": IR_FAMILY_DEDUCTION_BY_YEAR[2025],
        "max_personnes": IR_FAMILY_MAX_PERSONS,
        "cnss": CNSS_2025,
    },
    2026: {
        "ir_brackets": IR_BRACKETS_2026,
        "frais_professionnels": IR_PROFESSIONAL_EXPENSES_2026,
        "deduction_famille": IR_FAMILY_DEDUCTION,
        "max_personnes": IR_FAMILY_MAX_PERSONS,
        "cnss": CNSS_2026,
    },
}


def compute_ir_annual(
    net_imposable_annuel: Decimal | int | float | str, annee: int = 2026
) -> Decimal:
    """IR annuel selon le bareme progressif **de l'exercice** (somme a deduire)."""
    bareme = bareme_paie(annee)
    revenu = Decimal(str(net_imposable_annuel))
    if revenu <= 0:
        return money(0)
    for upper, rate, deduction in bareme["ir_brackets"]:  # type: ignore[union-attr]
        if revenu <= upper:
            return money(max(Decimal("0"), revenu * rate - deduction))
    return money(0)  # pragma: no cover - la derniere tranche est infinie


def compute_professional_expenses(
    gross_annual: Decimal | int | float | str, annee: int = 2026
) -> Decimal:
    """Frais professionnels deductibles (35 % ou 25 % selon le brut annuel)."""
    brut = Decimal(str(gross_annual))
    params = bareme_paie(annee)["frais_professionnels"]
    if params is None:
        raise BaremeIndisponible(
            f"Les frais professionnels de l'exercice {annee} ne sont pas documentes "
            "(CGI art. 59, version de l'exercice) : aucun taux n'est applique par "
            "defaut."
        )
    if brut <= params["gross_threshold"]:  # type: ignore[index]
        return money(min(brut * params["rate_below"], params["cap_below"]))  # type: ignore[index]
    return money(min(brut * params["rate_above"], params["cap_above"]))  # type: ignore[index]


def compute_cnss(
    gross_monthly: Decimal | int | float | str, annee: int = 2026
) -> dict[str, Decimal]:
    """Cotisations CNSS/AMO pour un salaire brut mensuel.

    Les taux sont ceux de l'**exercice demande** : un exercice dont les
    cotisations sociales ne sont pas documentees est **refuse** (aucun taux
    devine — regle permanente).
    """
    bar: dict[str, Decimal] | None = bareme_paie(annee)["cnss"]  # type: ignore[assignment]
    if bar is None:
        raise BaremeIndisponible(
            f"Les taux CNSS / AMO de l'exercice {annee} ne sont pas documentes : "
            "aucune cotisation n'est calculee par defaut."
        )
    brut = Decimal(str(gross_monthly))
    assiette_plafonnee = min(brut, bar["ceiling_social"])
    employee_social = money(assiette_plafonnee * bar["employee_social"])
    employee_amo = money(brut * bar["employee_amo"])
    employer_social = money(assiette_plafonnee * bar["employer_social"])
    employer_amo = money(brut * bar["employer_amo"])
    employer_family = money(brut * bar["employer_family"])
    employer_tfp = money(brut * bar["employer_tfp"])
    total_employee = money(employee_social + employee_amo)
    total_employer = money(
        employer_social + employer_amo + employer_family + employer_tfp
    )
    return {
        "assiette_plafonnee": money(assiette_plafonnee),
        "employee_social": employee_social,
        "employee_amo": employee_amo,
        "total_employee": total_employee,
        "employer_social": employer_social,
        "employer_amo": employer_amo,
        "employer_family": employer_family,
        "employer_tfp": employer_tfp,
        "total_employer": total_employer,
        "net_a_payer": money(brut - total_employee),
    }


def compute_is(
    bnf: Decimal | int | float | str,
    category: str = "standard",
    annee: int | None = None,
) -> Decimal:
    """IS sur le benefice net fiscal, au **taux de l'exercice**.

    ``annee`` est l'exercice fiscal : le taux applique est celui du registre
    `IS_RATES_BY_YEAR`. Un exercice non parametre est **refuse** (message
    explicite) : l'application ne devine jamais un taux et n'applique pas celui
    d'une autre annee. Sans ``annee`` (appels historiques), le dernier exercice
    parametre est utilise.

    Le taux de **droit commun** est automatiquement remplace, pour les exercices
    qui en disposent, par :
    - le taux **grandes entreprises** au-dela de `IS_LARGE_COMPANY_THRESHOLD` ;
    - le taux **transitoire** (`small_profit`, ex. 17,5 % en 2025) lorsque le
      benefice net fiscal ne depasse pas `IS_SMALL_PROFIT_THRESHOLD_BY_YEAR`.
    """
    benefice = Decimal(str(bnf))
    if annee is None:
        taux = IS_RATES_BY_YEAR[DERNIER_EXERCICE_IS]
    else:
        taux = is_rates(annee)
    if benefice <= 0:
        return money(0)
    if category == "standard":
        if benefice > IS_LARGE_COMPANY_THRESHOLD:
            category = "large_company"
        else:
            seuil_reduit = IS_SMALL_PROFIT_THRESHOLD_BY_YEAR.get(int(annee or 0))
            if "small_profit" in taux and seuil_reduit is not None and benefice <= seuil_reduit:
                category = "small_profit"
    return money(benefice * taux.get(category, taux["standard"]))


def is_rates(annee: int) -> dict[str, Decimal]:
    """Taux d'IS de l'exercice (leve une erreur si l'exercice n'est pas parametre)."""
    taux = IS_RATES_BY_YEAR.get(int(annee))
    if taux is None:
        raise ValueError(
            f"Taux d'IS non paramétré pour l'exercice {annee} : aucun taux n'est deviné. "
            "Ajoutez le barème officiel de l'exercice (loi de finances) dans "
            "`IS_RATES_BY_YEAR` (`app/core/rates_ma.py`) avant tout calcul fiscal."
        )
    return taux


def compute_cotisation_minimale(
    assiette: Decimal | int | float | str,
    months_of_activity: int = 12,
    *,
    annee: int | None = None,
) -> Decimal:
    """Cotisation minimale : 0,25 % des produits **hors TVA**, plancher 3 000 MAD.

    ``assiette`` est le montant **hors taxe sur la valeur ajoutee** des produits
    enumeres au CGI art. 144-I-B (CA, autres produits d'exploitation, produits
    financiers, subventions et dons) — jamais un montant TTC (voir
    `services.fiscal_liasse.assiette_cotisation_minimale`).

    Exoneration totale sur les **36 premiers mois d'activite** (art. 144-I-C-1°),
    cessant au plus tard **60 mois apres la constitution** : le nombre de mois
    doit etre calcule a partir des dates **reelles** de la societe (voir
    `services.fiscal_liasse.exoneration_cotisation_minimale`). Les parametres
    sont **histories par exercice** ; sans `annee`, le dernier connu est utilise.
    """
    parametres = (
        COTISATION_MINIMALE_BY_YEAR.get(int(annee))
        if annee is not None
        else COTISATION_MINIMALE_BY_YEAR[max(COTISATION_MINIMALE_BY_YEAR)]
    )
    if parametres is None:
        raise ValueError(
            f"Cotisation minimale non paramétrée pour l'exercice {annee} : fournissez les "
            "parametres officiels (taux, plancher, exoneration) — "
            "`COTISATION_MINIMALE_BY_YEAR` dans `app/core/rates_ma.py`."
        )
    if months_of_activity <= parametres["exemption_months"]:
        return money(0)
    cm = Decimal(str(assiette)) * parametres["rate"]
    return money(max(cm, parametres["minimum"]))