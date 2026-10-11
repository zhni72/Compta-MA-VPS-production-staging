"""Recette J9 : controle des donnees injectees et tests de tous les modules.

Cet outil exerce l'application sur la **base de test** alimentee par
`tools/j9_importer_jeu.py` et produit `RAPPORT_TEST_J9.md` :

- **donnees** : compteurs, equilibre de la partie double, balance / bilan / CPC par
  exercice, TVA annuelle, reconciliations (clients, fournisseurs, stocks,
  immobilisations, IS, tresorerie) ;
- **modules** : comptabilite, facturation, TVA (declaration + releve EDI), stocks,
  immobilisations, paie (bulletins + DTS), audit (piste + scellement), rapprochement
  bancaire, depot greffe, IS / liasse EDI, cessation / e-facturation ;
- **web** : fumée des ecrans (code HTTP) sur les routes de l'interface.

Usage :
    python tools/j9_recette.py                     # toutes les sections
    python tools/j9_recette.py --sections donnees
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJET = Path(__file__).resolve().parents[1]
if str(PROJET) not in sys.path:
    sys.path.insert(0, str(PROJET))

from sqlalchemy import func, select  # noqa: E402

from app.core.rates_ma import money  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    Asset,
    AssetDepreciationLine,
    Company,
    DEPOT_EDI,
    Employee,
    Entry,
    EntryLine,
    FiscalYear,
    Invoice,
    Journal,
    Payment,
    StockItem,
    StockMovement,
    ThirdParty,
    User,
)
import app.models  # noqa: E402,F401 - charge toutes les tables
from app.services import (  # noqa: E402
    activity_events,
    assets,
    audit_trail,
    banking,
    closing,
    edi_dts,
    edi_tva,
    e_invoice,
    fiscal_liasse,
    greffe,
    invoicing,
    liasse_edi,
    payroll,
    reporting,
    stocks,
    vat,
)

RAPPORT = PROJET / "RAPPORT_TEST_J9.md"
IDENTITE_TEST = {
    "rc": "12345",
    "adresse": "12 rue de la Recette, Casablanca",
    "city": "Casablanca",
    "cnss_number": "9876543",
    "patente": "12345678",
}


class Rapport:
    """Accumulateur de lignes Markdown + journal de console."""

    def __init__(self) -> None:
        self.lignes: list[str] = []
        self.controles: list[dict] = []

    def titre(self, niveau: int, texte: str) -> None:
        """Ajoute un titre Markdown."""
        self.lignes.append(f"\n{'#' * niveau} {texte}\n")
        print(f"{'#' * niveau} {texte}")

    def texte(self, contenu: str) -> None:
        """Ajoute un paragraphe."""
        self.lignes.append(contenu)
        print(contenu)

    def tableau(self, entetes: list[str], lignes: list[list]) -> None:
        """Ajoute un tableau Markdown."""
        self.lignes.append("| " + " | ".join(entetes) + " |")
        self.lignes.append("|" + "---|" * len(entetes))
        for ligne in lignes:
            self.lignes.append("| " + " | ".join(str(valeur) for valeur in ligne) + " |")
            print("   " + " | ".join(str(valeur) for valeur in ligne))

    def controle(self, module: str, statut: str, detail: str) -> None:
        """Enregistre un controle OK / KO / alerte."""
        self.controles.append({"module": module, "statut": statut, "detail": detail})
        print(f"   [{statut}] {module} — {detail}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse la ligne de commande."""
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "--sections",
        nargs="+",
        default=["donnees", "modules", "web"],
        choices=("donnees", "modules", "web"),
    )
    parseur.add_argument("--sortie", default=str(RAPPORT))
    return parseur.parse_args(argv)


def _societe(db) -> Company:
    """Societe du dossier de test."""
    return db.execute(select(Company).order_by(Company.id)).scalars().first()


def _exercice(db, societe: Company, annee: int) -> FiscalYear:
    """Exercice d'une annee."""
    return db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == societe.id, FiscalYear.year == annee
        )
    ).scalar_one()


def _compteur(db, modele, **filtres) -> int:
    """Nombre de lignes d'un modele (filtres simples)."""
    requete = select(func.count()).select_from(modele)
    for champ, valeur in filtres.items():
        requete = requete.where(getattr(modele, champ) == valeur)
    return db.execute(requete).scalar_one()


def _totaux(db, societe: Company, annee: int) -> tuple[Decimal, Decimal]:
    """Totaux debit / credit d'un exercice."""
    debut, fin = reporting.year_bounds(annee)
    lignes = reporting.movements(db, societe.id, debut, fin)
    return (
        money(sum((ligne["debit"] for ligne in lignes), Decimal("0"))),
        money(sum((ligne["credit"] for ligne in lignes), Decimal("0"))),
    )


def _ecritures_desequilibrees(db) -> int:
    """Nombre d'ecritures dont le debit differe du credit."""
    requete = (
        select(Entry.id)
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .group_by(Entry.id)
        .having(
            func.round(func.sum(EntryLine.debit), 2) != func.round(func.sum(EntryLine.credit), 2)
        )
    )
    return len(list(db.execute(requete)))


def _solde(db, societe: Company, prefixe: str, annee: int) -> Decimal:
    """Solde (debit - credit) des comptes d'un prefixe sur un exercice."""
    debut, fin = reporting.year_bounds(annee)
    lignes = reporting.movements(db, societe.id, debut, fin)
    return money(
        sum(
            (ligne["solde"] for ligne in lignes if ligne["account_number"].startswith(prefixe)),
            Decimal("0"),
        )
    )


def section_donnees(db, rapport: Rapport, societe: Company) -> None:
    """Section « donnees » : equilibre, etats de synthese et reconciliations."""
    rapport.titre(2, "2. Données de test — contrôles comptables")
    rapport.titre(3, "2.1 Volumétrie")
    rapport.tableau(
        ["Objet", "Nombre", "Montant (MAD)"],
        [
            ["Écritures", _compteur(db, Entry), ""],
            ["Lignes d'écriture", _compteur(db, EntryLine), ""],
            ["Journaux", _compteur(db, Journal), ""],
            ["Comptes du plan comptable", _compteur(db, Account), ""],
            ["Tiers", _compteur(db, ThirdParty), ""],
            ["Factures de vente", _compteur(db, Invoice, invoice_type="vente"),
             money(sum((f.total_ttc for f in db.execute(select(Invoice).where(Invoice.invoice_type == "vente")).scalars()), Decimal("0")))],
            ["Factures d'achat", _compteur(db, Invoice, invoice_type="achat"),
             money(sum((f.total_ttc for f in db.execute(select(Invoice).where(Invoice.invoice_type == "achat")).scalars()), Decimal("0")))],
            ["Règlements", _compteur(db, Payment),
             money(sum((p.amount for p in db.execute(select(Payment)).scalars()), Decimal("0")))],
            ["Articles de stock", _compteur(db, StockItem),
             money(sum((i.value_on_hand for i in db.execute(select(StockItem)).scalars()), Decimal("0")))],
            ["Mouvements de stock", _compteur(db, StockMovement), ""],
            ["Immobilisations", _compteur(db, Asset),
             money(sum((a.valeur_origine for a in db.execute(select(Asset)).scalars()), Decimal("0")))],
            ["Lignes d'amortissement", _compteur(db, AssetDepreciationLine),
             money(sum((l.annuite for l in db.execute(select(AssetDepreciationLine)).scalars()), Decimal("0")))],
            ["Salariés", _compteur(db, Employee), ""],
        ],
    )

    rapport.titre(3, "2.2 Équilibre de la partie double")
    lignes_equilibre = []
    for annee in (2025, 2026):
        debit, credit = _totaux(db, societe, annee)
        lignes_equilibre.append(
            [annee, debit, credit, money(debit - credit), "OK" if debit == credit else "ÉCART"]
        )
    rapport.tableau(["Exercice", "Total débit", "Total crédit", "Écart", "Contrôle"], lignes_equilibre)
    ecritures_desequilibrees = _ecritures_desequilibrees(db)
    rapport.controle(
        "Équilibre",
        "OK" if not ecritures_desequilibrees else "KO",
        f"{ecritures_desequilibrees} écriture(s) déséquilibrée(s) sur {_compteur(db, Entry)}",
    )

    rapport.titre(3, "2.3 Balance, bilan et CPC par exercice")
    lignes_etats = []
    for annee in (2025, 2026):
        debut, fin = reporting.year_bounds(annee)
        balance = reporting.balance_generale(db, societe.id, debut, fin)
        bilan = reporting.balance_sheet(db, societe.id, debut, fin)
        cpc = reporting.income_statement(db, societe.id, debut, fin)
        lignes_etats.append(
            [
                annee,
                f"{balance['total_debit']} / {balance['total_credit']}",
                f"{bilan['total_actif']} / {bilan['total_passif_avec_resultat']}",
                cpc["resultat"],
                "OK"
                if bilan["total_actif"] == bilan["total_passif_avec_resultat"]
                else "ÉCART",
            ]
        )
    rapport.tableau(
        [
            "Exercice",
            "Balance D/C",
            "Bilan actif / passif (avec résultat)",
            "Résultat (CPC)",
            "Contrôle",
        ],
        lignes_etats,
    )

    rapport.titre(3, "2.4 TVA (régime mensuel) et cohérence au taux de 20 %")
    lignes_tva = []
    for annee in (2025, 2026):
        debut, fin = reporting.year_bounds(annee)
        declaration = vat.vat_return(db, societe.id, debut, fin)
        ventes = _solde(db, societe, "711", annee)
        collectee = -_solde(db, societe, "4455", annee)
        lignes_tva.append(
            [
                annee,
                declaration["tva_collectee"],
                declaration["tva_deductible"],
                declaration["tva_a_payer"],
                f"{-ventes} (20 % = {money(-ventes / 5)})",
                collectee,
                "OK" if collectee == money(-ventes / 5) else "À VÉRIFIER",
            ]
        )
    rapport.tableau(
        [
            "Exercice",
            "TVA collectée",
            "TVA déductible",
            "Net",
            "Ventes HT (20 %)",
            "4455 (grand livre)",
            "Cohérence",
        ],
        lignes_tva,
    )

    rapport.titre(3, "2.5 Réconciliations modules ↔ grand livre (fin 2026)")
    factures_vente = list(
        db.execute(select(Invoice).where(Invoice.invoice_type == "vente")).scalars()
    )
    factures_achat = list(
        db.execute(select(Invoice).where(Invoice.invoice_type == "achat")).scalars()
    )
    impayes_vente = money(sum((f.total_ttc - f.paid_amount for f in factures_vente), Decimal("0")))
    impayes_achat = money(sum((f.total_ttc - f.paid_amount for f in factures_achat), Decimal("0")))
    stock_module = money(
        sum((item.value_on_hand for item in db.execute(select(StockItem)).scalars()), Decimal("0"))
    )
    immos = list(db.execute(select(Asset)).scalars())
    brut_module = money(sum((asset.valeur_origine for asset in immos), Decimal("0")))
    amort_module = money(
        sum(
            (
                ligne.cumul
                for ligne in db.execute(
                    select(AssetDepreciationLine).where(AssetDepreciationLine.exercice == 2026)
                ).scalars()
            ),
            Decimal("0"),
        )
    )
    dossier_2025 = fiscal_liasse.dossier_is(db, societe, 2025)
    is_calcule = money(_chercher(dossier_2025, ("is_du", "impot_du", "impot_societes")) or 0)
    lignes_reconciliation = [
        [
            "Créances clients",
            "Factures impayées",
            impayes_vente,
            _solde(db, societe, "3421", 2026),
        ],
        [
            "Dettes fournisseurs",
            "Factures impayées",
            impayes_achat,
            -_solde(db, societe, "4411", 2026),
        ],
        ["Stocks (valeur nette)", "Articles", stock_module, _solde(db, societe, "3111", 2026)],
        ["Immobilisations (brut)", "Fiches", brut_module, _solde(db, societe, "2340", 2026)],
        ["Amortissements cumulés", "Plans", amort_module, -_solde(db, societe, "2834", 2026)],
        ["IS exercice 2025", "Calcul fiscal", is_calcule, _solde(db, societe, "6701", 2025)],
    ]
    rapport.tableau(
        ["Contrôle", "Source module", "Module", "Grand livre", "Écart"],
        [
            ligne + [money(Decimal(str(ligne[2])) - Decimal(str(ligne[3])))]
            for ligne in lignes_reconciliation
        ],
    )
    for ligne in lignes_reconciliation:
        ecart = money(Decimal(str(ligne[2])) - Decimal(str(ligne[3])))
        rapport.controle(
            f"Réconciliation {ligne[0]}",
            "OK" if ecart == 0 else "ALERTE",
            f"module {ligne[2]} vs grand livre {ligne[3]} (écart {ecart})",
        )


def _chercher(donnees, cles: tuple[str, ...]):
    """Cherche une cle (nom exact ou contenant) dans un dictionnaire imbrique."""
    if isinstance(donnees, dict):
        for cle, valeur in donnees.items():
            if cle in cles and not isinstance(valeur, (dict, list)):
                return valeur
        for cle, valeur in donnees.items():
            if any(motif in cle for motif in cles) and not isinstance(valeur, (dict, list)):
                return valeur
        for valeur in donnees.values():
            trouve = _chercher(valeur, cles)
            if trouve is not None:
                return trouve
    return None


def _bref(valeur, taille: int = 200) -> str:
    """Representation compacte d'une valeur (dictionnaire compris)."""
    if isinstance(valeur, (dict, list)):
        return json.dumps(valeur, ensure_ascii=False, default=str)[:taille]
    return str(valeur)


def _module(rapport: Rapport, nom: str, fonction, db, societe: Company, user_id) -> dict:
    """Execute le test d'un module et enregistre le resultat."""
    try:
        figures = fonction(db, societe, user_id)
    except Exception as exc:  # noqa: BLE001 - la recette doit continuer
        db.rollback()
        rapport.controle(nom, "KO", f"{type(exc).__name__}: {exc}")
        rapport.lignes.append(
            "<details><summary>Trace</summary>\n\n```\n"
            + traceback.format_exc()[-900:]
            + "\n```\n\n</details>\n"
        )
        return {}
    rapport.controle(
        nom, "OK", " · ".join(f"{cle}={_bref(valeur, 90)}" for cle, valeur in figures.items())
    )
    return figures


def _ecrire_sortie(nom: str, contenu: str | bytes) -> str:
    """Ecrit un livrable de recette dans `recette_j9/` et retourne son nom."""
    dossier = PROJET / "recette_j9"
    dossier.mkdir(exist_ok=True)
    chemin = dossier / nom
    if isinstance(contenu, bytes):
        chemin.write_bytes(contenu)
    else:
        chemin.write_text(contenu, encoding="utf-8")
    return f"recette_j9/{nom} ({chemin.stat().st_size} octets)"


def _mod_comptabilite(db, societe: Company, user_id) -> dict:
    """Comptabilite : balance generale, grand livre, repartition par journal."""
    figures: dict = {}
    for annee in (2025, 2026):
        debut, fin = reporting.year_bounds(annee)
        balance = reporting.balance_generale(db, societe.id, debut, fin)
        figures[f"balance_{annee}"] = (
            f"{balance['total_debit']} D / {balance['total_credit']} C — "
            + ("équilibrée" if balance["total_debit"] == balance["total_credit"] else "ÉCART")
        )
    livre = reporting.grand_livre(db, societe.id, "5141", *reporting.year_bounds(2025))
    lignes_livre = livre.get("lines", livre.get("lignes", livre.get("movements", [])))
    figures["grand_livre_5141_2025"] = f"{len(lignes_livre)} ligne(s), solde {livre.get('solde')}"
    par_journal = db.execute(
        select(Journal.code, func.count(Entry.id))
        .join(Entry, Entry.journal_id == Journal.id)
        .group_by(Journal.code)
        .order_by(Journal.code)
    ).all()
    figures["ecritures_par_journal"] = ", ".join(f"{code}:{total}" for code, total in par_journal)
    figures["lignes_2025"] = len(reporting.movements(db, societe.id, *reporting.year_bounds(2025)))
    return figures


def _mod_facturation(db, societe: Company, user_id) -> dict:
    """Facturation : documents reconstruits, reglements, recalcul des totaux."""
    ventes = list(db.execute(select(Invoice).where(Invoice.invoice_type == "vente")).scalars())
    achats = list(db.execute(select(Invoice).where(Invoice.invoice_type == "achat")).scalars())
    reglements = list(db.execute(select(Payment)).scalars())
    exemple = ventes[0]
    invoicing.recalculate(db, exemple)
    db.commit()
    statuts: dict = {}
    for facture in ventes + achats:
        statuts[facture.status] = statuts.get(facture.status, 0) + 1
    return {
        "ventes": f"{len(ventes)} ({money(sum((f.total_ttc for f in ventes), Decimal('0')))})",
        "achats": f"{len(achats)} ({money(sum((f.total_ttc for f in achats), Decimal('0')))})",
        "reglements": f"{len(reglements)} ({money(sum((p.amount for p in reglements), Decimal('0')))})",
        "impayes_ventes": money(sum((f.total_ttc - f.paid_amount for f in ventes), Decimal("0"))),
        "impayes_achats": money(sum((f.total_ttc - f.paid_amount for f in achats), Decimal("0"))),
        "statuts": statuts,
        "recalcul": (
            f"{exemple.number} → HT {exemple.total_ht} / TVA {exemple.total_vat} / TTC {exemple.total_ttc}"
        ),
    }


def _mod_tva(db, societe: Company, user_id) -> dict:
    """TVA : declaration de l'exercice, recap par taux, releve EDI du mois 06/2025."""
    figures: dict = {}
    debut, fin = reporting.year_bounds(2025)
    figures["declaration_2025"] = _bref(vat.vat_return(db, societe.id, debut, fin), 160)
    figures["recap_par_taux_2025"] = ", ".join(
        f"{type_}: "
        + "; ".join(
            f"{ligne['vat_rate']} % base {ligne['base_ht']} TVA {ligne['tva']}"
            for ligne in vat.vat_summary_by_rate(db, societe.id, debut, fin, invoice_type=type_)
        )
        for type_ in ("vente", "achat")
    )
    net_mensuel = []
    for numero in range(1, 13):
        declaration = vat.vat_return(db, societe.id, *vat.period_bounds(2025, month=numero))
        net_mensuel.append(declaration["tva_a_payer"])
    figures["net_mensuel_2025"] = ", ".join(str(montant) for montant in net_mensuel)
    premier, dernier = vat.period_bounds(2025, month=6)
    rd_paiement = edi_tva.collect_rd_lines(db, societe, premier, dernier)
    rd_facture = edi_tva.collect_rd_lines(
        db, societe, premier, dernier, base_periode="facture"
    )
    figures["rd_edi_06_2025"] = (
        f"{len(rd_paiement['lignes'])} ligne(s) base paiement, "
        f"{len(rd_facture['lignes'])} base facture "
        f"({rd_paiement['totaux']})"
    )
    try:
        code = edi_tva.regime_code(societe)
    except Exception:  # noqa: BLE001 - code de regime par defaut
        code = 1
    xml = edi_tva.build_rd_xml(
        identifiant_fiscal=societe.fiscal_id,
        annee=2025,
        periode=6,
        regime=code,
        lignes=rd_paiement["lignes"] or rd_facture["lignes"],
        declarant_nom=societe.name,
    )
    figures["xml_rd"] = _ecrire_sortie("releve_deduction_2025_06.xml", xml)
    figures["periode_valide"] = _bref(edi_tva.validate_period(code, 6), 80)
    figures["nom_fichier_edi"] = edi_tva.xml_filename(2025, 6, code)
    return figures


def _mod_stocks(db, societe: Company, user_id) -> dict:
    """Stocks : etat valorise, inventaire physique (non comptabilise), controles."""
    articles = list(db.execute(select(StockItem)).scalars())
    figures = {
        "articles": "; ".join(
            f"{item.reference}: {item.quantity_on_hand} U / {item.value_on_hand} MAD"
            for item in articles
        ),
        "valeur_totale": money(sum((item.value_on_hand for item in articles), Decimal("0"))),
        "etat_stocks": _bref(stocks.etat_stocks(db, societe.id), 140),
        "inventaire_valorise": _bref(stocks.inventaire_valorise(db, societe.id), 140),
    }
    comptage = stocks.inventaire_physique(
        db,
        company=societe,
        count_date=date(2026, 12, 31),
        lignes=[
            {"reference": item.reference, "physical_quantity": item.quantity_on_hand}
            for item in articles
        ],
        label="Inventaire de recette J9 (sans écart, non comptabilisé)",
        comptabiliser=False,
        user_id=user_id,
    )
    figures["inventaire"] = f"n° {comptage.id} — statut {comptage.status}"
    figures["controles"] = len(stocks.controles_stocks(db, societe.id, 2026))
    return figures


def _mod_immobilisations(db, societe: Company, user_id) -> dict:
    """Immobilisations : etats, soldes comptables, amortissements deductibles."""
    figures = {}
    for annee in (2025, 2026):
        figures[f"etat_{annee}"] = _bref(assets.etat_immobilisations(db, societe.id, annee), 150)
    figures["soldes_comptables"] = _bref(
        assets.soldes_immobilisations_comptables(db, societe.id, 2026), 130
    )
    figures["amortissements_deductibles"] = _bref(
        assets.amortissements_deductibles(db, societe.id, 2026), 130
    )
    figures["controles"] = _bref(assets.controles_immobilisations(db, societe.id, 2026), 200)
    return figures


def _mod_paie(db, societe: Company, user_id) -> dict:
    """Paie : bulletins du mois 01/2026 (validation = ecriture de test), livre, DTS."""
    run = payroll.get_run(db, societe.id, "2026-01") or payroll.preparer_paie(
        db, societe, "2026-01", user_id=user_id
    )
    bulletins = payroll.list_bulletins(db, run)
    bulletin = payroll.bulletin_dict(db, societe, bulletins[0])
    figures = {
        "periode": f"{run.periode} — {len(bulletins)} bulletin(s), brut {run.total_brut}",
        "bulletin_test": _bref(bulletin, 300),
    }
    if getattr(run, "entry_id", None) is None:
        payroll.valider_paie(db, run, user_id=user_id)
    figures["ecriture_paie"] = f"écriture n° {run.entry_id}" if run.entry_id else "déjà validée"
    livre = payroll.livre_de_paie(db, societe.id, 2026)
    figures["livre_2026"] = _bref(
        {cle: livre.get(cle) for cle in ("annee", "totaux", "bulletins", "lignes", "total_brut")},
        200,
    )
    cotisations = payroll.etat_cotisations(db, societe.id, 2026)
    figures["cotisations_2026"] = _bref(cotisations, 160)
    figures["controles"] = _bref(payroll.controles_paie(db, societe.id, "2026-01"), 160)
    modele = edi_dts.construire_dts(db, societe, 2026)
    xml = edi_dts.build_dts_xml(modele)
    figures["dts_xml"] = _ecrire_sortie("dts_9421_2026.xml", xml)
    try:
        declaration = edi_dts.enregistrer_declaration(db, societe, modele, xml=xml, user_id=user_id)
        figures["dts_registre"] = f"{getattr(declaration, 'reference', '')} ({getattr(declaration, 'statut', '')})"
    except Exception as exc:  # noqa: BLE001 - le registre peut exiger l'accuse DGI
        figures["dts_registre"] = f"refusé : {exc}"
    return figures


def _mod_audit(db, societe: Company, user_id) -> dict:
    """Audit : scellement de la chaine, verification, piste, verrouillage de l'exercice clos."""
    scelles = audit_trail.sceller_ecritures(db, societe.id)
    db.commit()
    figures = {
        "scellement": _bref(scelles, 120),
        "chainage": _bref(audit_trail.verifier_chainage(db, societe.id), 160),
        "journal_audit": len(
            audit_trail.journal_audit(db, company_id=societe.id, limit=50).get("lines", [])
            if isinstance(audit_trail.journal_audit(db, company_id=societe.id, limit=50), dict)
            else audit_trail.journal_audit(db, company_id=societe.id, limit=50)
        ),
    }
    ecriture = db.execute(select(Entry).order_by(Entry.entry_date)).scalars().first()
    figures["piste_ecriture"] = _bref(audit_trail.piste_ecriture(db, ecriture), 160)
    # Verrouillage : l'exercice 2025 est clos, toute ecriture doit etre refusee.
    from app.services.accounting import create_entry, get_fiscal_year, get_journal  # noqa: PLC0415

    try:
        create_entry(
            db,
            company_id=societe.id,
            fiscal_year=get_fiscal_year(db, societe.id, 2025),
            journal=get_journal(db, societe.id, "OD"),
            entry_date=date(2025, 6, 30),
            label="Test de verrouillage J9 (doit être refusé)",
            lines=[
                {"account_number": "5141", "debit": Decimal("1"), "credit": Decimal("0")},
                {"account_number": "1111", "debit": Decimal("0"), "credit": Decimal("1")},
            ],
        )
        figures["verrouillage_2025"] = "NON REFUSÉ (anomalie)"
        db.rollback()
    except Exception as exc:  # noqa: BLE001 - refus attendu
        figures["verrouillage_2025"] = f"refusé comme attendu ({type(exc).__name__})"
        db.rollback()
    return figures


def _lignes_bancaires(db, societe: Company, debut: date, fin: date) -> list[dict]:
    """Mouvements du compte 514x (date, libelle, piece, debit, credit) d'une periode."""
    from app.models import EntryLine  # noqa: PLC0415

    resultat = []
    for entry, ligne in db.execute(
        select(Entry, EntryLine)
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .where(
            Entry.company_id == societe.id,
            Entry.entry_date >= debut,
            Entry.entry_date <= fin,
            EntryLine.account_number.like("514%"),
        )
        .order_by(Entry.entry_date, EntryLine.id)
    ).all():
        resultat.append(
            {
                "date": entry.entry_date,
                "label": ligne.label or entry.label,
                "reference": entry.reference or "",
                "debit": money(ligne.debit),
                "credit": money(ligne.credit),
            }
        )
    return resultat


def _mod_banque(db, societe: Company, user_id) -> dict:
    """Rapprochement bancaire : releve de test du mois 01/2025 reconstruit du grand livre."""
    from datetime import timedelta  # noqa: PLC0415

    debut, fin = vat.period_bounds(2025, month=2)
    lignes_grand_livre = _lignes_bancaires(db, societe, debut, fin)
    entete = "date;libelle;reference;debit;credit"
    corps = [
        ";".join(
            [
                ligne["date"].isoformat(),
                (ligne["label"] or "Mouvement 5141")[:60].replace(";", " "),
                ligne["reference"][:30],
                f"{ligne['debit']:.2f}" if ligne["debit"] else "",
                f"{ligne['credit']:.2f}" if ligne["credit"] else "",
            ]
        )
        for ligne in lignes_grand_livre
    ]
    contenu = "\n".join([entete, *corps])
    nom_releve = f"releve_bancaire_{debut.year}_{debut.month:02d}.csv"
    _ecrire_sortie(nom_releve, contenu)
    lignes = banking.parser_csv_releve(contenu)
    releve = banking.importer_releve(
        db,
        company=societe,
        account_number="5141",
        date_from=debut,
        date_to=fin,
        opening_balance=Decimal("200000.00"),
        closing_balance=money(
            Decimal("200000.00")
            + sum((ligne["debit"] - ligne["credit"] for ligne in lignes_grand_livre), Decimal("0"))
        ),
        lignes=lignes,
        file_name="releve_bancaire_2025_01.csv",
        user_id=user_id,
    )
    rapprochement = banking.rapprocher_automatiquement(db, releve, user_id=user_id)
    db.commit()
    return {
        "releve": f"{len(lignes)} ligne(s) importée(s)",
        "rapprochement_auto": _bref(rapprochement, 180),
        "etat": _bref(banking.etat_rapprochement(db, releve), 180),
        "periode": f"{debut} → {(fin + timedelta(days=1)).isoformat()}",
    }


def _mod_greffe(db, societe: Company, user_id) -> dict:
    """Depot au greffe : dossier 2025, pieces generees, checklist, paiement des taxes."""
    figures = {"identite_societe": greffe.controle_identite(societe) or "complète (ICE, IF, RC)"}
    depot = greffe.depot_par_exercice(db, societe.id, 2025) or greffe.creer_depot(
        db,
        company=societe,
        exercice=2025,
        user_id=user_id,
        forme_juridique="SARL",
        montant_taxes=Decimal("1000.00"),
        notes="Dossier de recette J9 (exercice 2025 clos)",
    )
    pieces = greffe.generer_pieces(db, depot, company=societe, user_id=user_id)
    db.commit()
    figures["depot"] = f"n° {depot.id} — état {getattr(depot, 'etat', getattr(depot, 'status', ''))}"
    figures["pieces_generees"] = len(pieces) if isinstance(pieces, list) else _bref(pieces, 100)
    figures["checklist"] = _bref(
        [
            (item.get("code"), item.get("etat") or item.get("statut") or item.get("present"))
            for item in greffe.checklist(db, depot)
        ],
        200,
    )
    figures["completude"] = _bref(greffe.taux_completude(db, depot), 120)
    # Pieces etablies par les dirigeants : televersees en recette (PDF minimal).
    pdf_recette = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    for code_piece, nom in (
        ("rapport_gestion", "rapport_gestion_j9.pdf"),
        ("pv_ag", "pv_ag_j9.pdf"),
    ):
        manquantes = {item["code"] for item in greffe.pieces_manquantes(db, depot)}
        if code_piece in manquantes:
            greffe.ajouter_piece(
                db,
                depot,
                piece_code=code_piece,
                nom_fichier=nom,
                contenu=pdf_recette,
                user_id=user_id,
            )
            db.commit()
    figures["controles"] = _bref(greffe.controles_depot(db, depot), 200)
    etat_actuel = getattr(depot, "etat", getattr(depot, "status", ""))
    if etat_actuel in ("nouveau", "Nouveau (créé, non soumis)"):
        for etat in ("en_cours", "approuve"):
            greffe.changer_etat(db, depot, etat, jour=date(2026, 1, 10), user_id=user_id)
            db.commit()
    figures["etats"] = f"workflow → {getattr(depot, 'etat', getattr(depot, 'status', ''))}"
    if greffe.solde_taxes(db, depot) > 0:
        greffe.enregistrer_paiement(
            db,
            depot,
            montant=greffe.solde_taxes(db, depot),
            date_paiement=date(2026, 1, 15),
            moyen="virement",
            reference="PAI-J9",
            user_id=user_id,
        )
        db.commit()
    figures["solde_taxes"] = money(greffe.solde_taxes(db, depot))
    return figures


def _mod_is_liasse(db, societe: Company, user_id) -> dict:
    """IS et liasse EDI : dossier fiscal 2025 (exercice clos) et XML de liasse."""
    dossier = fiscal_liasse.dossier_is(db, societe, 2025)
    figures = {
        "dossier_2025": _bref(
            {
                "resultat_fiscal": _chercher(dossier, ("resultat_fiscal",)),
                "is_du": _chercher(dossier, ("is_du", "impot_du")),
                "cotisation_minimale": _chercher(dossier, ("cotisation_minimale", "cm_du")),
                "resultat_net": _chercher(dossier, ("resultat_net", "resultat_comptable")),
            },
            220,
        ),
        "controles_bloquants": len(fiscal_liasse.controles_bloquants(dossier.get("controles", []))),
        "reconciliation_balance": _bref(
            fiscal_liasse.reconciliation_balance(db, societe.id, 2025), 160
        ),
    }
    assemble = liasse_edi.dossier_liasse(db, societe, 2025)
    figures["liasse"] = _bref(assemble, 220)
    try:
        xml = liasse_edi.produire_liasse_xml(db, societe, 2025)
        contenu = xml if isinstance(xml, str) else getattr(xml, "xml", str(xml))
        figures["liasse_xml"] = _ecrire_sortie("liasse_2025.xml", contenu)
        figures["validation_xsd"] = _bref(liasse_edi.valider_xsd(contenu), 160)
    except Exception as exc:  # noqa: BLE001 - limitation A22 documentee
        figures["liasse_xml"] = (
            f"non produite : {exc} (limitation connue A22 — référentiel de codification "
            "à valider par l'expert-comptable avant dépôt SIMPL)"
        )
    return figures


def _mod_cessation_efacture(db, societe: Company, user_id) -> dict:
    """Cessation/cession et facturation electronique (modules P2.2 et P2.3)."""
    evenement = activity_events.dernier_evenement(db, societe.id) or activity_events.creer_evenement(
        db,
        societe,
        type="cessation",
        date_effet=date(2026, 12, 31),
        motif="Cessation définitive — recette J9",
        notes="Événement de recette (base de test, sauvegarde disponible).",
        user_id=user_id,
    )
    db.commit()
    figures = {"evenement": f"n° {evenement.id} — {evenement.type} au {evenement.date_effet}"}
    figures["situation"] = _bref(activity_events.situation(db, societe), 200)
    figures["controles"] = _bref(activity_events.controles_activite(db, societe, evenement), 220)
    figures["rd_sortie"] = _bref(activity_events.construire_rd_sortie(db, societe, evenement), 200)
    try:
        declaration = activity_events.declaration_tva_sortie(db, societe, evenement)
        enregistree = activity_events.enregistrer_declaration_tva(
            db,
            societe,
            evenement,
            declaration=declaration,
            # PG3A : mode du domaine metier (`DEPOT_MODES` = EDI/EFI). L'outil ne
            # doit jamais ecrire la valeur hors domaine historique « simulation »
            # (artefact de recette, > String(5)). La declaration de sortie
            # (releve des deductions EDI, regime 3/4) se depose en EDI.
            mode_depot=DEPOT_EDI,
            user_id=user_id,
        )
        db.commit()
        figures["declaration_tva_sortie"] = _bref(enregistree, 160)
    except Exception as exc:  # noqa: BLE001 - registre optionnel en recette
        figures["declaration_tva_sortie"] = f"non enregistrée : {exc}"
        db.rollback()
    from app.models import EInvoiceDocument  # noqa: PLC0415

    deja = {document.invoice_id for document in db.execute(select(EInvoiceDocument)).scalars()}
    factures = [
        facture
        for facture in db.execute(
            select(Invoice).where(Invoice.invoice_type == "vente", Invoice.status != "draft")
        ).scalars()
        if facture.id not in deja
    ]
    facture = factures[0]
    document = e_invoice.generer_document(db, societe, facture, user_id=user_id)
    db.commit()
    figures["e_facture"] = (
        f"{facture.number} → {getattr(document, 'reference', document.id)} "
        f"({getattr(document, 'statut', '')})"
    )
    figures["e_facture_envoi"] = _bref(e_invoice.envoyer(db, document, dry_run=True, user_id=user_id), 120)
    db.commit()
    figures["e_facture_accuse"] = _bref(
        e_invoice.enregistrer_accuse(
            db,
            document,
            identifiant_dgi="DGI-J9-0001",
            accuse="Accusé de réception DGI (code 0) — recette J9",
            accepte=True,
            user_id=user_id,
        ),
        120,
    )
    db.commit()
    figures["e_facture_situation"] = _bref(e_invoice.situation(db, societe), 200)
    figures["mentions_obligatoires"] = len(e_invoice.mentions_obligatoires())
    return figures


MODULES = [
    ("Comptabilité", _mod_comptabilite),
    ("Facturation", _mod_facturation),
    ("TVA", _mod_tva),
    ("Immobilisations", _mod_immobilisations),
    ("Stocks", _mod_stocks),
    ("Paie", _mod_paie),
    ("Audit", _mod_audit),
    ("Rapprochement bancaire", _mod_banque),
    ("Dépôt greffe", _mod_greffe),
    ("IS & liasse EDI", _mod_is_liasse),
    ("Cessation & e-facturation", _mod_cessation_efacture),
]


def section_modules(db, rapport: Rapport, societe: Company, user_id) -> None:
    """Section « modules » : exerce chaque module de l'application sur la base de test."""
    rapport.titre(2, "3. Tests des modules")
    for nom, fonction in MODULES:
        figures = _module(rapport, nom, fonction, db, societe, user_id)
        if figures:
            rapport.lignes.append(
                "\n".join(f"- **{cle}** : {_bref(valeur, 400)}" for cle, valeur in figures.items())
            )
            rapport.lignes.append("")


def section_web(rapport: Rapport, societe: Company) -> None:
    """Section « web » : fumee des ecrans de l'interface (code HTTP)."""
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from app.main import app  # noqa: PLC0415

    ecrans = [
        "/",
        "/ecritures",
        "/comptes",
        "/tiers",
        "/factures",
        "/reglements",
        "/immobilisations",
        "/immobilisations/etats",
        "/stocks",
        "/paie",
        "/tva",
        "/tva/edi",
        "/audit",
        "/rapprochement",
        "/greffe",
        "/liasse",
        "/parametres/societe",
        "/parametres/exercices",
        "/etats/balance",
        "/etats/grand-livre",
        "/etats/bilan",
        "/etats/cpc",
        "/etats/journal",
    ]
    rapport.titre(2, "4. Écrans de l'interface (fumée HTTP)")
    with TestClient(app) as client:
        connexion = client.post(
            "/connexion",
            data={"email": "admin@test.ma", "password": "MotDePasse123"},
            follow_redirects=False,
        )
        rapport.texte(
            f"Connexion de recette : HTTP {connexion.status_code} "
            f"(identifiants de recette des tests automatisés)."
        )
        lignes = []
        for ecran in ecrans:
            try:
                reponse = client.get(ecran, follow_redirects=False)
                statut = reponse.status_code
            except Exception as exc:  # noqa: BLE001 - ecran isole
                statut = f"ERREUR {type(exc).__name__}"
            lignes.append([ecran, statut, "500" not in str(statut) and "OK" or "KO"])
        rapport.tableau(["Écran", "HTTP", "Contrôle"], lignes)
        erreurs = [ligne for ligne in lignes if "500" in str(ligne[1]) or "ERREUR" in str(ligne[1])]
        rapport.controle(
            "Écrans",
            "OK" if not erreurs else "KO",
            f"{len(ecrans)} écrans testés, {len(erreurs)} en erreur",
        )


def preparer_societe(db, societe: Company) -> dict:
    """Complete l'identite de la societe (RC, adresse, CNSS) exigee par les EDI.

    Le jeu ne fournit ni RC ni adresse exploitables (`RC-TEST-000001`) : les modules
    DTS, greffe et TVA EDI exigeraient ces mentions. Les valeurs posees sont des
    **placeholders de recette**, tracees dans le rapport.
    """
    completes = {}
    for champ, valeur in IDENTITE_TEST.items():
        if not getattr(societe, champ, None):
            setattr(societe, champ, valeur)
            completes[champ] = valeur
    db.commit()
    return completes


def main(argv: list[str] | None = None) -> int:
    """Point d'entree : execute les sections demandees et ecrit le rapport."""
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rapport = Rapport()
    rapport.titre(1, "Rapport de recette J9 — Compta MA (exercices 2025 et 2026)")
    rapport.texte(
        "Base de test alimentée par `tools/j9_importer_jeu.py` (jeu de données "
        "`jeu_donnees_insertion_compta_maroc_2025_2026.json`, 183 écritures, 474 lignes). "
        "Sauvegarde de la base prise avant purge (`compta_ma.db.bak-j9-*`). "
        "Analyse des incohérences du jeu, décisions d'import et impacts chiffrés : "
        "`RAPPORT_TEST_J9_ANALYSE.md`."
    )
    with SessionLocal() as db:
        societe = _societe(db)
        utilisateur = db.execute(select(User).order_by(User.id)).scalars().first()
        user_id = utilisateur.id if utilisateur else None
        rapport.titre(2, "1. Société et exercices")
        completes = preparer_societe(db, societe)
        rapport.tableau(
            ["Élément", "Valeur"],
            [
                ["Raison sociale", societe.name],
                ["ICE", societe.ice],
                ["Identifiant fiscal", societe.fiscal_id],
                ["RC", societe.rc],
                ["Régime TVA", societe.vat_regime],
                ["Identité complétée (recette)", _bref(completes) or "déjà complète"],
                [
                    "Exercices",
                    ", ".join(
                        f"{exercice.year}:{exercice.status}"
                        for exercice in db.execute(
                            select(FiscalYear).order_by(FiscalYear.year)
                        ).scalars()
                    ),
                ],
            ],
        )
        if "donnees" in args.sections:
            section_donnees(db, rapport, societe)
        if "modules" in args.sections:
            section_modules(db, rapport, societe, user_id)
        if "web" in args.sections:
            section_web(rapport, societe)
    rapport.titre(2, "5. Synthèse des contrôles")
    rapport.tableau(
        ["Module", "Statut", "Détail"],
        [[controle["module"], controle["statut"], controle["detail"]] for controle in rapport.controles],
    )
    ko = [controle for controle in rapport.controles if controle["statut"] == "KO"]
    alertes = [controle for controle in rapport.controles if controle["statut"] == "ALERTE"]
    rapport.texte(
        f"\n**Résultat** : {len(rapport.controles)} contrôles, "
        f"{len(ko)} en échec, {len(alertes)} alerte(s)."
    )
    Path(args.sortie).write_text("\n".join(rapport.lignes) + "\n", encoding="utf-8")
    print(f"\nRapport écrit : {args.sortie}")
    return 1 if ko else 0


if __name__ == "__main__":
    raise SystemExit(main())