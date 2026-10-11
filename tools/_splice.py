"""Splice ponctuel : remplace `_rapport` par la version corrigee (IS fiscal)."""

from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent
CIBLE = RACINE / "p1b_simulation_2025_v3.py"
NOUVEAU = RACINE / "_nouveau_rapport.txt"

source = CIBLE.read_text(encoding="utf-8")
nouveau = NOUVEAU.read_text(encoding="utf-8").rstrip("\n")

motif = re.compile(r"def _rapport\(contexte: dict\) -> str:.*?\n    return \"\\n\"\.join\(lignes\)\n", re.S)
resultat, nombre = motif.subn(nouveau + "\n", source, count=1)
if nombre != 1:
    raise SystemExit(f"Motif _rapport introuvable (remplacements : {nombre})")

# main : utilise le moteur fiscal corrige et ecrit le livrable corrige.
resultat = resultat.replace(
    "LIVRABLE = RACINE / \"P1B_SIMULATION_2025_V3.md\"",
    "LIVRABLE = RACINE / \"P1B_SIMULATION_2025_V3_CORRIGEE.md\"",
)
resultat = resultat.replace(
    """        is_theorique = _is_theorique_2025(chiffres["resultat_net"])
        cm = _cotisation_minimale_2025(
            chiffres["chiffre_affaires"], chiffres["tva_collectee"]
        )
        paie = _paie_2025(db, company.id)""",
    """        fiscal = _fiscal_2025(db, company, chiffres)
        paie = _paie_2025(db, company.id)""",
)
resultat = resultat.replace(
    """        print(
            f"  resultat net : {chiffres['resultat_net']} ; IS theorique "
            f"{is_theorique['is']} (taux {is_theorique['taux']}) ; cotisation minimale "
            f"{cm['due']} ; IS du {max(is_theorique['is'], cm['due'])}"
        )""",
    """        print(
            f"  resultat comptable avant IS : {fiscal['resultat_avant_impot']} ; "
            f"reintegrations : {fiscal['total_reintegrations']} ; resultat fiscal : "
            f"{fiscal['resultat_fiscal']}"
        )
        print(
            f"  IS 2025 : {fiscal['is']} (taux {fiscal['taux']}) ; CM theorique "
            f"{fiscal['cm_theorique']} ; CM exigible {fiscal['cm_exigible']} "
            f"(exoneration : {fiscal['exoneration']['exoneree']}) ; IS/CM comptabilise "
            f"{chiffres['is_comptabilise']} ; ecart {fiscal['ecart_is']}"
        )
        print(
            f"  impot du : {fiscal['impot_du']} ; resultat net corrige : "
            f"{fiscal['resultat_net_corrige']}"
        )""",
)
resultat = resultat.replace(
    """            "chiffres": chiffres,
            "is": is_theorique,
            "cm": cm,
            "ir": ir,""",
    """            "chiffres": chiffres,
            "fiscal": fiscal,
            "total_bilan": _total_bilan_2025(db, company),
            "ir": ir,""",
)
CIBLE.write_text(resultat, encoding="utf-8")
print("Splice effectue : _rapport corrige, main adapte.")
