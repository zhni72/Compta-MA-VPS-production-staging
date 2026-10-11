"""Rechargement du plan comptable CGNC / PCGE dans un dossier Compta MA.

Le plan de reference du projet est `app/data/plan_comptable_cgnc.csv` (format
`number;label;is_collectif`), regenere depuis le PCGE officiel. Cet outil :

1. cree les comptes absents du dossier ;
2. rafraichit les libelles et le caractere collectif des comptes existants
   (corrige notamment les libelles alteres par un import a l'encodage errone) ;
3. ne supprime jamais un compte et ne touche pas aux ecritures.

Securite : simulation par defaut (`--appliquer` pour ecrire), sauvegarde de la
base SQLite avant toute ecriture.

Usage :
    python tools/charger_plan_comptable.py                # simulation
    python tools/charger_plan_comptable.py --appliquer    # mise a jour reelle
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJET = Path(__file__).resolve().parents[1]
CSV_DEFAUT = PROJET / "app" / "data" / "plan_comptable_cgnc.csv"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse la ligne de commande."""
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--db", default=None, help="base cible (chemin SQLite)")
    parseur.add_argument("--csv", default=str(CSV_DEFAUT), help="plan comptable CSV")
    parseur.add_argument("--sans-etiquettes", action="store_true", help="ne pas rafraichir les libelles")
    parseur.add_argument("--sans-sauvegarde", action="store_true", help="ne pas copier la base")
    parseur.add_argument("--appliquer", action="store_true", help="ecrire reellement")
    return parseur.parse_args(argv)


def resoudre_base(chemin: str | None) -> Path | None:
    """Fixe DATABASE_URL avant l'import de l'application et retourne le fichier."""
    if chemin:
        cible = Path(chemin)
        if not cible.is_absolute():
            cible = (Path.cwd() / cible).resolve()
        os.environ["DATABASE_URL"] = f"sqlite:///{cible.as_posix()}"
        return cible
    if os.environ.get("DATABASE_URL"):
        return None
    return PROJET / "compta_ma.db"


def lire_plan(chemin: Path) -> list[dict]:
    """Lit le plan comptable de reference (number;label;is_collectif)."""
    comptes: list[dict] = []
    with chemin.open(encoding="utf-8-sig", newline="") as flux:
        for ligne in csv.DictReader(flux, delimiter=";"):
            number = (ligne.get("number") or "").strip()
            if not number:
                continue
            comptes.append(
                {
                    "number": number,
                    "label": (ligne.get("label") or "").strip() or f"Compte {number}",
                    "is_collectif": (ligne.get("is_collectif") or "0").strip() == "1",
                }
            )
    return comptes


def main(argv: list[str] | None = None) -> int:
    """Charge ou met a jour le plan comptable (simulation par defaut)."""
    args = parse_args(argv)
    chemin_base = resoudre_base(args.db)
    source = Path(args.csv)
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.exists():
        print(f"Plan comptable introuvable : {source}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(PROJET))
    from sqlalchemy import select  # noqa: PLC0415

    from app.core.config import settings  # noqa: PLC0415
    from app.db.base import creer_tables_dev  # noqa: PLC0415
    from app.db.session import SessionLocal, engine  # noqa: PLC0415
    from app.models import Account, EntryLine  # noqa: PLC0415

    creer_tables_dev(engine)
    comptes = lire_plan(source)
    mode = "ECRITURE REELLE" if args.appliquer else "SIMULATION (aucune ecriture)"
    print(f"Base cible : {settings.database_url}")
    print(f"Plan source: {source} ({len(comptes)} comptes)")
    print(f"Mode       : {mode}\n")

    if args.appliquer and not args.sans_sauvegarde and chemin_base and chemin_base.exists():
        horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
        sauvegarde = chemin_base.with_name(f"{chemin_base.name}.bak-{horodatage}")
        shutil.copy2(chemin_base, sauvegarde)
        print(f"Sauvegarde : {sauvegarde}\n")

    with SessionLocal() as db:
        existants = {
            compte.number: compte for compte in db.execute(select(Account)).scalars()
        }
        crees = 0
        rafraichis = 0
        exemples: list[str] = []
        for compte in comptes:
            actuel = existants.get(compte["number"])
            libelle = compte["label"][:180]
            if actuel is None:
                db.add(
                    Account(
                        number=compte["number"],
                        label=libelle,
                        account_class=int(compte["number"][0]),
                        is_collectif=compte["is_collectif"],
                    )
                )
                crees += 1
                continue
            if args.sans_etiquettes:
                continue
            if actuel.label != libelle or actuel.is_collectif != compte["is_collectif"]:
                if len(exemples) < 5:
                    exemples.append(
                        f"libelle corrige {actuel.number} : {actuel.label!r} -> {libelle!r}"
                    )
                actuel.label = libelle
                actuel.is_collectif = compte["is_collectif"]
                rafraichis += 1
        for exemple in exemples:
            print(f"   {exemple}")
        if args.appliquer:
            db.commit()
        else:
            db.rollback()

        plan = db.execute(select(Account)).scalars().all()
        utilises = {
            ligne for (ligne,) in db.execute(select(EntryLine.account_number).distinct())
        }
        manquants = sorted(numero for numero in utilises if numero not in {c.number for c in plan})
        print(f"\nComptes crees     : {crees}")
        print(f"Libelles corriges : {rafraichis}")
        print(f"Plan total        : {len(plan)} comptes")
        print(f"Comptes utilises par une ecriture mais absents du plan : {manquants or 'aucun'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

