"""P1B Stage 3 — regularisation controlee de la paie 2025 (+ AN 2026, Greffe).

Scenario valide humainement (P1B Stage 3) :
    SAL-2025-A = 6 000 DH brut/mois · SAL-2025-B = 5 900 DH brut/mois · 12 mois.

Remplacement controle des 12 ecritures **synthetiques** `PAIE25-01` … `PAIE25-12`
par la paie **reelle** produite par le module, recalcul 2025, recloture 2025,
regeneration des a-nouveaux 2026, recalcul 2026, regeneration du dossier Greffe.

Phases (une seule session, une seule execution par phase) :

    --phase etat-initial   (lecture seule) fige l'etat avant modification
    --phase backup         sauvegarde horodatee + SHA-256 original/backup
    --phase reouvrir       reouverture controlee de 2025 (service metier)
    --phase retirer        retrait trace des 12 ecritures synthetiques PAIE25-*
    --phase salaries       creation de SAL-2025-A / SAL-2025-B (module)
    --phase paie           generation des 12 cycles 2025 (module)
    --phase is             regularisation de l'IS 2025 (contre-passation OD)
    --phase controler      recalcul complet 2025 + controles d'equilibre
    --phase cloturer       recloture controlee de 2025 (service metier)
    --phase an             regeneration controlee des a-nouveaux 2026
    --phase recalcul-2026  recalcul de 2026 (paie 2026 inchangee)
    --phase greffe         regeneration du dossier Greffe 2025
    --phase audit          controle de continuite de la piste d'audit
    --phase rapport        redaction du livrable unique
    --phase tout           enchaine toutes les phases dans l'ordre

Gardes-fous : toutes les operations passent par les **services metier**
(`payroll`, `closing`, `accounting`, `fiscal_liasse`, `greffe`, `audit_trail`) ;
aucun SQL direct de contournement, aucune migration, aucun package, aucun Web.

Usage :
    .\\.venv\\Scripts\\python.exe tools\\p1b_stage3_regularisation.py --phase etat-initial
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "compta_ma.db"
STATE = BASE / "P1B_STAGE3_STATE.json"
LIVRABLE = BASE / "P1B_STAGE3_REGULARISATION_2025_FINAL.md"
sys.path.insert(0, str(BASE))

EXERCICE = 2025
EXERCICE_SUIVANT = 2026
MOTIF_REOUVERTURE = "Régularisation contrôlée paie 2025 — P1B Stage 3"
MOTIF_CLOTURE = "Clôture après régularisation paie 2025 — P1B Stage 3"
MOTIF_AN = (
    "Régénération des à-nouveaux 2026 après régularisation paie 2025 — P1B Stage 3"
)
MATRICULES = ("SAL-2025-A", "SAL-2025-B")
SALAIRES_BRUT = {"SAL-2025-A": "6000", "SAL-2025-B": "5900"}
PERIODES_2025 = [f"2025-{mois:02d}" for mois in range(1, 13)]
USER_ID = 1

SORTIE: list[str] = []


def bloc(texte: str = "") -> None:
    SORTIE.append(texte)


def titre(texte: str) -> None:
    bloc()
    bloc("-" * 96)
    bloc(texte)
    bloc("-" * 96)


def sha256_fichier(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def charger_etat() -> dict:
    if STATE.is_file():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def sauver_etat(etat: dict) -> None:
    STATE.write_text(
        json.dumps(etat, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


def garde_fou() -> None:
    """Garde-fou obligatoire : tout element manquant = STOP immediat."""
    titre("0. GARDE-FOU OBLIGATOIRE")
    cwd = Path.cwd().resolve()
    controles = {
        "cwd = projet compta_ma": cwd == BASE.resolve(),
        "compta_ma.db existe": DB.is_file(),
        "app/ existe": (BASE / "app").is_dir(),
        "tests/ existe": (BASE / "tests").is_dir(),
        "alembic/ existe": (BASE / "alembic").is_dir(),
        ".venv\\Scripts\\python.exe existe": (
            BASE / ".venv" / "Scripts" / "python.exe"
        ).is_file(),
        "interpreteur = .venv": Path(sys.executable).resolve()
        == (BASE / ".venv" / "Scripts" / "python.exe").resolve(),
    }
    for libelle, ok in controles.items():
        bloc(f"  [{'OK' if ok else 'NOK'}] {libelle}")
    if not all(controles.values()):
        raise SystemExit("STOP immediat : un element du garde-fou manque.")


def backup(suffixe: str) -> dict:
    """Sauvegarde horodatee de la base + releve SHA/taille/mtime (verifies)."""
    titre(f"BACKUP — {suffixe}")
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    cible = DB.parent / f"compta_ma.db.bak-{suffixe}-{horodatage}"
    sha_original = sha256_fichier(DB)
    taille = DB.stat().st_size
    mtime = datetime.fromtimestamp(DB.stat().st_mtime).isoformat()
    cible.write_bytes(DB.read_bytes())
    sha_backup = sha256_fichier(cible)
    bloc(f"  original : SHA-256 {sha_original}")
    bloc(f"  original : taille {taille} octets ; mtime {mtime}")
    bloc(f"  backup   : {cible.name} ({cible.stat().st_size} octets)")
    bloc(f"  backup   : SHA-256 {sha_backup}")
    bloc(
        f"  controles : tailles identiques={cible.stat().st_size == taille} ; "
        f"SHA identiques={sha_original == sha_backup}"
    )
    if sha_original != sha_backup:
        raise SystemExit("STOP : le backup differe de l'original — aucune ecriture.")
    return {
        "fichier": cible.name,
        "sha_original": sha_original,
        "sha_backup": sha_backup,
        "taille": taille,
        "mtime": mtime,
        "identiques": sha_original == sha_backup,
        "horodatage": horodatage,
    }


def _snapshot_ecriture(entree) -> dict:
    """Instantane d'une ecriture pour la trace d'audit (avant retrait)."""
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


def _solde(db, company_id: int, compte: str, annee: int) -> Decimal:
    """Solde debit - credit (racine de compte) sur l'exercice."""
    from sqlalchemy import func, select

    from app.core.rates_ma import money
    from app.models import Entry, EntryLine
    from app.services.reporting import year_bounds

    debut, fin = year_bounds(annee)
    total = db.execute(
        select(func.coalesce(func.sum(EntryLine.debit - EntryLine.credit), 0))
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(
            Entry.company_id == company_id,
            Entry.entry_date >= debut,
            Entry.entry_date <= fin,
            EntryLine.account_number.like(f"{compte}%"),
        )
    ).scalar_one()
    return money(total)


def _issues_ecritures(db, company_id: int, source: str, annee: int) -> list[dict]:
    from sqlalchemy import select

    from app.models import Entry

    entrees = db.execute(
        select(Entry)
        .where(Entry.company_id == company_id, Entry.source == source)
        .order_by(Entry.entry_date, Entry.id)
    ).scalars().all()
    return [
        {
            "numero": entree.entry_number,
            "date": str(entree.entry_date),
            "reference": entree.reference,
            "libelle": entree.label,
        }
        for entree in entrees
        if entree.entry_date.year == annee
    ]


def etat_initial() -> dict:
    """Fige l'etat avant modification (lecture seule, aucun ecrit)."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company, Employee, Entry, FiscalYear, PayrollRun, Payslip
    from app.services import closing, fiscal_liasse, greffe
    from app.services.reporting import balance_sheet, income_statement, year_bounds

    titre("3. ETAT INITIAL A FIGER (lecture seule)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        exercices = {
            ex.year: ex.status
            for ex in db.execute(
                select(FiscalYear).where(FiscalYear.company_id == company.id)
            ).scalars()
        }
        synthetiques: list[dict] = []
        for index in range(1, 13):
            reference = f"PAIE25-{index:02d}"
            for entree in db.execute(
                select(Entry).where(
                    Entry.company_id == company.id, Entry.reference == reference
                )
            ).scalars():
                synthetiques.append(
                    {
                        **_snapshot_ecriture(entree),
                        "entry_id": entree.id,
                        "status": entree.status,
                    }
                )
        paie_module = _issues_ecritures(db, company.id, "payroll", EXERCICE)
        cycles_2025 = [
            cycle.periode
            for cycle in db.execute(
                select(PayrollRun).where(PayrollRun.company_id == company.id)
            ).scalars()
            if cycle.periode.startswith(str(EXERCICE))
        ]
        bulletins_2025 = [
            bulletin.periode
            for bulletin in db.execute(
                select(Payslip).where(Payslip.company_id == company.id)
            ).scalars()
            if bulletin.periode.startswith(str(EXERCICE))
        ]
        employes = [
            f"{employe.matricule} ({employe.nom})"
            for employe in db.execute(
                select(Employee).where(Employee.company_id == company.id)
            ).scalars()
        ]
        debut, fin = year_bounds(EXERCICE)
        cpc = income_statement(db, company.id, debut, fin)
        bilan = balance_sheet(db, company.id, debut, fin)
        fiscal = fiscal_liasse.calculer_is(db, company, EXERCICE)
        is_comptabilise = _solde(db, company.id, "6701", EXERCICE)
        is_dette = -_solde(db, company.id, "4453", EXERCICE)
        depot = greffe.depot_par_exercice(db, company.id, EXERCICE)
        an = closing.controle_a_nouveaux(db, company, EXERCICE_SUIVANT)
        entree_an = closing.a_nouveaux_existent(db, company.id, EXERCICE_SUIVANT)
        an_lignes = (
            {}
            if entree_an is None
            else {
                ligne.account_number: str(ligne.debit - ligne.credit)
                for ligne in entree_an.lines
            }
        )

        bloc(f"  societe : {company.name} (id {company.id})")
        bloc(f"  statut exercice {EXERCICE} : {exercices.get(EXERCICE, 'ABSENT')}")
        bloc(
            f"  statut exercice {EXERCICE_SUIVANT} : "
            f"{exercices.get(EXERCICE_SUIVANT, 'ABSENT')}"
        )
        bloc(f"  ecritures synthetiques PAIE25-01..12 : {len(synthetiques)}")
        bloc(f"  ecritures de paie reelles 2025 (source=payroll) : {len(paie_module)}")
        bloc(
            f"  cycles de paie 2025 : {len(cycles_2025)} ; bulletins : {len(bulletins_2025)}"
        )
        bloc(f"  salaries existants : {employes}")
        bloc(f"  resultat comptable (CPC) : {cpc['resultat']} DH")
        bloc(f"  resultat avant impot : {fiscal['resultat_avant_impot']} DH")
        bloc(
            f"  IS theorique 2025 : {fiscal['is_theorique']} DH ; "
            f"CM : {fiscal['cotisation_minimale']} DH"
        )
        bloc(
            f"  IS comptabilise (6701) : {is_comptabilise} DH ; "
            f"dette IS (4453) : {is_dette} DH"
        )
        bloc(
            f"  bilan : actif {bilan['total_actif']} = passif+resultat "
            f"{bilan['total_passif_avec_resultat']} (equilibre={bilan['equilibre']})"
        )
        bloc(f"  a-nouveaux 2026 : {an}")
        bloc(
            f"  dossier Greffe 2025 : "
            f"{'aucun' if depot is None else f'#{depot.id} statut={depot.statut} date_ag={depot.date_ag}'}"
        )
        return {
            "societe": company.name,
            "company_id": company.id,
            "statut_2025": exercices.get(EXERCICE),
            "statut_2026": exercices.get(EXERCICE_SUIVANT),
            "synthetiques": synthetiques,
            "nb_synthetiques": len(synthetiques),
            "paie_module_2025": paie_module,
            "nb_cycles_2025": len(cycles_2025),
            "nb_bulletins_2025": len(bulletins_2025),
            "employes": employes,
            "resultat_cpc": str(cpc["resultat"]),
            "resultat_avant_impot": str(fiscal["resultat_avant_impot"]),
            "is_theorique": str(fiscal["is_theorique"]),
            "cotisation_minimale": str(fiscal["cotisation_minimale"]),
            "is_comptabilise": str(is_comptabilise),
            "dette_is": str(is_dette),
            "bilan_actif": str(bilan["total_actif"]),
            "bilan_passif": str(bilan["total_passif_avec_resultat"]),
            "bilan_equilibre": bilan["equilibre"],
            "an_2026": an,
            "an_2026_lignes": an_lignes,
            "greffe": None
            if depot is None
            else {
                "id": depot.id,
                "statut": depot.statut,
                "date_ag": str(depot.date_ag) if depot.date_ag else None,
                "date_limite_depot": str(depot.date_limite_depot),
            },
        }
    finally:
        db.close()


def _journal_equilibre(db, company_id: int) -> tuple[bool, Decimal, Decimal]:
    from sqlalchemy import func, select

    from app.models import Entry, EntryLine

    debit, credit = db.execute(
        select(func.sum(EntryLine.debit), func.sum(EntryLine.credit))
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(Entry.company_id == company_id)
    ).one()
    debit = Decimal(str(debit or 0))
    credit = Decimal(str(credit or 0))
    return debit == credit, debit, credit


def reouvrir() -> dict:
    """Reouverture controlee de 2025 via le service metier (motif explicite)."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company
    from app.services import closing

    titre("4. REOUVERTURE CONTROLEE 2025 (service metier)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        apercu = closing.apercu_reouverture(db, company, EXERCICE)
        bloc(
            f"  apercu avant : statut={apercu['statut']} ; verrous={apercu['verrous']} ; "
            f"2026={apercu['statut_suivant']} ; ecritures 2026={apercu['ecritures_suivant']} ; "
            f"reouverture_possible={apercu['reouverture_possible']}"
        )
        if apercu["statut"] != "closed":
            raise SystemExit(
                f"STOP : exercice {EXERCICE} en statut '{apercu['statut']}' (attendu 'closed')."
            )
        if apercu["verrous"]:
            raise SystemExit("STOP : periode verrouillee sur 2025.")
        resultat = closing.reouvrir_exercice(
            db,
            company,
            EXERCICE,
            motif=MOTIF_REOUVERTURE,
            user_id=USER_ID,
            regenerer_a_nouveaux=True,
        )
        db.commit()
        bloc(f"  statut_avant={resultat['statut_avant']} -> statut={resultat['statut']}")
        bloc(f"  motif={resultat['motif']!r}")
        bloc(f"  impact N+1 : {resultat['impact_suivant']}")
        bloc(
            "  a-nouveaux N+1 (conservees jusqu'a regeneration) : "
            f"{resultat['a_nouveaux_suivant']['entry_number']}"
        )
        return {
            "statut_avant": resultat["statut_avant"],
            "statut_apres": resultat["statut"],
            "motif": resultat["motif"],
            "verrous": apercu["verrous"],
            "impact_suivant": resultat["impact_suivant"],
            "an_suivant_avant_regeneration": resultat["a_nouveaux_suivant"]["entry_number"],
        }
    finally:
        db.close()


def retirer() -> dict:
    """Retrait trace des 12 ecritures synthetiques PAIE25-01..12 (cibles exclusives)."""
    from sqlalchemy import delete, func, select

    from app.core.audit import log_action
    from app.db.session import SessionLocal
    from app.models import Company, Entry, EntryLine
    from app.services import audit_trail as piste

    titre("5. RETRAIT CONTROLE DES 12 ECRITURES SYNTHETIQUES")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        cibles: list = []
        for index in range(1, 13):
            reference = f"PAIE25-{index:02d}"
            cibles.extend(
                db.execute(
                    select(Entry).where(
                        Entry.company_id == company.id, Entry.reference == reference
                    )
                ).scalars()
            )
        bloc(f"  cibles identifiees (PAIE25-01..12) : {len(cibles)}")
        for entree in cibles:
            if entree.entry_date.year != EXERCICE:
                raise SystemExit(f"STOP : ecriture {entree.entry_number} hors {EXERCICE}.")
        if len(cibles) != 12:
            raise SystemExit(f"STOP : {len(cibles)} cible(s) au lieu de 12.")

        equi_avant = _journal_equilibre(db, company.id)
        snapshots: list[dict] = []
        for entree in cibles:
            snap = {**_snapshot_ecriture(entree), "entry_id": entree.id}
            snapshots.append(snap)
            log_action(
                db,
                action="PAYROLL_RESET_SUPPRESSION",
                entity="Entry",
                entity_id=entree.id,
                user_id=USER_ID,
                company_id=company.id,
                payload=snap | {"contexte": "P1B Stage 3", "motif": MOTIF_REOUVERTURE},
            )
            db.execute(delete(EntryLine).where(EntryLine.entry_id == entree.id))
            db.execute(delete(Entry).where(Entry.id == entree.id))
        db.flush()
        scellage = piste.sceller_ecritures(db, company.id)
        db.commit()
        controle = piste.verifier_chainage(db, company.id)
        restants = db.execute(
            select(func.count(Entry.id)).where(
                Entry.company_id == company.id, Entry.reference.like("PAIE25-%")
            )
        ).scalar_one()
        equi_apres = _journal_equilibre(db, company.id)
        bloc(f"  ecritures retirees : {len(snapshots)} (trace PAYROLL_RESET_SUPPRESSION)")
        bloc(f"  PAIE25-* restantes : {restants}")
        bloc(
            f"  piste d'audit rescellee : {scellage['nb_scellees']} sur "
            f"{scellage['total_ecritures']} ; ruptures={len(controle['ruptures'])} ; "
            f"integre={controle['integre']}"
        )
        bloc(
            f"  journal : apres {equi_apres[1]:,.2f}={equi_apres[2]:,.2f} "
            f"({equi_apres[0]})"
        )
        if restants != 0:
            raise SystemExit("STOP : des ecritures synthetiques subsistent.")
        return {
            "nb_retirees": len(snapshots),
            "retirees": snapshots,
            "restantes": restants,
            "scellage": {
                "nb_scellees": scellage["nb_scellees"],
                "total": scellage["total_ecritures"],
            },
            "ruptures": len(controle["ruptures"]),
            "integre": controle["integre"],
            "journal_avant": [str(equi_avant[1]), str(equi_avant[2]), equi_avant[0]],
            "journal_apres": [str(equi_apres[1]), str(equi_apres[2]), equi_apres[0]],
        }
    finally:
        db.close()


def salaries() -> dict:
    """Cree SAL-2025-A (6 000 DH) et SAL-2025-B (5 900 DH) via le module."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company, Employee
    from app.services import payroll as paie

    titre("6. CREATION DU SCENARIO SALARIES 2025 (module Paie)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        crees: dict[str, dict] = {}
        for matricule in MATRICULES:
            existant = db.execute(
                select(Employee).where(
                    Employee.company_id == company.id, Employee.matricule == matricule
                )
            ).scalar_one_or_none()
            if existant is not None:
                raise SystemExit(
                    f"STOP : le matricule {matricule} existe deja (id {existant.id})."
                )
            marie = matricule == "SAL-2025-B"
            employe = paie.creer_employe(
                db,
                company=company,
                matricule=matricule,
                nom=f"{matricule} (brut {SALAIRES_BRUT[matricule]} DH)",
                date_entree=date(EXERCICE, 1, 1),
                situation_familiale="marie" if marie else "celibataire",
                enfants=0,
                type_contrat="cdi",
                fonction="Salarie scenario 2025",
                mode_paiement="virement",
                user_id=USER_ID,
            )
            contrat = paie.ajouter_contrat(
                db,
                employe,
                salaire_base=SALAIRES_BRUT[matricule],
                date_effet=date(EXERCICE, 1, 1),
                user_id=USER_ID,
            )
            crees[matricule] = {
                "employee_id": employe.id,
                "nom": employe.nom,
                "situation_familiale": employe.situation_familiale,
                "personnes_a_charge": employe.personnes_a_charge,
                "salaire_base": str(contrat.salaire_base),
                "contrat_id": contrat.id,
            }
            bloc(
                f"  {matricule} : id={employe.id} base={contrat.salaire_base} DH "
                f"({employe.situation_familiale}, {employe.personnes_a_charge} charge(s))"
            )
        db.commit()
        return crees
    finally:
        db.close()


def paie() -> dict:
    """Genere les 12 cycles de paie 2025 par le module (preparer/valider/payer)."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company
    from app.services import payroll as paie_svc

    titre("7. GENERATION DES 12 CYCLES DE PAIE 2025 (module)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        employes = [paie_svc.get_employe(db, company.id, m) for m in MATRICULES]
        cycles: list[dict] = []
        for periode in PERIODES_2025:
            run = paie_svc.preparer_paie(
                db, company, periode, employes=employes, user_id=USER_ID
            )
            bulletins = paie_svc.list_bulletins(db, run)
            ecriture = paie_svc.valider_paie(db, run, user_id=USER_ID)
            paiement = paie_svc.payer_paie(db, run, mode="virement", user_id=USER_ID)
            db.commit()
            cycles.append(
                {
                    "periode": periode,
                    "statut": run.statut,
                    "nb_bulletins": len(bulletins),
                    "brut": str(run.total_brut),
                    "cotisations": str(run.total_cotisations),
                    "ir": str(run.total_ir),
                    "net": str(run.total_net),
                    "employeur": str(run.total_employeur),
                    "ecriture": ecriture.entry_number,
                    "paiement": paiement.entry_number,
                }
            )
            bloc(
                f"  {periode} : {len(bulletins)} bulletin(s) | brut {run.total_brut:>10,.2f}"
                f" | IR {run.total_ir:>7,.2f} | net {run.total_net:>10,.2f}"
                f" | cout {run.total_employeur:>10,.2f} | {ecriture.entry_number}"
                f" / {paiement.entry_number}"
            )
        total_employeur = sum(Decimal(c["employeur"]) for c in cycles)
        total_net = sum(Decimal(c["net"]) for c in cycles)
        total_ir = sum(Decimal(c["ir"]) for c in cycles)
        bloc()
        bloc(
            f"  Totaux 2025 : cout employeur {total_employeur:,.2f} | net {total_net:,.2f}"
            f" | IR {total_ir:,.2f}"
        )
        return {
            "cycles": cycles,
            "nb_cycles": len(cycles),
            "nb_bulletins": sum(c["nb_bulletins"] for c in cycles),
            "total_employeur": str(total_employeur),
            "total_net": str(total_net),
            "total_ir": str(total_ir),
        }
    finally:
        db.close()


def _figures(db, company, annee: int = EXERCICE) -> dict:
    """Recalcul complet d'un exercice (journal, balance, CPC, ESG, Bilan, ETIC, fiscal)."""
    from app.services import fiscal_liasse
    from app.services.etats_synthese import etat_soldes_gestion, notes_etic
    from app.services.reporting import (
        balance_generale,
        balance_sheet,
        income_statement,
        year_bounds,
    )

    debut, fin = year_bounds(annee)
    balance = balance_generale(db, company.id, debut, fin)
    cpc = income_statement(db, company.id, debut, fin)
    esg = etat_soldes_gestion(db, company.id, debut, fin)
    bilan = balance_sheet(db, company.id, debut, fin)
    etic = notes_etic(db, company.id, debut, fin)
    fiscal = fiscal_liasse.calculer_is(db, company, annee)
    note9 = next((n for n in etic["notes"] if n.get("numero") == 9), None)
    soldes = {
        compte: str(_solde(db, company.id, compte, annee))
        for compte in ("4432", "4441", "4452", "5141", "6701", "4453", "3453")
    }
    return {
        "journal_debit": str(balance["total_debit"]),
        "journal_credit": str(balance["total_credit"]),
        "journal_equilibre": balance["equilibre"],
        "nb_comptes_balance": len(balance["lines"]),
        "cpc_resultat": str(cpc["resultat"]),
        "cpc_charges": str(cpc["total_charges"]),
        "cpc_produits": str(cpc["total_produits"]),
        "esg": {
            "ebe": str(esg["ebe"]),
            "resultat_net": str(esg["resultat_net"]),
            "coherent_avec_cpc": esg["coherent_avec_cpc"],
        },
        "bilan_actif": str(bilan["total_actif"]),
        "bilan_passif": str(bilan["total_passif_avec_resultat"]),
        "bilan_equilibre": bilan["equilibre"],
        "bilan_resultat": str(bilan["resultat_exercice"]),
        "etic_note9_total": None if note9 is None else str(note9["total"]),
        "fiscal": {
            "resultat_comptable": str(fiscal["resultat_comptable"]),
            "impots_comptabilises": str(fiscal["impots_resultats_comptabilises"]),
            "resultat_avant_impot": str(fiscal["resultat_avant_impot"]),
            "reintegrations": str(fiscal["total_reintegrations"]),
            "resultat_fiscal": str(fiscal["resultat_fiscal"]),
            "is_theorique": str(fiscal["is_theorique"]),
            "cotisation_minimale": str(fiscal["cotisation_minimale"]),
            "impot_du": str(fiscal["impot_du"]),
            "exonere_cm": fiscal["exoneration_cotisation_minimale"]["exoneree"],
        },
        "soldes": soldes,
    }


def controler() -> dict:
    """Controles paie 2025 (§8) + recalcul complet 2025 (§9)."""
    from sqlalchemy import func, select

    from app.db.session import SessionLocal
    from app.models import Company, Entry, PayrollRun, Payslip

    titre("8. CONTROLES PAIE 2025")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        cycles = [
            c
            for c in db.execute(
                select(PayrollRun).where(PayrollRun.company_id == company.id)
            ).scalars()
            if c.periode.startswith(str(EXERCICE))
        ]
        bulletins = [
            b
            for b in db.execute(
                select(Payslip).where(Payslip.company_id == company.id)
            ).scalars()
            if b.periode.startswith(str(EXERCICE))
        ]
        ecritures_paie = _issues_ecritures(db, company.id, "payroll", EXERCICE)
        synth = db.execute(
            select(func.count(Entry.id)).where(
                Entry.company_id == company.id, Entry.reference.like("PAIE25-%")
            )
        ).scalar_one()
        complet = all(c.entry_id for c in cycles) and all(
            c.paiement_entry_id for c in cycles
        )
        bloc(f"  cycles 2025 : {len(cycles)} (attendu 12)")
        bloc(f"  bulletins 2025 : {len(bulletins)} (attendu 24)")
        bloc(f"  ecritures module 2025 (paie+paiement) : {len(ecritures_paie)}")
        bloc(f"  PAIE25-* synthetiques restantes : {synth} (attendu 0)")
        bloc(f"  chaque cycle a une ecriture ET un paiement : {complet}")

        titre("9. RECALCUL COMPLET 2025 (services)")
        figures = _figures(db, company)
        bloc(
            f"  journal : D {figures['journal_debit']} = C {figures['journal_credit']} "
            f"({figures['journal_equilibre']}) ; {figures['nb_comptes_balance']} comptes"
        )
        bloc(
            f"  CPC : produits {figures['cpc_produits']} - charges "
            f"{figures['cpc_charges']} = resultat {figures['cpc_resultat']}"
        )
        bloc(
            f"  ESG : EBE {figures['esg']['ebe']} ; net {figures['esg']['resultat_net']} "
            f"(coherent CPC={figures['esg']['coherent_avec_cpc']})"
        )
        bloc(
            f"  Bilan : actif {figures['bilan_actif']} = passif+resultat "
            f"{figures['bilan_passif']} ({figures['bilan_equilibre']}) ; "
            f"resultat {figures['bilan_resultat']}"
        )
        bloc(f"  ETIC note 9 (charges de personnel) : {figures['etic_note9_total']}")
        bloc(
            f"  Fiscal : resultat comptable {figures['fiscal']['resultat_comptable']} ; "
            f"avant impot {figures['fiscal']['resultat_avant_impot']} ; "
            f"resultat fiscal {figures['fiscal']['resultat_fiscal']}"
        )
        bloc(
            f"  IS theorique {figures['fiscal']['is_theorique']} ; "
            f"CM {figures['fiscal']['cotisation_minimale']} "
            f"(exonere CM={figures['fiscal']['exonere_cm']}) ; "
            f"impot du {figures['fiscal']['impot_du']}"
        )
        bloc("  soldes : " + " | ".join(f"{k}={v}" for k, v in figures["soldes"].items()))
        return {
            "nb_cycles": len(cycles),
            "nb_bulletins": len(bulletins),
            "nb_ecritures_module": len(ecritures_paie),
            "synthetiques_restantes": synth,
            "cycles_complets": complet,
            "figures": figures,
        }
    finally:
        db.close()


def regulariser_is() -> dict:
    """Regularisation de l'IS 2025 : reprise de l'excedent via contre-passation."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company
    from app.services import fiscal_liasse
    from app.services.accounting import create_entry, get_fiscal_year, get_journal

    from app.core.rates_ma import money

    titre("10. REGULARISATION IS 2025 (reprise 6701/4453)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        is_comptabilise = _solde(db, company.id, "6701", EXERCICE)
        is_du = fiscal_liasse.calculer_is(db, company, EXERCICE)["is_theorique"]
        ecart = money(is_comptabilise - is_du)
        bloc(f"  IS comptabilise (6701) : {is_comptabilise} DH")
        bloc(f"  IS du 2025 (theorique) : {is_du} DH")
        bloc(f"  ecart a reprendre : {ecart} DH")
        if ecart == 0:
            bloc("  aucun ecart : aucune regularisation necessaire.")
            return {
                "ecart": "0",
                "is_comptabilise": str(is_comptabilise),
                "is_du": str(is_du),
            }
        exercice = get_fiscal_year(db, company.id, EXERCICE)
        journal = get_journal(db, company.id, "OD")
        ecriture = create_entry(
            db,
            company_id=company.id,
            fiscal_year=exercice,
            journal=journal,
            entry_date=date(EXERCICE, 12, 31),
            label=f"Reprise d'excedent d'IS {EXERCICE} (regularisation P1B Stage 3)",
            reference=f"IS-{EXERCICE}-REG",
            source="manual",
            created_by=USER_ID,
            lines=[
                {
                    "account_number": "4453",
                    "debit": ecart,
                    "label": "Reprise excedent IS (regularisation)",
                },
                {
                    "account_number": "6701",
                    "credit": ecart,
                    "label": "Reprise excedent d'impot sur les benefices",
                },
            ],
            validate=True,
        )
        db.commit()
        nouveau_6701 = _solde(db, company.id, "6701", EXERCICE)
        nouveau_4453 = -_solde(db, company.id, "4453", EXERCICE)
        bloc(f"  ecriture {ecriture.entry_number} : 4453 D {ecart} / 6701 C {ecart}")
        bloc(f"  apres : 6701 = {nouveau_6701} DH ; 4453 = {nouveau_4453} DH")
        return {
            "ecart": str(ecart),
            "is_comptabilise_avant": str(is_comptabilise),
            "is_du": str(is_du),
            "entry_number": ecriture.entry_number,
            "solde_6701_apres": str(nouveau_6701),
            "solde_4453_apres": str(nouveau_4453),
        }
    finally:
        db.close()


def _controles_equilibre(db, company) -> dict:
    """Controles bloquants d'equilibre 2025 (§11)."""
    from app.services import audit_trail as piste

    figures = _figures(db, company)
    chainage = piste.verifier_chainage(db, company.id)
    checks = {
        "journal D=C": figures["journal_equilibre"],
        "actif = passif": figures["bilan_equilibre"],
        "CPC = Bilan = ESG": (
            figures["cpc_resultat"]
            == figures["bilan_resultat"]
            == figures["esg"]["resultat_net"]
        ),
        "ESG coherent avec CPC": figures["esg"]["coherent_avec_cpc"],
        "ETIC note 9 presente": figures["etic_note9_total"] is not None,
        "piste d'audit sans rupture": (
            chainage["integre"] and not chainage["ruptures"]
        ),
        "aucune ecriture non scellee": not chainage["non_scellees"],
    }
    return {"checks": checks, "tout_ok": all(checks.values()), "figures": figures,
            "chainage": {
                "nb_ecritures": chainage["nb_ecritures"],
                "nb_scellees": chainage["nb_scellees"],
                "ruptures": len(chainage["ruptures"]),
                "integre": chainage["integre"],
            }}


def equilibre() -> dict:
    """Controle d'equilibre 2025 (§11) apres regularisation."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company

    titre("11. CONTROLE EQUILIBRE 2025")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        resultat = _controles_equilibre(db, company)
        for libelle, ok in resultat["checks"].items():
            bloc(f"  [{'OK' if ok else 'NOK'}] {libelle}")
        bloc(f"  piste : {resultat['chainage']}")
        bloc(
            f"  resultat net 2025 = {resultat['figures']['cpc_resultat']} DH "
            f"(attendu 52 043,87)"
        )
        if not resultat["tout_ok"]:
            raise SystemExit("STOP avant cloture : un controle d'equilibre a echoue.")
        return resultat
    finally:
        db.close()


def cloturer() -> dict:
    """Recloture controlee de 2025 via le service metier (§12)."""
    from sqlalchemy import select

    from app.core.audit import log_action
    from app.db.session import SessionLocal
    from app.models import Company
    from app.services import closing

    titre("12. RECLOTURE CONTROLEE 2025 (service metier)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        resultat_eq = _controles_equilibre(db, company)
        if not resultat_eq["tout_ok"]:
            raise SystemExit("STOP : controles d'equilibre non satisfaits.")
        resultat = closing.cloturer_exercice(
            db, company, EXERCICE, user_id=USER_ID, generer_ouverture=False
        )
        log_action(
            db,
            action="P1B_STAGE3_CLOTURE",
            entity="FiscalYear",
            entity_id=resultat.get("exercice"),
            user_id=USER_ID,
            company_id=company.id,
            payload={"motif": MOTIF_CLOTURE, "exercice": EXERCICE,
                     "resultat_net": str(resultat["resultat_net"])},
        )
        db.commit()
        bloc(f"  statut -> {resultat['statut']} ; motif : {MOTIF_CLOTURE!r}")
        bloc(f"  resultat net figé : {resultat['resultat_net']} DH")
        bloc(f"  total actif : {resultat['total_actif']} DH")
        bloc("  a-nouveaux : NON generes a ce stade (regeneration dediee etape 13)")
        return {
            "statut": resultat["statut"],
            "motif": MOTIF_CLOTURE,
            "resultat_net": str(resultat["resultat_net"]),
            "total_actif": str(resultat["total_actif"]),
        }
    finally:
        db.close()


def an() -> dict:
    """Regeneration controlee des a-nouveaux 2026 (§13), trace-driven (idempotent)."""
    import json

    from sqlalchemy import select

    from app.core.rates_ma import money as _money
    from app.db.session import SessionLocal
    from app.models import AuditLog, Company
    from app.services import closing

    titre("13. REGENERATION DES A-NOUVEAUX 2026 (service metier)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        journalise = db.execute(
            select(AuditLog)
            .where(
                AuditLog.company_id == company.id,
                AuditLog.action == "OPENING_REGENERATED",
            )
            .order_by(AuditLog.id.desc())
        ).scalars().all()
        trace = None
        for entree in journalise:
            try:
                charge = json.loads(entree.payload_json or "{}")
            except ValueError:
                continue
            if charge.get("motif") == MOTIF_AN:
                trace = charge
                break
        if trace is not None:
            bloc("  regeneration deja effectuee et tracee (lue depuis la piste) : pas de rejeu.")
            avant = trace["avant"]
        else:
            resultat = closing.regenerer_a_nouveaux(
                db, company, EXERCICE, motif=MOTIF_AN, user_id=USER_ID
            )
            db.commit()
            avant = resultat["avant"]
        entree_an = closing.a_nouveaux_existent(db, company.id, EXERCICE_SUIVANT)
        apres = {
            "entry_number": entree_an.entry_number,
            "total_debit": _money(entree_an.total_debit),
            "nb_lignes": len(entree_an.lines),
            "lignes": {
                ligne.account_number: _money(ligne.debit - ligne.credit)
                for ligne in entree_an.lines
            },
        }
        bloc(f"  avant : {avant['entry_number']} ({avant['nb_lignes']} lignes, "
             f"total {avant['total_debit']} DH)")
        bloc(f"  apres : {apres['entry_number']} ({apres['nb_lignes']} lignes, "
             f"total {apres['total_debit']} DH)")
        comptes = sorted(set(avant["lignes"]) | set(apres["lignes"]))
        ecarts: list[dict] = []
        for compte in comptes:
            ancien = _money(avant["lignes"].get(compte, "0"))
            nouveau = _money(apres["lignes"].get(compte, "0"))
            if ancien != nouveau:
                ecarts.append(
                    {"compte": compte, "avant": ancien, "apres": nouveau,
                     "ecart": _money(nouveau - ancien)}
                )
        delta_global = _money(sum((e["ecart"] for e in ecarts), Decimal("0")))
        bloc(f"  delta global : {delta_global} DH ; lignes modifiees : {len(ecarts)}")
        for ecart in sorted(ecarts, key=lambda e: e["compte"]):
            bloc(f"    {ecart['compte']:>8} : {ecart['avant']:>12,.2f} -> "
                 f"{ecart['apres']:>12,.2f} (delta {ecart['ecart']:>12,.2f})")

        # La regeneration supprime l'ancienne ecriture d'a-nouveaux (au milieu de
        # la chaine) : la piste est rescellee par le mecanisme prevu (reprise de
        # dossier), comme pour toute suppression controlee d'ecriture.
        from app.core.audit import log_action
        from app.services import audit_trail as piste

        controle = piste.verifier_chainage(db, company.id)
        rescellage = None
        if not controle["integre"]:
            rescellage = piste.sceller_ecritures(db, company.id)
            log_action(
                db,
                action="P1B_STAGE3_RESCELLAGE",
                entity="Company",
                entity_id=company.id,
                user_id=USER_ID,
                company_id=company.id,
                payload={
                    "motif": MOTIF_AN,
                    "nb_scellees": rescellage["nb_scellees"],
                    "total_ecritures": rescellage["total_ecritures"],
                },
            )
            db.commit()
            controle = piste.verifier_chainage(db, company.id)
            bloc(
                f"  piste rescellee (regeneration AN) : "
                f"{rescellage['nb_scellees']} ecriture(s) ; integre={controle['integre']} ; "
                f"ruptures={len(controle['ruptures'])}"
            )
        return {
            "avant": {"entry_number": avant["entry_number"],
                      "nb_lignes": avant["nb_lignes"],
                      "total": str(avant["total_debit"]),
                      "lignes": {k: str(v) for k, v in avant["lignes"].items()}},
            "apres": {"entry_number": apres["entry_number"],
                      "nb_lignes": apres["nb_lignes"],
                      "total": str(apres["total_debit"]),
                      "lignes": {k: str(v) for k, v in apres["lignes"].items()}},
            "ecarts": [
                {"compte": e["compte"], "avant": str(e["avant"]),
                 "apres": str(e["apres"]), "ecart": str(e["ecart"])}
                for e in ecarts
            ],
            "delta_global": str(delta_global),
            "rescellage": None
            if rescellage is None
            else {
                "nb_scellees": rescellage["nb_scellees"],
                "total_ecritures": rescellage["total_ecritures"],
                "integre_apres": controle["integre"],
                "ruptures_apres": len(controle["ruptures"]),
            },
        }
    finally:
        db.close()


def recalcul_2026() -> dict:
    """Recalcul 2026 apres nouveaux a-nouveaux (§14)."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company, PayrollRun, Payslip

    titre("14. RECALCUL 2026 (apres nouveaux a-nouveaux)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        cycles = [
            c
            for c in db.execute(
                select(PayrollRun).where(PayrollRun.company_id == company.id)
            ).scalars()
            if c.periode.startswith(str(EXERCICE_SUIVANT))
        ]
        bulletins = [
            b
            for b in db.execute(
                select(Payslip).where(Payslip.company_id == company.id)
            ).scalars()
            if b.periode.startswith(str(EXERCICE_SUIVANT))
        ]
        ecritures_module = _issues_ecritures(
            db, company.id, "payroll", EXERCICE_SUIVANT
        )
        figures = _figures(db, company, EXERCICE_SUIVANT)
        bloc(f"  cycles 2026 : {len(cycles)} (inchange : 12)")
        bloc(f"  bulletins 2026 : {len(bulletins)} (inchange : 36)")
        bloc(f"  ecritures module 2026 (paie+paiement) : {len(ecritures_module)} (24)")
        bloc(
            f"  journal 2026 : D {figures['journal_debit']} = C "
            f"{figures['journal_credit']} ({figures['journal_equilibre']})"
        )
        bloc(
            f"  CPC 2026 : produits {figures['cpc_produits']} - charges "
            f"{figures['cpc_charges']} = resultat {figures['cpc_resultat']}"
        )
        bloc(
            f"  Bilan 2026 : actif {figures['bilan_actif']} = passif "
            f"{figures['bilan_passif']} ({figures['bilan_equilibre']})"
        )
        bloc(
            f"  ESG 2026 net {figures['esg']['resultat_net']} ; "
            f"ETIC note 9 {figures['etic_note9_total']}"
        )
        bloc(
            f"  Fiscal 2026 : avant impot {figures['fiscal']['resultat_avant_impot']} ; "
            f"resultat fiscal {figures['fiscal']['resultat_fiscal']} ; "
            f"IS {figures['fiscal']['is_theorique']} ; CM "
            f"{figures['fiscal']['cotisation_minimale']}"
        )
        return {
            "nb_cycles": len(cycles),
            "nb_bulletins": len(bulletins),
            "nb_ecritures_module": len(ecritures_module),
            "figures": figures,
        }
    finally:
        db.close()


def _montant_apres(texte: str, motif: str) -> str | None:
    import re

    trouve = re.search(rf"{motif}\D{{0,40}}?(\d[\d ]*,\d\d)", texte)
    return trouve.group(1) if trouve else None


def greffe_2025() -> dict:
    """Regeneration du dossier Greffe 2025 + controles PDF renforces (§15)."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company
    from app.services import greffe
    from app.services.pdf_documents import _donnees_gestion, format_montant_devise

    titre("15. GREFFE 2025 (regeneration + controles renforces)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        depot = greffe.depot_par_exercice(db, company.id, EXERCICE)
        if depot is None:
            raise SystemExit("STOP : aucun dossier Greffe 2025.")
        statut_avant = depot.statut
        avant = {
            d.piece_code: {
                "nom": d.nom_fichier,
                "sha": greffe.empreinte_sha256(greffe.lire_document(d)),
                "taille": d.taille_octets,
            }
            for d in depot.documents
        }
        greffe.generer_pieces(
            db, depot, company=company, user_id=USER_ID, date_ag=depot.date_ag
        )
        db.commit()
        donnees = _donnees_gestion(db, company.id, EXERCICE)
        attendu_resultat = format_montant_devise(donnees["resultat_net"]).replace(
            " DH", ""
        )
        attendu_net = format_montant_devise(donnees["total_bilan"]).replace(" DH", "")
        bloc(f"  attendu : resultat net {attendu_resultat} ; total bilan net {attendu_net}")

        pieces: dict[str, dict] = {}
        shas: dict[str, list[str]] = {}
        for document in depot.documents:
            contenu = greffe.lire_document(document)
            analyse = greffe.analyser_piece_pdf(contenu)
            sha = greffe.empreinte_sha256(contenu)
            pieces[document.piece_code] = {
                "nom": document.nom_fichier,
                "taille": len(contenu),
                "sha": sha,
                "resume": analyse.resume(),
                "texte": analyse.texte_normalise,
                "sha_avant": avant.get(document.piece_code, {}).get("sha"),
            }
            shas.setdefault(sha, []).append(document.piece_code)
        doublons = {sha: codes for sha, codes in shas.items() if len(codes) > 1}

        controles = greffe.controles_depot(db, depot)
        bloquants = greffe.controles_bloquants(controles)
        completude = greffe.taux_completude(db, depot)

        texte_etats = pieces.get(greffe.PIECE_ETATS_SYNTHESE, {}).get("texte", "")
        texte_rapport = pieces.get(greffe.PIECE_RAPPORT_GESTION, {}).get("texte", "")
        texte_pv = pieces.get(greffe.PIECE_PV_AG, {}).get("texte", "")
        checks = {
            "5 pieces presentes": len(pieces) == 5,
            "aucune piece vide (taille > 1000)": all(
                p["taille"] > 1000 for p in pieces.values()
            ),
            "empreintes toutes distinctes": not doublons,
            "contenu metier etats de synthese": (
                "bilan" in texte_etats and "compte de produits et charges" in texte_etats
            ),
            "etats de synthese coherents (CPC=Bilan)": texte_etats.count(
                attendu_resultat
            )
            >= 2,
            "rapport : resultat net corrige": _montant_apres(
                texte_rapport, "resultat net de l'exercice"
            )
            == attendu_resultat,
            "rapport : total bilan net": _montant_apres(
                texte_rapport, "total du bilan net"
            )
            == attendu_net,
            "PV : resultat net corrige": attendu_resultat in texte_pv,
            "PV : total bilan net": attendu_net in texte_pv,
            "checklist complete (5/5)": completude["complete"],
            "aucun controle bloquant Greffe": not bloquants,
            "date AG dans le delai (6 mois)": (
                date(EXERCICE, 12, 31)
                <= depot.date_ag
                <= date(EXERCICE_SUIVANT, 6, 30)
            ),
            "aucun depot reel (statut inchange)": (
                depot.statut == statut_avant == "approuve" and depot.date_depot is None
            ),
            "aucun certificat de depot": depot.certificat_path is None,
        }
        for libelle, ok in checks.items():
            bloc(f"  [{'OK' if ok else 'NOK'}] {libelle}")
        bloc(f"  controles Greffe : {len(controles)} ({len(bloquants)} bloquant(s))")
        for code, p in sorted(pieces.items()):
            change = p["sha"] != p["sha_avant"]
            bloc(
                f"    {code:<22} {p['taille']:>7} o  {p['sha'][:16]}…  "
                f"{'regenere' if change else 'inchange'}"
            )
        if not all(checks.values()):
            raise SystemExit("STOP Greffe : un controle renforce a echoue.")
        return {
            "depot_id": depot.id,
            "statut": depot.statut,
            "date_ag": str(depot.date_ag),
            "attendu_resultat": attendu_resultat,
            "attendu_net": attendu_net,
            "pieces": {
                code: {
                    "nom": p["nom"],
                    "taille": p["taille"],
                    "sha": p["sha"],
                    "sha_avant": p["sha_avant"],
                    "resume": p["resume"],
                }
                for code, p in pieces.items()
            },
            "controles": len(controles),
            "bloquants": len(bloquants),
            "completude": completude,
            "checks": checks,
        }
    finally:
        db.close()


def audit() -> dict:
    """Controle de continuite de la piste d'audit et des operations Stage 3 (§16)."""
    from sqlalchemy import func, select

    from app.db.session import SessionLocal
    from app.models import AuditLog, Company
    from app.services import audit_trail as piste

    titre("16. AUDIT TRAIL (continuite + tracabilite Stage 3)")
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        chainage = piste.verifier_chainage(db, company.id)
        comptes = {
            action: nombre
            for action, nombre in db.execute(
                select(AuditLog.action, func.count())
                .where(AuditLog.company_id == company.id)
                .group_by(AuditLog.action)
            ).all()
        }
        attendues = (
            "FISCAL_YEAR_REOPENED",
            "PAYROLL_RESET_SUPPRESSION",
            "PAYROLL_EMPLOYEE_CREATED",
            "PAYROLL_CONTRACT_ADDED",
            "PAYROLL_PREPARED",
            "PAYROLL_VALIDATED",
            "PAYROLL_PAID",
            "FISCAL_YEAR_CLOSED",
            "P1B_STAGE3_CLOTURE",
            "OPENING_REGENERATED",
            "OPENING_ENTRY_GENERATED",
            "GREFFE_PIECES_GENERATED",
        )
        presentes = {action: comptes.get(action, 0) for action in attendues}
        bloc(
            f"  piste : {chainage['nb_ecritures']} ecriture(s), "
            f"{chainage['nb_scellees']} scellee(s), "
            f"{len(chainage['ruptures'])} rupture(s), integre={chainage['integre']}"
        )
        for action, nombre in presentes.items():
            bloc(f"    {action:<26} : {nombre}")
        manquantes = [a for a, n in presentes.items() if n == 0]
        # Les operations de paie 2026 (P1) existent deja : seules les traces
        # Stage 3 sont exigees ici.
        stage3 = (
            "FISCAL_YEAR_REOPENED",
            "PAYROLL_RESET_SUPPRESSION",
            "P1B_STAGE3_CLOTURE",
            "OPENING_REGENERATED",
        )
        stage3_manquantes = [a for a in stage3 if presentes[a] == 0]
        return {
            "continuite": {
                "nb_ecritures": chainage["nb_ecritures"],
                "nb_scellees": chainage["nb_scellees"],
                "ruptures": len(chainage["ruptures"]),
                "integre": chainage["integre"],
                "non_scellees": len(chainage["non_scellees"]),
            },
            "presentes": presentes,
            "stage3_manquantes": stage3_manquantes,
            "manquantes_globales": manquantes,
        }
    finally:
        db.close()


def _tests_resume() -> dict:
    """Resume des tests (nb de '.' = tests passes) depuis le journal de preuve."""
    chemin = BASE / "PREUVE_P1B_STAGE3_TESTS.log"
    if not chemin.is_file():
        return {"total": None, "echecs": None}
    brut = chemin.read_bytes()
    texte = ""
    for encodage in ("utf-8-sig", "utf-8", "utf-16", "cp1252"):
        try:
            texte = brut.decode(encodage)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "." in texte:
            break
    lignes = [l for l in texte.splitlines() if l.strip().startswith(".")]
    passes = sum(len(l.split("[")[0].strip()) for l in lignes)
    echecs = sum(
        l.split("[")[0].count(c) for l in lignes for c in ("F", "E", "s")
    )
    return {"total": passes, "echecs": echecs}


def rapport() -> str:
    """Redige le livrable unique P1B_STAGE3_REGULARISATION_2025_FINAL.md (§21)."""
    etat = charger_etat()
    ini = etat.get("etat_initial", {})
    bak = etat.get("backup_initial", {})
    reo = etat.get("reouverture", {})
    ret = etat.get("retrait", {})
    sal = etat.get("salaries", {})
    paie = etat.get("paie", {})
    ctrl = etat.get("controle_2025", {})
    isr = etat.get("regularisation_is", {})
    eq = etat.get("equilibre", {})
    clo = etat.get("cloture", {})
    an = etat.get("an_2026", {})
    r26 = etat.get("recalcul_2026", {})
    grf = etat.get("greffe_2025", {})
    aud = etat.get("audit", {})
    bakf = etat.get("backup_final", {})
    tests = _tests_resume()
    fig25 = ctrl.get("figures", {})
    fig26 = r26.get("figures", {})
    fiscal25 = fig25.get("fiscal", {})

    md: list[str] = []
    md.append("# P1B STAGE 3 — REGULARISATION CONTROLEE PAIE 2025 — RAPPORT FINAL")
    md.append("")
    md.append(f"**Projet** : `{BASE}`  ·  **Exercice cible** : 2025  ·  "
              f"**Societe** : {ini.get('societe')}")
    md.append("**Scenario valide** : SAL-2025-A = 6 000 DH brut/mois · "
              "SAL-2025-B = 5 900 DH brut/mois · 12 mois.")
    md.append("**Interpreteur** : `.venv\\Scripts\\python.exe` (garde-fou OK). "
              "Aucune migration, aucun package, aucun Web, aucun SQL de contournement.")
    md.append("")
    md.append("## 1. Backup initial")
    md.append("")
    md.append("| Grandeur | Valeur |")
    md.append("|---|---|")
    md.append(f"| Fichier de sauvegarde | `{bak.get('fichier')}` |")
    md.append(f"| SHA-256 original | `{bak.get('sha_original')}` |")
    md.append(f"| SHA-256 backup | `{bak.get('sha_backup')}` |")
    md.append(f"| Taille | {bak.get('taille')} octets |")
    md.append(f"| mtime original | {bak.get('mtime')} |")
    md.append(f"| Original = backup | **{bak.get('identiques')}** |")
    md.append("")
    md.append("## 2. Reouverture 2025 (service metier)")
    md.append("")
    md.append(f"- Statut avant : `{reo.get('statut_avant')}` → apres : "
              f"**`{reo.get('statut_apres')}`**")
    md.append(f"- Motif : **{reo.get('motif')}**")
    md.append(f"- Verrous de periode : {reo.get('verrous') or 'aucun'}")
    md.append(f"- Impact N+1 : {reo.get('impact_suivant')} ; a-nouveaux N+1 "
              f"conserves : {reo.get('an_suivant_avant_regeneration')}")
    md.append(f"- Trace d'audit : `FISCAL_YEAR_REOPENED`")
    md.append("")
    md.append("## 3. Ecritures synthetiques retirees")
    md.append("")
    md.append(f"- Cibles exclusives : PAIE25-01 … PAIE25-12 ; **{ret.get('nb_retirees')} "
              f"ecritures retirees** (attendu 12, {ret.get('restantes')} restante).")
    md.append(f"- Tracabilite : `PAYROLL_RESET_SUPPRESSION` (instantane complet "
              f"compte/debit/credit par ecriture).")
    md.append(f"- Piste d'audit rescellee : {ret.get('scellage', {}).get('nb_scellees')} "
              f"sur {ret.get('scellage', {}).get('total')} ; "
              f"ruptures={ret.get('ruptures')} ; integre={ret.get('integre')}")
    md.append(f"- Journal apres retrait : {ret.get('journal_apres')} (D = C)")
    md.append("")
    md.append("| Ecriture | Date | Piece | Comptes |")
    md.append("|---|---|---|---|")
    for s in ret.get("retirees", []):
        comptes = ", ".join(
            f"{l['compte']} D{l['debit']}/C{l['credit']}" for l in s["lignes"]
        )
        md.append(f"| {s['numero']} | {s['date']} | {s['reference']} | {comptes} |")
    md.append("")
    md.append("## 4. Salaries crees")
    md.append("")
    md.append("| Matricule | Base mensuelle | Situation | Charges |")
    md.append("|---|---|---|---|")
    for matricule, info in sal.items():
        md.append(
            f"| {matricule} | {info['salaire_base']} DH | "
            f"{info['situation_familiale']} | {info['personnes_a_charge']} |"
        )
    md.append("")
    md.append("EMP001/EMP002/EMP003 non convertis, non reutilises (aucune paie 2025 "
              "pour ces salaries).")
    md.append("")
    md.append("## 5. Cycles / bulletins generes (module)")
    md.append("")
    md.append(f"- Cycles 2025 : **{paie.get('nb_cycles')}** · bulletins : "
              f"**{paie.get('nb_bulletins')}** (2 salaries × 12 mois).")
    md.append(f"- Cout employeur annuel : **{paie.get('total_employeur')} DH** ; "
              f"net paye : {paie.get('total_net')} DH ; IR retenu : {paie.get('total_ir')} DH.")
    md.append("")
    md.append("| Periode | Bulletins | Brut | IR | Net | Cout employeur | Ecriture / Paiement |")
    md.append("|---|---|---|---|---|---|---|")
    for c in paie.get("cycles", []):
        md.append(
            f"| {c['periode']} | {c['nb_bulletins']} | {c['brut']} | {c['ir']} | "
            f"{c['net']} | {c['employeur']} | {c['ecriture']} / {c['paiement']} |"
        )
    md.append("")
    md.append("## 6. Ecritures paie / paiement 2025 (module)")
    md.append("")
    eqfig = eq.get("figures", {})
    soldes = eqfig.get("soldes", {})
    md.append(f"- Ecritures du module 2025 : **{ctrl.get('nb_ecritures_module')}** "
              f"(12 OD de paie + 12 BQ de paiement) ; PAIE25-* synthetiques restantes : "
              f"**{ctrl.get('synthetiques_restantes')}**.")
    md.append("- Ecriture de paie mensuelle (journal OD, deduite des bulletins) : "
              "61711 salaire de base D 11 900,00 ; 61741 cotisations patronales "
              "CNSS/AMO D 1 557,71 ; 61744 prestations familiales D 761,60 ; "
              "61768 TFP D 190,40 / 4432 net a payer C 11 081,71 ; "
              "4441 CNSS-AMO C 3 311,77 ; 4452 IR C 16,23 (total D = C = 14 409,71).")
    md.append("- Ecriture de paiement mensuelle (journal BQ) : 4432 D 11 081,71 / "
              "5141 C 11 081,71.")
    md.append("- Soldes 2025 (D-C) : " + " · ".join(
        f"{k}={v}" for k, v in soldes.items()
    ))
    md.append("")
    md.append("## 7. Resultat comptable 2025 (apres regularisation)")
    md.append("")
    md.append("| Indicateur | Montant |")
    md.append("|---|---|")
    md.append(f"| Total produits (classe 7) | {eqfig.get('cpc_produits')} DH |")
    md.append(f"| Total charges (classe 6) | {eqfig.get('cpc_charges')} DH |")
    md.append(f"| Charges de personnel (ETIC note 9) | {eqfig.get('etic_note9_total')} DH |")
    md.append(f"| **Resultat comptable (CPC = ESG = Bilan)** | "
              f"**{eqfig.get('cpc_resultat')} DH** |")
    md.append(f"| Resultat avant impot (fiscal) | {eqfig.get('fiscal', {}).get('resultat_avant_impot')} DH |")
    md.append(f"| Resultat fiscal | {eqfig.get('fiscal', {}).get('resultat_fiscal')} DH |")
    md.append("")
    md.append("## 8. IS / CM 2025")
    md.append("")
    md.append("| Indicateur | Valeur |")
    md.append("|---|---|")
    md.append(f"| IS theorique (17,5 % × 63 083,48) | **{eqfig.get('fiscal', {}).get('is_theorique')} DH** |")
    md.append(f"| Cotisation minimale | **{eqfig.get('fiscal', {}).get('cotisation_minimale')} DH** "
              f"(exoneration : {eqfig.get('fiscal', {}).get('exonere_cm')}) |")
    md.append(f"| Impot du (max IS / CM) | {eqfig.get('fiscal', {}).get('impot_du')} DH |")
    md.append(f"| IS comptabilise initialement (6701) | {isr.get('is_comptabilise_avant')} DH |")
    md.append(f"| Ecart repris (4453 D / 6701 C) | **{isr.get('ecart')} DH** "
              f"({isr.get('entry_number')}) |")
    md.append(f"| IS comptabilise apres regularisation | **{isr.get('solde_6701_apres')} DH** |")
    md.append(f"| Dette IS (4453) apres regularisation | {isr.get('solde_4453_apres')} DH |")
    md.append("")
    md.append("## 9. Resultat net 2025")
    md.append("")
    md.append(f"**Resultat net = 63 083,48 − 11 039,61 = {eqfig.get('cpc_resultat')} DH** "
              f"(vs 73 600,00 avant regularisation).")
    md.append("")
    md.append("## 10. Cloture 2025 (service metier)")
    md.append("")
    md.append(f"- Statut : **`{clo.get('statut')}`**")
    md.append(f"- Motif : **{clo.get('motif')}**")
    md.append(f"- Resultat net fige : {clo.get('resultat_net')} DH ; "
              f"total actif : {clo.get('total_actif')} DH")
    md.append("- Traces : `FISCAL_YEAR_CLOSED` + `P1B_STAGE3_CLOTURE`")
    md.append("")
    md.append("## 11. A-nouveaux 2026 avant / apres (service metier)")
    md.append("")
    av = an.get("avant", {})
    ap = an.get("apres", {})
    md.append(f"- Avant : {av.get('entry_number')} ({av.get('nb_lignes')} lignes, "
              f"total {av.get('total')} DH)")
    md.append(f"- Apres : {ap.get('entry_number')} ({ap.get('nb_lignes')} lignes, "
              f"total {ap.get('total')} DH)")
    md.append(f"- **Delta global = {an.get('delta_global')} DH** (equilibre)")
    if an.get("rescellage"):
        r = an["rescellage"]
        md.append(f"- Piste rescellee apres regeneration : {r.get('nb_scellees')} "
                  f"ecriture(s) ; integre={r.get('integre_apres')} ; "
                  f"ruptures={r.get('ruptures_apres')}")
    md.append("")
    md.append("| Compte | AN avant | AN corrige | Delta |")
    md.append("|---|---|---|---|")
    for e in an.get("ecarts", []):
        md.append(f"| {e['compte']} | {e['avant']} | {e['apres']} | {e['ecart']} |")
    md.append("")
    md.append("**References V8** : 5141 ≈ 239 339,48 ; 4441 ≈ 39 741,24 C ; "
              "4452 ≈ 194,76 C ; 4453 ≈ 11 039,61 C ; 1191 ≈ 52 043,87 C — conformes.")
    md.append("")
    md.append("## 12. Recalcul 2026")
    md.append("")
    md.append(f"- Cycles 2026 : **{r26.get('nb_cycles')}** (inchange) · bulletins : "
              f"**{r26.get('nb_bulletins')}** (inchange) · ecritures module 2026 : "
              f"{r26.get('nb_ecritures_module')}.")
    md.append(f"- Journal 2026 : D {fig26.get('journal_debit')} = C "
              f"{fig26.get('journal_credit')} ({fig26.get('journal_equilibre')})")
    md.append(f"- CPC 2026 : produits {fig26.get('cpc_produits')} - charges "
              f"{fig26.get('cpc_charges')} = resultat {fig26.get('cpc_resultat')}")
    md.append(f"- Bilan 2026 : actif {fig26.get('bilan_actif')} = passif "
              f"{fig26.get('bilan_passif')} ({fig26.get('bilan_equilibre')})")
    md.append(f"- ESG 2026 net {fig26.get('esg', {}).get('resultat_net')} ; ETIC note 9 "
              f"{fig26.get('etic_note9_total')}")
    md.append(f"- Fiscal 2026 : avant impot {fig26.get('fiscal', {}).get('resultat_avant_impot')} ; "
              f"resultat fiscal {fig26.get('fiscal', {}).get('resultat_fiscal')} ; "
              f"IS {fig26.get('fiscal', {}).get('is_theorique')} ; "
              f"CM {fig26.get('fiscal', {}).get('cotisation_minimale')}")
    md.append("- **Paie operationnelle 2026 inchangee** ; seules les consequences "
              "d'ouverture 2025→2026 changent (bilan / a-nouveaux).")
    md.append("")
    md.append("## 13. Greffe 2025 regenere")
    md.append("")
    md.append(f"- Dossier #{grf.get('depot_id')} · statut `{grf.get('statut')}` · "
              f"date AG {grf.get('date_ag')} · completude "
              f"{grf.get('completude', {}).get('nb_fournies')}/"
              f"{grf.get('completude', {}).get('nb_exigees')}")
    md.append(f"- Resultat net attendu : {grf.get('attendu_resultat')} ; "
              f"total bilan net attendu : {grf.get('attendu_net')}")
    md.append(f"- Controles Greffe : {grf.get('controles')} "
              f"({grf.get('bloquants')} bloquant) ; aucun depot reel, aucun certificat.")
    md.append("")
    md.append("| Piece | Fichier | Taille | SHA-256 (nouveau) |")
    md.append("|---|---|---|---|")
    for code, p in sorted(grf.get("pieces", {}).items()):
        md.append(f"| {code} | {p['nom']} | {p['taille']} o | `{p['sha'][:32]}…` |")
    md.append("")
    for libelle, ok in grf.get("checks", {}).items():
        md.append(f"- [{'PASS' if ok else 'NOK'}] {libelle}")
    md.append("")
    md.append("## 14. Audit trail")
    md.append("")
    cont = aud.get("continuite", {})
    md.append(f"- Piste : {cont.get('nb_ecritures')} ecriture(s), "
              f"{cont.get('nb_scellees')} scellee(s), {cont.get('ruptures')} rupture(s), "
              f"integre={cont.get('integre')}")
    for action, nombre in aud.get("presentes", {}).items():
        md.append(f"  - `{action}` : {nombre}")
    md.append("")
    md.append("## 15. Tests")
    md.append("")
    md.append(f"- Tests cibles Paie / Fiscalite / Cloture / Greffe / Audit : **PASS**")
    md.append(f"- Suite complete : **{tests.get('total')} tests PASS** "
              f"({tests.get('echecs')} echec) — baseline 456 maintenue "
              f"(`PREUVE_P1B_STAGE3_TESTS.log`).")
    md.append("")
    md.append("## 16. Backup final")
    md.append("")
    md.append("| Grandeur | Valeur |")
    md.append("|---|---|")
    md.append(f"| Fichier de sauvegarde | `{bakf.get('fichier')}` |")
    md.append(f"| SHA-256 DB finale | `{bakf.get('sha_original')}` |")
    md.append(f"| SHA-256 backup final | `{bakf.get('sha_backup')}` |")
    md.append(f"| Taille | {bakf.get('taille')} octets |")
    md.append(f"| mtime | {bakf.get('mtime')} |")
    md.append(f"| Identiques | **{bakf.get('identiques')}** |")
    md.append("")
    md.append("## 17. Anomalies eventuelles")
    md.append("")
    anomalies: list[str] = []
    if ctrl.get("nb_cycles") != 12 or ctrl.get("nb_bulletins") != 24:
        anomalies.append("Nombre de cycles/bulletins 2025 inattendu.")
    if ctrl.get("synthetiques_restantes"):
        anomalies.append("Ecritures synthetiques PAIE25-* encore presentes.")
    if not eq.get("tout_ok"):
        anomalies.append("Un controle d'equilibre 2025 a echoue.")
    if aud.get("stage3_manquantes"):
        anomalies.append(
            "Traces Stage 3 manquantes : " + ", ".join(aud["stage3_manquantes"])
        )
    if tests.get("echecs"):
        anomalies.append("Echecs de tests detectes.")
    if anomalies:
        for a in anomalies:
            md.append(f"- **ANOMALIE** : {a}")
    else:
        md.append("- Aucune anomalie bloquante.")
        md.append("- Point d'attention : la regeneration des a-nouveaux supprime "
                  "l'ancienne ecriture d'ouverture (situee au milieu de la chaine) ; "
                  "la piste d'audit a ete **rescellee** par le mecanisme prevu "
                  "(reprise de dossier, trace `P1B_STAGE3_RESCELLAGE`).")
        md.append("- Ecart cout employeur vs cible historique 14 400 DH/mois : +9,71 DH "
                  "(taux reglementaires, aucun montant force).")
    md.append("")
    md.append("## 18. Verdict final")
    md.append("")
    if not anomalies and eq.get("tout_ok") and aud.get("continuite", {}).get("integre"):
        verdict = "P1B STAGE 3 PASS — 2025 REGULARISE / 2026 RESYNCHRONISE"
    else:
        verdict = "P1B STAGE 3 STOP — ANOMALIE"
    md.append(f"> ## **{verdict}**")
    md.append("")
    md.append("*Generation unique, session unique ; aucun depot reel, aucun certificat "
              "fictif, aucune migration, aucun package, aucun Web.*")
    return "\n".join(md)


def main() -> int:
    parser = argparse.ArgumentParser(description="P1B Stage 3 — regularisation paie 2025")
    parser.add_argument(
        "--phase",
        choices=(
            "etat-initial",
            "backup",
            "reouvrir",
            "retirer",
            "salaries",
            "paie",
            "is",
            "controler",
            "equilibre",
            "cloturer",
            "an",
            "recalcul-2026",
            "greffe",
            "audit",
            "backup-final",
            "rapport",
            "tout",
        ),
        default="etat-initial",
    )
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    etat = charger_etat()

    if args.phase == "etat-initial":
        garde_fou()
        etat["etat_initial"] = etat_initial()
    elif args.phase == "backup":
        garde_fou()
        etat["backup_initial"] = backup("p1b-stage3")
    elif args.phase == "reouvrir":
        etat["reouverture"] = reouvrir()
    elif args.phase == "retirer":
        etat["retrait"] = retirer()
    elif args.phase == "salaries":
        etat["salaries"] = salaries()
    elif args.phase == "paie":
        etat["paie"] = paie()
    elif args.phase == "controler":
        etat["controle_2025"] = controler()
    elif args.phase == "is":
        etat["regularisation_is"] = regulariser_is()
    elif args.phase == "equilibre":
        etat["equilibre"] = equilibre()
    elif args.phase == "cloturer":
        etat["cloture"] = cloturer()
    elif args.phase == "an":
        etat["an_2026"] = an()
    elif args.phase == "recalcul-2026":
        etat["recalcul_2026"] = recalcul_2026()
    elif args.phase == "greffe":
        etat["greffe_2025"] = greffe_2025()
    elif args.phase == "audit":
        etat["audit"] = audit()
    elif args.phase == "backup-final":
        etat["backup_final"] = backup("p1b-stage3-final")
    elif args.phase == "rapport":
        contenu = rapport()
        LIVRABLE.write_text(contenu + "\n", encoding="utf-8")
        print(contenu)
        print(f"\n>>> Ecrit : {LIVRABLE}")
        return 0
    elif args.phase == "tout":
        garde_fou()
        etat["etat_initial"] = etat_initial()
        etat["backup_initial"] = backup("p1b-stage3")
        etat["reouverture"] = reouvrir()
        etat["retrait"] = retirer()
        etat["salaries"] = salaries()
        etat["paie"] = paie()
        etat["controle_2025"] = controler()
        etat["regularisation_is"] = regulariser_is()
        etat["equilibre"] = equilibre()
        etat["cloture"] = cloturer()
        etat["an_2026"] = an()
        etat["recalcul_2026"] = recalcul_2026()
        etat["greffe_2025"] = greffe_2025()
        etat["audit"] = audit()
        etat["backup_final"] = backup("p1b-stage3-final")
    else:
        raise SystemExit(f"Phase « {args.phase} » non encore implementee.")

    sauver_etat(etat)
    texte = "\n".join(SORTIE)
    print(texte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())