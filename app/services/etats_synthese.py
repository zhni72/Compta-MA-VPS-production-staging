"""Etats de synthese CGNC : bilan (brut / amortissements / net), ESG, ETIC.

Ces calculs **completent** `services/reporting.py` sans le modifier : ils
reutilisent `reporting.movements`, seule source des montants affiches a l'ecran,
ce qui garantit que les PDF presentent des montants **identiques au centime**
a l'interface.

Reference : **CGNC — Titre I (etats de synthese)** du modele normal :
1. Bilan (actif brut / amortissements / net — passif) ;
2. CPC (compte de produits et charges) — deja calcule par `reporting` ;
3. **ESG** — Etat des Soldes de Gestion (marge brute, valeur ajoutee, EBE,
   resultat d'exploitation, resultat courant, resultat net) ;
4. **ETIC** — Etat des Informations Complementaires (notes annexes).

La presentation retenue est celle du modele CGNC ; elle reste a valider par
l'expert-comptable (CDC GLOBAL, regle permanente n° 2 : aucune donnee fiscale
n'est devinee).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rates_ma import money
from app.models import FiscalYear
from app.services.reporting import balance_sheet, income_statement, movements

# ---------------------------------------------------------------------------
# Bibliotheques de postes (racines du PCGE) utilisees pour la presentation
# ---------------------------------------------------------------------------
# Familles de charges/produits de l'ESG (racines a 3 chiffres du PCGE marocain).
FAMILLES_ESG: dict[str, str] = {
    "711": "Ventes de marchandises",
    "611": "Achats de marchandises",
    "712": "Ventes de biens et services produits",
    "713": "Variation des stocks de produits",
    "714": "Immobilisations produites",
    "716": "Subventions d'exploitation",
    "718": "Autres produits d'exploitation",
    "612": "Achats de matieres et fournitures consommables",
    "613": "Autres charges externes (locations, entretien, assurances...)",
    "614": "Autres charges externes (transports, honoraires, telecom, banque)",
    "616": "Impots et taxes",
    "617": "Charges de personnel",
    "618": "Autres charges d'exploitation",
    "619": "Dotations d'exploitation",
    "719": "Reprises d'exploitation",
}
# Postes d'actif : (racine, libelle CGNC). Regroupement par racine de compte.
POSTES_ACTIF_IMMOBILISE: tuple[tuple[str, str], ...] = (
    ("21", "Immobilisations en non-valeurs"),
    ("22", "Immobilisations incorporelles"),
    ("23", "Immobilisations corporelles"),
    ("24", "Immobilisations financieres"),
)
POSTES_STOCKS_ET_CREANCES: tuple[tuple[str, str], ...] = (
    ("31", "Stocks de marchandises"),
    ("32", "Stocks de matieres et fournitures"),
    ("33", "Stocks de produits"),
    ("345", "Etat - TVA recuperable (creance sur l'Etat)"),
    ("34", "Creances de l'actif circulant"),
    ("35", "Titres et valeurs de placement"),
)
POSTES_TRESORERIE_ACTIF: tuple[tuple[str, str], ...] = (
    ("51", "Tresorerie (banques, caisses, placements a court terme)"),
)
# Postes venant en DEDUCTION de l'actif (presentation CGNC).
POSTES_DEDUCTIONS_ACTIF: tuple[tuple[str, str], ...] = (
    ("28", "Amortissements des immobilisations"),
    ("29", "Provisions pour depreciation des immobilisations"),
    ("39", "Provisions pour depreciation des stocks"),
    ("49", "Provisions pour depreciation des creances"),
)
POSTES_PASSIF: tuple[tuple[str, str], ...] = (
    ("11", "Capital, primes, reserves et report a nouveau"),
    ("13", "Subventions d'investissement et provisions reglementees"),
    ("14", "Dettes de financement"),
    ("15", "Provisions durables pour risques et charges"),
    ("16", "Comptes de liaison"),
    ("44", "Dettes du passif circulant (fournisseurs, sociales, fiscales)"),
    ("45", "Autres dettes du passif circulant"),
    ("51", "Tresorerie - soldes crediteurs (decouverts bancaires)"),
    ("55", "Tresorerie (credits de tresorerie et decouverts)"),
)


RACINES_DEDUCTIONS_ACTIF = ("28", "29", "39", "49")


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------
def exercice_clos(db: Session, company_id: int, year: int) -> bool:
    """Vrai si l'exercice est cloture (statut « closed » ou « locked »).

    Sert a apposer la mention « provisoire / brouillon » sur les documents tant
    que l'exercice n'est pas cloture.
    """
    statut = db.execute(
        select(FiscalYear.status).where(
            FiscalYear.company_id == company_id, FiscalYear.year == year
        )
    ).scalar_one_or_none()
    return statut in ("closed", "locked")


def _est_deduction(numero: str) -> bool:
    """Vrai si le compte vient en deduction de l'actif (amortissements, provisions)."""
    return numero[:2] in RACINES_DEDUCTIONS_ACTIF


def _postes(lignes: list[dict], mapping: tuple[tuple[str, str], ...]) -> list[dict]:
    """Agrege des lignes d'etats par poste (racine de compte).

    Garantit qu'**aucun montant n'est perdu** : les comptes qui ne correspondent a
    aucun poste du modele sont regroupes dans un poste « Autres comptes », ce qui
    permet de reconcilier le PDF avec l'ecran au centime.
    """
    postes: list[dict] = []
    utilises: set[str] = set()
    for racine, libelle in mapping:
        comptes = [
            l
            for l in lignes
            if l["account_number"].startswith(racine)
            and l["account_number"] not in utilises
        ]
        if not comptes:
            continue
        utilises.update(l["account_number"] for l in comptes)
        postes.append(
            {
                "racine": racine,
                "libelle": libelle,
                "solde": money(sum((l["solde"] for l in comptes), Decimal("0"))),
                "comptes": [
                    {
                        "compte": l["account_number"],
                        "libelle": l["label"],
                        "solde": l["solde"],
                    }
                    for l in comptes
                ],
            }
        )
    autres = [l for l in lignes if l["account_number"] not in utilises]
    if autres:
        postes.append(
            {
                "racine": "",
                "libelle": "Autres comptes",
                "solde": money(sum((l["solde"] for l in autres), Decimal("0"))),
                "comptes": [
                    {
                        "compte": l["account_number"],
                        "libelle": l["label"],
                        "solde": l["solde"],
                    }
                    for l in autres
                ],
            }
        )
    return postes


def _total(lignes: list[dict]) -> Decimal:
    """Somme des soldes (deja arrondis) : aucun arrondi supplementaire."""
    return money(sum((l["solde"] for l in lignes), Decimal("0")))



# ---------------------------------------------------------------------------
# 3. ESG — Etat des Soldes de Gestion (CGNC, modele normal)
# ---------------------------------------------------------------------------
def etat_soldes_gestion(
    db: Session, company_id: int, date_from: date, date_to: date
) -> dict:
    """ESG : marge brute, valeur ajoutee, EBE et resultats (exploitation, courant, net).

    Formules appliquees (CGNC, modele normal) ::

        Marge brute             = Ventes de marchandises (711) - Achats de marchandises (611)
        Valeur ajoutee          = Marge brute + (712 + 713 + 714 + 716 + 718)
                                  - (612 + 613 + 614)
        EBE                     = Valeur ajoutee - (616 + 617)
        Resultat d'exploitation = EBE - (618 + 619) + 719
        Resultat courant        = Resultat d'exploitation + (73x) - (63x)
        Resultat net            = Resultat courant + (75x) - (65x) - (67x)

    Le resultat net est **reconcilie avec le CPC** (`coherent_avec_cpc`) : les deux
    etats doivent afficher le meme resultat.
    """
    lignes = [
        l
        for l in movements(db, company_id, date_from, date_to)
        if l["account_class"] in (6, 7)
    ]
    familles: dict[str, Decimal] = {}
    for ligne in lignes:
        famille = ligne["account_number"][:3]
        # Classe 6 : charge positive. Classe 7 : produit positif (solde crediteur).
        montant = ligne["solde"] if ligne["account_class"] == 6 else -ligne["solde"]
        familles[famille] = familles.get(famille, Decimal("0")) + montant
    familles = {cle: money(valeur) for cle, valeur in familles.items()}

    def groupe(*racines: str) -> Decimal:
        """Somme des familles commencant par l'une des racines (2 ou 3 chiffres)."""
        return money(
            sum(
                (
                    valeur
                    for famille, valeur in familles.items()
                    if famille.startswith(racines)
                ),
                Decimal("0"),
            )
        )

    marge_brute = money(groupe("711") - groupe("611"))
    valeur_ajoutee = money(
        marge_brute
        + groupe("712")
        + groupe("713")
        + groupe("714")
        + groupe("716")
        + groupe("718")
        - groupe("612")
        - groupe("613")
        - groupe("614")
    )
    ebe = money(valeur_ajoutee - groupe("616") - groupe("617"))
    resultat_exploitation = money(ebe - groupe("618") - groupe("619") + groupe("719"))
    resultat_courant = money(resultat_exploitation + groupe("73") - groupe("63"))
    resultat_net = money(resultat_courant + groupe("75") - groupe("65") - groupe("67"))
    cpc = income_statement(db, company_id, date_from, date_to)

    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "familles": familles,
        "marge_brute": marge_brute,
        "valeur_ajoutee": valeur_ajoutee,
        "ebe": ebe,
        "resultat_exploitation": resultat_exploitation,
        "resultat_courant": resultat_courant,
        "resultat_net": resultat_net,
        "resultat_cpc": cpc["resultat"],
        "coherent_avec_cpc": resultat_net == cpc["resultat"],
        "soldes": [
            ("Marge brute sur marchandises", marge_brute),
            ("Valeur ajoutee", valeur_ajoutee),
            ("Excedent brut d'exploitation (EBE)", ebe),
            ("Resultat d'exploitation", resultat_exploitation),
            ("Resultat courant", resultat_courant),
            ("Resultat net de l'exercice", resultat_net),
        ],
    }



# ---------------------------------------------------------------------------
# 1. Bilan — presentation CGNC en brut / amortissements / net
# ---------------------------------------------------------------------------
def bilan_normal(
    db: Session, company_id: int, date_from: date, date_to: date
) -> dict:
    """Bilan CGNC presente en **brut / amortissements et provisions / net**.

    Le classement des comptes reprend **exactement la regle de `reporting.balance_sheet`**
    (classes 2/3/5 au debit -> actif ; classes 1/4 au credit -> passif), afin que le
    PDF se reconcilie **au centime** avec l'ecran. La presentation CGNC ajoute la
    colonne des amortissements et provisions, deduite de l'actif :

        actif net = total actif (ecran) - amortissements et provisions

    ce qui reste equilibre avec `total passif (hors amortissements) + resultat`.
    """
    lignes = movements(db, company_id, date_from, date_to)
    ecran = balance_sheet(db, company_id, date_from, date_to)
    cpc = income_statement(db, company_id, date_from, date_to)

    actif_brut: list[dict] = []
    deductions: list[dict] = []
    passif: list[dict] = []
    for ligne in lignes:
        if ligne["account_class"] not in (1, 2, 3, 4, 5):
            continue
        solde = ligne["solde"]
        if ligne["account_class"] in (2, 3, 5):
            cote_actif = solde >= 0
        else:
            cote_actif = solde > 0
        if cote_actif:
            (deductions if _est_deduction(ligne["account_number"]) else actif_brut).append(ligne)
        elif _est_deduction(ligne["account_number"]):
            deductions.append(ligne)
        else:
            passif.append(ligne)

    postes_actif = _postes(
        actif_brut,
        POSTES_ACTIF_IMMOBILISE + POSTES_STOCKS_ET_CREANCES + POSTES_TRESORERIE_ACTIF,
    )
    postes_deductions = _postes(deductions, POSTES_DEDUCTIONS_ACTIF)
    postes_passif = _postes(passif, POSTES_PASSIF)

    total_actif_brut = _total(actif_brut)
    total_deductions = money(abs(_total(deductions)))
    total_passif = money(abs(_total(passif)))
    resultat = cpc["resultat"]
    actif_net = money(total_actif_brut - total_deductions)

    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "actif": postes_actif,
        "deductions": postes_deductions,
        "passif": postes_passif,
        "total_actif_brut": total_actif_brut,
        "total_deductions": total_deductions,
        "actif_net": actif_net,
        "total_passif": total_passif,
        "resultat_exercice": resultat,
        "total_passif_avec_resultat": money(total_passif + resultat),
        "equilibre": actif_net == money(total_passif + resultat),
        # Reconciliation avec l'ecran (criteres de recette du CDC) :
        "ecran_total_actif": ecran["total_actif"],
        "ecran_total_passif_avec_resultat": ecran["total_passif_avec_resultat"],
        "ecart_ecran_actif": money(actif_net - ecran["total_actif"]),
        "coherent_avec_ecran": money(actif_net - ecran["total_actif"])
        == money(-total_deductions),
    }



# ---------------------------------------------------------------------------
# 4. ETIC — Etat des Informations Complementaires (notes annexes)
# ---------------------------------------------------------------------------
NOTES_INDISPONIBLES: tuple[tuple[str, str], ...] = (
    (
        "Effectif et charges de personnel detailles",
        "module Paie (P1.4) a venir : effectif moyen, repartition par categorie",
    ),
    (
        "Remunerations des dirigeants et jetons de presence",
        "a saisir (donnee non disponible en comptabilite generale)",
    ),
    (
        "Engagements hors bilan (cautions, nantissements, litiges)",
        "a saisir (donnee non disponible en comptabilite generale)",
    ),
    (
        "Stocks : methode de valorisation et inventaire physique",
        "module Stocks (P1.3) a venir : methodes CMUP/FIFO et ecarts d'inventaire",
    ),
)


def note_immobilisations(db: Session, company_id: int, exercice: int) -> dict:
    """Note ETIC « immobilisations » alimentee par le module P1.2 (fiches).

    Le module P1.2 fournit le **detail des mouvements** (acquisitions, dotations,
    cessions, mises au rebut, regularisations art. 106) que le grand livre ne
    restitue pas compte par compte : c'est l'information attendue par l'ETIC.
    """
    # Import local : le module des immobilisations consomme `reporting`, lui-meme
    # utilise ici — l'import differe evite tout cycle au chargement.
    from app.services.assets import list_assets, tableau_cessions

    lignes: list[tuple[str, str, Decimal]] = []
    for asset in list_assets(db, company_id, exercice=exercice):
        lignes.append(
            (
                asset.code,
                f"{asset.label} (compte {asset.account_number})",
                money(asset.valeur_origine),
            )
        )
        lignes.append(
            (
                "     ",
                f"Acquisition {asset.acquisition_date.strftime('%d/%m/%Y')} - "
                f"mise en service "
                f"{asset.service_date.strftime('%d/%m/%Y') if asset.service_date else 'non renseignee'}",
                money(-asset.valeur_origine),
            )
        )
    cessions = tableau_cessions(db, company_id, exercice)
    for ligne in cessions["lignes"]:
        lignes.append(
            (
                "     ",
                f"Sortie du {ligne['date_sortie'].strftime('%d/%m/%Y')} "
                f"({ligne['type']}) - VNC {ligne['vnc']} - prix {ligne['prix']} - "
                f"resultat {ligne['resultat']}",
                money(ligne["valeur_origine"]),
            )
        )
    return {
        "numero": 2,
        "titre": "Immobilisations : mouvements de l'exercice (modules P1.2)",
        "colonnes": ("Code", "Mouvement", "Montant"),
        "lignes": lignes,
        "total": money(
            sum((ligne[2] for ligne in lignes), Decimal("0"))
        ),
        "commentaire": (
            "Detail issu des fiches d'immobilisation (acquisitions, sorties) ; les "
            "dotations et la VNC figurent dans les notes 2 et 3 ci-apres."
        ),
    }



def notes_etic(
    db: Session, company_id: int, date_from: date, date_to: date
) -> dict:
    """ETIC : notes annexes calculables a partir de la comptabilite.

    Retourne une liste de notes structurees (numero, titre, colonnes, lignes,
    total) et la liste des informations **non disponibles**, explicitement
    signalees avec le module a l'origine de la donnee (regle de transparence).
    """
    lignes = movements(db, company_id, date_from, date_to)

    def detail(*racines: str) -> list[tuple[str, str, Decimal]]:
        # Comparaison sur le **prefixe** et non sur les 2 premiers caracteres :
        # les notes ETIC utilisent aussi des racines a 3 caracteres (« 617 »
        # charges de personnel, « 619 » dotations) qui ne pouvaient jamais
        # correspondre a `account_number[:2]` (defaut de recette J9 : note 9 vide
        # alors que le CPC portait 6171/61711/6174/...).
        return [
            (l["account_number"], l["label"], l["solde"])
            for l in lignes
            if l["account_number"].startswith(racines)
        ]

    def total(*racines: str) -> Decimal:
        return money(
            sum(
                (l["solde"] for l in lignes if l["account_number"].startswith(racines)),
                Decimal("0"),
            )
        )

    def note(
        numero: int,
        titre: str,
        racines: tuple[str, ...],
        commentaire: str | None = None,
    ) -> dict:
        lignes_note = detail(*racines)
        return {
            "numero": numero,
            "titre": titre,
            "colonnes": ("Compte", "Libelle", "Montant (solde debiteur - crediteur)"),
            "lignes": lignes_note,
            "total": money(sum((l[2] for l in lignes_note), Decimal("0"))),
            "commentaire": commentaire,
        }

    capitaux = money(
        sum(
            (-l["solde"] for l in lignes if l["account_number"][:2] == "11"),
            Decimal("0"),
        )
    )
    notes = [
        {
            "numero": 1,
            "titre": "Referentiel comptable et methodes appliquees",
            "colonnes": ("Element", "Regle appliquee"),
            "lignes": [
                ("Referentiel", "CGNC / PCGE (plan comptable general des entreprises)"),
                ("Evaluation", "cout historique (CGNC, methodes d'evaluation)"),
                ("Methodes", "permanence des methodes et specialisation des exercices"),
                ("Monnaie de tenue", "dirham (MAD)"),
            ],
            "total": None,
            "commentaire": (
                "Presentation du modele normal CGNC, a valider par l'expert-comptable."
            ),
        },
        note_immobilisations(db, company_id, date_to.year),
        note(3, "Immobilisations brutes (classes 2)", ("21", "22", "23", "24", "27")),
        note(
            4,
            "Amortissements des immobilisations et dotations de l'exercice",
            ("28", "29", "619"),
            "Les dotations de l'exercice (619x) figurent au CPC ; les amortissements "
            "cumules (28x) sont deduits de l'actif.",
        ),
        note(5, "Stocks et provisions pour depreciation", ("31", "32", "33", "39")),
        note(6, "Creances de l'actif circulant et provisions", ("34", "49")),
        note(7, "Tresorerie et concours bancaires courants", ("51", "55")),
        note(
            8,
            "Dettes du passif circulant (fournisseurs, sociales, fiscales)",
            ("44", "45"),
        ),
        note(9, "Charges de personnel de l'exercice", ("617",)),
        {
            "numero": 10,
            "titre": "Capitaux propres (hors resultat de l'exercice)",
            "colonnes": ("Element", "Montant"),
            "lignes": [
                (
                    "Capital, primes, reserves, report a nouveau (11x)",
                    capitaux,
                ),
                (
                    "Subventions d'investissement et provisions reglementees (13x)",
                    money(
                        sum(
                            (
                                -l["solde"]
                                for l in lignes
                                if l["account_number"][:2] == "13"
                            ),
                            Decimal("0"),
                        )
                    ),
                ),
            ],
            "total": capitaux,
            "commentaire": "Le resultat de l'exercice est presente au bilan et au CPC.",
        },
    ]
    return {"notes": notes, "indisponibles": list(NOTES_INDISPONIBLES)}

