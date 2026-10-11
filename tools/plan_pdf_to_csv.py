"""Convertit le plan comptable marocain (PDF) en CSV pour l'amorcage.

Usage :
    python tools/plan_pdf_to_csv.py "C:/chemin/Plan_Comptable_Marocain.pdf" \
        app/data/plan_comptable_cgnc.csv

Le PDF officiel presente la hierarchie du CGNC : rubriques (2 chiffres),
postes (3 chiffres), comptes principaux (4 chiffres) et comptes divisionnaires
(5 chiffres) ou sous-comptes (6 chiffres et plus).

Le CSV produit (`number;label;is_collectif`) est celui consomme par
`app.db.seed.load_plan_comptable`. Filtre de fiabilite : un compte n'est retenu
que si son poste (3 premiers chiffres) existe bien dans le PDF, ce qui elimine
les faux positifs (numeros de page, dates, references).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ACCOUNT_LINE = re.compile(r"^(\d{2,10})\s+(\D.*)$")

# Certains postes du plan sont imprimes groupes : « 613/614 Autres charges
# externes », « 294/295 Provisions pour depreciation des immobilisations
# financieres ». Chaque element du groupe est un poste distinct.
GROUPED_POSTE_LINE = re.compile(r"^(\d{2,3}(?:/\d{2,3})+)\s+(\D.*)$")

# Comptes de regroupement (collectifs) du CGNC : la saisie se fait sur leurs
# divisionnaires (34210001 pour un client, 44110001 pour un fournisseur...).
COLLECTIF_ACCOUNTS = {"3421", "4411", "3455"}


def extract_text(pdf_path: Path) -> str:
    """Extrait le texte du PDF (une ligne par entree du plan)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "pypdf est requis : pip install pypdf"
        ) from exc
    reader = PdfReader(str(pdf_path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def parse_plan(text: str) -> dict[str, str]:
    """Retourne {numero_compte: libelle} pour les comptes a 4 chiffres et plus.

    Filtre de fiabilite : un compte n'est retenu que si son poste (3 chiffres)
    ou, a defaut, sa rubrique (2 chiffres) est presente dans le document.
    Le plan officiel omet parfois la ligne du poste (2441, 51231, 7591x,
    91957, 9396, 011x...) et imprime certains postes groupes (613/614,
    294/295) : la verification sur le poste ET sur la rubrique evite de perdre
    ces comptes tout en ecartant le bruit (numeros de page, dates).
    """
    rubriques: set[str] = set()
    postes: set[str] = set()
    comptes: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())

        groupe = GROUPED_POSTE_LINE.match(line)
        if groupe:
            for partie in groupe.group(1).split("/"):
                if len(partie) == 2:
                    rubriques.add(partie)
                else:
                    postes.add(partie)
            continue

        match = ACCOUNT_LINE.match(line)
        if not match:
            continue
        number, label = match.group(1), match.group(2).strip()
        if len(label) < 3:
            continue
        if len(number) == 2:
            rubriques.add(number)
        elif len(number) == 3:
            postes.add(number)
        elif 4 <= len(number) <= 8:
            comptes[number] = label

    return {
        number: label
        for number, label in comptes.items()
        if number[:3] in postes or number[:2] in rubriques
    }


def write_csv(accounts: dict[str, str], csv_path: Path) -> None:
    """Ecrit le CSV trie par numero de compte."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["number", "label", "is_collectif"])
        for number in sorted(accounts):
            writer.writerow(
                [
                    number,
                    accounts[number],
                    "1" if number in COLLECTIF_ACCOUNTS else "0",
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan comptable PDF -> CSV")
    parser.add_argument("pdf", help="chemin du PDF du plan comptable marocain")
    parser.add_argument(
        "csv",
        nargs="?",
        default="app/data/plan_comptable_cgnc.csv",
        help="chemin du CSV a produire",
    )
    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"PDF introuvable : {pdf_path}", file=sys.stderr)
        return 1

    accounts = parse_plan(extract_text(pdf_path))
    write_csv(accounts, Path(args.csv))

    par_classe: dict[str, int] = {}
    for number in accounts:
        par_classe[number[0]] = par_classe.get(number[0], 0) + 1
    print(f"{len(accounts)} comptes ecrits dans {args.csv}")
    for classe in sorted(par_classe):
        print(f"  classe {classe} : {par_classe[classe]} comptes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())