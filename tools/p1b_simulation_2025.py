"""P1-b : simulation (LECTURE SEULE) de la regularisation de la paie 2025.

Aucune ecriture : ce script mesure l'etat actuel de 2025, verifie la
**faisabilite** de la sequence de reouverture (bareme de paie 2025, taux d'IS
2025) et **projette** l'impact chiffre pour validation avant toute modification.

Usage :
    .\\.venv\\Scripts\\python.exe tools\\p1b_simulation_2025.py
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from sqlalchemy import func, select  # noqa: E402

from app.core.rates_ma import (  # noqa: E402
    BAREMES_PAIE,
    COTISATION_MINIMALE_BY_YEAR,
    IS_RATES_BY_YEAR,
    is_rates,
    money,
)
from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, Entry, EntryLine  # noqa: E402
from app.services.closing import apercu_reouverture, controle_a_nouveaux  # noqa: E402
from app.services.fiscal_liasse import exoneration_cotisation_minimale  # noqa: E402
from app.services.reporting import income_statement  # noqa: E402

SORTIE: list[str] = []


def bloc(texte: str = "") -> None:
    SORTIE.append(texte)


def titre(texte: str) -> None:
    bloc()
    bloc(f"## {texte}")
    bloc()


def _ecritures_paie(db, company_id: int, annee: int) -> list[dict]:
    lignes = db.execute(
        select(Entry.entry_number, Entry.entry_date, Entry.reference, Entry.source)
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .where(
            Entry.company_id == company_id,
            Entry.entry_date >= date(annee, 1, 1),
            Entry.entry_date <= date(annee, 12, 31),
            EntryLine.account_number.like("617%"),
        )
        .order_by(Entry.entry_date)
        .distinct()
    ).all()
    return [
        {"numero": l[0], "date": l[1], "reference": l[2], "source": l[3]} for l in lignes
    ]


def _total_compte(db, company_id: int, annee: int, prefixe: str) -> Decimal:
    debit, credit = db.execute(
        select(func.sum(EntryLine.debit), func.sum(EntryLine.credit))
        .select_from(EntryLine)
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(
            Entry.company_id == company_id,
            Entry.entry_date >= date(annee, 1, 1),
            Entry.entry_date <= date(annee, 12, 31),
            EntryLine.account_number.like(f"{prefixe}%"),
        )
    ).one()
    return money(Decimal(str(debit or 0)) - Decimal(str(credit or 0)))


def main() -> int:
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        bloc("# P1-b — Simulation (lecture seule) de la régularisation de la paie 2025")
        bloc()
        bloc(
            "Généré par `tools/p1b_simulation_2025.py` : **aucune écriture n'est créée ni "
            "modifiée**. Les projections servent de base de validation avant la séquence "
            "réelle (réouverture → régularisation → reclôture → régénération des "
            "à-nouveaux 2026)."
        )

        titre("1. État actuel de l'exercice 2025 (référence)")
        ecritures = _ecritures_paie(db, company.id, 2025)
        charges = _total_compte(db, company.id, 2025, "617")
        cpc = income_statement(db, company.id, date(2025, 1, 1), date(2025, 12, 31))
        a_nouveaux = controle_a_nouveaux(db, company, 2026)
        apercu = apercu_reouverture(db, company, 2025)
        bloc(
            f"- Statut de l'exercice 2025 : **{apercu['statut']}** ; verrous de période : "
            f"{apercu['verrous'] or 'aucun'}"
        )
        bloc(
            f"- Écritures de charges de personnel 2025 hors module : **{len(ecritures)}** "
            f"(sources : {sorted({e['source'] for e in ecritures}) or ['-']})"
        )
        bloc(f"- Charges de personnel 2025 (617x) : **{charges:,.2f} DH**")
        bloc(
            f"- Résultat comptable 2025 : **{cpc['resultat']:,.2f} DH** "
            f"({cpc['nature_resultat']})"
        )
        bloc(
            f"- À-nouveaux 2026 : écriture {a_nouveaux['entry_number']} — débit "
            f"{a_nouveaux['total_debit']:,.2f} DH, {a_nouveaux['nb_lignes']} lignes, "
            f"équilibre {a_nouveaux['equilibre']}"
        )
        exoneration = exoneration_cotisation_minimale(db, company, 2025)
        bloc(
            f"- Exonération de cotisation minimale 2025 : {exoneration['exoneree']} "
            f"({exoneration['mois_activite']} mois d'activité depuis "
            f"{exoneration['date_debut_activite']}, fin d'exonération "
            f"{exoneration['fin_exoneration']})"
        )

        titre("2. Faisabilité de la séquence (pré-requis)")
        prerequis = [
            (
                "Barème de paie 2025 (`BAREMES_PAIE`)",
                2025 in BAREMES_PAIE,
                "sans le barème officiel 2025 (IR/CNSS/AMO), la paie 2025 ne peut pas être "
                "**régénérée par le module** (`app/core/rates_ma.py`)",
            ),
            (
                "Taux d'IS 2025 (`IS_RATES_BY_YEAR`)",
                2025 in IS_RATES_BY_YEAR,
                "le recalcul fiscal 2025 exige le taux de l'exercice (loi de finances 2025) : "
                "aucun taux n'est deviné",
            ),
            (
                "Paramètres de cotisation minimale 2025",
                2025 in COTISATION_MINIMALE_BY_YEAR,
                "taux 0,25 %, plancher 3 000 DH et exonération : à confirmer pour 2025",
            ),
            (
                "Réouverture encadrée + régénération des à-nouveaux",
                True,
                "livré et testé en P1 (motif, verrous, comparaison avant/après)",
            ),
        ]
        bloc("| Pré-requis | État | Commentaire |")
        bloc("|---|---|---|")
        for libelle, etat, commentaire in prerequis:
            bloc(f"| {libelle} | {'**OK**' if etat else '**À FOURNIR**'} | {commentaire} |")

        titre("3. Impact projeté (illustration — barème 2026 faute de barème 2025)")
        # Projection : remplacer les 12 écritures synthetiques de 2025 par 12 paies du
        # module. Le cout mensuel est celui constate par le module en 2026 : il sert
        # uniquement d'**illustration** tant que le barème 2025 n'est pas fourni.
        charge_module = Decimal("30495.60")
        charges_projetees = money(charge_module * 12)
        ecart_charges = money(charges_projetees - charges)
        resultat_projete = money(cpc["resultat"] - ecart_charges)
        bloc(
            f"- Charges de personnel 2025 : {charges:,.2f} → **{charges_projetees:,.2f} DH** "
            f"({ecart_charges:+,.2f} DH)"
        )
        bloc(
            f"- Résultat 2025 : {cpc['resultat']:,.2f} → **{resultat_projete:,.2f} DH** "
            f"({'perte' if resultat_projete < 0 else 'benefice'})"
        )
        try:
            taux = is_rates(2025)
            bloc(f"- Taux d'IS 2025 : {taux['standard']}")
        except ValueError as exc:
            bloc(f"- IS 2025 : **calcul refusé** — {exc}")
        bloc(
            f"- À-nouveaux 2026 : report à nouveau ajusté de {ecart_charges:+,.2f} DH "
            f"(total actuel {a_nouveaux['total_debit']:,.2f} DH) — comparaison avant/après "
            "restituée par `closing.regenerer_a_nouveaux`"
        )
        bloc(
            "- Impact 2026 : recalcul intégral (Balance → CPC → ESG → Bilan → ETIC → IS) sur "
            "les nouveaux à-nouveaux, sans correction manuelle."
        )

        titre("4. Séquence proposée (à valider avant exécution)")
        bloc("1. Fournir le **barème de paie 2025** et le **taux d'IS 2025** (paramétrage).")
        bloc("2. `reouvrir_exercice(2025, motif=…, regenerer_a_nouveaux=True)` — opération tracée.")
        bloc(
            "3. Retirer les 12 écritures de paie synthétiques 2025 (réinitialisation "
            "contrôlée et tracée) puis générer les **12 paies 2025 par le module**."
        )
        bloc(
            "4. `cloturer_exercice(2025)` puis `regenerer_a_nouveaux(2025)` : écarts par "
            "compte restitués pour validation."
        )
        bloc(
            "5. Recalcul complet 2026 et contrôle de l'équilibre des à-nouveaux avant "
            "validation définitive."
        )
        bloc()
        bloc(
            "**Tant que les étapes 1 à 5 ne sont pas validées, aucune écriture 2025 n'est "
            "touchée** (exigence du donneur d'ordre)."
        )
    finally:
        db.close()
    texte = "\n".join(SORTIE)
    (BASE / "P1B_SIMULATION_2025.md").write_text(texte + "\n", encoding="utf-8")
    print(texte)
    print(f"\n>>> Ecrit : {BASE / 'P1B_SIMULATION_2025.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
