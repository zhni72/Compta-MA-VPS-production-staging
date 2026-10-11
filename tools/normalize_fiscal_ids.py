"""Verification et correction des identifiants fiscaux deja enregistres.

**Norme appliquee** : l'identifiant fiscal marocain (IF) comporte **7 ou 8
chiffres** et s'utilise **tel quel** — ni ajout, ni suppression de zero
(« 1084612 » reste « 1084612 »). L'ancienne regle de complement a 8 chiffres
(zfill) etait erronee : elle transformait « 1084612 » en « 01084612 », soit un
identifiant different de celui attribue par la DGI.

Cet outil sert donc a :
1. **verifier** tous les IF du dossier (societes et tiers) : seuls 7 ou 8
   chiffres sont acceptes ;
2. **retirer, sur demande explicite**, le zero de tete ajoute par l'ancienne
   regle (`--retirer-zero-initial`) — a n'utiliser que si les IF du dossier ont
   ete completes par cette ancienne regle (8 chiffres commencant par 0 ) ;
3. verifier les ICE (15 chiffres).

Simulation par defaut ; `--appliquer` ecrit les corrections.

Usage :
    python -m tools.normalize_fiscal_ids                              # verification
    python -m tools.normalize_fiscal_ids --retirer-zero-initial       # simulation
    python -m tools.normalize_fiscal_ids --retirer-zero-initial --appliquer
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Permet d'executer le script depuis la racine du projet (python tools/...).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, ThirdParty  # noqa: E402
from app.services.identifiers import (  # noqa: E402
    ComplianceError,
    normalize_fiscal_id,
    validate_ice,
)


def chemin_sqlite() -> Path | None:
    """Chemin du fichier SQLite du dossier (None si le SGBD est un serveur)."""
    url = settings.database_url
    if not url.startswith("sqlite"):
        return None
    chemin = url.split("sqlite:///")[-1]
    return Path(chemin) if chemin else None


def zero_initial_a_retirer(valeur: str | None) -> str | None:
    """IF prive du zero de tete ajoute par l'ancienne regle (sinon None).

    L'ancienne regle completait les IF a 8 chiffres : un IF de 7 chiffres etait
    stocke avec un zero de tete (« 1084612 » -> « 01084612 »). Seules les valeurs
    a 8 chiffres commencant par « 0 » sont concernees.
    """
    if valeur is None:
        return None
    nettoye = str(valeur).strip()
    if nettoye.isdigit() and len(nettoye) == 8 and nettoye.startswith("0"):
        return nettoye[1:]
    return None


def main() -> None:
    parseur = argparse.ArgumentParser(
        description="Verification des IF (7 ou 8 chiffres, sans transformation)"
    )
    parseur.add_argument(
        "--appliquer",
        action="store_true",
        help="ecrire les corrections (par defaut : simulation)",
    )
    parseur.add_argument(
        "--retirer-zero-initial",
        action="store_true",
        help="retirer le zero de tete ajoute par l'ancienne regle (01084612 -> 1084612)",
    )
    parseur.add_argument(
        "--sans-sauvegarde",
        action="store_true",
        help="ne pas copier la base SQLite avant ecriture",
    )
    args = parseur.parse_args()

    print(f"Base : {settings.database_url}")
    print(f"Mode : {'APPLICATION' if args.appliquer else 'SIMULATION'}")

    # Sauvegarde horodatee avant toute ecriture (regle du projet : pas d'ecriture
    # en masse sans point de restauration).
    if args.appliquer and not args.sans_sauvegarde:
        fichier = chemin_sqlite()
        if fichier is not None and fichier.exists():
            horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
            sauvegarde = fichier.with_name(f"{fichier.name}.bak-{horodatage}")
            shutil.copy2(fichier, sauvegarde)
            print(f"Sauvegarde : {sauvegarde}")
    print(
        "Regle IF : 7 ou 8 chiffres, utilise tel quel"
        + ("  |  retrait du zero initial : ACTIF" if args.retirer_zero_initial else "")
        + "\n"
    )

    corrections = 0
    rejets: list[tuple[str, str]] = []
    conformes = 0

    with SessionLocal() as db:
        for tiers in db.execute(select(ThirdParty).order_by(ThirdParty.id)).scalars().all():
            if tiers.fiscal_id:
                try:
                    normalize_fiscal_id(tiers.fiscal_id)
                    conformes += 1
                except ComplianceError as exc:
                    rejets.append((f"{tiers.code} - {tiers.name}", str(exc)))
                else:
                    if args.retirer_zero_initial:
                        corrige = zero_initial_a_retirer(tiers.fiscal_id)
                        if corrige is not None:
                            print(
                                f"TIERS  {tiers.code:8} {tiers.name[:28]:30} "
                                f"IF « {tiers.fiscal_id} » -> « {corrige} » (zero initial retire)"
                            )
                            if args.appliquer:
                                tiers.fiscal_id = corrige
                            corrections += 1
            if tiers.ice:
                try:
                    ice = validate_ice(tiers.ice)
                except ComplianceError as exc:
                    rejets.append((f"{tiers.code} - {tiers.name}", str(exc)))
                    continue
                if ice != tiers.ice:
                    print(
                        f"TIERS  {tiers.code:8} {tiers.name[:28]:30} "
                        f"ICE « {tiers.ice} » -> « {ice} »"
                    )
                    if args.appliquer:
                        tiers.ice = ice
                    corrections += 1

        for societe in db.execute(select(Company).order_by(Company.id)).scalars().all():
            if societe.fiscal_id:
                try:
                    normalize_fiscal_id(societe.fiscal_id)
                    conformes += 1
                except ComplianceError as exc:
                    rejets.append((f"SOCIETE {societe.name}", str(exc)))
                else:
                    if args.retirer_zero_initial:
                        corrige = zero_initial_a_retirer(societe.fiscal_id)
                        if corrige is not None:
                            print(
                                f"SOCIETE {societe.name[:26]:28} "
                                f"IF « {societe.fiscal_id} » -> « {corrige} » (zero initial retire)"
                            )
                            if args.appliquer:
                                societe.fiscal_id = corrige
                            corrections += 1
            if societe.ice:
                try:
                    ice = validate_ice(societe.ice)
                except ComplianceError as exc:
                    rejets.append((f"SOCIETE {societe.name}", str(exc)))
                    continue
                if ice != societe.ice:
                    print(f"SOCIETE {societe.name[:26]:28} ICE « {societe.ice} » -> « {ice} »")
                    if args.appliquer:
                        societe.ice = ice
                    corrections += 1

        if args.appliquer:
            db.commit()

    print(f"\nIF conformes (7 ou 8 chiffres) : {conformes}")
    print(f"Corrections {'appliquees' if args.appliquer else 'a appliquer'} : {corrections}")
    for reference, motif in rejets:
        print(f"  A VERIFIER : {reference} -> {motif}")


if __name__ == "__main__":
    main()