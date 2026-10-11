"""Referentiel de codification de la liasse fiscale — inspection et verification.

Le **schema XSD** officiel de chaque modele de liasse fixe les `tableau/id` et les
`cellule/codeEdi` **legaux**, mais il ne porte **aucun libelle** : la correspondance
`codeEdi` <-> rubrique comptable vient du referentiel `codification_liasse.csv`
(annexe DGI « Codification des cellules » non fournie — ambiguite A22 du CDC).

Cet outil sert a :

- `--contrat` : afficher la structure lue dans le XSD (racine, id du modele,
  nombre de tableaux, de codes, types de `valeur` / `numeroLigne`) ;
- `--codes` : imprimer les `codeEdi` legaux d'un modele (a recopier depuis l'annexe) ;
- `--rubriques` : imprimer le **catalogue des rubriques** alimentees par l'application ;
- `--gabarit` : ecrire un **gabarit** de referentiel (une ligne par tableau) a
  completer par l'expert-comptable ;
- `--verifier` : controler le referentiel courant (modele, tableau, code, rubrique).

Aucun code n'est devine : l'outil **refuse** un `codeEdi` ou un `tableau/id` absent
du schema, et signale les rubriques hors catalogue.

Usage :
    python tools/liasse_codification.py --contrat
    python tools/liasse_codification.py --codes "comptable simplifié"
    python tools/liasse_codification.py --gabarit "comptable simplifié"
    python tools/liasse_codification.py --verifier
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJET = Path(__file__).resolve().parents[1]
if str(PROJET) not in sys.path:  # permet d'executer l'outil sans installation
    sys.path.insert(0, str(PROJET))

from app.core.config import settings  # noqa: E402
from app.services.liasse_edi import (  # noqa: E402
    COLONNES_CODIFICATION,
    MODELE_PAR_DEFAUT,
    PREFIXES_RUBRIQUES,
    RUBRIQUES_FIXES,
    LiasseError,
    charger_codification,
    contrat_modele,
    resoudre_modele,
    rubrique_documentee,
    xsds_disponibles,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse la ligne de commande."""
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "modele",
        nargs="?",
        default=MODELE_PAR_DEFAUT,
        help=f"modele de liasse (defaut : {MODELE_PAR_DEFAUT})",
    )
    parseur.add_argument("--contrat", action="store_true", help="structure lue dans le XSD")
    parseur.add_argument("--codes", action="store_true", help="codes codeEdi legaux du modele")
    parseur.add_argument("--rubriques", action="store_true", help="catalogue des rubriques")
    parseur.add_argument("--gabarit", action="store_true", help="ecrire un gabarit de referentiel")
    parseur.add_argument("--verifier", action="store_true", help="controler le referentiel")
    parseur.add_argument("--fichier", default=None, help="referentiel a verifier (CSV)")
    parseur.add_argument("--cible", default=None, help="fichier du gabarit a ecrire")
    parseur.add_argument("--xsd-dir", default=None, help="dossier des XSD (defaut : projet)")
    parseur.add_argument("--force", action="store_true", help="ecraser le gabarit existant")
    return parseur.parse_args(argv)


def afficher_contrat(modele: str, xsd_dir: Path | None) -> None:
    """Affiche la structure du modele telle que declaree par le schema."""
    contrat = contrat_modele(modele, xsd_dir=xsd_dir)
    print(f"Modele            : {contrat['modele']}")
    print(f"Libelle           : {contrat['libelle']}")
    print(f"Schema            : {contrat['fichier']}")
    print(f"Racine XML        : {contrat['racine']}")
    print(f"Id du modele      : {contrat['modele_id']}")
    print(f"Tableaux legaux   : {len(contrat['tableaux'])} -> {contrat['tableaux']}")
    print(f"Codes codeEdi     : {len(contrat['codes'])}")
    print(f"Codes extraField  : {contrat['extra_fields']}")
    print(f"Type de 'valeur'  : {contrat['type_valeur']}")
    print(f"Type 'numeroLigne': {contrat['type_numero_ligne']}")


def ecrire_gabarit(modele: str, cible: Path, xsd_dir: Path | None, *, force: bool) -> int:
    """Ecrit un gabarit de referentiel (une ligne par tableau du schema)."""
    if cible.exists() and not force:
        print(f"Le fichier {cible} existe deja (--force pour l'ecraser).")
        return 1
    modele_resolu = resoudre_modele(modele)
    contrat = contrat_modele(modele_resolu, xsd_dir=xsd_dir)
    cible.parent.mkdir(parents=True, exist_ok=True)
    with cible.open("w", encoding="utf-8", newline="") as flux:
        writer = csv.writer(flux, lineterminator="\r\n")
        writer.writerow(COLONNES_CODIFICATION)
        for tableau_id in contrat["tableaux"]:
            writer.writerow(
                [
                    modele_resolu,
                    tableau_id,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "gabarit genere depuis le XSD — a completer (annexe DGI "
                    "« Codification des cellules »)",
                ]
            )
    print(f"Gabarit ecrit : {cible} ({len(contrat['tableaux'])} tableau(x) du schema)")
    print("Completer les colonnes tableau_libelle, code_edi, rubrique et libelle.")
    return 0


def verifier(fichier: Path, xsd_dir: Path | None) -> int:
    """Controle le referentiel de codification contre les schemas et le catalogue."""
    try:
        lignes = charger_codification(chemin=fichier)
    except LiasseError as exc:
        print(f"ERREUR : {exc}")
        return 1
    par_modele: dict[str, list[dict]] = {}
    for ligne in lignes:
        par_modele.setdefault(ligne["modele"], []).append(ligne)
    print(f"Referentiel : {fichier} — {len(lignes)} ligne(s), {len(par_modele)} modele(s)")
    anomalies = 0
    for modele, modele_lignes in sorted(par_modele.items()):
        try:
            contrat = contrat_modele(modele, xsd_dir=xsd_dir)
        except LiasseError as exc:
            print(f"  [KO] modele « {modele} » : {exc}")
            anomalies += 1
            continue
        anomalies_modele = 0
        for ligne in modele_lignes:
            if ligne["tableau_id"] not in contrat["tableaux"]:
                print(
                    f"  [KO] tableau {ligne['tableau_id']} (code {ligne['code_edi']}) "
                    "absent de l'énumération du schéma"
                )
                anomalies_modele += 1
            if ligne["code_edi"] not in contrat["codes_ensemble"]:
                print(
                    f"  [KO] codeEdi {ligne['code_edi']} (tableau {ligne['tableau_id']}) "
                    "absent de l'énumération du schéma"
                )
                anomalies_modele += 1
            if not rubrique_documentee(ligne["rubrique"]):
                print(
                    f"  [KO] rubrique « {ligne['rubrique']} » (code {ligne['code_edi']}) "
                    "hors catalogue (voir --rubriques)"
                )
                anomalies_modele += 1
        anomalies += anomalies_modele
        print(
            f"  [{'OK' if anomalies_modele == 0 else 'KO'}] {modele} : "
            f"{len(modele_lignes)} ligne(s) contrôlée(s)"
        )
    if anomalies:
        print(f"\n{anomalies} anomalie(s) : la liasse sera refusée jusqu'à correction.")
        return 1
    print("\nRéférentiel conforme aux schémas et au catalogue des rubriques.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Point d'entree de l'outil (les erreurs de referentiel sont expliquees)."""
    args = parse_args(argv)
    xsd_dir = Path(args.xsd_dir) if args.xsd_dir else None
    try:
        return executer(args, xsd_dir)
    except LiasseError as exc:
        print(f"ERREUR : {exc}")
        print(f"Schémas présents : {', '.join(xsds_disponibles(xsd_dir=xsd_dir)) or 'aucun'}")
        return 1


def executer(args: argparse.Namespace, xsd_dir: Path | None) -> int:
    """Execute l'action demandee sur la ligne de commande."""
    if args.rubriques:
        print("Rubriques dynamiques (prefixe + element comptable) :")
        for prefixe, description in PREFIXES_RUBRIQUES.items():
            print(f"  {prefixe:<9} {description}")
        print("\nRubriques fixes (calculees par les modules) :")
        for cle, libelle in RUBRIQUES_FIXES.items():
            print(f"  {cle:<38} {libelle}")
        return 0
    if args.codes:
        for code in contrat_modele(args.modele, xsd_dir=xsd_dir)["codes"]:
            print(code)
        return 0
    if args.gabarit:
        cible = Path(args.cible) if args.cible else (
            settings.liasse_racine / "codification_liasse.gabarit.csv"
        )
        return ecrire_gabarit(args.modele, cible, xsd_dir, force=args.force)
    if args.verifier:
        return verifier(
            Path(args.fichier) if args.fichier else settings.liasse_codification, xsd_dir
        )
    afficher_contrat(args.modele, xsd_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())