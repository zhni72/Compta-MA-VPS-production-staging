"""Purge des donnees metier d'un dossier Compta MA (recette J9).

Cet outil **vide les donnees de gestion** d'une base de test en **conservant** :

- le **plan comptable** et les **taux de TVA** (referentiels) ;
- la **societe** et ses **exercices** (reinitialises a `open`) ;
- les **roles**, **utilisateurs** et leurs rattachements.

Sont supprimes : factures, reglements, ecritures, tiers, stocks, immobilisations,
paie, declarations (dont liasse), greffe, banque, audit et verrous, activite et
factures electroniques.

Securite : **simulation par defaut** (`--appliquer` pour ecrire) et **sauvegarde
horodatee** de la base avant toute suppression.

Usage :
    python tools/j9_purge_donnees.py                 # simulation (compteurs)
    python tools/j9_purge_donnees.py --appliquer     # purge reelle (avec sauvegarde)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJET = Path(__file__).resolve().parents[1]
if str(PROJET) not in sys.path:
    sys.path.insert(0, str(PROJET))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db import seed as seed_module  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, FiscalYear  # noqa: E402
import app.models  # noqa: E402,F401 - charge toutes les tables

# Tables (et ordre) **conservees** : la purge part de `Base.metadata` et supprime
# tout le reste dans l'ordre inverse des dependances.
TABLES_CONSERVEES = {
    "accounts",
    "vat_rates",
    "companies",
    "fiscal_years",
    "roles",
    "users",
    "user_roles",
    "user_companies",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse la ligne de commande."""
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--appliquer", action="store_true", help="ecrire reellement")
    parseur.add_argument("--sans-sauvegarde", action="store_true", help="ne pas copier la base")
    return parseur.parse_args(argv)


def sauvegarder_base() -> Path | None:
    """Copie horodatee de la base SQLite (retourne le chemin du fichier cree)."""
    if not settings.is_sqlite:
        print("Base non SQLite : sauvegarde manuelle requise avant purge.")
        return None
    origine = Path(settings.database_url.replace("sqlite:///", ""))
    if not origine.is_file():
        return None
    cible = origine.with_name(
        f"{origine.name}.bak-j9-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(origine, cible)
    print(f"Sauvegarde : {cible.name} ({cible.stat().st_size} octets)")
    return cible


def compter(db) -> dict[str, int]:
    """Nombre de lignes par table (hors tables conservees)."""
    compteurs: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in TABLES_CONSERVEES:
            continue
        compteurs[table.name] = db.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
    return {nom: total for nom, total in compteurs.items()}


def purger(db) -> None:
    """Supprime toutes les lignes des tables metier (ordre inverse des dependances)."""
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in TABLES_CONSERVEES:
            continue
        db.execute(delete(table))
    db.flush()


def main(argv: list[str] | None = None) -> int:
    """Point d'entree : purge des donnees metier (simulation par defaut)."""
    args = parse_args(argv)
    with SessionLocal() as db:
        avant = compter(db)
        total = sum(avant.values())
        print(f"Tables metier : {len(avant)} | lignes a supprimer : {total}")
        for nom, compte in sorted(avant.items()):
            if compte:
                print(f"    {nom:<26} {compte}")
        if not args.appliquer:
            print("\nSimulation : relancez avec --appliquer pour purger.")
            return 0
        if not args.sans_sauvegarde:
            sauvegarder_base()
        purger(db)
        # Exercices reinitialises (statut `open`) et compteurs de numerotation purges.
        for exercice in db.execute(select(FiscalYear)).scalars():
            exercice.status = "open"
            exercice.closed_at = None
        for societe in db.execute(select(Company)).scalars():
            seed_module.create_default_journals(db, societe)
        db.commit()
        apres = compter(db)
        restant = sum(apres.values())
        print(f"\nPurge terminee : {total} lignes supprimees, {restant} restantes.")
        if restant:
            print("  Tables non vides :", {k: v for k, v in apres.items() if v})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
