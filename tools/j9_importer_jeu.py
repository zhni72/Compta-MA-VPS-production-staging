"""Injection du jeu de donnees de recette J9 (exercices 2025 et 2026).

Le jeu (`jeu_donnees_insertion_compta_maroc_2025_2026.json`) contient : la societe,
deux exercices, **183 ecritures** (474 lignes, equilibrees : 3 678 560 DH), 2
immobilisations, un resume de stocks (3 articles x 2 ans), 3 salaries de test IR et
3 factures de vente. Cet outil l'injecte dans un dossier Compta MA **vide** (voir
`tools/j9_purge_donnees.py`) en respectant les regles suivantes :

1. le **grand livre du jeu fait foi** : les ecritures sont creees par le service
   comptable (numerotation, controles, piste d'audit) avec le **mapping des journaux**
   `ACH -> AC`, `VTE -> VE`, `BNQ -> BQ`, `PAI -> BQ` (le projet utilise 5 journaux
   standards) et la **piece du jeu en reference** ;
2. l'**exercice 2025 est cloture par l'application** (`closing.cloturer_exercice`) :
   les ecritures d'a-nouveaux `OUV-2026` et `STK-OUV-2026` **du jeu ne sont pas
   importees** (l'application les genere) ;
3. les **documents** (factures, immobilisations, stocks, salaries) sont importes
   **sans nouvelle ecriture** : ils sont rattaches a l'ecriture existante par la
   **reference de piece** (aucun double comptage) ;
4. les **factures** (vente et achat) sont **reconstruites depuis le grand livre**
   (piece par piece) et les **reglements** sont affectes en **FIFO** sur les
   encaissements/decaissements reellement portes au grand livre.

Usage :
    python tools/j9_importer_jeu.py --json <chemin> --phase tout --appliquer
    phases : societe, 2025, cloture, 2026, factures, documents, tout
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import OrderedDict, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

PROJET = Path(__file__).resolve().parents[1]
if str(PROJET) not in sys.path:
    sys.path.insert(0, str(PROJET))

from sqlalchemy import delete, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.rates_ma import money  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Asset,
    AssetDepreciationLine,
    Company,
    Employee,
    Entry,
    FiscalYear,
    Invoice,
    InvoiceLine,
    Journal,
    PayContract,
    Payment,
    StockItem,
    StockMovement,
    ThirdParty,
    User,
)
from app.services.accounting import create_entry, get_fiscal_year, get_journal  # noqa: E402
from app.services.closing import cloturer_exercice  # noqa: E402
from app.services.invoicing import recalculate  # noqa: E402
from app.services.parties import create_third_party  # noqa: E402
from app.services.payroll import ajouter_contrat, creer_employe  # noqa: E402
from app.services.stocks import enregistrer_mouvement  # noqa: E402

JSON_DEFAUT = Path(
    r"C:\Users\Belyazid\Desktop\image\compta_maroc\deepsesk\donnees"
    r"\jeu_donnees_insertion_compta_maroc_2025_2026.json"
)
# Journaux du jeu -> journaux standards du projet (AC, VE, BQ, CA, OD).
MAPPING_JOURNAUX = {"ACH": "AC", "VTE": "VE", "BNQ": "BQ", "PAI": "BQ", "OD": "OD"}
# Ecritures d'a-nouveaux **du jeu** : remplacees par celles de l'application.
# (`STK-OUV-2026` n'est **pas** un a-nouveaux mais la contre-passation du stock
# initial 2026 : elle est importee avec les flux, via `--phase complement`.)
PIECES_A_NOUVEAUX = {"OUV-2026"}
PIECES_COMPLEMENT = {"STK-OUV-2026"}
# Clients nommes par le jeu (les autres pieces de vente vont au client divers).
CLIENTS_DU_JEU = {
    "FV25-01": "CLIENT-TEST-A",
    "FV26-01": "CLIENT-TEST-A",
    "FV26-02": "CLIENT-TEST-B",
}
TAUX_TVA_DEFAUT = Decimal("20")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse la ligne de commande."""
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--json", default=str(JSON_DEFAUT), help="jeu de donnees JSON")
    parseur.add_argument(
        "--phase",
        default="tout",
        choices=(
            "societe",
            "2025",
            "cloture",
            "2026",
            "complement",
            "factures",
            "documents",
            "nettoyer",
            "tout",
        ),
        help="etape a executer",
    )
    parseur.add_argument("--appliquer", action="store_true", help="ecrire reellement")
    return parseur.parse_args(argv)


def charger(chemin: Path) -> dict:
    """Charge le jeu de donnees et retourne son contenu + son empreinte SHA-256."""
    contenu = chemin.read_bytes()
    donnees = json.loads(contenu.decode("utf-8"))
    donnees["_json"] = str(chemin)
    donnees["_sha256"] = hashlib.sha256(contenu).hexdigest()
    return donnees


def _societe(db, donnees: dict) -> Company:
    """Societe du dossier (les identifiants conformes existants sont conserves)."""
    return db.execute(select(Company).order_by(Company.id)).scalars().first()


def _utilisateur(db) -> User | None:
    """Premier utilisateur (auteur des ecritures importees)."""
    return db.execute(select(User).order_by(User.id)).scalars().first()


def phase_societe(db, donnees: dict, *, appliquer: bool) -> dict:
    """Applique les parametres du jeu a la societe et prepare les deux exercices.

    Les **identifiants fiscaux du jeu** (`ICE-TEST-…`, `IF-TEST-…`) sont **refuses**
    par les controles de l'application (ICE 15 chiffres, IF 7 ou 8 chiffres) : les
    identifiants **conformes deja en base** sont donc conserves et seuls la raison
    sociale, la devise et le regime declaratif sont repris du jeu.
    """
    societe = _societe(db, donnees)
    if societe is None:
        raise SystemExit("Aucune societe en base : executez l'amorcage.")
    jeu = donnees["company"]
    resume = {
        "raison_sociale_jeu": jeu["raison_sociale"],
        "ice_jeu": jeu["ice"],
        "if_jeu": jeu["if"],
        "ice_conserve": societe.ice,
        "fiscal_id_conserve": societe.fiscal_id,
        "rc_conserve": societe.rc,
    }
    if not appliquer:
        return resume
    societe.name = jeu["raison_sociale"][:180]
    societe.vat_regime = "mensuel"  # flux mensuels du jeu (seuil 1 M DH a confirmer)
    db.flush()
    for exercice_jeu in donnees["fiscal_years"]:
        annee = int(exercice_jeu["year"])
        exercice = db.execute(
            select(FiscalYear).where(
                FiscalYear.company_id == societe.id, FiscalYear.year == annee
            )
        ).scalar_one_or_none()
        if exercice is None:
            exercice = FiscalYear(company_id=societe.id, year=annee)
            db.add(exercice)
        exercice.status = "open"  # le jeu indique `open_for_test`
        exercice.start_date = date.fromisoformat(exercice_jeu["start_date"])
        exercice.end_date = date.fromisoformat(exercice_jeu["end_date"])
    db.commit()
    resume["exercices"] = [int(item["year"]) for item in donnees["fiscal_years"]]
    return resume


def importer_ecritures(
    db,
    donnees: dict,
    annee: int,
    *,
    user_id: int | None,
    exclure_pieces: set[str] | None = None,
    pieces_requises: set[str] | None = None,
) -> dict:
    """Importe les ecritures d'un exercice (service comptable, ecritures validees).

    Les lignes du jeu sont regroupees par `ecriture_id` : chaque groupe devient une
    ecriture validee du projet (journal mappe, **piece du jeu en reference**), ce qui
    garantit numerotation continue, controle d'equilibre et piste d'audit.
    `exclure_pieces` / `pieces_requises` permettent de choisir les pieces a importer.
    """
    exclure_pieces = exclure_pieces or set()
    societe = _societe(db, donnees)
    exercice = get_fiscal_year(db, societe.id, annee)
    groupes: OrderedDict[str, list[dict]] = OrderedDict()
    for ligne in donnees["journal_entries"]:
        if int(ligne["exercice"]) != annee or ligne["piece"] in exclure_pieces:
            continue
        if pieces_requises is not None and ligne["piece"] not in pieces_requises:
            continue
        groupes.setdefault(ligne["ecriture_id"], []).append(ligne)
    total_debit = Decimal("0")
    for identifiant, lignes in groupes.items():
        premiere = lignes[0]
        journal = get_journal(db, societe.id, MAPPING_JOURNAUX[premiere["journal"]])
        entry = create_entry(
            db,
            company_id=societe.id,
            fiscal_year=exercice,
            journal=journal,
            entry_date=date.fromisoformat(premiere["date"]),
            label=premiere["libelle"][:200],
            reference=premiere["piece"][:60],
            notes=f"Jeu de recette J9 — écriture {identifiant} ({premiere['journal']})",
            source="import_jeu_j9",
            lines=[
                {
                    "account_number": str(ligne["compte"]),
                    "debit": Decimal(str(ligne["debit"] or 0)),
                    "credit": Decimal(str(ligne["credit"] or 0)),
                    "label": ligne["libelle"][:200],
                }
                for ligne in lignes
            ],
            validate=True,
        )
        total_debit += sum(
            (Decimal(str(ligne["debit"] or 0)) for ligne in lignes), Decimal("0")
        )
    db.commit()
    return {
        "annee": annee,
        "ecritures": len(groupes),
        "lignes": sum(len(lignes) for lignes in groupes.values()),
        "total_debit": money(total_debit),
        "journal_mapping": MAPPING_JOURNAUX,
        "pieces_exclues": sorted(exclure_pieces),
    }


def phase_cloture(db, donnees: dict, *, user_id: int | None, appliquer: bool) -> dict:
    """Cloture 2025 par l'application (genere les a-nouveaux 2026)."""
    societe = _societe(db, donnees)
    if not appliquer:
        return {"exercice": 2025, "action": "cloture (simulation)"}
    resultat = cloturer_exercice(db, societe, 2025, user_id=user_id, generer_ouverture=True)
    db.commit()
    return {"exercice": 2025, "cloture": {cle: str(valeur) for cle, valeur in resultat.items()}}


# ---------------------------------------------------------------------------
# Documents : tiers, factures (reconstruites du grand livre), immos, stocks, paie
# ---------------------------------------------------------------------------
def _tiers(
    db, societe: Company, nom: str, *, kind: str, ice: str, fiscal_id: str
) -> ThirdParty:
    """Tiers existant ou cree (identifiants fictifs **conformes** — le jeu n'en a pas)."""
    tiers = db.execute(
        select(ThirdParty).where(
            ThirdParty.company_id == societe.id, ThirdParty.name == nom
        )
    ).scalar_one_or_none()
    if tiers is None:
        tiers = create_third_party(
            db,
            company=societe,
            kind=kind,
            name=nom,
            ice=ice,
            fiscal_id=fiscal_id,
            payment_terms_days=0,
        )
        db.flush()
    return tiers


def _lignes_ecriture(db, societe: Company, annee: int) -> dict[int, list[dict]]:
    """Lignes d'ecriture (compte, debit, credit, libelle) par ecriture de l'exercice."""
    from app.models import EntryLine  # noqa: PLC0415 - import local

    codes_journaux = {
        journal.id: journal.code
        for journal in db.execute(
            select(Journal).where(Journal.company_id == societe.id)
        ).scalars()
    }
    lignes: dict[int, list[dict]] = defaultdict(list)
    for entry, ligne in db.execute(
        select(Entry, EntryLine)
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .where(
            Entry.company_id == societe.id,
            Entry.entry_date >= date(annee, 1, 1),
            Entry.entry_date <= date(annee, 12, 31),
        )
    ).all():
        lignes[entry.id].append(
            {
                "numero": ligne.account_number,
                "debit": money(ligne.debit),
                "credit": money(ligne.credit),
                "label": ligne.label or entry.label,
                "date": entry.entry_date,
                "reference": entry.reference or "",
                "journal": codes_journaux.get(entry.journal_id, ""),
            }
        )
    return lignes


def _nature_facture(lignes: list[dict]) -> str | None:
    """`vente`, `achat` ou `None` (ecriture sans facture : paie, IS, stock, dotation)."""
    if any(ligne["numero"].startswith("71") and ligne["credit"] > 0 for ligne in lignes):
        return "vente"
    if any(
        (ligne["numero"].startswith("61") or ligne["numero"].startswith("23"))
        and ligne["debit"] > 0
        for ligne in lignes
    ):
        return "achat"
    return None


def _nettoyer_factures(db, societe: Company) -> int:
    """Supprime les factures reconstruites (et leurs reglements et lignes)."""
    factures = list(
        db.execute(
            select(Invoice).where(
                Invoice.company_id == societe.id,
                Invoice.notes.like("Facture reconstruite%"),
            )
        ).scalars()
    )
    identifiants = [facture.id for facture in factures]
    if identifiants:
        db.execute(delete(Payment).where(Payment.invoice_id.in_(identifiants)))
        db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id.in_(identifiants)))
        db.execute(delete(Invoice).where(Invoice.id.in_(identifiants)))
    return len(identifiants)


def _nettoyer_mouvements(db, societe: Company) -> int:
    """Supprime les mouvements de stock du jeu et remet les caches a zero."""
    supprimes = db.execute(
        delete(StockMovement).where(
            StockMovement.company_id == societe.id,
            StockMovement.reference.like("J9-%"),
        )
    ).rowcount
    for article in db.execute(
        select(StockItem).where(StockItem.company_id == societe.id)
    ).scalars():
        article.quantity_on_hand = Decimal("0")
        article.cmup = Decimal("0")
        article.value_on_hand = Decimal("0")
    return supprimes


def _nettoyer_dotations(db, societe: Company) -> int:
    """Supprime les lignes de plan d'amortissement (recreees a l'import)."""
    identifiants = [
        asset.id
        for asset in db.execute(
            select(Asset).where(Asset.company_id == societe.id)
        ).scalars()
    ]
    if not identifiants:
        return 0
    return db.execute(
        delete(AssetDepreciationLine).where(
            AssetDepreciationLine.asset_id.in_(identifiants)
        )
    ).rowcount


def nettoyer_documents(db, donnees: dict) -> dict:
    """Nettoie **tous** les documents reconstruits (factures, stocks, dotations).

    Rend les phases `factures` et `documents` **idempotentes** ; les fiches
    (immobilisations, articles, salaries) et le grand livre sont **conserves**.
    """
    societe = _societe(db, donnees)
    resultat = {
        "factures_supprimees": _nettoyer_factures(db, societe),
        "mouvements_supprimes": _nettoyer_mouvements(db, societe),
        "dotations_supprimees": _nettoyer_dotations(db, societe),
    }
    db.commit()
    return resultat


def _totaux_facture(lignes: list[dict], nature: str) -> tuple[Decimal, Decimal, Decimal, list]:
    """HT, TVA, TTC et lignes (compte, montant) d'une facture deduite de l'ecriture."""
    if nature == "vente":
        ht = money(sum(l["credit"] for l in lignes if l["numero"].startswith("71")))
        tva = money(sum(l["credit"] for l in lignes if l["numero"] == "4455"))
        ttc = money(
            sum(l["debit"] for l in lignes if l["numero"].startswith(("342", "514", "516")))
        )
        detail = [
            (l["numero"], l["label"], l["credit"])
            for l in lignes
            if l["numero"].startswith("71") and l["credit"] > 0
        ]
    else:
        ht = money(
            sum(l["debit"] for l in lignes if l["numero"].startswith(("61", "23")))
        )
        tva = money(sum(l["debit"] for l in lignes if l["numero"].startswith("345")))
        ttc = money(
            sum(l["credit"] for l in lignes if l["numero"].startswith(("441", "514", "516")))
        )
        detail = [
            (l["numero"], l["label"], l["debit"])
            for l in lignes
            if l["numero"].startswith(("61", "23")) and l["debit"] > 0
        ]
    return ht, tva, ttc, detail


def reconstruire_factures(db, donnees: dict, *, user_id: int | None) -> dict:
    """Reconstruit les **factures de vente et d'achat depuis le grand livre**.

    Chaque piece d'ecriture de vente (compte `71x` crediteur) ou d'achat (compte
    `61x`/`23x` debiteur) devient une **facture rattachee a son ecriture**
    (`entry_id`) : **aucun double comptage**. Les reglements sont ensuite affectes en
    **FIFO** (`_affecter_reglements`).
    """
    societe = _societe(db, donnees)
    _nettoyer_factures(db, societe)
    tiers_client = _tiers(
        db, societe, "CLIENT-DIVERS", kind="client",
        ice="000000000000201", fiscal_id="1000201",
    )
    tiers_fournisseur = _tiers(
        db, societe, "FOURNISSEUR-DIVERS", kind="fournisseur",
        ice="000000000000202", fiscal_id="1000202",
    )
    clients_nommes = {
        nom: _tiers(
            db, societe, nom, kind="client",
            ice=f"000000000000{300 + index:03d}", fiscal_id=f"100030{index}",
        )
        for index, nom in enumerate(sorted(set(CLIENTS_DU_JEU.values())), start=1)
    }
    resume: dict[str, int] = {"vente": 0, "achat": 0}
    for annee in (2025, 2026):
        for entry_id, lignes in _lignes_ecriture(db, societe, annee).items():
            nature = _nature_facture(lignes)
            if nature is None:
                continue
            # Une facture ne provient que du journal d'achat (AC) ou de vente (VE) :
            # les ecritures OD (paie 617x, dotation 6193, variation 6114, a-nouveaux
            # 2340) sont exclues.
            journal_attendu = "VE" if nature == "vente" else "AC"
            if lignes[0]["journal"] != journal_attendu:
                continue
            ht, tva, ttc, detail = _totaux_facture(lignes, nature)
            if not detail:
                continue
            reference = lignes[0]["reference"] or f"ECR-{entry_id}"
            partenaire = (
                clients_nommes.get(CLIENTS_DU_JEU.get(reference, ""), tiers_client)
                if nature == "vente"
                else tiers_fournisseur
            )
            facture = Invoice(
                company_id=societe.id,
                fiscal_year_id=get_fiscal_year(db, societe.id, annee).id,
                number=reference[:30],
                invoice_type=nature,
                partner_id=partenaire.id,
                invoice_date=lignes[0]["date"],
                payment_mode="virement" if nature == "vente" else "espece",
                reference=reference[:60],
                notes=(
                    "Facture reconstruite depuis le grand livre (jeu J9, "
                    f"écriture {entry_id}) — aucune écriture créée."
                ),
                entry_id=entry_id,
                row_version=1,
            )
            db.add(facture)
            db.flush()
            for position, (compte, libelle, montant) in enumerate(detail, start=1):
                montant = money(montant)
                tva_ligne = money(montant * TAUX_TVA_DEFAUT / Decimal("100"))
                db.add(
                    InvoiceLine(
                        invoice_id=facture.id,
                        position=position,
                        designation=f"{compte} — {(libelle or '')[:80]}",
                        quantity=Decimal("1"),
                        unit_price=montant,
                        discount_percent=Decimal("0"),
                        vat_rate=TAUX_TVA_DEFAUT,
                        account_number=compte,
                        line_ht=montant,
                        line_vat=tva_ligne,
                        line_ttc=money(montant + tva_ligne),
                    )
                )
            db.flush()
            recalculate(db, facture)
            if not facture.total_ttc:  # filet : totaux issus du grand livre
                facture.total_ht, facture.total_vat, facture.total_ttc = ht, tva, ttc
            resume[nature] += 1
    db.commit()
    return resume


def _affecter_reglements(db, donnees: dict) -> dict:
    """Affecte les reglements du grand livre aux factures reconstruites (**FIFO**).

    Les encaissements (`3421` crediteur) et decaissements (`4411` debiteur) du journal
    bancaire sont consommes dans l'ordre chronologique sur les factures de vente et
    d'achat : le total affecte reste **egal** au total porte au grand livre.
    """
    societe = _societe(db, donnees)
    resume = {"reglements": 0, "solde_du": 0, "total_affecte": Decimal("0")}
    # File **cumulative** (2025 + 2026) : les creances d'un exercice sont reglees par
    # les encaissements de l'exercice suivant, comme au grand livre.
    toutes = [
        ligne
        for annee in (2025, 2026)
        for lignes in _lignes_ecriture(db, societe, annee).values()
        for ligne in lignes
    ]
    flux = {
        "vente": sorted(
            (
                (ligne, ligne["credit"] if ligne["numero"] == "3421" else ligne["debit"])
                for ligne in toutes
                if (ligne["numero"] == "3421" and ligne["credit"] > 0)
                or (
                    ligne["journal"] == "VE"
                    and ligne["numero"].startswith(("514", "516"))
                    and ligne["debit"] > 0
                )
            ),
            key=lambda couple: couple[0]["date"],
        ),
        "achat": sorted(
            (
                (ligne, ligne["debit"] if ligne["numero"] == "4411" else ligne["credit"])
                for ligne in toutes
                if (ligne["numero"] == "4411" and ligne["debit"] > 0)
                or (
                    ligne["journal"] == "AC"
                    and ligne["numero"].startswith(("514", "516"))
                    and ligne["credit"] > 0
                )
            ),
            key=lambda couple: couple[0]["date"],
        ),
    }
    for nature, couples in flux.items():
        file = [
            {"date": ligne["date"], "montant": money(montant), "reference": ligne["reference"]}
            for ligne, montant in couples
        ]
        factures = list(
            db.execute(
                select(Invoice)
                .where(Invoice.company_id == societe.id, Invoice.invoice_type == nature)
                .order_by(Invoice.invoice_date, Invoice.id)
            ).scalars()
        )
        for facture in factures:
            restant = facture.total_ttc
            for entree in file:
                if restant <= 0:
                    break
                montant = min(restant, entree["montant"])
                if montant <= 0:
                    continue
                db.add(
                    Payment(
                        company_id=societe.id,
                        fiscal_year_id=facture.fiscal_year_id,
                        invoice_id=facture.id,
                        partner_id=facture.partner_id,
                        amount=money(montant),
                        payment_date=max(entree["date"], facture.invoice_date),
                        method="virement" if nature == "vente" else "espece",
                        reference=(entree["reference"] or None),
                        treasury_account="5141",
                    )
                )
                facture.paid_amount = money(facture.paid_amount + montant)
                restant = money(restant - montant)
                entree["montant"] = money(entree["montant"] - montant)
                resume["reglements"] += 1
                resume["total_affecte"] = money(resume["total_affecte"] + montant)
            facture.status = (
                "paid" if restant <= 0 else ("partially_paid" if facture.paid_amount > 0 else "validated")
            )
            if restant > 0:
                resume["solde_du"] += 1
        resume[f"reste_{nature}"] = money(sum(entree["montant"] for entree in file))
    db.commit()
    return resume


# ---------------------------------------------------------------------------
# Immobilisations, stocks, salaires
# ---------------------------------------------------------------------------
def phase_immobilisations(db, donnees: dict, *, user_id: int | None, appliquer: bool) -> dict:
    """Importe les fiches d'immobilisations **et leurs dotations du grand livre**.

    Les fiches sont creees **sans ecriture** : le jeu a deja comptabilise les
    acquisitions (`2340`) et les dotations (`6193` / `2834`). Les lignes du plan
    d'amortissement reprennent les montants **du grand livre** (12 000 en 2025 ;
    12 000 + 3 000 en 2026) afin que les etats du module reconcilient le grand livre,
    sans rejouer d'ecriture.
    """
    societe = _societe(db, donnees)
    _nettoyer_dotations(db, societe)
    if not appliquer:
        return {"immobilisations": len(donnees["fixed_assets"])}
    resume = {"immobilisations": 0, "dotations": 0}
    dotations = {"IMM-001": {2025: "12000", 2026: "12000"}, "IMM-002": {2026: "3000"}}
    for bien in donnees["fixed_assets"]:
        existant = db.execute(
            select(Asset).where(
                Asset.company_id == societe.id, Asset.code == bien["asset_id"]
            )
        ).scalar_one_or_none()
        if existant is None:
            acquisition = date.fromisoformat(bien["acquisition_date"])
            valeur = money(bien["gross_value_mad"])
            existant = Asset(
                company_id=societe.id,
                code=bien["asset_id"],
                label=bien["label"],
                account_number="2340",
                acquisition_date=acquisition,
                service_date=acquisition,
                valeur_origine=valeur,
                duree_annees=int(bien["useful_life_years"]),
                tva_montant=money(valeur * TAUX_TVA_DEFAUT / Decimal("100")),
                tva_compte="34551",
                notes=(
                    "Immobilisation du jeu de recette J9 — acquisition et dotation déjà "
                    "comptabilisées par le jeu (aucune écriture créée à l'import)."
                ),
                created_by=user_id,
            )
            db.add(existant)
            db.flush()
            resume["immobilisations"] += 1
        valeur = money(existant.valeur_origine)
        cumul = Decimal("0")
        for exercice in (2025, 2026):
            montant = dotations.get(bien["asset_id"], {}).get(exercice)
            if montant is None:
                continue
            annuite = money(montant)
            cumul = money(cumul + annuite)
            ecriture = db.execute(
                select(Entry).where(
                    Entry.company_id == societe.id, Entry.reference == f"AMO-{exercice}"
                )
            ).scalar_one_or_none()
            db.add(
                AssetDepreciationLine(
                    asset_id=existant.id,
                    exercice=exercice,
                    base=valeur,
                    annuite=annuite,
                    cumul=money(min(cumul, valeur)),
                    vnc=money(valeur - min(cumul, valeur)),
                    entry_id=ecriture.id if ecriture is not None else None,
                )
            )
            resume["dotations"] += 1
    db.commit()
    return resume


def phase_stocks(db, donnees: dict, *, user_id: int | None, appliquer: bool) -> dict:
    """Cree les articles et **reconstitue les mouvements** depuis le resume du jeu.

    Le jeu ne fournit qu'un **resume par article et par annee** : chaque annee devient
    une **entree** (achat de juin) et une **sortie** (vente de decembre) au cout
    unitaire du jeu. Les mouvements sont enregistres **sans comptabilisation** : le
    grand livre du jeu porte deja la variation de stocks (`3111` / `6114`).
    """
    societe = _societe(db, donnees)
    resume_lignes = donnees["stock_movements_summary"]
    _nettoyer_mouvements(db, societe)
    if not appliquer:
        return {"articles": len({ligne["sku"] for ligne in resume_lignes})}
    resume = {"articles": 0, "mouvements": 0}
    for ligne in resume_lignes:
        article = db.execute(
            select(StockItem).where(
                StockItem.company_id == societe.id, StockItem.reference == ligne["sku"]
            )
        ).scalar_one_or_none()
        if article is None:
            article = StockItem(
                company_id=societe.id,
                reference=ligne["sku"],
                label=f"{ligne['label']} ({ligne['sku']})",
                unit="U",
                stock_account="3111",
                valuation_method="cmup",
                notes="Article du jeu de recette J9 (mouvements reconstitués du résumé).",
            )
            db.add(article)
            db.flush()
            resume["articles"] += 1
        cout = money(ligne["unit_cost_mad"])
        for jour, quantite in (
            (date(int(ligne["year"]), 6, 30), ligne["purchased_quantity"]),
            (date(int(ligne["year"]), 12, 15), -ligne["issued_quantity"]),
        ):
            if not quantite:
                continue
            enregistrer_mouvement(
                db,
                article=article,
                movement_date=jour,
                movement_type="entree" if quantite > 0 else "sortie",
                quantity=abs(quantite),
                reason="achat" if quantite > 0 else "vente",
                unit_cost=cout,
                label=f"{'Achat' if quantite > 0 else 'Vente'} {ligne['sku']} {ligne['year']}",
                reference=f"J9-{ligne['sku']}-{ligne['year']}",
                user_id=user_id,
            )
            resume["mouvements"] += 1
    db.commit()
    return resume


def phase_paie(db, donnees: dict, *, user_id: int | None, appliquer: bool) -> dict:
    """Cree les salaries de test IR du jeu (aucun bulletin genere a l'import).

    Le jeu fournit des **cas de test d'IR** (revenu imposable mensuel, personnes a
    charge) et non des fiches de paie completes : matricules, CIN et n° CNSS sont des
    **placeholders documentes**. Un contrat par exercice reprend le revenu imposable
    mensuel du jeu ; la paie applique ensuite ses propres regles (CNSS/AMO, frais
    professionnels, bareme IR).
    """
    societe = _societe(db, donnees)
    matricules = sorted(
        {ligne["employee_test_name"].split(" - ")[0] for ligne in donnees["payroll_employees"]}
    )
    if not appliquer:
        return {"salaries": len(matricules)}
    resume: dict = {"salaries": 0, "contrats": 0, "cas_ir": {}}
    for matricule in matricules:
        employe = db.execute(
            select(Employee).where(
                Employee.company_id == societe.id, Employee.matricule == matricule
            )
        ).scalar_one_or_none()
        if employe is None:
            cas = next(
                ligne
                for ligne in donnees["payroll_employees"]
                if ligne["employee_test_name"].startswith(matricule)
            )
            employe = creer_employe(
                db,
                company=societe,
                matricule=matricule,
                nom=f"{matricule} — {cas['employee_test_name'].split(' - ')[-1]}"[:160],
                date_entree=date(2025, 1, 1),
                cin=f"CIN{matricule[3:]}TEST1",
                cnss=f"CNSS{matricule[3:]}TEST",
                situation_familiale="marie" if cas["dependents"] else "celibataire",
                enfants=int(cas["dependents"]),
                type_contrat="cdi",
                fonction="Salarié du jeu de recette J9",
                user_id=user_id,
            )
            resume["salaries"] += 1
        for annee in (2025, 2026):
            cas = next(
                (
                    ligne
                    for ligne in donnees["payroll_employees"]
                    if int(ligne["year"]) == annee
                    and ligne["employee_test_name"].startswith(matricule)
                ),
                None,
            )
            if cas is None:
                continue
            contrats = list(
                db.execute(
                    select(PayContract)
                    .where(
                        PayContract.employee_id == employe.id,
                        PayContract.date_effet == date(annee, 1, 1),
                    )
                    .order_by(PayContract.id)
                ).scalars()
            )
            for doublon in contrats[1:]:  # idempotence : contrat unique par effet
                db.delete(doublon)
            if contrats:
                continue
            ajouter_contrat(
                db,
                employe,
                salaire_base=money(cas["monthly_taxable_income_mad"]),
                date_effet=date(annee, 1, 1),
            )
            resume["contrats"] += 1
            resume["cas_ir"][f"{matricule}-{annee}"] = {
                "revenu_imposable_mensuel_jeu": str(money(cas["monthly_taxable_income_mad"])),
                "personnes_a_charge": int(cas["dependents"]),
                "deduction_familiale_annuelle": str(
                    money(cas["annual_family_deduction_per_person_mad"])
                ),
            }
    db.commit()
    return resume


PHASES = ("societe", "2025", "cloture", "2026", "complement", "factures", "documents")


def main(argv: list[str] | None = None) -> int:
    """Point d'entree : injecte le jeu de donnees par phases."""
    args = parse_args(argv)
    donnees = charger(Path(args.json))
    print(f"Jeu : {Path(args.json).name} (SHA-256 {donnees['_sha256'][:16]}…)")
    print(f"  {donnees['meta']['description']} — exercices {donnees['meta']['years']}")
    print(f"  societe du jeu : {donnees['company']['raison_sociale']}")
    print(
        f"  ecritures : {len(donnees['journal_entries'])} lignes / "
        f"{len({ligne['ecriture_id'] for ligne in donnees['journal_entries']})} ecritures"
    )
    if not args.appliquer:
        print("\nSimulation : ajoutez --appliquer pour ecrire.")
        return 0
    phases = PHASES if args.phase == "tout" else (args.phase,)
    with SessionLocal() as db:
        utilisateur = _utilisateur(db)
        user_id = utilisateur.id if utilisateur is not None else None
        for phase in phases:
            if phase == "societe":
                resultat = phase_societe(db, donnees, appliquer=True)
            elif phase == "2025":
                resultat = importer_ecritures(db, donnees, 2025, user_id=user_id)
            elif phase == "cloture":
                resultat = phase_cloture(db, donnees, user_id=user_id, appliquer=True)
            elif phase == "2026":
                resultat = importer_ecritures(
                    db,
                    donnees,
                    2026,
                    user_id=user_id,
                    exclure_pieces=set(PIECES_A_NOUVEAUX),
                )
            elif phase == "complement":
                resultat = importer_ecritures(
                    db,
                    donnees,
                    2026,
                    user_id=user_id,
                    pieces_requises=set(PIECES_COMPLEMENT),
                )
            elif phase == "factures":
                resultat = reconstruire_factures(db, donnees, user_id=user_id)
                resultat.update(_affecter_reglements(db, donnees))
            elif phase == "nettoyer":
                resultat = nettoyer_documents(db, donnees)
            else:
                resultat = {
                    "immobilisations": phase_immobilisations(
                        db, donnees, user_id=user_id, appliquer=True
                    ),
                    "stocks": phase_stocks(db, donnees, user_id=user_id, appliquer=True),
                    "paie": phase_paie(db, donnees, user_id=user_id, appliquer=True),
                }
            print(f"\n[{phase}] {json.dumps(resultat, ensure_ascii=False, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())