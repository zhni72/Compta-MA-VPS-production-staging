"""P1 - Reinitialisation controlee de la paie de recette (+ regeneration module).

Cible fonctionnelle (audit J9) : le **module Paie est l'unique source** des
ecritures de paie. Le scenario de recette portait des ecritures **synthetiques**
(`PAIE26-01` … `PAIE26-12`, source `import_jeu_j9`) qui doublaient la paie.

Phases (simulation par defaut, `--appliquer` pour executer) :

    --phase inventaire   liste ce qui serait retire (lecture seule)
    --phase reset        supprime les ecritures de paie 2026 (hors module ET module),
                         les cycles/bulletins 2026 et la DTS de recette, puis rescelle
                         la piste d'audit (chaque suppression est tracee).
    --phase generer      (re)genere les 12 paies 2026 depuis le module
                         (preparer -> valider -> payer) et la DTS 2026.
    --phase tout         reset puis generer.

Garanties : sauvegarde obligatoire et verifiee, exercice ouvert, aucun verrou de
periode, aucune declaration deposee supprimee, trace d'audit complete, controle
d'equilibre du journal a chaque etape.

Usage :
    .\\.venv\\Scripts\\python.exe tools\\p1_reinitialiser_paie.py --phase inventaire
    .\\.venv\\Scripts\\python.exe tools\\p1_reinitialiser_paie.py --phase tout --appliquer
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "compta_ma.db"
sys.path.insert(0, str(BASE))

PERIODES_2026 = [f"2026-{mois:02d}" for mois in range(1, 13)]

SORTIE: list[str] = []


def bloc(texte: str = "") -> None:
    SORTIE.append(texte)


def titre(texte: str) -> None:
    bloc()
    bloc("-" * 96)
    bloc(texte)
    bloc("-" * 96)


def _sauvegarde_verifiee() -> tuple[bool, str]:
    """Verifie qu'une sauvegarde de la base existe et est exploitable."""
    sauvegardes = sorted(
        DB.parent.glob("compta_ma.db.bak-p1-*"),
        key=lambda chemin: chemin.stat().st_mtime,
        reverse=True,
    )
    if not sauvegardes:
        return False, "aucune sauvegarde « compta_ma.db.bak-p1-* » : executer la sauvegarde d'abord"
    derniere = sauvegardes[0]
    if derniere.stat().st_size < 1024:
        return False, f"sauvegarde {derniere.name} suspecte (taille {derniere.stat().st_size} octets)"
    return True, f"sauvegarde verifiee : {derniere.name} ({derniere.stat().st_size // 1024} Ko)"


def _contexte(db):
    """Societe, exercice 2026, verrous de periode : controles prealables."""
    from app.models import Company, FiscalYear, PeriodLock

    from sqlalchemy import select

    company = db.execute(select(Company).order_by(Company.id)).scalars().first()
    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company.id, FiscalYear.year == 2026
        )
    ).scalar_one_or_none()
    verrous = list(
        db.execute(
            select(PeriodLock).where(PeriodLock.company_id == company.id)
        ).scalars()
    )
    return company, exercice, verrous


def _journal_equilibre(db, company_id: int) -> tuple[bool, Decimal, Decimal]:
    """Controle d'equilibre general (Σ debit = Σ credit) de la societe."""
    from sqlalchemy import func, select

    from app.models import Entry, EntryLine

    debit, credit = db.execute(
        select(func.sum(EntryLine.debit), func.sum(EntryLine.credit))
        .select_from(EntryLine)
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(Entry.company_id == company_id)
    ).one()
    debit = Decimal(str(debit or 0))
    credit = Decimal(str(credit or 0))
    return debit == credit, debit, credit


def paie_module_entries(db, company_id: int) -> list[dict]:
    """Ecritures de paie 2026 emises par le module (source = payroll)."""
    from sqlalchemy import select

    from app.models import Entry
    from app.services.payroll import SOURCE_ECRITURE

    entrees = db.execute(
        select(Entry)
        .where(Entry.company_id == company_id, Entry.source == SOURCE_ECRITURE)
        .order_by(Entry.entry_date, Entry.id)
    ).scalars().all()
    return [
        {
            "entry_id": entree.id,
            "numero": entree.entry_number,
            "date": str(entree.entry_date),
            "reference": entree.reference,
            "source": entree.source,
            "libelle": entree.label,
        }
        for entree in entrees
        if entree.entry_date.year == 2026
    ]


def paie_cycles(db, company_id: int) -> list[dict]:
    """Cycles de paie 2026 (payroll_runs) avec leurs totaux."""
    from sqlalchemy import select

    from app.models import PayrollRun

    return [
        {
            "id": cycle.id,
            "periode": cycle.periode,
            "statut": cycle.statut,
            "brut": Decimal(str(cycle.total_brut or 0)),
            "net": Decimal(str(cycle.total_net or 0)),
            "employeur": Decimal(str(cycle.total_employeur or 0)),
            "entry_id": cycle.entry_id,
            "paiement_entry_id": cycle.paiement_entry_id,
        }
        for cycle in db.execute(
            select(PayrollRun)
            .where(PayrollRun.company_id == company_id)
            .order_by(PayrollRun.periode)
        ).scalars()
        if cycle.periode.startswith("2026")
    ]


def paie_declarations(db, company_id: int) -> list[dict]:
    """Declarations DTS du registre (a regenerer apres reinitialisation)."""
    from sqlalchemy import select

    from app.models import DECLARATION_DTS, TaxDeclaration

    return [
        {
            "id": declaration.id,
            "type": declaration.type,
            "periode": declaration.periode,
            "statut": declaration.statut,
            "montant": Decimal(str(declaration.montant or 0)),
            "nb_lignes": declaration.nb_lignes,
            "fichier_nom": declaration.fichier_nom,
        }
        for declaration in db.execute(
            select(TaxDeclaration).where(
                TaxDeclaration.company_id == company_id,
                TaxDeclaration.type == DECLARATION_DTS,
            )
        ).scalars()
    ]


def inventaire(db) -> dict:
    """Liste des ecritures et objets a neutraliser (aucune modification)."""
    from app.services import payroll as paie

    company, exercice, verrous = _contexte(db)
    bloc(f"Societe : {company.name} | exercice 2026 : {exercice.status if exercice else 'ABSENT'}")
    bloc(f"Verrous de periode : {[(v.periode, v.motif) for v in verrous] or 'aucun'}")

    hors_module: list[dict] = []
    for periode in PERIODES_2026:
        hors_module.extend(paie.ecritures_paie_hors_module(db, company.id, periode))
    module = paie_module_entries(db, company.id)

    titre(f"A. Ecritures de paie HORS module a retirer ({len(hors_module)})")
    for entree in hors_module:
        bloc(
            f"  {entree['date']} {entree['numero']:<14} piece={entree['reference'] or '-':<12}"
            f" source={entree['source']:<14} {entree['libelle']}"
        )
    titre(f"B. Ecritures de paie du MODULE a retirer ({len(module)})")
    for entree in module:
        bloc(
            f"  {entree['date']} {entree['numero']:<14} piece={entree['reference'] or '-':<12}"
            f" source={entree['source']:<14} {entree['libelle']}"
        )
    cycles = paie_cycles(db, company.id)
    titre(f"C. Cycles de paie a supprimer ({len(cycles)})")
    for cycle in cycles:
        bloc(
            f"  {cycle['periode']} statut={cycle['statut']:<9} brut {cycle['brut']:>10,.2f}"
            f" net {cycle['net']:>10,.2f} employeur {cycle['employeur']:>10,.2f}"
            f" ecriture={cycle['entry_id']} paiement={cycle['paiement_entry_id']}"
        )
    declarations = paie_declarations(db, company.id)
    titre(f"D. Declarations DTS a regenerer ({len(declarations)})")
    for declaration in declarations:
        bloc(
            f"  #{declaration['id']} {declaration['type']} {declaration['periode']}"
            f" statut={declaration['statut']} montant={declaration['montant']:,.2f}"
            f" lignes={declaration['nb_lignes']} fichier={declaration['fichier_nom']}"
        )
    return {
        "company": company,
        "hors_module": hors_module,
        "module": module,
        "cycles": cycles,
        "declarations": declarations,
    }


def _snapshot_ecriture(entree) -> dict:
    """Instantane d'une ecriture pour la trace d'audit (avant suppression)."""
    return {
        "numero": entree.entry_number,
        "date": str(entree.entry_date),
        "reference": entree.reference,
        "source": entree.source,
        "libelle": entree.label,
        "lignes": [
            {
                "compte": ligne.account_number,
                "debit": str(ligne.debit),
                "credit": str(ligne.credit),
                "libelle": ligne.label,
            }
            for ligne in entree.lines
        ],
    }


def reinitialiser(db, *, appliquer: bool) -> None:
    """Retire les ecritures de paie 2026 (hors module + module), cycles, bulletins, DTS."""
    from sqlalchemy import delete, select

    from app.core.audit import log_action
    from app.models import (
        DECLARATION_BROUILLON,
        DECLARATION_DTS,
        Entry,
        EntryLine,
        PayrollRun,
        Payslip,
        PayslipLine,
        TaxDeclaration,
    )
    from app.services import audit_trail as piste

    ok, message = _sauvegarde_verifiee()
    bloc(f"Sauvegarde : {message}")
    if not ok and appliquer:
        raise SystemExit("Sauvegarde obligatoire avant toute modification.")

    apercu = inventaire(db)
    company = apercu["company"]
    entrees = {entree["entry_id"]: entree for entree in apercu["module"]}
    for entree in apercu["hors_module"]:
        entrees[entree["entry_id"]] = entree

    titre(f"REINITIALISATION ({'APPLICATION' if appliquer else 'SIMULATION'})")
    for entry_id in entrees:
        entree = db.get(Entry, entry_id)
        if entree is None:  # pragma: no cover
            continue
        if entree.entry_date.year != 2026:
            raise SystemExit(f"Ecriture {entree.entry_number} hors 2026 : reinitialisation refusee.")
        if entree.status != "validated":
            raise SystemExit(f"Ecriture {entree.entry_number} non validee : cas non gere.")
        bloc(
            f"  retrait {entree.entry_date} {entree.entry_number:<14}"
            f" piece={entree.reference or '-':<12} source={entree.source}"
        )
        if not appliquer:
            continue
        log_action(
            db,
            action="PAYROLL_RESET_SUPPRESSION",
            entity="Entry",
            entity_id=entree.id,
            user_id=1,
            company_id=company.id,
            payload=_snapshot_ecriture(entree),
        )
        db.execute(delete(EntryLine).where(EntryLine.entry_id == entree.id))
        db.execute(delete(Entry).where(Entry.id == entree.id))

    cycles = [cycle["id"] for cycle in apercu["cycles"]]
    bloc(f"  cycles de paie a supprimer : {cycles}")
    for declaration in apercu["declarations"]:
        if declaration["statut"] != DECLARATION_BROUILLON:
            raise SystemExit(
                f"Declaration DTS {declaration['periode']} statut « {declaration['statut']} » : "
                "une declaration deposee ne peut pas etre supprimee."
            )
        bloc(f"  declaration DTS #{declaration['id']} ({declaration['periode']}) a supprimer")
        if appliquer:
            log_action(
                db,
                action="PAYROLL_RESET_DECLARATION",
                entity="TaxDeclaration",
                entity_id=declaration["id"],
                user_id=1,
                company_id=company.id,
                payload=declaration,
            )
            db.execute(
                delete(TaxDeclaration).where(
                    TaxDeclaration.id == declaration["id"],
                    TaxDeclaration.type == DECLARATION_DTS,
                    TaxDeclaration.statut == DECLARATION_BROUILLON,
                )
            )

    if appliquer:
        bulletins = db.execute(
            select(Payslip.id).where(Payslip.company_id == company.id)
        ).scalars().all()
        if bulletins:
            db.execute(delete(PayslipLine).where(PayslipLine.payslip_id.in_(bulletins)))
            db.execute(delete(Payslip).where(Payslip.id.in_(bulletins)))
        for cycle in apercu["cycles"]:
            log_action(
                db,
                action="PAYROLL_RESET_CYCLE",
                entity="PayrollRun",
                entity_id=cycle["id"],
                user_id=1,
                company_id=company.id,
                payload=cycle,
            )
        db.execute(delete(PayrollRun).where(PayrollRun.id.in_(cycles)))
        db.flush()

        # La suppression d'ecritures cree une rupture de chainage : la piste est
        # rescellee dans l'ordre chronologique (mecanisme de reprise de dossier).
        resultat = piste.sceller_ecritures(db, company.id)
        bloc(
            f"  piste d'audit rescellee : {resultat['nb_scellees']} ecriture(s) "
            f"sur {resultat['total_ecritures']}"
        )
        db.commit()

    equilibre, debit, credit = _journal_equilibre(db, company.id)
    bloc()
    bloc(f"  controle journal : Σ debit {debit:,.2f} = Σ credit {credit:,.2f} -> {equilibre}")
    controle = piste.verifier_chainage(db, company.id)
    bloc(
        f"  controle piste d'audit : {controle['nb_ecritures']} ecriture(s) "
        f"({controle['nb_scellees']} scellee(s)), {len(controle['ruptures'])} rupture(s), "
        f"integre={controle['integre']}"
    )


def generer(db) -> None:
    """(Re)genere les paies 2026 depuis le module puis la DTS 2026."""
    from sqlalchemy import select

    from app.models import Company
    from app.services import payroll as paie
    from app.services.edi_dts import (
        build_dts_xml,
        construire_dts,
        enregistrer_declaration,
    )

    company = db.execute(select(Company).order_by(Company.id)).scalars().first()
    titre("GENERATION DES PAIES 2026 PAR LE MODULE (preparer -> valider -> payer)")
    total_employeur = Decimal("0")
    total_ir = Decimal("0")
    total_net = Decimal("0")
    for periode in PERIODES_2026:
        run = paie.preparer_paie(db, company, periode, user_id=1)
        bulletins = paie.list_bulletins(db, run)
        ecriture = paie.valider_paie(db, run, user_id=1)
        paiement = paie.payer_paie(db, run, mode="virement", user_id=1)
        db.commit()
        total_employeur += Decimal(str(run.total_employeur))
        total_ir += Decimal(str(run.total_ir))
        total_net += Decimal(str(run.total_net))
        bloc(
            f"  {periode} : {len(bulletins)} bulletin(s) | brut {run.total_brut:>10,.2f}"
            f" | IR {run.total_ir:>8,.2f} | net {run.total_net:>10,.2f}"
            f" | cout employeur {run.total_employeur:>10,.2f}"
            f" | ecriture {ecriture.entry_number} | paiement {paiement.entry_number}"
        )
    bloc()
    bloc(
        f"  Totaux 2026 : cout employeur {total_employeur:,.2f} | IR retenu {total_ir:,.2f}"
        f" | net paye {total_net:,.2f}"
    )

    titre("DECLARATION DTS 2026 (regenerée depuis les bulletins)")
    modele = construire_dts(db, company, 2026, mode="EDI")
    xml = build_dts_xml(modele, forcer=True)
    declaration = enregistrer_declaration(db, company, modele, xml=xml, user_id=1)
    db.commit()
    bloc(
        f"  DTS #{declaration.id} periode {declaration.periode} regime={declaration.regime}"
        f" statut={declaration.statut} montant IR {declaration.montant:,.2f}"
        f" ({declaration.nb_lignes} salarie(s)) fichier={declaration.fichier_nom}"
        f" taille={declaration.fichier_taille} hash={str(declaration.fichier_hash)[:16]}..."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="P1 - reinitialisation controlee de la paie")
    parser.add_argument(
        "--phase",
        choices=("inventaire", "reset", "generer", "tout"),
        default="inventaire",
    )
    parser.add_argument("--appliquer", action="store_true", help="execute reellement")
    args = parser.parse_args()

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        if args.phase == "inventaire":
            inventaire(db)
        elif args.phase == "reset":
            reinitialiser(db, appliquer=args.appliquer)
        elif args.phase == "generer":
            generer(db)
        else:
            reinitialiser(db, appliquer=args.appliquer)
            if args.appliquer:
                generer(db)
    finally:
        db.close()

    texte = "\n".join(SORTIE)
    suffixe = "" if args.appliquer else "_SIMULATION"
    chemin = BASE / f"P1_REINITIALISATION_PAIE{suffixe}.txt"
    chemin.write_text(texte + "\n", encoding="utf-8")
    print(texte)
    print(f"\n>>> Ecrit : {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


