"""Documents PDF comptables : etats de synthese, pieces et bordereaux.

Ce module est la **couche metier du rendu PDF** : il construit des `Document`
(voir `services/pdf.py`, moteur ReportLab) a partir des **mêmes services que
l'ecran** (`reporting`, `etats_synthese`, `invoicing`, `edi_tva`) : les montants
des PDF sont donc **identiques a l'ecran au centime** (critere de recette J1).

Contraintes respectees :
- **PDF ≤ 10 Mo** par fichier (portail de depot au greffe, guide de novembre
  2025) : controle systematique par `pdf.controle_taille_pdf` (via `rendre_pdf`) ;
- mention **« PROVISOIRE »** (filigrane + pied) tant que l'exercice n'est pas
  cloture (`etats_synthese.exercice_clos`) ;
- les formateurs de montants reproduisent exactement les filtres de l'interface
  (`1 234,56`) — un test verifie l'egalite avec `app.web.deps.format_amount`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.rates_ma import money
from app.models import Company, FiscalYear, Invoice, ThirdParty
from app.services import reporting
from app.services.invoicing import AccountingError, controles_coherence_facture


class DocumentIncoherentError(AccountingError):
    """Le document demande ne peut pas etre emis : donnees incoherentes.

    Cas typique (recette J9) : ligne de facture ou ventilation de TVA a zero
    alors que les totaux generaux sont corrects. Le document est **refuse** au
    lieu d'etre transmis avec des montants incoherents.
    """


from app.services.edi_tva import (
    MAX_XML_BYTES,
    collect_rd_lines,
    limite_lignes,
    regime_code,
    xml_filename,
)
from app.services.vat import period_bounds
from app.services.etats_synthese import (
    bilan_normal,
    etat_soldes_gestion,
    exercice_clos,
    notes_etic,
)
from app.services.pdf import Colonne, Document, Tableau, rendre_pdf

DEVISE = "DH"
# Postes obligatoires du dossier de depot au greffe, par forme juridique
# (guide « Depot electronique des etats de synthese », Ministere de la Justice,
# novembre 2025 ; liste exacte du portail a confirmer a la premiere adhesion).
PIECES_GREFFE_COMMUNES: tuple[str, ...] = (
    "Etats de synthese (bilan, CPC, ESG, ETIC) certifies conformes",
    "Rapport de gestion",
    "Proces-verbal de l'assemblee generale d'approbation et texte des resolutions",
)
PIECES_GREFFE_PAR_FORME: dict[str, tuple[str, ...]] = {
    "SA": ("Rapport du ou des commissaires aux comptes",),
    "SARL": ("Rapport du commissaire aux comptes (si nomme)",),
    "SNC": (),
    "SCS": (),
    "SCA": ("Rapport du ou des commissaires aux comptes",),
}


# ---------------------------------------------------------------------------
# Formateurs (identiques aux filtres de l'interface : « 1 234,56 »)
# ---------------------------------------------------------------------------
def format_montant(valeur: Any) -> str:
    """Montant sans devise, format marocain (espace pour les milliers)."""
    if valeur is None:
        return "0,00"
    return f"{Decimal(str(valeur)):,.2f}".replace(",", " ").replace(".", ",")


def format_montant_devise(valeur: Any) -> str:
    """Montant suivi de la devise (« 1 234,56 DH »)."""
    return f"{format_montant(valeur)} {DEVISE}"


def format_date_fr(valeur: date | None) -> str:
    """Date au format 18/09/2026."""
    return valeur.strftime("%d/%m/%Y") if valeur else "—"


def format_taux(valeur: Any) -> str:
    """Taux en pourcentage, format francais (« 20 » ou « 4,48 »)."""
    if valeur is None:
        return ""
    return f"{Decimal(str(valeur)).normalize():f}".replace(".", ",")


def format_quantite(valeur: Any) -> str:
    """Quantite (jusqu'a 3 decimales, zeros inutiles supprimes) — filtres de l'ecran."""
    if valeur is None:
        return "0"
    texte = f"{Decimal(str(valeur)):,.3f}".rstrip("0").rstrip(".")
    return texte.replace(",", " ").replace(".", ",") or "0"


# ---------------------------------------------------------------------------
# Contexte commun (societe, exercice, mention provisoire)
# ---------------------------------------------------------------------------
def mention_provisoire(db: Session, company_id: int, exercice: int) -> str | None:
    """Mention a apposer tant que l'exercice n'est pas cloture (None sinon)."""
    if exercice_clos(db, company_id, exercice):
        return None
    return (
        "PROVISOIRE — exercice non cloture : document de travail sans valeur "
        "definitive (a soumettre a validation avant depot)."
    )


def _identite_societe(company: Company) -> str:
    """Ligne d'identification legale de la societe (mentions CGI art. 145)."""
    elements: list[str] = []
    if company.ice:
        elements.append(f"ICE : {company.ice}")
    if company.fiscal_id:
        elements.append(f"IF : {company.fiscal_id}")
    if company.rc:
        elements.append(f"RC : {company.rc}")
    if company.patente:
        elements.append(f"Patente : {company.patente}")
    return " — ".join(elements) if elements else "Identifiants legaux non renseignes"


# ---------------------------------------------------------------------------
# Identite **harmonisee** de la societe (fiche societe = source unique)
#
# Correctif de recette : le rapport de gestion et le PV d'AG affichaient une forme
# juridique vide et un siege « non renseigne » (fiche societe incomplete), et la
# qualite « associe unique » n'etait deduite que dans le PV. Ces fonctions
# alimentent **tous** les documents de la meme facon : forme juridique, siege
# social et qualite de l'assemblee (SARL AU = associe unique).
# ---------------------------------------------------------------------------
def forme_juridique(company: Company) -> str:
    """Forme sociale des documents : fiche societe, sinon raison sociale."""
    declaree = (company.legal_form or "").strip().upper()
    if declaree:
        return declaree
    nom = (company.name or "").upper()
    for code in ("SARL AU", "SARL", "SNC", "SCS", "SCA", "SA"):
        if code in nom:
            return code
    return "non renseignee"


def forme_code(company: Company) -> str:
    """Code de forme pour les referentiels (SARL AU -> SARL, SA -> SA)."""
    forme = forme_juridique(company)
    for code in ("SARL", "SNC", "SCS", "SCA", "SA"):
        if forme.startswith(code):
            return code
    return forme


def _associe_unique_fiche(company: Company) -> bool:
    """(interne) Vrai pour une SARL a associe unique (SARL AU)."""
    forme = forme_juridique(company)
    if "UNIQUE" in forme or "AU" in forme.split():
        return True
    return "SARL AU" in (company.name or "").upper()


def associe_unique(company: Company) -> bool:
    """API : societe a associe unique (SARL AU) — qualite de l'assemblee."""
    return _associe_unique_fiche(company)


def qualite_assemblee(company: Company) -> str:
    """Qualite des participants (« l'associe unique » ou « l'assemblee des associes »)."""
    return (
        "l'associe unique de la societe"
        if associe_unique(company)
        else "l'assemblee generale des associes"
    )


def siege_social(company: Company) -> str:
    """Siege social **issu de la fiche societe** (adresse, ville) et signale s'il manque."""
    morceaux = [texte for texte in (company.address, company.city) if texte]
    if not morceaux:
        return "a completer dans la fiche societe (adresse et ville non renseignees)"
    siege = ", ".join(morceaux)
    if not company.address:
        return f"{siege} (adresse a completer dans la fiche societe)"
    return siege


def _entete(
    company: Company,
    exercice: int,
    date_from: date,
    date_to: date,
) -> list[str]:
    """Lignes d'en-tete communes a tous les etats."""
    return [
        f"{company.name} — {_identite_societe(company)}",
        f"Exercice {exercice} : du {format_date_fr(date_from)} au {format_date_fr(date_to)}",
        f"Monnaie de tenue : {DEVISE} — referentiel CGNC / PCGE",
    ]


def _document(
    *,
    titre: str,
    sous_titre: str | None,
    entete: list[str],
    tableaux: list[Tableau],
    pied: str,
    provisoire: str | None,
) -> Document:
    """Assemble le document et rappelle la mention provisoire (corps + filigrane).

    La mention est **ecrite dans le corps** du document (premiere ligne d'en-tete),
    en plus du filigrane : un document provisoire doit etre identifiable
    immediatement, y compris apres extraction du texte.
    """
    lignes_entete = list(entete)
    if provisoire:
        lignes_entete.insert(0, provisoire)
    return Document(
        titre=titre,
        sous_titre=sous_titre,
        entete=lignes_entete,
        tableaux=tableaux,
        pied=f"{pied} - {provisoire}" if provisoire else pied,
        filigrane="PROVISOIRE" if provisoire else None,
    )



# ---------------------------------------------------------------------------
# Etats de synthese (CGNC, modele normal)
# ---------------------------------------------------------------------------
COLONNE_COMPTE = Colonne("Compte", largeur=20)
COLONNE_LIBELLE = Colonne("Libelle", largeur=95)
COLONNE_MONTANT = Colonne("Montant", largeur=35, alignement="right")


def _lignes_postes(postes: list[dict]) -> list[list[str]]:
    """Lignes « poste + detail des comptes » (le poste porte le sous-total)."""
    lignes: list[list[str]] = []
    for poste in postes:
        lignes.append([poste["racine"], poste["libelle"], format_montant(poste["solde"])])
        for compte in poste["comptes"]:
            lignes.append(
                [
                    compte["compte"],
                    f"     {compte['libelle']}",
                    format_montant(compte["solde"]),
                ]
            )
    return lignes or [["—", "Aucun mouvement sur la periode", format_montant(0)]]


def pdf_bilan(db: Session, company: Company, exercice: int) -> bytes:
    """Bilan PDF : **brut / amortissements et provisions / net**, equilibre controle.

    La colonne « net » est le brut diminue des amortissements et provisions
    (presentation CGNC) : le total net est reconcilie avec le total affiche a
    l'ecran (bilan simplifie), l'ecart etant precisement les amortissements et
    provisions reclasses en deduction de l'actif.
    """
    date_from, date_to = reporting.year_bounds(exercice)
    bilan = bilan_normal(db, company.id, date_from, date_to)
    provisoire = mention_provisoire(db, company.id, exercice)

    lignes_passif = _lignes_postes(bilan["passif"])
    lignes_passif.append(
        ["", "Resultat de l'exercice", format_montant(bilan["resultat_exercice"])]
    )

    tableaux = [
        Tableau(
            titre="ACTIF — valeurs brutes (postes et comptes)",
            colonnes=(COLONNE_COMPTE, COLONNE_LIBELLE, COLONNE_MONTANT),
            lignes=_lignes_postes(bilan["actif"]),
            total=["", "TOTAL ACTIF BRUT", format_montant(bilan["total_actif_brut"])],
        ),
        Tableau(
            titre="AMORTISSEMENTS ET PROVISIONS (en deduction de l'actif)",
            colonnes=(COLONNE_COMPTE, COLONNE_LIBELLE, COLONNE_MONTANT),
            lignes=_lignes_postes(bilan["deductions"]),
            total=[
                "",
                "TOTAL AMORTISSEMENTS ET PROVISIONS",
                format_montant(bilan["total_deductions"]),
            ],
        ),
        Tableau(
            titre="PASSIF",
            colonnes=(COLONNE_COMPTE, COLONNE_LIBELLE, COLONNE_MONTANT),
            lignes=lignes_passif,
            total=[
                "",
                "TOTAL PASSIF + RESULTAT",
                format_montant(bilan["total_passif_avec_resultat"]),
            ],
        ),
        Tableau(
            titre="CONTROLES",
            colonnes=(
                Colonne("Controle", largeur=95),
                Colonne("Valeur", largeur=55, alignement="right"),
            ),
            lignes=[
                [
                    "Actif brut - amortissements et provisions",
                    format_montant(bilan["actif_net"]),
                ],
                [
                    "Passif + resultat de l'exercice",
                    format_montant(bilan["total_passif_avec_resultat"]),
                ],
                [
                    "Equilibre du bilan (actif net = passif + resultat)",
                    "EQUILIBRE" if bilan["equilibre"] else "ECART A JUSTIFIER",
                ],
                [
                    "Total actif affiche a l'ecran (bilan simplifie)",
                    format_montant(bilan["ecran_total_actif"]),
                ],
                [
                    "Ecart de presentation (amortissements et provisions)",
                    format_montant(bilan["ecart_ecran_actif"]),
                ],
                [
                    "Coherence avec l'ecran",
                    "OK" if bilan["coherent_avec_ecran"] else "A VERIFIER",
                ],
            ],
        ),
    ]
    document = _document(
        titre=f"BILAN - exercice {exercice}",
        sous_titre="Etats de synthese CGNC, modele normal (brut / amortissements / net)",
        entete=_entete(company, exercice, date_from, date_to),
        tableaux=tableaux,
        pied="Document genere par Compta MA - conservation obligatoire 10 ans (CGNC / CGI).",
        provisoire=provisoire,
    )
    return rendre_pdf(document)



def pdf_cpc(db: Session, company: Company, exercice: int) -> bytes:
    """CPC PDF : charges (classe 6), produits (classe 7) et resultat de l'exercice."""
    date_from, date_to = reporting.year_bounds(exercice)
    cpc = reporting.income_statement(db, company.id, date_from, date_to)
    provisoire = mention_provisoire(db, company.id, exercice)

    def lignes(classe: list[dict], inverser: bool) -> list[list[str]]:
        if not classe:
            return [["—", "Aucun mouvement sur la periode", format_montant(0)]]
        return [
            [
                ligne["account_number"],
                ligne["label"],
                format_montant(-ligne["solde"] if inverser else ligne["solde"]),
            ]
            for ligne in classe
        ]

    tableaux = [
        Tableau(
            titre="CHARGES (classe 6)",
            colonnes=(COLONNE_COMPTE, COLONNE_LIBELLE, COLONNE_MONTANT),
            lignes=lignes(cpc["charges"], inverser=False),
            total=["", "TOTAL DES CHARGES", format_montant(cpc["total_charges"])],
        ),
        Tableau(
            titre="PRODUITS (classe 7)",
            colonnes=(COLONNE_COMPTE, COLONNE_LIBELLE, COLONNE_MONTANT),
            lignes=lignes(cpc["produits"], inverser=True),
            total=["", "TOTAL DES PRODUITS", format_montant(cpc["total_produits"])],
        ),
        Tableau(
            titre="RESULTAT DE L'EXERCICE",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=55, alignement="right"),
            ),
            lignes=[
                ["Total des produits", format_montant(cpc["total_produits"])],
                ["Total des charges", format_montant(cpc["total_charges"])],
                [
                    f"Resultat ({cpc['nature_resultat']})",
                    format_montant(cpc["resultat"]),
                ],
            ],
        ),
    ]
    document = _document(
        titre=f"COMPTE DE PRODUITS ET CHARGES - exercice {exercice}",
        sous_titre="Etats de synthese CGNC : CPC (les soldes de gestion figurent dans l'ESG)",
        entete=_entete(company, exercice, date_from, date_to),
        tableaux=tableaux,
        pied="Document genere par Compta MA - conservation obligatoire 10 ans (CGNC / CGI).",
        provisoire=provisoire,
    )
    return rendre_pdf(document)


def pdf_esg(db: Session, company: Company, exercice: int) -> bytes:
    """ESG PDF : marge brute, valeur ajoutee, EBE, resultats (exploitation, courant, net)."""
    date_from, date_to = reporting.year_bounds(exercice)
    esg = etat_soldes_gestion(db, company.id, date_from, date_to)
    provisoire = mention_provisoire(db, company.id, exercice)

    lignes_soldes = [
        [libelle, format_montant(montant)] for libelle, montant in esg["soldes"]
    ]
    lignes_familles = [
        [famille, format_montant(montant)]
        for famille, montant in sorted(esg["familles"].items())
    ]
    tableaux = [
        Tableau(
            titre="SOLDES DE GESTION (CGNC)",
            colonnes=(
                Colonne("Solde", largeur=110),
                Colonne("Montant", largeur=40, alignement="right"),
            ),
            lignes=lignes_soldes,
            total=["RESULTAT NET DE L'EXERCICE", format_montant(esg["resultat_net"])],
        ),
        Tableau(
            titre="DETAIL PAR FAMILLE DE COMPTES (racines de gestion)",
            colonnes=(
                Colonne("Famille", largeur=30),
                Colonne("Montant net (produit ou charge)", largeur=120, alignement="right"),
            ),
            lignes=lignes_familles
            or [["—", format_montant(0)]],
        ),
        Tableau(
            titre="CONTROLE DE COHERENCE",
            colonnes=(
                Colonne("Controle", largeur=110),
                Colonne("Valeur", largeur=40, alignement="right"),
            ),
            lignes=[
                [
                    "Resultat net de l'ESG",
                    format_montant(esg["resultat_net"]),
                ],
                [
                    "Resultat du CPC",
                    format_montant(esg["resultat_cpc"]),
                ],
                [
                    "Coherence ESG / CPC",
                    "OK" if esg["coherent_avec_cpc"] else "A VERIFIER",
                ],
            ],
        ),
    ]
    document = _document(
        titre=f"ETAT DES SOLDES DE GESTION (ESG) - exercice {exercice}",
        sous_titre="Etats de synthese CGNC : marge brute, valeur ajoutee, EBE et resultats",
        entete=_entete(company, exercice, date_from, date_to),
        tableaux=tableaux,
        pied=(
            "Formules CGNC appliquees aux comptes de gestion (classes 6 et 7) - "
            "document genere par Compta MA."
        ),
        provisoire=provisoire,
    )
    return rendre_pdf(document)



def pdf_etic(db: Session, company: Company, exercice: int) -> bytes:
    """ETIC PDF : notes annexes (informations complementaires) et donnees indisponibles.

    Les notes calculables sont produites depuis la comptabilite ; les informations
    qui dependent d'un module non encore developpe (paie, immobilisations,
    stocks) sont **explicitement listees** avec leur origine : aucune donnee n'est
    inventee (CDC GLOBAL, regle permanente n° 2).
    """
    date_from, date_to = reporting.year_bounds(exercice)
    etic = notes_etic(db, company.id, date_from, date_to)
    provisoire = mention_provisoire(db, company.id, exercice)

    largeurs = {2: (85, 75), 3: (25, 90, 35)}
    tableaux: list[Tableau] = []
    for note in etic["notes"]:
        titres = note["colonnes"]
        nb = len(titres)
        lignes: list[list[str]] = []
        for ligne in note["lignes"]:
            if nb == 3:
                compte, libelle, montant = ligne
                lignes.append([str(compte), str(libelle), format_montant(montant)])
            else:
                lignes.append([str(ligne[0]), str(ligne[1])])
        if note["commentaire"]:
            lignes.append(([""] * (nb - 1)) + [note["commentaire"]])
        total = None
        if note["total"] is not None:
            total = ([""] * (nb - 1)) + [format_montant(note["total"])]
        colonnes = tuple(
            Colonne(
                titre,
                largeur=largeur,
                alignement="right" if index == nb - 1 and total else "left",
            )
            for index, (titre, largeur) in enumerate(zip(titres, largeurs[nb]))
        )
        tableaux.append(
            Tableau(
                titre=f"Note {note['numero']} - {note['titre']}",
                colonnes=colonnes,
                lignes=lignes or [["", "Aucune donnee sur la periode"]],
                total=total,
            )
        )

    tableaux.append(
        Tableau(
            titre="INFORMATIONS NON DISPONIBLES (transparence)",
            colonnes=(
                Colonne("Information", largeur=75),
                Colonne("Origine / action a mener", largeur=85),
            ),
            lignes=[[information, origine] for information, origine in etic["indisponibles"]],
        )
    )
    document = _document(
        titre=f"ETIC - ETAT DES INFORMATIONS COMPLEMENTAIRES - exercice {exercice}",
        sous_titre="Notes annexes (CGNC, modele normal)",
        entete=_entete(company, exercice, date_from, date_to),
        tableaux=tableaux,
        pied=(
            "Notes etablies a partir de la comptabilite - document genere par Compta MA ; "
            "a completer avec l'expert-comptable avant depot."
        ),
        provisoire=provisoire,
    )
    return rendre_pdf(document)



# ---------------------------------------------------------------------------
# Pieces comptables
# ---------------------------------------------------------------------------
def nom_fichier_pdf(prefixe: str, *elements: object) -> str:
    """Nom de fichier PDF normalise (sans accent, espace ni caractere special)."""
    morceaux = [str(element) for element in elements if element not in (None, "")]
    brut = "_".join([prefixe, *morceaux])
    propre = "".join(
        caractere if (caractere.isalnum() or caractere in "-_") else "_"
        for caractere in brut
    )
    return f"{propre}.pdf"


def pdf_facture(db: Session, invoice: Invoice, *, duplicata: bool = False) -> bytes:
    """Facture PDF avec les mentions obligatoires (CGI art. 145).

    Les montants proviennent de la meme base que l'ecran (`invoicing`) : totaux de
    la facture, ventilation par taux de TVA et mentions legales (ICE, IF, RC,
    patente, mode de reglement, somme arretee en toutes taxes comprises).

    **Controle bloquant** : un document dont les lignes (ou la ventilation de TVA)
    ne reconcilient pas les totaux est **refuse** (`DocumentIncoherentError`) afin
    qu'aucun document incoherent ne puisse etre transmis au client ou au
    fournisseur (defaut A4 de la recette J9).
    """
    company = db.get(Company, invoice.company_id)
    tiers = db.get(ThirdParty, invoice.partner_id)
    if company is None:
        raise ValueError("Societe de la facture introuvable")
    incoherences = controles_coherence_facture(invoice)
    if incoherences:
        raise DocumentIncoherentError(
            "Document refuse : facture incoherente (lignes / totaux) -> "
            + " ; ".join(incoherences)
        )
    if invoice.number is None:
        provisoire: str | None = (
            "BROUILLON : facture non validee, sans valeur comptable."
        )
    else:
        provisoire = mention_provisoire(db, company.id, invoice.invoice_date.year)

    ventilation: dict[Decimal, list[Decimal]] = {}
    for ligne in invoice.lines:
        base, tva = ventilation.get(ligne.vat_rate, [Decimal("0"), Decimal("0")])
        ventilation[ligne.vat_rate] = [
            money(base + ligne.line_ht),
            money(tva + ligne.line_vat),
        ]

    tableaux = [
        Tableau(
            titre="Detail des lignes",
            colonnes=(
                Colonne("Designation", largeur=60),
                Colonne("Qte", largeur=15, alignement="right"),
                Colonne("P.U. HT", largeur=25, alignement="right"),
                Colonne("Total HT", largeur=25, alignement="right"),
                Colonne("TVA", largeur=15, alignement="right"),
                Colonne("Total TTC", largeur=25, alignement="right"),
            ),
            lignes=[
                [
                    ligne.designation,
                    format_quantite(ligne.quantity),
                    format_montant(ligne.unit_price),
                    format_montant(ligne.line_ht),
                    f"{format_taux(ligne.vat_rate)} %",
                    format_montant(ligne.line_ttc),
                ]
                for ligne in invoice.lines
            ],
            total=[
                "",
                "",
                "",
                format_montant(invoice.total_ht),
                format_montant(invoice.total_vat),
                format_montant(invoice.total_ttc),
            ],
        ),
        Tableau(
            titre="Ventilation de la TVA par taux",
            colonnes=(
                Colonne("Taux", largeur=30, alignement="right"),
                Colonne("Base HT", largeur=65, alignement="right"),
                Colonne("Montant TVA", largeur=65, alignement="right"),
            ),
            lignes=[
                [f"{format_taux(taux)} %", format_montant(base), format_montant(tva)]
                for taux, (base, tva) in sorted(ventilation.items())
            ],
        ),
    ]

    tableaux.extend(
        [
            Tableau(
                titre="Recapitulatif",
                colonnes=(
                    Colonne("Element", largeur=95),
                    Colonne("Montant", largeur=65, alignement="right"),
                ),
                lignes=[
                    ["Total HT", format_montant(invoice.total_ht)],
                    ["Total TVA", format_montant(invoice.total_vat)],
                    ["Total TTC", format_montant(invoice.total_ttc)],
                    ["Deja regle", format_montant(invoice.paid_amount)],
                    ["Reste a payer", format_montant(invoice.remaining_amount)],
                ],
                total=["TOTAL TTC", format_montant_devise(invoice.total_ttc)],
            ),
            Tableau(
                titre="Mentions legales",
                colonnes=(
                    Colonne("Mention", largeur=70),
                    Colonne("Valeur", largeur=90),
                ),
                lignes=[
                    [
                        "Document",
                        "DUPLICATA (original deja delivre)"
                        if duplicata
                        else "Facture originale - le duplicata est delivre sur demande",
                    ],
                    ["Mode de reglement", str(invoice.payment_mode or "a convenir")],
                    ["Reference", str(invoice.reference or "-")],
                    [
                        "Identifiants du tiers",
                        f"ICE : {tiers.ice if tiers and tiers.ice else 'non renseigne'} - "
                        f"IF : {tiers.fiscal_id if tiers and tiers.fiscal_id else 'non renseigne'}",
                    ],
                    [
                        "Arretee la presente facture a la somme de",
                        f"{format_montant_devise(invoice.total_ttc)} toutes taxes comprises",
                    ],
                    [
                        "Conservation",
                        "10 ans (CGNC / CGI) - document genere par Compta MA",
                    ],
                ],
            ),
        ]
    )

    if invoice.status == "cancelled":
        filigrane = "ANNULE"
    elif invoice.number is None:
        filigrane = "BROUILLON"
    else:
        filigrane = "PROVISOIRE" if provisoire else None

    document = Document(
        titre=(
            f"{'AVOIR' if invoice.is_credit_note else 'FACTURE'} "
            f"{'D ACHAT' if invoice.invoice_type == 'achat' else 'DE VENTE'} - "
            f"{invoice.number or 'brouillon'}"
        ),
        sous_titre=(
            f"{company.name} - {_identite_societe(company)} | "
            f"Date : {format_date_fr(invoice.invoice_date)} | "
            f"Echeance : {format_date_fr(invoice.due_date)}"
        ),
        entete=[
            *([provisoire] if provisoire else []),
            f"Tiers : {tiers.name if tiers else '-'} "
            f"({tiers.code if tiers else '-'})",
        ],
        tableaux=tableaux,
        pied=(
            f"{provisoire + ' - ' if provisoire else ''}"
            "Document genere par Compta MA - conservation obligatoire 10 ans (CGNC / CGI)."
        ),
        filigrane=filigrane,
    )
    return rendre_pdf(document)



CHAMPS_BULLETIN = ("periode", "societe", "salarie", "lignes", "totaux")


def pdf_bulletin_paie(bulletin: dict) -> bytes:
    """Bulletin de paie PDF — interface prete pour le module **Paie (P1.4)**.

    Structure attendue (dictionnaire) ::

        {
          "periode": "2026-01",
          "societe": {"nom": "...", "ice": "...", "fiscal_id": "...", "cnss_number": "..."},
          "salarie": {"matricule": "S001", "nom": "...", "cnss": "...",
                      "situation": "marie", "enfants": 2, "date_entree": date(...)},
          "lignes": [{"libelle": "Salaire de base", "base": D, "taux": D,
                      "gain": D, "retenue": D}, ...],
          "totaux": {"brut": D, "cotisations": D, "ir": D, "net": D},
          "provisoire": "..."   # optionnel
        }

    Le module Paie n'etant pas encore developpe, cette fonction est livree avec sa
    structure de donnees et ses tests : elle sera branchee sur les bulletins reels
    sans modification de l'interface.
    """
    manquants = [champ for champ in CHAMPS_BULLETIN if champ not in bulletin]
    if manquants:
        raise ValueError(f"Bulletin de paie incomplet : champs manquants {manquants}")
    societe = bulletin["societe"] or {}
    salarie = bulletin["salarie"] or {}
    totaux = bulletin["totaux"] or {}

    tableaux = [
        Tableau(
            titre="Elements de la paie",
            colonnes=(
                Colonne("Libelle", largeur=75),
                Colonne("Base", largeur=20, alignement="right"),
                Colonne("Taux", largeur=15, alignement="right"),
                Colonne("Gain", largeur=25, alignement="right"),
                Colonne("Retenue", largeur=25, alignement="right"),
            ),
            lignes=[
                [
                    ligne.get("libelle", ""),
                    format_montant(ligne.get("base")) if ligne.get("base") else "",
                    f"{format_taux(ligne.get('taux'))} %" if ligne.get("taux") else "",
                    format_montant(ligne.get("gain")) if ligne.get("gain") else "",
                    format_montant(ligne.get("retenue")) if ligne.get("retenue") else "",
                ]
                for ligne in bulletin["lignes"]
            ]
            or [["Aucun element de paie", "", "", "", ""]],
        ),
        Tableau(
            titre="Recapitulatif du bulletin",
            colonnes=(
                Colonne("Element", largeur=100),
                Colonne("Montant", largeur=60, alignement="right"),
            ),
            lignes=[
                ["Salaire brut", format_montant(totaux.get("brut"))],
                ["Cotisations salariales (CNSS / AMO / retraite)", format_montant(totaux.get("cotisations"))],
                ["Impot sur le revenu retenu a la source", format_montant(totaux.get("ir"))],
            ],
            total=["NET A PAYER", format_montant_devise(totaux.get("net"))],
        ),
        Tableau(
            titre="Mentions",
            colonnes=(Colonne("Mention", largeur=70), Colonne("Valeur", largeur=90)),
            lignes=[
                ["Periode de paie", str(bulletin["periode"])],
                ["Salarie", f"{salarie.get('nom', '-')} (matricule {salarie.get('matricule', '-')})"],
                ["N° CNSS", str(salarie.get("cnss") or "non renseigne")],
                [
                    "Situation",
                    f"{salarie.get('situation', '-')} - {salarie.get('enfants', 0)} enfant(s)",
                ],
                ["Employeur", f"{societe.get('nom', '-')} - ICE : {societe.get('ice') or '-'}"],
                ["Conservation", "Bulletin a conserver sans limitation de duree (Code du travail)"],
            ],
        ),
    ]
    document = Document(
        titre=f"BULLETIN DE PAIE - {bulletin['periode']}",
        sous_titre=f"{societe.get('nom', '')} - CNSS : {societe.get('cnss_number') or '-'}",
        entete=[f"Salarie : {salarie.get('nom', '-')} - entree le "
                f"{format_date_fr(salarie.get('date_entree'))}"],
        tableaux=tableaux,
        pied=bulletin.get("provisoire")
        or "Document genere par Compta MA - baremes 2026 a valider par l'expert-comptable.",
        filigrane="PROVISOIRE" if bulletin.get("provisoire") else None,
    )
    return rendre_pdf(document)



# ---------------------------------------------------------------------------
# Bordereaux (recapitulatifs de depot)
# ---------------------------------------------------------------------------
def pdf_bordereau_tva(
    db: Session,
    company: Company,
    year: int,
    *,
    month: int | None = None,
    quarter: int | None = None,
) -> bytes:
    """Bordereau recapitulatif du releve des deductions TVA (avant depot EDI).

    Les donnees proviennent de `edi_tva.collect_rd_lines` : le document decrit
    **exactement** le fichier XML a deposer (mêmes totaux, mêmes exclusions, mêmes
    anomalies).
    """
    date_from, date_to = period_bounds(year, month=month, quarter=quarter)
    collecte = collect_rd_lines(db, company, date_from, date_to)
    regime = regime_code(company)
    periode = month or quarter or 0
    totaux = collecte["totaux"]

    lignes_taux = [
        [
            f"{taux} %",
            str(valeurs["nb"]),
            format_montant(valeurs["base"]),
            format_montant(valeurs["tva"]),
        ]
        for taux, valeurs in totaux["par_taux"].items()
    ]
    tableaux = [
        Tableau(
            titre="Recapitulatif du releve",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Societe declarante", company.name],
                ["Identifiant fiscal (IF)", str(company.fiscal_id or "non renseigne")],
                ["Periode declaree", f"Exercice {year} - periode {periode}"],
                ["Regime", "Mensuel" if regime == 1 else "Trimestriel"],
                [
                    "Base de rattachement",
                    "Date de paiement"
                    if collecte["base_periode"] == "paiement"
                    else "Date de facture",
                ],
                ["Nombre de lignes retenues", str(totaux["nb_lignes"])],
                ["Base HT deductible", format_montant(totaux["mht"])],
                ["TVA deductible", format_montant(totaux["tva"])],
                ["Total TTC", format_montant(totaux["ttc"])],
                ["Fichier XML a deposer", xml_filename(year, periode, regime)],
            ],
        ),
        Tableau(
            titre="Ventilation par taux",
            colonnes=(
                Colonne("Taux", largeur=25, alignement="right"),
                Colonne("Lignes", largeur=20, alignement="right"),
                Colonne("Base HT", largeur=55, alignement="right"),
                Colonne("TVA", largeur=55, alignement="right"),
            ),
            lignes=lignes_taux or [["-", "0", format_montant(0), format_montant(0)]],
        ),
        Tableau(
            titre="Lignes ecartees du releve",
            colonnes=(
                Colonne("Reference", largeur=40),
                Colonne("Motif", largeur=80),
                Colonne("Base HT", largeur=35, alignement="right"),
            ),
            lignes=[
                [exclue["reference"], exclue["motif"], format_montant(exclue["mht"])]
                for exclue in collecte["exclues"]
            ]
            or [["-", "Aucune ligne ecartee", format_montant(0)]],
        ),
        Tableau(
            titre="Anomalies a verifier",
            colonnes=(
                Colonne("Reference", largeur=35),
                Colonne("Motif", largeur=85),
                Colonne("Gravite", largeur=35),
            ),
            lignes=[
                [
                    anomalie["reference"],
                    anomalie["motif"],
                    "BLOQUANTE" if anomalie["bloquant"] else "a verifier",
                ]
                for anomalie in collecte["anomalies"]
            ]
            or [["-", "Aucune anomalie detectee", "-"]],
        ),
        Tableau(
            titre="Rappel des controles du depot EDI (DGI)",
            colonnes=(
                Colonne("Controle", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Format attendu", "XML (jamais une archive ZIP)"],
                ["Taille maximale du fichier", f"{MAX_XML_BYTES // 1000} Ko"],
                ["Nombre maximal de lignes du fichier", str(limite_lignes())],
                ["Lignes a TVA nulle", "hors releve (declaration principale)"],
                ["TVA deductible declaree", format_montant(totaux["tva"])],
            ],
        ),
    ]
    document = _document(
        titre=f"BORDEREAU - RELEVE DES DEDUCTIONS TVA {year} P{periode}",
        sous_titre="Recapitulatif du fichier EDI a deposer sur SIMPL-TVA (DGI)",
        entete=_entete(company, year, date_from, date_to),
        tableaux=tableaux,
        pied="Document genere par Compta MA - a joindre au dossier de travail (conservation 10 ans).",
        provisoire=mention_provisoire(db, company.id, year),
    )
    return rendre_pdf(document)



def _donnees_gestion(db: Session, company_id: int, exercice: int) -> dict:
    """Chiffres de l'exercice servant au **rapport de gestion** et au **PV d'AG**.

    Tous les montants viennent des memes services que l'ecran (`etat_soldes_gestion`
    pour la gestion, `balance_sheet` pour le bilan) : aucune valeur n'est inventee
    ni saisie en dur.
    """
    date_from, date_to = reporting.year_bounds(exercice)
    esg = etat_soldes_gestion(db, company_id, date_from, date_to)
    bilan_cgnc = bilan_normal(db, company_id, date_from, date_to)
    familles: dict[str, Decimal] = esg["familles"]

    def somme(*racines: str) -> Decimal:
        return money(
            sum(
                (valeur for famille, valeur in familles.items() if famille.startswith(racines)),
                Decimal("0"),
            )
        )

    return {
        "date_from": date_from,
        "date_to": date_to,
        "chiffre_affaires": somme("711", "712", "713", "714", "716", "718", "719"),
        "achats_consommes": somme("611", "612", "613"),
        "charges_personnel": somme("616", "617"),
        "marge_brute": esg["marge_brute"],
        "valeur_ajoutee": esg["valeur_ajoutee"],
        "ebe": esg["ebe"],
        "resultat_exploitation": esg["resultat_exploitation"],
        "resultat_courant": esg["resultat_courant"],
        "resultat_net": esg["resultat_net"],
        # Total du bilan **net** (presentation CGNC brut / amortissements / net) :
        # c'est le seul total approuve par l'assemblee et depose au greffe. Le
        # "total actif brut" de l'ecran ne doit **jamais** servir de total du bilan
        # (correctif de recette : 387 520 brut au lieu de 375 520 net equilibre).
        "total_bilan": bilan_cgnc["actif_net"],
        "total_actif_brut": bilan_cgnc["total_actif_brut"],
        "total_deductions": bilan_cgnc["total_deductions"],
        "total_passif": bilan_cgnc["total_passif"],
        "total_passif_avec_resultat": bilan_cgnc["total_passif_avec_resultat"],
        "equilibre": bilan_cgnc["equilibre"],
    }


def affectation_resultat(resultat_net: Decimal | float | None) -> str:
    """Affectation **par defaut** du resultat, libellee sans ambiguite.

    Aucune distribution de dividendes n'est decidee par l'application : un
    benefice est porte au **report a nouveau**, une perte au **report a nouveau
    debiteur** (l'assemblee generale reste libre de modifier cette affectation).
    """
    montant = money(resultat_net or 0)
    if montant >= 0:
        return (
            "Affectation proposee : affectation du resultat beneficiaire de "
            f"{format_montant_devise(montant)} au compte « Report a nouveau » "
            "(aucune distribution de dividendes n'est decidee par l'application)."
        )
    return (
        "Affectation proposee : report a nouveau debiteur de "
        f"{format_montant_devise(abs(montant))} (perte de l'exercice)."
    )


def pdf_bordereau_greffe(db: Session, company: Company, exercice: int) -> bytes:
    """Bordereau et checklist du depot des etats de synthese au greffe du tribunal.

    References : guide « Depot electronique des etats de synthese » (Ministere de la
    Justice, novembre 2025), portail `depotbilan.justice.gov.ma` ; **loi 5-96**
    (art. 10 : assemblee dans les six mois de la cloture ; art. 93 : publicite par
    depot au greffe) et **loi 17-95** (art. 14) pour les societes anonymes.
    """
    date_from, date_to = reporting.year_bounds(exercice)
    forme = forme_code(company)
    pieces = list(PIECES_GREFFE_COMMUNES) + list(PIECES_GREFFE_PAR_FORME.get(forme, ()))
    clos = exercice_clos(db, company.id, exercice)

    tableaux = [
        Tableau(
            titre="Identite du deposant",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Societe", company.name],
                ["Forme juridique", forme_juridique(company)],
                ["Qualite (associe unique)", "oui" if associe_unique(company) else "non"],
                [
                    "Registre de commerce (exige par le portail)",
                    str(company.rc or "non renseigne"),
                ],
                ["Identifiant fiscal (IF)", str(company.fiscal_id or "non renseigne")],
                ["ICE", str(company.ice or "non renseigne")],
                ["Siege social", siege_social(company)],
                ["Exercice concerne", str(exercice)],
                [
                    "Etat des comptes",
                    "Etats definitifs (exercice cloture)"
                    if clos
                    else "PROVISOIRE - exercice non cloture",
                ],
            ],
        ),
        Tableau(
            titre="Pieces obligatoires du dossier (a verifier avant depot)",
            colonnes=(
                Colonne("Piece", largeur=110),
                Colonne("Etat", largeur=30, alignement="right"),
            ),
            lignes=[[piece, "a joindre"] for piece in pieces],
        ),
        Tableau(
            titre="Contraintes du portail (guide de novembre 2025)",
            colonnes=(
                Colonne("Contrainte", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Portail de depot", "https://depotbilan.justice.gov.ma"],
                ["Format des pieces", "PDF uniquement"],
                ["Taille maximale par fichier", "10 Mo"],
                ["Delai d'assemblee (loi 5-96, art. 10)", "6 mois apres la cloture"],
                [
                    "Publicite legale (loi 5-96 art. 93 / loi 17-95 art. 14)",
                    "depot au greffe du tribunal du siege",
                ],
                [
                    "Paiement des taxes apres approbation",
                    "3 jours (au-dela : rejet automatique)",
                ],
                ["Etat du depot dans Compta MA", "a deposer (module P1.5 a venir)"],
            ],
        ),
    ]
    document = _document(
        titre=f"BORDEREAU DE DEPOT AU GREFFE - exercice {exercice}",
        sous_titre="Etats de synthese (CGNC) - dossier a deposer au greffe du tribunal",
        entete=_entete(company, exercice, date_from, date_to),
        tableaux=tableaux,
        pied=(
            "Liste des pieces a confirmer a la premiere adhesion sur le portail - "
            "document genere par Compta MA."
        ),
        provisoire=mention_provisoire(db, company.id, exercice),
    )
    return rendre_pdf(document)



# ---------------------------------------------------------------------------
# P1 greffe : Rapport de gestion et PV d'AG **reels** (alimentes par l'exercice)
# ---------------------------------------------------------------------------
def pdf_rapport_gestion(db: Session, company: Company, exercice: int) -> bytes:
    """Rapport de gestion de l'exercice, **alimente par les donnees comptables**.

    Piece obligatoire du dossier de depot au greffe (loi 5-96, art. 10 et 93 ;
    guide « Depot electronique des etats de synthese », novembre 2025). Le rapport
    expose l'activite, les chiffres cles, la situation financiere, l'affectation
    proposee du resultat et les perspectives : **tous les montants** viennent de
    `etat_soldes_gestion` / `balance_sheet` (identiques a l'ecran, au centime).
    """
    donnees = _donnees_gestion(db, company.id, exercice)
    clos = exercice_clos(db, company.id, exercice)
    forme = forme_juridique(company)
    resultat = donnees["resultat_net"]

    tableaux = [
        Tableau(
            titre="1. Situation de la societe",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Raison sociale", company.name],
                ["Forme juridique", forme],
                ["Qualite de l'assemblee", qualite_assemblee(company)],
                ["Registre de commerce", str(company.rc or "non renseigne")],
                ["Identifiant fiscal", str(company.fiscal_id or "non renseigne")],
                ["ICE", str(company.ice or "non renseigne")],
                ["Siege social", siege_social(company)],
                [
                    "Exercice",
                    f"{exercice} (du {format_date_fr(donnees['date_from'])} au "
                    f"{format_date_fr(donnees['date_to'])})",
                ],
                [
                    "Etat des comptes",
                    "Comptes definitifs (exercice cloture)"
                    if clos
                    else "Comptes provisoires (exercice non cloture)",
                ],
            ],
        ),
        Tableau(
            titre="2. Activite et chiffres cles de l'exercice",
            colonnes=(
                Colonne("Indicateur", largeur=95),
                Colonne("Montant", largeur=65, alignement="right"),
            ),
            lignes=[
                [
                    "Chiffre d'affaires (produits 71x)",
                    format_montant(donnees["chiffre_affaires"]),
                ],
                ["Achats consommes (611/612/613)", format_montant(donnees["achats_consommes"])],
                ["Marge brute", format_montant(donnees["marge_brute"])],
                ["Valeur ajoutee", format_montant(donnees["valeur_ajoutee"])],
                ["Excedent brut d'exploitation (EBE)", format_montant(donnees["ebe"])],
                ["Charges de personnel (616/617)", format_montant(donnees["charges_personnel"])],
                ["Resultat d'exploitation", format_montant(donnees["resultat_exploitation"])],
                ["Resultat courant", format_montant(donnees["resultat_courant"])],
            ],
            total=[
                "Resultat net de l'exercice",
                format_montant_devise(resultat),
            ],
        ),
        Tableau(
            titre=f"3. Situation financiere au {format_date_fr(donnees['date_to'])}",
            colonnes=(
                Colonne("Poste", largeur=95),
                Colonne("Montant", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Total du bilan net (actif net)", format_montant(donnees["total_bilan"])],
                ["Pour memoire : total actif brut", format_montant(donnees["total_actif_brut"])],
                [
                    "Amortissements et provisions deduits de l'actif",
                    format_montant(donnees["total_deductions"]),
                ],
                ["Passif hors resultat de l'exercice", format_montant(donnees["total_passif"])],
                ["Resultat de l'exercice porte au passif", format_montant(resultat)],
                [
                    "Controle d'equilibre (actif net = passif)",
                    "equilibre" if donnees["equilibre"] else "ECART A EXPLIQUER",
                ],
            ],
            total=[
                "Total du bilan net (actif = passif)",
                format_montant_devise(donnees["total_bilan"]),
            ],
        ),
        Tableau(
            titre="4. Affectation du resultat de l'exercice",
            colonnes=(Colonne("Decision", largeur=160),),
            lignes=[
                [
                    f"Resultat net comptable de l'exercice {exercice} : "
                    f"{format_montant_devise(resultat)}."
                ],
                [affectation_resultat(resultat)],
                [
                    "Cette affectation est soumise a l'assemblee generale d'approbation des "
                    "comptes (voir proces-verbal joint) : elle reste modifiable par l'organe "
                    "competent."
                ],
            ],
        ),
        Tableau(
            titre="5. Perspectives et informations a confirmer",
            colonnes=(Colonne("Point", largeur=160),),
            lignes=[
                [
                    "Perspectives : l'exercice suivant s'inscrit dans la continuite de "
                    "l'exploitation ; aucune information de nature a remettre en cause la "
                    "continuite d'exploitation n'est enregistree dans l'application."
                ],
                [
                    "Evenements marquants, litiges, conventions reglementees : aucune "
                    "information n'est enregistree a ce titre dans l'application ; ce point "
                    "doit etre confirme par l'organe d'administration avant depot."
                ],
                [
                    "Investissements engages et recherche et developpement : a completer par "
                    "l'organe d'administration si l'activite le justifie."
                ],
            ],
        ),
        Tableau(
            titre="6. Rappel des obligations legales applicables",
            colonnes=(
                Colonne("Obligation", largeur=95),
                Colonne("Reference", largeur=65, alignement="right"),
            ),
            lignes=[
                [
                    "Assemblee d'approbation des comptes",
                    "6 mois apres la cloture (loi 5-96, art. 10)",
                ],
                [
                    "Publicite des comptes",
                    "depot au greffe du tribunal du siege (loi 5-96, art. 93)",
                ],
                [
                    "Depot electronique",
                    "portail depotbilan.justice.gov.ma (PDF, 10 Mo max par fichier)",
                ],
                [
                    "Pieces jointes obligatoires",
                    "etats de synthese + rapport de gestion + PV d'AG",
                ],
            ],
        ),
    ]
    document = _document(
        titre=f"RAPPORT DE GESTION - exercice {exercice}",
        sous_titre=(
            "Rapport de l'organe d'administration sur l'activite et les comptes de "
            "l'exercice"
        ),
        entete=_entete(company, exercice, donnees["date_from"], donnees["date_to"]),
        tableaux=tableaux,
        pied=(
            "Rapport de gestion genere par Compta MA a partir des comptes de l'exercice "
            "- a presenter a l'assemblee generale d'approbation des comptes."
        ),
        provisoire=mention_provisoire(db, company.id, exercice),
    )
    return rendre_pdf(document)



def pdf_pv_ag(
    db: Session,
    company: Company,
    exercice: int,
    *,
    date_ag: date | None = None,
    date_limite: date | None = None,
    associe_unique: bool | None = None,
    signataire: str | None = None,
) -> bytes:
    """Proces-verbal de l'assemblee generale d'approbation des comptes (reel).

    Le PV porte **la date d'assemblee** (obligatoire), la qualite des participants
    (associe unique ou assemblee des associes selon la forme sociale), l'ordre du
    jour et les **resolutions** (approbation des comptes, affectation du resultat,
    pouvoirs pour les formalites) avec les **montants reels de l'exercice**.
    Sans date d'assemblee, aucun PV ne peut etre produit.
    """
    if date_ag is None:
        raise DocumentIncoherentError(
            "La date de l'assemblee generale est obligatoire pour produire le "
            "proces-verbal (loi 5-96, art. 10)."
        )
    donnees = _donnees_gestion(db, company.id, exercice)
    clos = exercice_clos(db, company.id, exercice)
    forme = forme_juridique(company)
    # Le parametre public reste prioritaire s'il est fourni explicitement.
    unique = _associe_unique_fiche(company) if associe_unique is None else associe_unique
    qualite = (
        "l'associe unique de la societe" if unique else "l'assemblee generale des associes"
    )
    resultat = donnees["resultat_net"]
    delai = (
        "assemblee tenue dans le delai legal de six mois suivant la cloture "
        "(loi 5-96, art. 10)"
    )
    if date_limite is not None and date_ag > date_limite:
        delai = (
            "ATTENTION : assemblee tenue au-dela du delai de six mois suivant la cloture "
            "(loi 5-96, art. 10) - depot susceptible d'etre amendable"
        )
    tableaux = [
        Tableau(
            titre="Identification de la societe et de l'assemblee",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Raison sociale", company.name],
                ["Forme juridique", forme],
                ["Registre de commerce", str(company.rc or "non renseigne")],
                ["Identifiant fiscal", str(company.fiscal_id or "non renseigne")],
                ["ICE", str(company.ice or "non renseigne")],
                ["Siege social", siege_social(company)],
                ["Exercice soumis a approbation", str(exercice)],
                ["Date de l'assemblee generale", format_date_fr(date_ag)],
                ["Qualite des participants", qualite],
                [
                    "Etat des comptes",
                    "comptes definitifs (exercice cloture)"
                    if clos
                    else "comptes provisoires (exercice non cloture)",
                ],
            ],
        ),
        Tableau(
            titre="Ordre du jour",
            colonnes=(Colonne("Point", largeur=160),),
            lignes=[
                [
                    "1. Rapport de gestion de l'organe d'administration pour l'exercice "
                    f"{exercice}."
                ],
                [
                    "2. Etats de synthese de l'exercice (bilan, compte de produits et "
                    "charges, etat des soldes de gestion, ETIC)."
                ],
                ["3. Approbation des comptes de l'exercice et affectation du resultat."],
                ["4. Pouvoirs pour les formalites de publicite legale et de depot au greffe."],
            ],
        ),
        Tableau(
            titre="Premiere resolution - Approbation des comptes de l'exercice",
            colonnes=(Colonne("Resolution", largeur=160),),
            lignes=[
                [
                    f"{qualite.capitalize()} approuve les comptes de l'exercice {exercice} "
                    "tels qu'ils sont presentes : total du bilan net "
                    f"{format_montant_devise(donnees['total_bilan'])}, resultat net comptable "
                    f"{format_montant_devise(resultat)}, chiffre d'affaires "
                    f"{format_montant_devise(donnees['chiffre_affaires'])}."
                ],
                [
                    "Les comptes sont equilibres : "
                    + (
                        "actif net = passif (controle d'equilibre verifie ; total actif brut "
                        f"de {format_montant_devise(donnees['total_actif_brut'])} ramene au net "
                        "apres amortissements et provisions)."
                        if donnees["equilibre"]
                        else "un ecart a ete releve et doit etre explique avant approbation."
                    )
                ],
            ],
        ),
        Tableau(
            titre="Deuxieme resolution - Affectation du resultat",
            colonnes=(Colonne("Resolution", largeur=160),),
            lignes=[
                [affectation_resultat(resultat)],
                [
                    "Le resultat net de l'exercice est fixe a "
                    f"{format_montant_devise(resultat)} conformement au compte de produits et "
                    "charges et a l'etat des soldes de gestion approuves ci-dessus."
                ],
            ],
        ),
        Tableau(
            titre="Troisieme resolution - Pouvoirs pour les formalites",
            colonnes=(Colonne("Resolution", largeur=160),),
            lignes=[
                [
                    "Tous pouvoirs sont donnes au representant legal de la societe pour "
                    "accomplir les formalites de publicite legale et de depot des comptes au "
                    "greffe du tribunal du siege (loi 5-96, art. 93) et signer tout document "
                    "necessaire."
                ],
                [
                    "Le proces-verbal sera depose avec les etats de synthese, le rapport de "
                    "gestion et les autres pieces exigees par le portail de depot "
                    "electronique."
                ],
            ],
        ),
        Tableau(
            titre="Mentions et signatures",
            colonnes=(Colonne("Mention", largeur=160),),
            lignes=[
                [delai + "."],
                [
                    "Proces-verbal etabli par Compta MA a partir des comptes de l'exercice "
                    f"{exercice} ; il constate les resolutions ci-dessus, a signer par "
                    "l'organe competent avant tout depot au greffe."
                ],
                [
                    "Signataire : "
                    + (
                        signataire
                        if signataire
                        else "a completer par le representant legal lors de la signature"
                    )
                ],
                ["Fait le " + format_date_fr(date_ag) + ", au siege social de la societe."],
            ],
        ),
    ]
    document = _document(
        titre=(
            "PROCES-VERBAL DE L'ASSEMBLEE GENERALE ORDINAIRE ANNUELLE - "
            f"exercice {exercice}"
        ),
        sous_titre=(
            "Approbation des comptes de l'exercice et affectation du resultat "
            "(loi 5-96, art. 10)"
        ),
        entete=_entete(company, exercice, donnees["date_from"], donnees["date_to"]),
        tableaux=tableaux,
        pied=(
            f"Proces-verbal d'assemblee generale - exercice {exercice} - document genere "
            "par Compta MA a partir des comptes approuves."
        ),
        provisoire=mention_provisoire(db, company.id, exercice),
    )
    return rendre_pdf(document)


# ---------------------------------------------------------------------------
# Immobilisations (P1.2) : etat, plan d'amortissement, tableau des cessions
# ---------------------------------------------------------------------------
def pdf_etat_immobilisations(db: Session, company: Company, exercice: int) -> bytes:
    """Etat des immobilisations : brut / amortissements / net par poste (CGNC).

    Le document affiche la **reconciliation avec la comptabilite** : un ecart entre
    les fiches et le grand livre est visible dans le PDF (aucun montant n'est
    presente comme juste s'il diverge).
    """
    from app.services.assets import etat_immobilisations

    etat = etat_immobilisations(db, company.id, exercice)
    date_from, date_to = reporting.year_bounds(exercice)
    provisoire = mention_provisoire(db, company.id, exercice)

    lignes: list[list[str]] = []
    for poste in etat["postes"]:
        lignes.append(
            [
                poste["compte"],
                poste["libelle"],
                format_montant(poste["brut"]),
                format_montant(poste["amortissements"]),
                format_montant(poste["vnc"]),
            ]
        )
        for bien in poste["biens"]:
            lignes.append(
                [
                    bien["code"],
                    f"     {bien['label']} (acquis le {format_date_fr(bien['date_acquisition'])})",
                    format_montant(bien["valeur_origine"]),
                    format_montant(bien["amortissements"]),
                    format_montant(bien["vnc"]),
                ]
            )
    tableaux = [
        Tableau(
            titre="IMMOBILISATIONS PAR POSTE (CGNC)",
            colonnes=(
                Colonne("Compte", largeur=20),
                Colonne("Libelle", largeur=75),
                Colonne("Brut", largeur=30, alignement="right"),
                Colonne("Amortissements", largeur=30, alignement="right"),
                Colonne("Net", largeur=30, alignement="right"),
            ),
            lignes=lignes or [["-", "Aucune immobilisation inscrite", "-", "-", "-"]],
            total=[
                "",
                "TOTAUX (fiches)",
                format_montant(etat["total_brut"]),
                format_montant(etat["total_amortissements"]),
                format_montant(etat["total_vnc"]),
            ],
        ),
        Tableau(
            titre="RECONCILIATION AVEC LA COMPTABILITE",
            colonnes=(
                Colonne("Controle", largeur=95),
                Colonne("Fiches", largeur=30, alignement="right"),
                Colonne("Grand livre", largeur=30, alignement="right"),
                Colonne("Ecart", largeur=30, alignement="right"),
            ),
            lignes=[
                [
                    "Valeurs brutes (comptes 2xxx)",
                    format_montant(etat["total_brut"]),
                    format_montant(etat["comptabilite"]["brut"]),
                    format_montant(etat["ecarts"]["brut"]),
                ],
                [
                    "Amortissements (comptes 28x)",
                    format_montant(etat["total_amortissements"]),
                    format_montant(etat["comptabilite"]["amortissements"]),
                    format_montant(etat["ecarts"]["amortissements"]),
                ],
                [
                    "Controler : brut = amortissements + net",
                    format_montant(etat["total_brut"]),
                    format_montant(
                        etat["total_amortissements"] + etat["total_vnc"]
                    ),
                    format_montant(0),
                ],
            ],
        ),
    ]
    document = _document(
        titre=f"ETAT DES IMMOBILISATIONS - exercice {exercice}",
        sous_titre="CGNC, titre II chapitre I (actif immobilise) : brut / amortissements / net",
        entete=_entete(company, exercice, date_from, date_to),
        tableaux=tableaux,
        pied=(
            "Etat etabli depuis les fiches d'immobilisation et reconcilie avec le grand "
            "livre - document genere par Compta MA."
        ),
        provisoire=provisoire,
    )
    return rendre_pdf(document)



def pdf_plan_amortissement(db: Session, company: Company, asset) -> bytes:
    """Plan d'amortissement d'une immobilisation (lineaire/degressif, prorata)."""
    from app.services.assets import comptes_immobilisation, plan_amortissement

    plan = plan_amortissement(asset)
    comptes = comptes_immobilisation(db, asset.account_number)
    provisoire = mention_provisoire(db, company.id, asset.acquisition_date.year)
    mode = "lineaire" if asset.mode == "lineaire" else "degressif"
    if asset.mode == "degressif" and asset.coefficient:
        mode += f" (coefficient {asset.coefficient})"
    tableaux = [
        Tableau(
            titre="IDENTIFICATION DU BIEN",
            colonnes=(Colonne("Element", largeur=75), Colonne("Valeur", largeur=85)),
            lignes=[
                ["Code fiche", asset.code],
                ["Libelle", asset.label],
                ["Compte d'immobilisation", f"{asset.account_number} (PCGE)"],
                ["Date d'acquisition", format_date_fr(asset.acquisition_date)],
                ["Date de mise en service", format_date_fr(asset.service_date)],
                ["Valeur d'origine", format_montant_devise(asset.valeur_origine)],
                ["Valeur residuelle", format_montant_devise(asset.valeur_residuelle)],
                [
                    "Base amortissable",
                    format_montant_devise(
                        asset.valeur_origine - asset.valeur_residuelle
                    ),
                ],
                ["Duree / mode", f"{asset.duree_annees} an(s) - {mode}"],
                [
                    "Prorata temporis (CGI art. 10)",
                    "oui" if asset.prorata_temporis else "non (annee pleine)",
                ],
                [
                    "Comptes d'amortissement",
                    f"{comptes['dotation']} (dotation) / "
                    f"{comptes['amortissement']} (amortissement)",
                ],
                [
                    "TVA recuperable",
                    f"{format_montant(asset.tva_montant)} au {asset.tva_compte}",
                ],
                ["Statut", asset.statut],
            ],
        ),
        Tableau(
            titre="PLAN D'AMORTISSEMENT",
            colonnes=(
                Colonne("Exercice", largeur=20, alignement="right"),
                Colonne("Base", largeur=30, alignement="right"),
                Colonne("Annuite", largeur=30, alignement="right"),
                Colonne("Cumul", largeur=30, alignement="right"),
                Colonne("VNC", largeur=30, alignement="right"),
                Colonne("Etat", largeur=30),
            ),
            lignes=[
                [
                    str(ligne["exercice"]),
                    format_montant(ligne["base"]),
                    format_montant(ligne["annuite"]),
                    format_montant(ligne["cumul"]),
                    format_montant(ligne["vnc"]),
                    "constatee" if ligne["constatee"] else "projetee",
                ]
                for ligne in plan
            ]
            or [["-", "-", "-", "-", "-", "aucun plan (bien non amortissable)"]],
            total=[
                "",
                "",
                format_montant(sum((l["annuite"] for l in plan), Decimal("0"))),
                format_montant(sum((l["cumul"] for l in plan), Decimal("0"))),
                "",
                "",
            ],
        ),
    ]
    document = _document(
        titre=f"PLAN D'AMORTISSEMENT - {asset.code}",
        sous_titre=f"{asset.label} - compte {asset.account_number}",
        entete=_entete(
            company,
            asset.acquisition_date.year,
            asset.acquisition_date,
            asset.acquisition_date,
        ),
        tableaux=tableaux,
        pied=(
            "Plan projete (les lignes « constatee » correspondent aux dotations "
            "comptabilisees) - document genere par Compta MA."
        ),
        provisoire=provisoire,
    )
    return rendre_pdf(document)



def pdf_tableau_cessions(db: Session, company: Company, exercice: int) -> bytes:
    """Tableau des cessions et mises au rebut de l'exercice (plus/moins-value)."""
    from app.services.assets import tableau_cessions

    tableau = tableau_cessions(db, company.id, exercice)
    date_from, date_to = reporting.year_bounds(exercice)
    tableaux = [
        Tableau(
            titre="CESSIONS ET MISES AU REBUT DE L'EXERCICE",
            colonnes=(
                Colonne("Code", largeur=22),
                Colonne("Libelle", largeur=42),
                Colonne("Sortie", largeur=20),
                Colonne("Valeur d'origine", largeur=26, alignement="right"),
                Colonne("Amortissements", largeur=26, alignement="right"),
                Colonne("VNC", largeur=24, alignement="right"),
                Colonne("Prix", largeur=24, alignement="right"),
                Colonne("Resultat", largeur=24, alignement="right"),
            ),
            lignes=[
                [
                    ligne["code"],
                    ligne["label"],
                    format_date_fr(ligne["date_sortie"]),
                    format_montant(ligne["valeur_origine"]),
                    format_montant(ligne["amortissements"]),
                    format_montant(ligne["vnc"]),
                    format_montant(ligne["prix"]),
                    format_montant(ligne["resultat"]),
                ]
                for ligne in tableau["lignes"]
            ]
            or [["-", "Aucune cession sur la periode", "-", "-", "-", "-", "-", "-"]],
            total=[
                "",
                "TOTAUX",
                "",
                format_montant(tableau["total_valeur_origine"]),
                "",
                format_montant(tableau["total_vnc"]),
                format_montant(tableau["total_prix"]),
                format_montant(tableau["total_resultat"]),
            ],
        ),
        Tableau(
            titre="REGULARISATIONS DE TVA (CGI art. 106)",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                [
                    "TVA regularisee sur les immobilisations sorties",
                    format_montant(tableau["total_regularisation"]),
                ],
                [
                    "Regle appliquee",
                    "fractions egales (5 ans meubles / 10 ans immeubles) - a confirmer",
                ],
            ],
        ),
    ]
    document = _document(
        titre=f"TABLEAU DES CESSIONS - exercice {exercice}",
        sous_titre="Sorties d'actif immobilise : VNA (6513/6512) et produits (7513/7512)",
        entete=_entete(company, exercice, date_from, date_to),
        tableaux=tableaux,
        pied=(
            "Document genere par Compta MA - conservation obligatoire 10 ans "
            "(CGNC / CGI)."
        ),
        provisoire=mention_provisoire(db, company.id, exercice),
    )
    return rendre_pdf(document)

