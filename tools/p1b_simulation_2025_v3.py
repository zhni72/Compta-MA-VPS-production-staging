"""P1B v3 — simulation **lecture seule** de l'exercice 2025 (referentiels 2025).

Objectif : chiffrer l'impact des **referentiels 2025** (IR, IS, cotisation
minimale) sur l'exercice 2025 **sans modifier aucune ecriture comptable**.

Principes :
- les taux viennent de `app/core/rates_ma.py` (`BAREMES_PAIE[2025]`,
  `IS_RATES_BY_YEAR[2025]`, `COTISATION_MINIMALE_BY_YEAR[2025]`) : **aucun taux
  n'est saisi en dur dans l'outil** ;
- les parametres 2025 **non documentes** (frais professionnels, CNSS/AMO,
  prestations familiales, TFP) ne sont **jamais devines** : ils sont listes et
  excluent tout calcul qui en depend (cout employeur) ;
- l'outil verifie que l'empreinte SHA-256 de la base est **identique** avant et
  apres execution et qu'aucune ecriture n'a ete creee.

Usage :
    python tools/p1b_simulation_2025_v3.py            # simulation + livrable
    python tools/p1b_simulation_2025_v3.py --detail   # ajoute les soldes de comptes
"""

from __future__ import annotations

import hashlib
import sys
from decimal import Decimal
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from sqlalchemy import func, select  # noqa: E402

from app.core import rates_ma  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, Entry, EntryLine  # noqa: E402
from app.services.etats_synthese import etat_soldes_gestion  # noqa: E402
from app.services.reporting import year_bounds  # noqa: E402

BASE = RACINE / "compta_ma.db"
LIVRABLE = RACINE / "P1B_SIMULATION_2025_V3_CORRIGEE.md"
EXERCICE = 2025

# Comptes suivis pour la confrontation theorique / comptabilise.
COMPTES_IS_CHARGES = ("6701", "6703", "6705")
COMPTES_IS_DETTE = ("4453", "3453")
COMPTES_IR = ("4452", "4441", "4443", "4445")
SEUIL_BNF_2025 = rates_ma.IS_SMALL_PROFIT_THRESHOLD_2025


def empreinte_base() -> str:
    return hashlib.sha256(BASE.read_bytes()).hexdigest()


def _solde(db, company_id: int, compte: str) -> Decimal:
    """Solde debit - credit d'un compte pour l'exercice (credit positif = dette)."""
    debut, fin = year_bounds(EXERCICE)
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
    return rates_ma.money(total)


def _nb_ecritures(db, company_id: int) -> int:
    return db.execute(
        select(func.count(Entry.id)).where(Entry.company_id == company_id)
    ).scalar_one()


def _chiffres_2025(db, company: Company) -> dict:
    """Chiffres de gestion 2025 (services de l'application, aucune saisie)."""
    debut, fin = year_bounds(EXERCICE)
    esg = etat_soldes_gestion(db, company.id, debut, fin)
    familles: dict[str, Decimal] = esg["familles"]

    def somme(*racines: str) -> Decimal:
        return rates_ma.money(
            sum(
                (
                    valeur
                    for famille, valeur in familles.items()
                    if famille.startswith(racines)
                ),
                Decimal("0"),
            )
        )

    return {
        "resultat_net": esg["resultat_net"],
        "chiffre_affaires": somme("711", "712", "713", "714", "716", "718", "719"),
        "tva_collectee": abs(_solde(db, company.id, "4455")),
        # Charge d'IS comptabilisee (67x) : reintegree une seule fois par le moteur.
        "is_comptabilise": sum(
            (abs(_solde(db, company.id, compte)) for compte in COMPTES_IS_CHARGES),
            Decimal("0"),
        ),
        # Dette d'impot portee au passif (4453/3453) : meme montant, presente a part.
        "dette_is": sum(
            (abs(_solde(db, company.id, compte)) for compte in COMPTES_IS_DETTE),
            Decimal("0"),
        ),
        "ir_comptabilise": sum(
            (abs(_solde(db, company.id, compte)) for compte in COMPTES_IR), Decimal("0")
        ),
    }


def _total_bilan_2025(db, company: Company) -> Decimal:
    """Total du bilan **net** 2025 (bilan CGNC : brut - amortissements et provisions)."""
    from app.services.etats_synthese import bilan_normal

    return bilan_normal(db, company.id, *year_bounds(EXERCICE))["actif_net"]


def _paie_2025(db, company_id: int) -> dict:
    """Paie 2025 disponible : periodes, bulletins et net imposable cumule.

    Aucune donnee n'est inventee : si aucune paie 2025 n'existe, l'outil le dit
    et ne calcule aucun IR.
    """
    from app.models.payroll import Payslip  # import local (module optionnel)

    bulletins = list(
        db.scalars(
            select(Payslip).where(
                Payslip.company_id == company_id,
                Payslip.periode.like(f"{EXERCICE}-%"),
            )
        )
    )
    net_imposable = rates_ma.money(
        sum((Decimal(str(b.net_imposable or 0)) for b in bulletins), Decimal("0"))
    )
    return {
        "periodes": sorted({bulletin.periode for bulletin in bulletins}),
        "nb_bulletins": len(bulletins),
        "net_imposable_cumule": net_imposable,
        "disponible": bool(bulletins),
        "bulletins": bulletins,
    }


def _fiscal_2025(db, company: Company, chiffres: dict) -> dict:
    """IS 2025 par le **moteur fiscal de l'application** (CGI art. 11 et 144).

    Demarche (aucune ecriture creee) :
    1. **resultat comptable avant impot** = resultat comptable + impots sur les
       resultats comptabilises (67x) : l'IS et la cotisation minimale ne sont
       **pas deductibles** (CGI art. 11), donc re-integres une seule fois ;
    2. **reintegrations / deductions** complementaires du catalogue (CGI art. 11) ;
    3. **resultat fiscal** puis **IS au taux de l'exercice 2025** (`IS_RATES_BY_YEAR`) ;
    4. **cotisation minimale** : taux et plancher affiches a part ; exigibilite
       determinee par `fiscal_liasse.exoneration_cotisation_minimale` (36 premiers
       mois d'activite depuis les **dates reelles** de la societe).
    """
    from app.services import fiscal_liasse

    calcul = fiscal_liasse.calculer_is(db, company, EXERCICE)
    exo = fiscal_liasse.exoneration_cotisation_minimale(db, company, EXERCICE)
    parametres_cm = rates_ma.COTISATION_MINIMALE_BY_YEAR[EXERCICE]
    base_cm = chiffres["chiffre_affaires"] + chiffres["tva_collectee"]
    cm_theorique = max(
        rates_ma.money(base_cm * parametres_cm["rate"]),  # type: ignore[operator]
        Decimal(str(parametres_cm["minimum"])),
    )
    impot_du = calcul["impot_du"]
    return {
        "calcul": calcul,
        "resultat_comptable": calcul["resultat_comptable"],
        "impots_comptabilises": calcul["impots_resultats_comptabilises"],
        "resultat_avant_impot": calcul["resultat_avant_impot"],
        "reintegrations": calcul["detail_reintegrations"],
        "total_reintegrations": calcul["total_reintegrations"],
        "deductions": calcul["detail_deductions"],
        "total_deductions": calcul["total_deductions"],
        "resultat_fiscal": calcul["resultat_fiscal"],
        "taux": rates_ma.IS_RATES_BY_YEAR[EXERCICE]["small_profit"]
        if 0 < calcul["resultat_fiscal"] <= SEUIL_BNF_2025
        else rates_ma.IS_RATES_BY_YEAR[EXERCICE]["standard"],
        "is": calcul["is_theorique"],
        "cm_theorique": cm_theorique,
        "cm_parametres": parametres_cm,
        "cm_base": base_cm,
        "exoneration": exo,
        "cm_exigible": calcul["cotisation_minimale"] if not exo["exoneree"] else Decimal("0"),
        "impot_du": impot_du,
        "acomptes": calcul["acomptes_verses"],
        "credits": calcul["credits_impot"],
        "solde": calcul["solde_a_payer"],
        "ecart_is": rates_ma.money(chiffres["is_comptabilise"] - impot_du),
        "resultat_net_corrige": rates_ma.money(
            calcul["resultat_avant_impot"] - impot_du
        ),
        "resultat_net_comptabilise": chiffres["resultat_net"],
    }


def _ir_2025(theorique: dict | None, comptabilise: Decimal) -> dict:
    """IR 2025 recalcule **bulletin par bulletin** avec le bareme 2025."""
    if not theorique or not theorique["disponible"]:
        return {"calcule": False, "motif": "aucune donnee de paie 2025"}
    total = Decimal("0")
    detail: list[tuple[str, Decimal, int, Decimal]] = []
    for bulletin in theorique["bulletins"]:
        net = Decimal(str(bulletin.net_imposable or 0))
        personnes = int(bulletin.personnes_a_charge or 0)
        if net <= 0:
            continue
        ir = rates_ma.compute_ir_monthly(net, personnes, EXERCICE)
        total += ir
        detail.append((bulletin.periode, net, personnes, ir))
    total = rates_ma.money(total)
    return {
        "calcule": True,
        "nb_bulletins": len(detail),
        "ir_recalcule": total,
        "ir_comptabilise": comptabilise,
        "ecart": rates_ma.money(total - comptabilise),
        "detail": detail,
    }



def _montant(valeur: object) -> str:
    rendu = f"{Decimal(str(valeur or 0)):,.2f}"
    return rendu.replace(",", " ").replace(".", ",")


def _taux(valeur: object) -> str:
    """Taux en pourcentage lisible (« 17,50 % »)."""
    rendu = f"{Decimal(str(valeur or 0)) * 100:,.2f}"
    return rendu.replace(",", " ").replace(".", ",") + " %"


def _rapport(contexte: dict) -> str:
    """Livrable `P1B_SIMULATION_2025_V3_CORRIGEE.md` (lecture seule).

    Demarche fiscale demandee : resultat comptable -> reintegrations -> deductions
    -> resultat fiscal -> IS au taux de l'exercice -> cotisation minimale
    (exigibilite selon les dates reelles) -> impot du -> resultat net corrige ->
    impact sur les a-nouveaux 2026.
    """
    chiffres = contexte["chiffres"]
    fiscal = contexte["fiscal"]
    ir = contexte["ir"]
    exo = fiscal["exoneration"]
    manquants = contexte["manquants"]
    lignes = [
        "# P1B v3 CORRIGEE — IS 2025 par la demarche fiscale (lecture seule)",
        "",
        f"**Societe** : {contexte['company'].name}  ·  **Exercice** : {EXERCICE}  ·  "
        f"**Ecritures** : {contexte['nb_ecritures']}",
        f"**Base inchangee pendant l'execution** : {contexte['base_identique']} "
        f"(SHA-256 {contexte['empreinte_avant'][:16]}…) — aucune ecriture modifiee.",
        "",
        "## 1. Resultat comptable -> resultat fiscal -> IS 2025",
        "",
        "| Etape | Montant |",
        "|---|---|",
        f"| Resultat net **comptabilise** (apres IS) | "
        f"{_montant(fiscal['resultat_comptable'])} DH |",
        f"| + Reintegration de l'IS comptabilise (**non deductible**, CGI art. 11) | "
        f"{_montant(fiscal['impots_comptabilises'])} DH |",
        f"| = **Resultat comptable avant IS** | "
        f"**{_montant(fiscal['resultat_avant_impot'])} DH** |",
    ]
    if fiscal["total_reintegrations"]:
        for ligne in fiscal["reintegrations"]:
            lignes.append(
                f"| + Reintegration : {ligne['libelle']} ({ligne['reference']}) | "
                f"{_montant(ligne['montant'])} DH |"
            )
    else:
        lignes.append("| + Autres reintegrations (catalogue CGI art. 11) | 0,00 DH |")
    if fiscal["total_deductions"]:
        for ligne in fiscal["deductions"]:
            lignes.append(
                f"| - Deduction : {ligne['libelle']} ({ligne['reference']}) | "
                f"{_montant(ligne['montant'])} DH |"
            )
    else:
        lignes.append("| - Deductions fiscales | 0,00 DH (aucune identifiee) |")
    lignes += [
        f"| **Resultat fiscal (BNF) 2025** | **{_montant(fiscal['resultat_fiscal'])} DH** |",
        f"| Taux IS applicable (exercice 2025) | **{_taux(fiscal['taux'])}** "
        f"(BNF <= 300 000 DH : grille transitoire 2025) |",
        f"| **IS 2025 calcule** | **{_montant(fiscal['is'])} DH** |",
        f"| IS comptabilise (compte 6701) | {_montant(chiffres['is_comptabilise'])} DH |",
        f"| **Ecart (IS comptabilise - IS calcule)** | "
        f"**{_montant(fiscal['ecart_is'])} DH** |",
        "",
        "## 2. Cotisation minimale 2025 et exoneration",
        "",
        "| Element | Valeur |",
        "|---|---|",
        f"| Taux theorique | {_taux(fiscal['cm_parametres']['rate'])} du CA TTC |",
        f"| Plancher theorique | {_montant(fiscal['cm_parametres']['minimum'])} DH |",
        f"| Base (CA TTC : CA HT + TVA collectee) | {_montant(fiscal['cm_base'])} DH |",
        f"| **CM theorique** (avant exoneration) | {_montant(fiscal['cm_theorique'])} DH |",
        f"| Debut d'exploitation retenu | {exo['date_debut_activite']} (fiche societe) |",
        f"| Duree d'exoneration legale | {exo['duree_exoneration_mois']} mois |",
        f"| Fin d'exoneration | {exo['fin_exoneration']} |",
        f"| Mois d'activite de l'exercice | {exo['mois_activite']} |",
        f"| **Cotisation minimale exigible 2025** | "
        + (
            "**NON (0,00 DH)**"
            if exo["exoneree"]
            else f"**{_montant(fiscal['cm_exigible'])} DH**"
        )
        + " |",
        f"| Justification | "
        + (
            f"societe en activite depuis le {exo['date_debut_activite']} : les 36 premiers "
            f"mois couvrent l'exercice {EXERCICE} (jusqu'au {exo['fin_exoneration']}) — "
            "cotisation minimale **non exigible** ; les 3 000 DH de plancher ne constituent "
            "**pas** une dette fiscale."
            if exo["exoneree"]
            else "exoneration terminee : cotisation minimale exigible."
        )
        + " |",
        "",
        "## 3. Impot finalement du et resultat net corrige",
        "",
        "| Element | Montant |",
        "|---|---|",
        f"| IS calcule | {_montant(fiscal['is'])} DH |",
        f"| Cotisation minimale exigible | {_montant(fiscal['cm_exigible'])} DH |",
        f"| **Impot finalement du 2025** | **{_montant(fiscal['impot_du'])} DH** |",
        f"| Acomptes verses (3453) | {_montant(fiscal['acomptes'])} DH |",
        f"| Credits d'impot | {_montant(fiscal['credits'])} DH |",
        f"| Solde a payer | {_montant(fiscal['solde'])} DH |",
        f"| **Resultat net corrige 2025** (resultat avant IS - IS du) | "
        f"**{_montant(fiscal['resultat_net_corrige'])} DH** |",
        f"| Resultat net comptabilise | {_montant(fiscal['resultat_net_comptabilise'])} DH |",
        "",
        "## 4. Impact projete sur les a-nouveaux 2026 (simulation)",
        "",
        "| Poste | Situation actuelle | Apres correction | Ecart |",
        "|---|---|---|---|",
        f"| Report a nouveau (resultat 2025) | "
        f"{_montant(fiscal['resultat_net_comptabilise'])} DH | "
        f"{_montant(fiscal['resultat_net_corrige'])} DH | "
        f"+{_montant(fiscal['ecart_is'])} DH |",
        f"| Dette d'IS (6701 / 4453) | {_montant(chiffres['is_comptabilise'])} DH | "
        f"{_montant(fiscal['impot_du'])} DH | -{_montant(fiscal['ecart_is'])} DH |",
        f"| Total du bilan net 2025 | {_montant(contexte['total_bilan'])} DH | "
        f"{_montant(contexte['total_bilan'])} DH | 0,00 DH (equilibre conserve) |",
        "",
        f"> Correction **strictement interne** : baisse de la charge d'IS "
        f"({_montant(fiscal['ecart_is'])} DH) et de la dette d'impot du meme montant ; le "
        "total du bilan reste inchange. **Aucune ecriture n'a ete passee** (simulation).",
        "",
        "## 5. Paie / IR 2025 — blocage maintenu",
        "",
    ]
    if manquants:
        for manquant in manquants:
            lignes.append(f"- {manquant}")
        lignes.append("")
        lignes.append(
            "> Les parametres sociaux et de frais professionnels 2025 n'etant pas "
            "documentes, **aucune paie 2025 n'est calculee** (le moteur refuse : "
            "`BaremeIndisponible`) et l'IR 2025 reste **non chiffre** — aucun taux devine."
        )
    else:
        lignes.append("- aucun")
    if ir["calcule"]:
        lignes.append(
            f"- IR 2025 recalcule : {_montant(ir['ir_recalcule'])} DH (comptabilise "
            f"{_montant(ir['ir_comptabilise'])}, ecart {_montant(ir['ecart'])})"
        )
    else:
        lignes.append(f"- IR 2025 : {ir['motif']}")
    lignes += [
        "",
        "## 6. References et statut",
        "",
        "| Element | Valeur | Source |",
        "|---|---|---|",
    ]
    for entree in rates_ma.sources_referentiel(EXERCICE):
        lignes.append(
            f"| {entree['element']} | {entree['valeur']} | {entree['source']} "
            f"({entree['statut']}) |"
        )
    lignes += [
        "",
        "## 7. Conclusion",
        "",
        f"- **IS 2025** : base fiscale {_montant(fiscal['resultat_fiscal'])} DH x "
        f"{fiscal['taux']} = **{_montant(fiscal['is'])} DH** ; cotisation minimale "
        + (
            "**non exigible (exoneration des 36 premiers mois)**"
            if exo["exoneree"]
            else "**exigible**"
        )
        + f" ; impot du **{_montant(fiscal['impot_du'])} DH** ; ecart de "
        f"**{_montant(fiscal['ecart_is'])} DH** avec l'IS comptabilise.",
        f"- **Resultat net corrige 2025** : **{_montant(fiscal['resultat_net_corrige'])} DH** "
        "(avant toute regularisation de paie).",
        f"- **Simulation uniquement** : exercice 2025 inchange (SHA-256 de la base identique, "
        f"{contexte['nb_ecritures']} ecritures avant et apres).",
        "- **P1B etape 3 non lancee** : elle suppose la validation humaine de la presente "
        "simulation corrigee (et, pour l'IR, la documentation des parametres de paie 2025).",
        "",
    ]
    return "\n".join(lignes)


def main() -> int:
    detail = "--detail" in sys.argv
    avant = empreinte_base()
    db = SessionLocal()
    try:
        company = db.scalars(select(Company).order_by(Company.id)).first()
        if company is None:
            print("Aucune societe en base : rien a simuler.")
            return 1
        nb_avant = _nb_ecritures(db, company.id)
        chiffres = _chiffres_2025(db, company)
        fiscal = _fiscal_2025(db, company, chiffres)
        paie = _paie_2025(db, company.id)
        ir = _ir_2025(paie, chiffres["ir_comptabilise"])
        manquants = rates_ma.parametres_paie_manquants(EXERCICE)

        print(f"P1B v3 — simulation {EXERCICE} (lecture seule) — {company.name}")
        print(f"  referentiel 2025 complet : {rates_ma.referentiel_complet(EXERCICE)}")
        print(f"  parametres 2025 non figes : {manquants or 'aucun'}")
        print(
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
        )
        if ir["calcule"]:
            print(
                f"  IR {EXERCICE} recalcule : {ir['ir_recalcule']} (comptabilise "
                f"{ir['ir_comptabilise']}, ecart {ir['ecart']})"
            )
        else:
            print(f"  IR {EXERCICE} : {ir['motif']}")
        if detail:
            for compte in COMPTES_IS_CHARGES + COMPTES_IS_DETTE + COMPTES_IR:
                print(f"    compte {compte} : {_solde(db, company.id, compte)}")

        nb_apres = _nb_ecritures(db, company.id)
        apres = empreinte_base()
        contexte = {
            "company": company,
            "chiffres": chiffres,
            "fiscal": fiscal,
            "total_bilan": _total_bilan_2025(db, company),
            "ir": ir,
            "manquants": manquants,
            "nb_ecritures": nb_apres,
            "base_identique": avant == apres and nb_avant == nb_apres,
            "empreinte_avant": avant,
        }
        LIVRABLE.write_text(_rapport(contexte) + "\n", encoding="utf-8")
        print(
            f"\n  ecritures avant/apres : {nb_avant}/{nb_apres} ; base identique : "
            f"{avant == apres}"
        )
        print(f"  livrable ecrit : {LIVRABLE}")
        return 0 if (avant == apres and nb_avant == nb_apres) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

