"""POC du moteur PDF (jalon J0) — decision d'architecture D1.

Mesure la disponibilite des moteurs, le temps de rendu et la taille des fichiers
produits pour un document realiste (bilan a N lignes), afin de trancher la
decision **D1** du CDC GLOBAL (module P1.1 Export PDF).

Usage :
    python tools/poc_pdf.py [--lignes 120]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pdf import (  # noqa: E402
    TAILLE_MAX_GREFFE,
    Colonne,
    Document,
    Tableau,
    PdfError,
    controle_taille_pdf,
    moteur_disponible,
    rendre_pdf,
)


def diagnostic_weasyprint() -> str:
    """Etat du moteur WeasyPrint sur ce poste (import seul, sans rendu).

    L'import est encapsule : WeasyPrint imprime un long message d'erreur sur la
    sortie standard lorsqu'il ne trouve pas les bibliotheques systeme (GTK).
    """
    import contextlib
    import io

    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            import weasyprint  # noqa: PLC0415

        return f"disponible (version {weasyprint.__version__})"
    except Exception as exc:  # noqa: BLE001 - diagnostic d'environnement
        message = str(exc).split(".")[0][:110]
        return f"INDISPONIBLE ({type(exc).__name__}: {message})"


def document_bilan(nb_lignes: int) -> Document:
    """Document de test : bilan avec compte, libelle, brut, amortissements, net."""
    colonnes = [
        Colonne("Compte", largeur=18),
        Colonne("Libelle", largeur=70),
        Colonne("Brut", largeur=28, alignement="right"),
        Colonne("Amort./Prov.", largeur=28, alignement="right"),
        Colonne("Net", largeur=28, alignement="right"),
    ]
    lignes: list[list[str]] = []
    for index in range(1, nb_lignes + 1):
        brut = Decimal("1000.00") * index
        amort = (brut * Decimal("0.25")).quantize(Decimal("0.01"))
        lignes.append(
            [
                f"23{index:02d}",
                f"Immobilisation corporelle numero {index} (libelle de controle)",
                f"{brut:,.2f}".replace(",", " "),
                f"{amort:,.2f}".replace(",", " "),
                f"{brut - amort:,.2f}".replace(",", " "),
            ]
        )
    total = [
        "TOTAL",
        f"{nb_lignes} comptes",
        f"{Decimal('1000.00') * nb_lignes:,.2f}".replace(",", " "),
        "—",
        "—",
    ]
    return Document(
        titre="Bilan — exercice 2026 (POC moteur PDF)",
        sous_titre="Compta MA — document de test, non contractuel",
        entete=[
            "Societe Demo — IF 1234567 — ICE 001234567000099 — RC 11111",
            "Etats de synthese (CGNC) — presentation provisoire",
        ],
        tableaux=[
            Tableau(
                titre="ACTIF IMMOBILISE (brut / amortissements / net)",
                colonnes=colonnes,
                lignes=lignes,
                total=total,
            )
        ],
        pied="Document de travail — filigrane BROUILLON (POC J0)",
        filigrane="BROUILLON",
    )


def main() -> int:
    """Execute le POC et affiche le verdict."""
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--lignes", type=int, default=120, help="nombre de lignes du bilan")
    args = parseur.parse_args()

    print("=== POC moteur PDF (decision D1) ===")
    try:
        print(f"ReportLab   : {moteur_disponible()}")
    except Exception as exc:  # noqa: BLE001
        print(f"ReportLab   : INDISPONIBLE ({exc})")
    print(f"WeasyPrint  : {diagnostic_weasyprint()}")

    document = document_bilan(args.lignes)
    debut = time.perf_counter()
    try:
        pdf = rendre_pdf(document)
    except PdfError as exc:
        print(f"\nECHEC du rendu : {exc}")
        return 1
    duree = time.perf_counter() - debut

    print(f"\n--- Rendu ReportLab ({args.lignes} lignes) ---")
    print(f"temps            : {duree:.3f} s")
    print(f"taille           : {len(pdf):,} octets ({len(pdf) / 1024:.1f} Ko)")
    print(f"limite greffe    : {TAILLE_MAX_GREFFE:,} octets (10 Mo) -> "
          f"{'CONFORME' if len(pdf) <= TAILLE_MAX_GREFFE else 'DEPASSEMENT'}")

    # Controle de taille : un document volontairement trop volumineux doit etre refuse.
    try:
        controle_taille_pdf(pdf, limite=1024)
    except PdfError as exc:
        print(f"controle taille  : OK (refus d'un PDF de {len(pdf)} octets > 1024)")

    sortie = Path(
        os.environ.get("TEMP", str(Path(__file__).resolve().parents[1]))
    ) / "compta_ma_poc"
    sortie.mkdir(parents=True, exist_ok=True)
    fichier = sortie / "poc_bilan.pdf"
    fichier.write_bytes(pdf)
    print(f"fichier temoin   : {fichier}")
    print(
        "\nVERDICT : ReportLab retenu (pur Python, sans dependance systeme). "
        "WeasyPrint ecarte : runtime GTK requis (libgobject-2.0-0)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
