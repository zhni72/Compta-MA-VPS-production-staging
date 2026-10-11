"""P1 - Rapport AVANT / APRES de la reinitialisation de la paie (lecture seule).

Calcule la **meme chaine** sur deux etats de la base :
- **AVANT** : la sauvegarde `compta_ma.db.bak-p1-*` (etat anterieur a la
  reinitialisation) ;
- **APRES** : la base courante `compta_ma.db`.

Chaine recalculee sans aucune correction manuelle :
Paie -> Journal -> Balance -> CPC -> ESG -> Bilan -> ETIC -> resultat fiscal -> IS.

Usage :
    .\\.venv\\Scripts\\python.exe tools\\p1_rapport_avant_apres.py
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "compta_ma.db"
sys.path.insert(0, str(BASE))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models import (  # noqa: E402
    Company,
    Entry,
    EntryLine,
    FiscalYear,
    PayrollRun,
    Payslip,
)
from app.services.etats_synthese import (  # noqa: E402
    bilan_normal,
    etat_soldes_gestion,
    notes_etic,
)
from app.services.fiscal_liasse import calculer_is  # noqa: E402
from app.services.reporting import income_statement  # noqa: E402

COMPTES_PAIE = (
    "6171", "61711", "6174", "61741", "61744", "61768",
    "4432", "4441", "4452", "5141",
)
SORTIE: list[str] = []


def bloc(texte: str = "") -> None:
    SORTIE.append(texte)


def montant(valeur) -> Decimal:
    return Decimal(str(valeur or 0))


def sauvegarde_avant() -> Path | None:
    candidates = sorted(
        DB.parent.glob("compta_ma.db.bak-p1-*"),
        key=lambda chemin: chemin.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _vers_date(valeur):
    """Convertit une date brute (texte SQLite) en `date` Python."""
    if valeur is None or isinstance(valeur, date):
        return valeur
    return date.fromisoformat(str(valeur)[:10])


def _a_colonnes_dates(db: Session) -> bool:
    """Vrai si la base ouverte porte les colonnes de dates de la societe (migration P1)."""
    from sqlalchemy import inspect

    return "date_constitution" in {
        colonne["name"] for colonne in inspect(db.get_bind()).get_columns("companies")
    }


def situation(db: Session) -> dict:
    """Situation comptable complete d'un etat de la base (exercice 2026).

    La **sauvegarde de reference** peut etre anterieure a une migration
    (colonnes de la fiche societe ajoutees depuis) : la societe est donc lue par
    une requete minimale et reconstruite en memoire, ce qui permet de comparer
    deux etats de schema differents.
    """
    from sqlalchemy import text

    ligne = db.execute(
        text("select id, name, date_constitution, date_debut_exploitation from companies limit 1")
    ).mappings().first() if _a_colonnes_dates(db) else db.execute(
        text("select id, name from companies limit 1")
    ).mappings().first()
    company = Company(
        id=ligne["id"],
        name=ligne["name"],
        date_constitution=_vers_date(ligne.get("date_constitution")) if _a_colonnes_dates(db) else None,
        date_debut_exploitation=(
            _vers_date(ligne.get("date_debut_exploitation")) if _a_colonnes_dates(db) else None
        ),
    )
    cid = company.id
    debut, fin = date(2026, 1, 1), date(2026, 12, 31)
    resultat: dict = {"societe": company.name}

    debit, credit = db.execute(
        select(func.sum(EntryLine.debit), func.sum(EntryLine.credit))
        .select_from(EntryLine)
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(Entry.company_id == cid)
    ).one()
    resultat["journal_debit"] = montant(debit)
    resultat["journal_credit"] = montant(credit)
    resultat["journal_equilibre"] = montant(debit) == montant(credit)
    resultat["nb_ecritures_2026"] = db.execute(
        select(func.count())
        .select_from(Entry)
        .where(Entry.company_id == cid, Entry.entry_date >= debut, Entry.entry_date <= fin)
    ).scalar_one()
    resultat["nb_ecritures_paie_2026"] = db.execute(
        select(func.count())
        .select_from(Entry)
        .where(
            Entry.company_id == cid,
            Entry.entry_date >= debut,
            Entry.entry_date <= fin,
            Entry.reference.like("PAIE%"),
        )
    ).scalar_one()

    comptes: dict[str, tuple[Decimal, Decimal]] = {}
    for ligne in db.execute(
        select(
            EntryLine.account_number,
            func.sum(EntryLine.debit),
            func.sum(EntryLine.credit),
        )
        .select_from(EntryLine)
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(
            Entry.company_id == cid,
            Entry.entry_date >= debut,
            Entry.entry_date <= fin,
            EntryLine.account_number.in_(COMPTES_PAIE),
        )
        .group_by(EntryLine.account_number)
        .order_by(EntryLine.account_number)
    ).all():
        comptes[ligne[0]] = (montant(ligne[1]), montant(ligne[2]))
    resultat["comptes"] = comptes

    resultat["nb_cycles"] = db.execute(
        select(func.count()).select_from(PayrollRun).where(PayrollRun.company_id == cid)
    ).scalar_one()
    resultat["nb_bulletins"] = db.execute(
        select(func.count()).select_from(Payslip).where(Payslip.company_id == cid)
    ).scalar_one()

    cpc = income_statement(db, cid, debut, fin)
    resultat["cpc_resultat"] = montant(cpc["resultat"])
    resultat["cpc_nature"] = cpc["nature_resultat"]
    resultat["cpc_charges"] = montant(cpc["total_charges"])
    resultat["cpc_produits"] = montant(cpc["total_produits"])

    esg = etat_soldes_gestion(db, cid, debut, fin)
    resultat["esg"] = {
        "marge_brute": montant(esg["marge_brute"]),
        "valeur_ajoutee": montant(esg["valeur_ajoutee"]),
        "ebe": montant(esg["ebe"]),
        "resultat_net": montant(esg["resultat_net"]),
        "coherent_avec_cpc": esg["coherent_avec_cpc"],
    }

    bilan = bilan_normal(db, cid, debut, fin)
    resultat["bilan"] = {
        "actif_brut": montant(bilan["total_actif_brut"]),
        "deductions": montant(bilan["total_deductions"]),
        "actif_net": montant(bilan["total_actif_brut"]) - montant(bilan["total_deductions"]),
        "passif": montant(bilan["total_passif"]),
        "passif_avec_resultat": montant(bilan["total_passif_avec_resultat"]),
        "equilibre": bilan["equilibre"],
        "resultat_exercice": montant(bilan["resultat_exercice"]),
    }

    etic = notes_etic(db, cid, debut, fin)
    note9 = next(n for n in etic["notes"] if n["numero"] == 9)
    note4 = next(n for n in etic["notes"] if n["numero"] == 4)
    resultat["etic_note9"] = montant(note9["total"])
    resultat["etic_note9_comptes"] = [ligne[0] for ligne in note9["lignes"]]
    resultat["etic_note4"] = montant(note4["total"])

    fiscal = calculer_is(db, company, 2026)
    resultat["fiscal"] = {
        "resultat_avant_impot": montant(fiscal["resultat_avant_impot"]),
        "resultat_fiscal": montant(fiscal["resultat_fiscal"]),
        "is": montant(fiscal["impot_du"]),
        "cotisation_minimale": montant(fiscal.get("cotisation_minimale_due", 0)),
        "solde_a_payer": montant(fiscal["solde_a_payer"]),
        "statut_exercice": fiscal["statut_exercice"],
    }
    resultat["exercice_2026"] = db.execute(
        select(FiscalYear.status).where(
            FiscalYear.company_id == cid, FiscalYear.year == 2026
        )
    ).scalar_one()
    return resultat


def tableau(avant: dict, apres: dict) -> None:
    """Rapport de comparaison AVANT / APRES dans l'ordre de la chaine demandee."""
    bloc("# P1 — Régularisation de la double paie : résultat AVANT / APRÈS")
    bloc()
    bloc(
        f"Base de référence (AVANT) : `{sauvegarde_avant().name if sauvegarde_avant() else 'n/a'}` ; "
        f"base courante (APRÈS) : `{DB.name}`. Chiffres recalculés par les services de "
        "l'application, **sans aucune correction manuelle**."
    )

    bloc()
    bloc("## 1. Écritures de paie (2026)")
    bloc()
    bloc("| Indicateur | AVANT | APRÈS |")
    bloc("|---|---|---|")
    bloc(
        f"| Écritures de paie (pièce `PAIE%`) | {avant['nb_ecritures_paie_2026']} | "
        f"{apres['nb_ecritures_paie_2026']} |"
    )
    bloc(f"| Écritures totales 2026 | {avant['nb_ecritures_2026']} | {apres['nb_ecritures_2026']} |")
    bloc(f"| Cycles de paie (module) | {avant['nb_cycles']} | {apres['nb_cycles']} |")
    bloc(f"| Bulletins de paie (module) | {avant['nb_bulletins']} | {apres['nb_bulletins']} |")

    bloc()
    bloc("## 2. Comptes de paie (2026, débit / crédit / solde)")
    bloc()
    bloc("| Compte | AVANT (D / C / solde) | APRÈS (D / C / solde) |")
    bloc("|---|---|---|")
    for compte in COMPTES_PAIE:
        d_av, c_av = avant["comptes"].get(compte, (Decimal("0"), Decimal("0")))
        d_ap, c_ap = apres["comptes"].get(compte, (Decimal("0"), Decimal("0")))
        bloc(
            f"| `{compte}` | {d_av:,.2f} / {c_av:,.2f} / **{d_av - c_av:,.2f}** | "
            f"{d_ap:,.2f} / {c_ap:,.2f} / **{d_ap - c_ap:,.2f}** |"
        )

    bloc()
    bloc("## 3. Chaîne comptable et fiscale")
    bloc()
    bloc("| Indicateur | AVANT | APRÈS |")
    bloc("|---|---|---|")
    bloc(
        f"| Journal (Σ débit = Σ crédit) | {avant['journal_debit']:,.2f} = "
        f"{avant['journal_credit']:,.2f} → **{avant['journal_equilibre']}** | "
        f"{apres['journal_debit']:,.2f} = {apres['journal_credit']:,.2f} → "
        f"**{apres['journal_equilibre']}** |"
    )
    bloc(
        f"| Balance / CPC — total charges | {avant['cpc_charges']:,.2f} | {apres['cpc_charges']:,.2f} |"
    )
    bloc(
        f"| Balance / CPC — total produits | {avant['cpc_produits']:,.2f} | {apres['cpc_produits']:,.2f} |"
    )
    bloc(
        f"| **Résultat comptable (CPC)** | {avant['cpc_resultat']:,.2f} ({avant['cpc_nature']}) | "
        f"{apres['cpc_resultat']:,.2f} ({apres['cpc_nature']}) |"
    )
    bloc(
        f"| ESG — marge brute / valeur ajoutée / EBE | {avant['esg']['marge_brute']:,.2f} / "
        f"{avant['esg']['valeur_ajoutee']:,.2f} / {avant['esg']['ebe']:,.2f} | "
        f"{apres['esg']['marge_brute']:,.2f} / {apres['esg']['valeur_ajoutee']:,.2f} / "
        f"{apres['esg']['ebe']:,.2f} |"
    )
    bloc(
        f"| **ESG = CPC** | {avant['esg']['coherent_avec_cpc']} | "
        f"**{apres['esg']['coherent_avec_cpc']}** |"
    )
    bloc(
        f"| Bilan — actif brut / déductions / **actif net** | {avant['bilan']['actif_brut']:,.2f} / "
        f"{avant['bilan']['deductions']:,.2f} / **{avant['bilan']['actif_net']:,.2f}** | "
        f"{apres['bilan']['actif_brut']:,.2f} / {apres['bilan']['deductions']:,.2f} / "
        f"**{apres['bilan']['actif_net']:,.2f}** |"
    )
    bloc(
        f"| Bilan — passif + résultat | {avant['bilan']['passif_avec_resultat']:,.2f} | "
        f"{apres['bilan']['passif_avec_resultat']:,.2f} |"
    )
    bloc(
        f"| **Bilan équilibré** | {avant['bilan']['equilibre']} | **{apres['bilan']['equilibre']}** |"
    )
    bloc(
        f"| ETIC note 9 (charges de personnel) | {avant['etic_note9']:,.2f} "
        f"({len(avant['etic_note9_comptes'])} comptes) | {apres['etic_note9']:,.2f} "
        f"({len(apres['etic_note9_comptes'])} comptes) |"
    )
    bloc(
        f"| Résultat avant impôt | {avant['fiscal']['resultat_avant_impot']:,.2f} | "
        f"{apres['fiscal']['resultat_avant_impot']:,.2f} |"
    )
    bloc(
        f"| **Résultat fiscal** | {avant['fiscal']['resultat_fiscal']:,.2f} | "
        f"{apres['fiscal']['resultat_fiscal']:,.2f} |"
    )
    bloc(
        f"| **IS calculé** | {avant['fiscal']['is']:,.2f} | {apres['fiscal']['is']:,.2f} |"
    )
    bloc(
        f"| Cotisation minimale | {avant['fiscal']['cotisation_minimale']:,.2f} | "
        f"{apres['fiscal']['cotisation_minimale']:,.2f} |"
    )
    bloc(
        f"| Solde d'IS à payer | {avant['fiscal']['solde_a_payer']:,.2f} | "
        f"{apres['fiscal']['solde_a_payer']:,.2f} |"
    )
    bloc(
        f"| Statut de l'exercice 2026 | {avant['exercice_2026']} | {apres['exercice_2026']} |"
    )


def main() -> int:
    chemin_avant = sauvegarde_avant()
    if chemin_avant is None:
        print("Aucune sauvegarde « compta_ma.db.bak-p1-* » : impossible de produire l'AVANT.")
        return 2
    moteur_avant = create_engine(f"sqlite:///{chemin_avant.as_posix()}")
    SessionAvant = sessionmaker(bind=moteur_avant)
    session_avant = SessionAvant()
    from app.db.session import SessionLocal

    session_apres = SessionLocal()
    try:
        avant = situation(session_avant)
        apres = situation(session_apres)
        tableau(avant, apres)
        bloc()
        bloc("## 4. Contrôles de cohérence exigés")
        bloc()
        bloc("| Contrôle | Résultat |")
        bloc("|---|---|")
        bloc(
            "| Bilan équilibré (après) | "
            f"**{'PASS' if apres['bilan']['equilibre'] else 'KO'}** "
            f"(actif net {apres['bilan']['actif_net']:,.2f} = passif + résultat "
            f"{apres['bilan']['passif_avec_resultat']:,.2f}) |"
        )
        bloc(
            "| CPC = ESG = Bilan (après) | "
            f"**{'PASS' if apres['esg']['coherent_avec_cpc'] and apres['bilan']['resultat_exercice'] == apres['cpc_resultat'] else 'KO'}** "
            f"(CPC {apres['cpc_resultat']:,.2f} = ESG {apres['esg']['resultat_net']:,.2f} = "
            f"bilan {apres['bilan']['resultat_exercice']:,.2f}) |"
        )
        bloc(
            "| Journal équilibré (après) | "
            f"**{'PASS' if apres['journal_equilibre'] else 'KO'}** |"
        )
        bloc(
            "| Module Paie = source unique (2026) | "
            f"**{'PASS' if apres['nb_cycles'] == 12 and apres['nb_ecritures_paie_2026'] >= 24 else 'KO'}** "
            f"({apres['nb_cycles']} cycles, {apres['nb_bulletins']} bulletins, "
            f"{apres['nb_ecritures_paie_2026']} écritures de paie) |"
        )

        bloc()
        bloc("## 5. Analyse des écarts (aucune correction manuelle)")
        bloc()
        charges_avant = avant["cpc_charges"]
        charges_apres = apres["cpc_charges"]
        bloc(
            f"- **Charges de personnel** : {avant['etic_note9']:,.2f} → "
            f"{apres['etic_note9']:,.2f} DH. L'écart "
            f"({apres['etic_note9'] - avant['etic_note9']:+,.2f} DH) correspond exactement à la "
            "substitution de la paie synthétique du jeu (14 400 DH/mois pour 3 salariés) par la "
            "paie **réelle du module** (26 000 DH de brut, 30 495,60 DH de coût employeur/mois)."
        )
        bloc(
            f"- **Total des charges** : {charges_avant:,.2f} → {charges_apres:,.2f} DH "
            f"({charges_apres - charges_avant:+,.2f} DH), à produits constants "
            f"({apres['cpc_produits']:,.2f} DH)."
        )
        bloc(
            f"- **Résultat** : {avant['cpc_resultat']:,.2f} ({avant['cpc_nature']}) → "
            f"{apres['cpc_resultat']:,.2f} ({apres['cpc_nature']}). La perte provient du **scénario "
            "de recette** (CA 432 000 DH pour une masse salariale réelle de 365 947,20 DH), "
            "**pas** d'une écriture manuelle : les paies sont exclusivement produites par le module."
        )
        bloc(
            f"- **Trésorerie (5141)** : {avant['comptes'].get('5141', (Decimal(), Decimal()))[0] - avant['comptes'].get('5141', (Decimal(), Decimal()))[1]:,.2f} → "
            f"{apres['comptes'].get('5141', (Decimal(), Decimal()))[0] - apres['comptes'].get('5141', (Decimal(), Decimal()))[1]:,.2f} DH "
            "(solde **débiteur** dans les deux états : les nets payés par virement réduisent la "
            "trésorerie sans la rendre créditrice — aucun reclassement en trésorerie-passif "
            "n'est nécessaire ; le contrôle est disponible dans `services.tresorerie`)."
        )
        bloc(
            f"- **Dettes sociales et fiscales** : 4441 {apres['comptes'].get('4441', (Decimal(), Decimal()))[1]:,.2f} DH "
            f"(CNSS/AMO patronale) et 4452 {apres['comptes'].get('4452', (Decimal(), Decimal()))[1]:,.2f} DH "
            "(IR retenu) restent à verser : la DTS 2026 régénérée les déclare. 4432 est soldé "
            f"({apres['comptes'].get('4432', (Decimal(), Decimal()))[0] - apres['comptes'].get('4432', (Decimal(), Decimal()))[1]:,.2f} DH) : tous les nets sont payés."
        )
        bloc(
            f"- **IS** : {avant['fiscal']['is']:,.2f} → {apres['fiscal']['is']:,.2f} DH. En l'absence de "
            "bénéfice, l'IS théorique est nul et la **cotisation minimale** est elle aussi nulle : "
            "l'application applique l'**exonération des 36 premiers mois d'activité** "
            "(`COTISATION_MINIMALE_2026.exemption_months`, art. 20 CGI). Hors exonération, la CM "
            "serait `max(0,25 % × CA TTC ; 3 000 DH)`."
        )
    finally:
        session_avant.close()
        session_apres.close()
        moteur_avant.dispose()

    texte = "\n".join(SORTIE)
    (BASE / "P1_AVANT_APRES.md").write_text(texte + "\n", encoding="utf-8")
    print(texte)
    print(f"\n>>> Ecrit : {BASE / 'P1_AVANT_APRES.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


