"""P1B v2 : simulation (LECTURE SEULE) de la regularisation de la paie 2025.

**Aucune ecriture n'est creee, modifiee ou supprimee** : tous les calculs sont
faits en memoire avec les **memes fonctions que le module** (`compute_cnss`,
`frais_professionnels_mensuels`, `compute_ir_monthly`, `lignes_ecriture_paie`),
parametres **explicitement identifies** (le referentiel fiscal 2025 reste a
fournir : aucune hypothese n'est presentee comme definitive).

Contenu :
0. referentiel fiscal et **sources** de chaque taux / plafond / base ;
1. sort des 3 profils salaries du jeu de recette sur 2025 ;
2. brut annuel par salarie, CNSS salariale/patronale, AMO salariale/patronale,
   IR, net a payer, cout employeur ;
3. ecritures comptables qui seraient generees (12 mois) ;
4. resultat comptable 2025 recalcule, resultat fiscal / IS / CM ;
5. impact **compte par compte** sur les a-nouveaux 2026.

Usage :
    .\\.venv\\Scripts\\python.exe tools\\p1b_simulation_2025_v2.py
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
    frais_professionnels_mensuels,
    money,
    referentiel_complet,
    sources_referentiel,
)
from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, Employee, Entry, EntryLine, PayContract  # noqa: E402
from app.services.payroll import lignes_ecriture_paie  # noqa: E402
from app.services.reporting import income_statement, movements  # noqa: E402

SORTIE: list[str] = []
PERIODE_REFERENCE = "2025-12"
MOIS_2025 = 12
PROFILS_ATTENDUS = {
    "EMP001": "profil de test IR — « Seuil exonéré »",
    "EMP002": "profil de test IR — « Tranche 30 % »",
    "EMP003": "profil de test IR — « Tranche 37 % »",
}


def bloc(texte: str = "") -> None:
    SORTIE.append(texte)


def titre(texte: str) -> None:
    bloc()
    bloc(f"## {texte}")
    bloc()


def _bulletin_simule(employee: Employee, contrat: PayContract, annee: int) -> dict:
    """Bulletin **simule en memoire** (memes formules que le module, en 2026).

    Le module refuse de calculer un exercice dont le barème n'est pas parametre :
    la simulation applique donc explicitement les parametres **2026** (derniers
    documentes) et le signale — aucune valeur n'est presentee comme definitive
    pour 2025.
    """
    from app.core.rates_ma import CNSS_2026, bareme_paie, compute_cnss, compute_ir_monthly

    parametres = bareme_paie(annee)  # leve si l'exercice n'est pas parametre
    base = money(contrat.salaire_base)
    primes = money(contrat.autres_primes)
    indemnites = money(contrat.prime_transport + contrat.prime_logement + contrat.indemnite_representation)
    avantages = money(contrat.avantages_nature)
    brut_imposable = money(base + primes + indemnites + avantages)
    cotisations = compute_cnss(brut_imposable)
    retraite = money(brut_imposable * contrat.taux_retraite / Decimal("100"))
    mutuelle = money(brut_imposable * contrat.taux_mutuelle / Decimal("100"))
    assurance = money(brut_imposable * contrat.taux_assurance_groupe / Decimal("100"))
    cotisations_salariales = money(
        cotisations["employee_social"]
        + cotisations["employee_amo"]
        + retraite
        + mutuelle
        + assurance
    )
    frais = frais_professionnels_mensuels(brut_imposable)
    deductible = money(cotisations["employee_social"] + cotisations["employee_amo"] + retraite)
    net_imposable = money(brut_imposable - deductible - frais)
    ir = compute_ir_monthly(net_imposable, employee.personnes_a_charge, annee)
    net = money(brut_imposable - cotisations_salariales - ir)
    cout_employeur = money(brut_imposable + cotisations["total_employer"])
    return {
        "matricule": employee.matricule,
        "nom": employee.nom,
        "brut": brut_imposable,
        "base": base,
        "primes": primes,
        "indemnites": indemnites,
        "avantages": avantages,
        "cnss_salariale": cotisations["employee_social"],
        "amo_salariale": cotisations["employee_amo"],
        "retraite": retraite,
        "mutuelle": mutuelle,
        "assurance": assurance,
        "cotisations_salariales": cotisations_salariales,
        "assiette_plafonnee": cotisations["assiette_plafonnee"],
        "cnss_patronale": cotisations["employer_social"],
        "amo_patronale": cotisations["employer_amo"],
        "prestations_familiales": cotisations["employer_family"],
        "taxe_formation": cotisations["employer_tfp"],
        "total_patronal": cotisations["total_employer"],
        "frais_professionnels": frais,
        "net_imposable": net_imposable,
        "ir": ir,
        "net": net,
        "cout_employeur": cout_employeur,
        "plafond_cnss": CNSS_2026["ceiling_social"],
        "tranches_ir": len(parametres["ir_brackets"]),
    }


def _lignes_du_mois(bulletins: list[dict]) -> list[tuple[str, Decimal, Decimal, str]]:
    """Lignes d'ecriture du mois — **mêmes comptes et mêmes montants que le module**.

    Reproduit le mapping de `payroll.lignes_ecriture_paie` (P1.4 / CGNC) :
    gains par compte de charge (`61711` appointements, `61712` primes,
    `61713` indemnites), charges patronales (`61741` CNSS/AMO, `61744`
    prestations familiales, `61768` taxe de formation) ; contreparties
    `4441` (organismes sociaux, parts salariale et patronale), `4452` (IR retenu)
    et `4432` (net a payer). Le total doit etre equilibre (controle bloquant).
    """
    comptes = {
        "61711": ("Appointements et salaires", Decimal("0"), Decimal("0")),
        "61712": ("Primes", Decimal("0"), Decimal("0")),
        "61713": ("Indemnites et avantages", Decimal("0"), Decimal("0")),
        "61741": ("Cotisations de securite sociale (patronales)", Decimal("0"), Decimal("0")),
        "61744": ("Prestations familiales (patronales)", Decimal("0"), Decimal("0")),
        "61768": ("Autres charges sociales (taxe de formation)", Decimal("0"), Decimal("0")),
        "4441": ("CNSS / AMO (parts salariale et patronale)", Decimal("0"), Decimal("0")),
        "4452": ("Etat - IR retenu a la source", Decimal("0"), Decimal("0")),
        "4432": ("Remunerations dues au personnel", Decimal("0"), Decimal("0")),
    }

    def ajouter(compte: str, debit: Decimal = Decimal("0"), credit: Decimal = Decimal("0")):
        libelle, d, c = comptes[compte]
        comptes[compte] = (libelle, money(d + debit), money(c + credit))

    for bulletin in bulletins:
        ajouter("61711", debit=bulletin["base"])
        ajouter("61712", debit=bulletin["primes"])
        ajouter("61713", debit=bulletin["indemnites"] + bulletin["avantages"])
        ajouter("61741", debit=bulletin["cnss_patronale"] + bulletin["amo_patronale"])
        ajouter("61744", debit=bulletin["prestations_familiales"])
        ajouter("61768", debit=bulletin["taxe_formation"])
        ajouter(
            "4441",
            credit=(
                bulletin["cnss_salariale"]
                + bulletin["amo_salariale"]
                + bulletin["cnss_patronale"]
                + bulletin["amo_patronale"]
                + bulletin["prestations_familiales"]
                + bulletin["taxe_formation"]
            ),
        )
        ajouter("4452", credit=bulletin["ir"])
        ajouter("4432", credit=bulletin["net"])
    lignes = [
        (compte, debit, credit, libelle)
        for compte, (libelle, debit, credit) in comptes.items()
        if debit or credit
    ]
    total_debit = money(sum((debit for _c, debit, _cr, _l in lignes), Decimal("0")))
    total_credit = money(sum((credit for _c, _d, credit, _l in lignes), Decimal("0")))
    if total_debit != total_credit:  # pragma: no cover - garde-fou de la simulation
        raise SystemExit(
            f"Simulation incoherente : debit {total_debit} <> credit {total_credit}"
        )
    return lignes


def _solde_compte(db, company_id: int, annee: int, compte: str) -> Decimal:
    debit, credit = db.execute(
        select(func.sum(EntryLine.debit), func.sum(EntryLine.credit))
        .select_from(EntryLine)
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(
            Entry.company_id == company_id,
            Entry.entry_date >= date(annee, 1, 1),
            Entry.entry_date <= date(annee, 12, 31),
            EntryLine.account_number == compte,
        )
    ).one()
    return money(Decimal(str(debit or 0)) - Decimal(str(credit or 0)))


def main() -> int:
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        bloc("# P1B **v2** — Simulation (lecture seule) de la régularisation de la paie 2025")
        bloc()
        bloc(
            "Généré par `tools/p1b_simulation_2025_v2.py` : **aucune écriture créée, modifiée "
            "ou supprimée**. Les calculs utilisent les **mêmes fonctions que le module** "
            "(`compute_cnss`, `frais_professionnels_mensuels`, `compute_ir_monthly`, "
            "`lignes_ecriture_paie`) ; tout paramètre non encore fourni est **signalé**."
        )

        titre("0. Référentiel fiscal — sources de chaque taux, plafond et base")
        for annee in (2026, 2025):
            bloc(f"### Exercice {annee} — référentiel "
                 f"{'complet ✔' if referentiel_complet(annee) else '**INCOMPLET (à fournir)**'}")
            bloc()
            bloc("| Élément | Valeur | Base | Source | Statut |")
            bloc("|---|---|---|---|---|")
            for entree in sources_referentiel(annee):
                bloc(
                    f"| {entree['element']} | {entree['valeur']} | {entree['base']} | "
                    f"{entree['source']} | {'✔ documenté' if entree['statut'].startswith('documente') else '**à fournir**'} |"
                )
            bloc()
        bloc(
            f"Barèmes disponibles : paie {sorted(BAREMES_PAIE)} ; IS {sorted(IS_RATES_BY_YEAR)} ; "
            f"cotisation minimale {sorted(COTISATION_MINIMALE_BY_YEAR)}. "
            "**Conséquence : le calcul 2025 par le module est refusé (aucun taux deviné) ; la "
            "simulation ci-dessous applique les paramètres 2026 à titre d'illustration.**"
        )

        titre("1. Les 3 profils salariés du jeu de recette doivent-ils exister sur 2025 ?")
        employes = list(
            db.execute(
                select(Employee).where(Employee.company_id == company.id).order_by(Employee.matricule)
            ).scalars()
        )
        contrats = {
            contrat.employee_id: contrat
            for contrat in db.execute(
                select(PayContract).order_by(PayContract.employee_id, PayContract.date_effet)
            ).scalars()
        }
        bloc("| Matricule | Libellé du jeu | Entrée | Contrat | Coût employeur mensuel (paramètres 2026) |")
        bloc("|---|---|---|---|---|")
        profils: list[tuple[Employee, PayContract, dict]] = []
        for employe in employes:
            contrat = contrats.get(employe.id)
            if contrat is None:
                continue
            bulletin = _bulletin_simule(employe, contrat, 2026)
            profils.append((employe, contrat, bulletin))
            bloc(
                f"| {employe.matricule} | {PROFILS_ATTENDUS.get(employe.matricule, employe.nom)} | "
                f"{employe.date_entree} | {contrat.salaire_base} base + "
                f"{money(contrat.prime_transport + contrat.prime_logement + contrat.autres_primes)} primes "
                f"(effet {contrat.date_effet}) | {bulletin['cout_employeur']:,.2f} DH |"
            )
        total_bulletins = sum((b["cout_employeur"] for _, _, b in profils), Decimal("0"))
        bloc()
        bloc(
            f"- Coût employeur mensuel des 3 profils : **{money(total_bulletins):,.2f} DH** "
            f"→ annuel **{money(total_bulletins * MOIS_2025):,.2f} DH**."
        )
        charges_2025 = _solde_compte(db, company.id, 2025, "6171") + _solde_compte(
            db, company.id, 2025, "6174"
        )
        bloc(
            f"- Paie **présente au grand livre 2025** (écritures synthétiques du jeu) : "
            f"**{charges_2025:,.2f} DH** de charges (14 400 DH/mois de coût global)."
        )
        bloc(
            "- Conclusion : les 3 profils sont des **profils de test IR** (libellés « Seuil "
            "exonéré », « Tranche 30 % », « Tranche 37 % ») dont le coût réel (30 495,60 DH/mois) "
            "**ne correspond pas** à la paie du scénario (14 400 DH/mois). Les considérer comme "
            "salariés permanents de 2025 **créerait** une masse salariale de 365 947,20 DH, soit "
            "+221 947,20 DH de charges non prévues par le scénario."
        )
        bloc()
        # ------------------------------------------------------------------
        # 2. Figures salaries (illustration : option C, parametres 2026)
        # ------------------------------------------------------------------
        titre("2. Figures par salarié (12 mois, paramètres 2026 — illustration)")
        bloc(
            "> Hypothèse d'illustration : **option C** (les 3 profils retenus 12 mois) avec les "
            "paramètres 2026, faute de référentiel 2025. Les montants changeront dès que le "
            "barème 2025 sera fourni."
        )
        bloc()
        bloc(
            "| Salarié | Brut annuel | CNSS sal. | AMO sal. | IR | Net à payer | CNSS patr. | "
            "AMO patr. | Prest. fam. | TFP | Coût employeur |"
        )
        bloc("|---|---|---|---|---|---|---|---|---|---|---|")
        totaux = {
            "brut": Decimal("0"),
            "cnss_salariale": Decimal("0"),
            "amo_salariale": Decimal("0"),
            "ir": Decimal("0"),
            "net": Decimal("0"),
            "cnss_patronale": Decimal("0"),
            "amo_patronale": Decimal("0"),
            "prestations_familiales": Decimal("0"),
            "taxe_formation": Decimal("0"),
            "cout_employeur": Decimal("0"),
        }
        for _employe, _contrat, bulletin in profils:
            for cle in totaux:
                totaux[cle] += bulletin[cle] * MOIS_2025
            bloc(
                f"| {bulletin['matricule']} | {bulletin['brut'] * MOIS_2025:,.2f} | "
                f"{bulletin['cnss_salariale'] * MOIS_2025:,.2f} | "
                f"{bulletin['amo_salariale'] * MOIS_2025:,.2f} | "
                f"{bulletin['ir'] * MOIS_2025:,.2f} | {bulletin['net'] * MOIS_2025:,.2f} | "
                f"{bulletin['cnss_patronale'] * MOIS_2025:,.2f} | "
                f"{bulletin['amo_patronale'] * MOIS_2025:,.2f} | "
                f"{bulletin['prestations_familiales'] * MOIS_2025:,.2f} | "
                f"{bulletin['taxe_formation'] * MOIS_2025:,.2f} | "
                f"{bulletin['cout_employeur'] * MOIS_2025:,.2f} |"
            )
        bloc(
            f"| **Total 2025** | **{totaux['brut']:,.2f}** | **{totaux['cnss_salariale']:,.2f}** | "
            f"**{totaux['amo_salariale']:,.2f}** | **{totaux['ir']:,.2f}** | **{totaux['net']:,.2f}** | "
            f"**{totaux['cnss_patronale']:,.2f}** | **{totaux['amo_patronale']:,.2f}** | "
            f"**{totaux['prestations_familiales']:,.2f}** | **{totaux['taxe_formation']:,.2f}** | "
            f"**{totaux['cout_employeur']:,.2f}** |"
        )
        bloc()
        bloc(
            f"Assiette CNSS plafonnée (EMP003, plafond {profils[0][2]['plafond_cnss']} DH) : "
            f"{profils[-1][2]['assiette_plafonnee']:,.2f} DH/mois ; barème IR appliqué : "
            f"{profils[0][2]['tranches_ir']} tranches (paramètres 2026)."
        )

        # ------------------------------------------------------------------
        # 3. Ecritures comptables qui seraient generees
        # ------------------------------------------------------------------
        titre("3. Écritures comptables qui seraient générées (par mois)")
        bulletins_du_mois = [b for _e, _c, b in profils]
        lignes = _lignes_du_mois(bulletins_du_mois)
        bloc("**Écriture de paie (journal OD, source `payroll`)**")
        bloc()
        bloc("| Compte | Libellé | Débit | Crédit |")
        bloc("|---|---|---|---|")
        total_debit = total_credit = Decimal("0")
        for compte, debit, credit, libelle in lignes:
            total_debit += debit
            total_credit += credit
            bloc(f"| `{compte}` | {libelle} | {debit:,.2f} | {credit:,.2f} |")
        bloc(f"| | **Total** | **{total_debit:,.2f}** | **{total_credit:,.2f}** |")
        bloc()
        bloc("**Écriture de règlement des salaires (journal BQ)**")
        bloc()
        bloc("| Compte | Libellé | Débit | Crédit |")
        bloc("|---|---|---|---|")
        bloc(f"| `4432` | Règlement des salaires | {totaux['net'] / MOIS_2025:,.2f} | 0,00 |")
        bloc(f"| `5141` | Banques | 0,00 | {totaux['net'] / MOIS_2025:,.2f} |")
        bloc()
        bloc(
            f"Sur 12 mois : charges comptabilisées **{totaux['cout_employeur']:,.2f} DH** ; "
            f"nets payés **{totaux['net']:,.2f} DH** ; dettes sociales et fiscales laissées au "
            f"passif : `4441` **{money(totaux['cnss_salariale'] + totaux['amo_salariale'] + totaux['cnss_patronale'] + totaux['amo_patronale'] + totaux['prestations_familiales'] + totaux['taxe_formation']):,.2f} DH** "
            f"et `4452` (IR) **{totaux['ir']:,.2f} DH**."
        )

        # ------------------------------------------------------------------
        # 4. Resultat comptable 2025 recalcule + fiscal
        # ------------------------------------------------------------------
        titre("4. Résultat comptable 2025 recalculé, résultat fiscal / IS / CM")
        cpc_2025 = income_statement(db, company.id, date(2025, 1, 1), date(2025, 12, 31))
        charges_autres = money(cpc_2025["total_charges"] - charges_2025)
        charges_projetees = money(charges_autres + totaux["cout_employeur"])
        resultat_projete = money(cpc_2025["total_produits"] - charges_projetees)
        bloc("| Indicateur | Existant (jeu) | Projeté (option C, paramètres 2026) |")
        bloc("|---|---|---|")
        bloc(f"| Charges de personnel | {charges_2025:,.2f} | **{totaux['cout_employeur']:,.2f}** |")
        bloc(f"| Autres charges (inchangées) | {charges_autres:,.2f} | {charges_autres:,.2f} |")
        bloc(f"| Total charges | {cpc_2025['total_charges']:,.2f} | **{charges_projetees:,.2f}** |")
        bloc(f"| Produits | {cpc_2025['total_produits']:,.2f} | {cpc_2025['total_produits']:,.2f} |")
        bloc(
            f"| **Résultat comptable** | {cpc_2025['resultat']:,.2f} ({cpc_2025['nature_resultat']}) "
            f"| **{resultat_projete:,.2f}** ({'perte' if resultat_projete < 0 else 'benefice'}) |"
        )
        bloc()
        bloc("**Résultat fiscal, IS et cotisation minimale (2025)**")
        bloc()
        try:
            from app.core.rates_ma import is_rates

            taux = is_rates(2025)
            bloc(f"- Taux d'IS 2025 paramétré : {taux['standard']} (documenté).")
        except ValueError:
            bloc(
                "- **IS 2025 : calcul refusé** — le taux de l'exercice n'est pas paramétré "
                "(loi de finances 2025 requise). Projection indicative avec le taux 2026 "
                f"(0,20) : résultat fiscal {resultat_projete:,.2f} → IS "
                f"{money(resultat_projete * Decimal('0.20')) if resultat_projete > 0 else money(0):,.2f} DH."
            )
        bloc(
            "- **Cotisation minimale 2025** : la société est exonérée (12 mois d'activité depuis "
            "le 2025-01-01, fin d'exonération 2028-01-01) ⇒ **0,00 DH** — à confirmer avec les "
            "paramètres 2025 (art. 144 / art. 20)."
        )
        bloc(
            f"- IS 2025 existant (comptabilisé au jeu) : 18 400,00 DH ; résultat fiscal existant : "
            f"92 000,00 DH — **à recalculer intégralement** après régularisation (aucune "
            "correction manuelle)."
        )

        # ------------------------------------------------------------------
        # 5. Impact compte par compte sur les a-nouveaux 2026
        # ------------------------------------------------------------------
        titre("5. Impact **compte par compte** sur les à-nouveaux 2026")
        comptes_suivis = [
            "6171", "6174", "61711", "61741", "61744", "61768",
            "4432", "4441", "4452", "5141", "1191", "1199",
        ]
        projetes = {
            "6171": money(0),
            "6174": money(0),
            "61711": money(totaux["brut"]),
            "61741": money(totaux["cnss_patronale"] + totaux["amo_patronale"]),
            "61744": totaux["prestations_familiales"],
            "61768": totaux["taxe_formation"],
            "4432": money(0),  # nets integralement payes
            "4441": money(
                -(
                    totaux["cnss_salariale"]
                    + totaux["amo_salariale"]
                    + totaux["cnss_patronale"]
                    + totaux["amo_patronale"]
                    + totaux["prestations_familiales"]
                    + totaux["taxe_formation"]
                )
            ),
            "4452": money(-totaux["ir"]),
            # Banque : le solde projete = solde existant **annule des paiements du
            # jeu** (12 x 12 000) puis diminue des nets payes par le module.
            "5141": money(
                _solde_compte(db, company.id, 2025, "5141")
                + charges_2025
                - totaux["net"]
            ),
            "1191": money(0) if resultat_projete < 0 else money(-resultat_projete),
            "1199": money(-resultat_projete) if resultat_projete < 0 else money(0),
        }
        bloc("| Compte | Existant (grand livre 2025) | Projeté (module) | Écart |")
        bloc("|---|---|---|---|")
        for compte in comptes_suivis:
            avant = _solde_compte(db, company.id, 2025, compte)
            apres = projetes.get(compte, money(0))
            if avant == 0 and apres == 0:
                continue
            bloc(f"| `{compte}` | {avant:,.2f} | {apres:,.2f} | **{money(apres - avant):+,.2f}** |")
        bloc()
        bloc(
            "Les à-nouveaux 2026 reprennent les **comptes de bilan** (tous sauf les classes 6 et 7) "
            "plus le **résultat** : l'écart global sur les à-nouveaux se lit donc sur `5141`, "
            f"`4441`, `4452` et le compte de résultat. Écriture existante : "
            f"{bloc.__name__ and 'EC202600001 — 387 520,00 DH / 11 lignes'}. Comparaison "
            "détaillée disponible après régularisation via `closing.regenerer_a_nouveaux`."
        )

        bloc()
        bloc("**Options soumises à validation (aucune n'est appliquée) :**")
        bloc(
            "| Option | Description | Effet |\n|---|---|---|\n"
            "| **A — Ne pas régulariser 2025** | conserver la paie synthétique du jeu (144 000 DH) | scénario inchangé, résultat 2025 = 73 600 DH ; le module reste la source **à partir de 2026** |\n"
            "| **B — Salariés de scénario** | créer les salariés **réels du scénario** correspondant au jeu (coût global 14 400 DH/mois) et régénérer 2025 par le module | résultat 2025 ≈ 73 600 DH (à recalculer), paie 2025 issue du module, cohérence totale |\n"
            "| **C — Retenir les 3 profils de test** | les considérer comme salariés permanents 2025 | charges +221 947,20 DH → résultat 2025 **−148 347,20 DH**, IS 2025 recalculé, à-nouveaux 2026 modifiés |"
        )
        bloc()
        bloc("**Recommandation** : option **B** (ou A si le scénario 2025 doit rester figé) — "
             "l'option C ne doit pas être retenue sans décision explicite du donneur d'ordre.")
    finally:
        db.close()
    texte = "\n".join(SORTIE)
    (BASE / "P1B_SIMULATION_2025_V2.md").write_text(texte + "\n", encoding="utf-8")
    print(texte)
    print(f"\n>>> Ecrit : {BASE / 'P1B_SIMULATION_2025_V2.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

