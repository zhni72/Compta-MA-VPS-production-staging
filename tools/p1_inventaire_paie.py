"""Inventaire AVANT reinitialisation de la paie (P1) - LECTURE SEULE.

Produit `P1_INVENTAIRE_PAIE.txt` : liste **exacte** des ecritures de paie
concernees (seed `PAIE26-xx` et ecriture du module), cycles et bulletins,
salaries/contrats, declarations DTS, totaux par compte et **situation
comptable de reference** (resultat, bilan, IS) avant toute modification.

Usage :
    .\\.venv\\Scripts\\python.exe tools\\p1_inventaire_paie.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "compta_ma.db"
sys.path.insert(0, str(BASE))

SORTIE: list[str] = []


def bloc(texte: str = "") -> None:
    SORTIE.append(texte)


def titre(texte: str) -> None:
    bloc()
    bloc("=" * 100)
    bloc(texte)
    bloc("=" * 100)


def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def d(valeur) -> Decimal:
    return Decimal(str(valeur or 0))


def ecritures_paie(conn: sqlite3.Connection, cid: int, prefixe: str) -> None:
    """Ecritures touchant la paie pour une annee (reference PAIE ou source payroll)."""
    entrees = q(
        conn,
        """
        select e.id, e.entry_number, e.entry_date, j.code as journal, e.reference, e.label,
               e.source, e.status, e.validated_at
        from entries e join journals j on j.id = e.journal_id
        where e.company_id=? and strftime('%Y', e.entry_date)=?
          and (e.reference like 'PAIE%' or e.source in ('payroll','import_jeu_j9')
               and exists (select 1 from entry_lines l where l.entry_id=e.id
                           and (l.account_number like '617%' or l.account_number like '443%'
                                or l.account_number like '444%' or l.account_number like '4452%')))
        order by e.entry_date, e.entry_number
        """,
        (cid, prefixe),
    )
    deja: set[int] = set()
    total = Decimal("0")
    bloc(f"{len(entrees)} ecriture(s) de paie en {prefixe} :")
    for entree in entrees:
        if entree["id"] in deja:  # pragma: no cover
            continue
        deja.add(entree["id"])
        bloc()
        bloc(
            f"  {entree['entry_date']} | {entree['entry_number']} | journal {entree['journal']} | "
            f"ref={entree['reference']} | source={entree['source']} | {entree['status']} | "
            f"{entree['label']}"
        )
        lignes = q(
            conn,
            "select account_number,label,debit,credit from entry_lines where entry_id=? "
            "order by position",
            (entree["id"],),
        )
        for ligne in lignes:
            total += d(ligne["debit"])
            bloc(
                f"      {ligne['account_number']:<8} D {d(ligne['debit']):>12,.2f}"
                f" C {d(ligne['credit']):>12,.2f}  {ligne['label'][:58]}"
            )
        debit = sum((d(l["debit"]) for l in lignes), Decimal("0"))
        credit = sum((d(l["credit"]) for l in lignes), Decimal("0"))
        bloc(f"      -> equilibre : {'OUI' if debit == credit else 'NON'} ({debit:,.2f})")
    bloc()
    bloc(f"  Total debit des ecritures listees en {prefixe} : {total:,.2f} DH")


def cycles_et_bulletins(conn: sqlite3.Connection, cid: int) -> None:
    bloc()
    bloc("Cycles de paie (payroll_runs) :")
    for r in q(
        conn,
        "select id,periode,date_paie,statut,total_brut,total_ir,total_net,total_employeur,"
        "entry_id,paiement_entry_id from payroll_runs where company_id=? order by periode",
        (cid,),
    ):
        bloc(
            f"  {r['periode']} statut={r['statut']:<9} paie du {r['date_paie']} brut {d(r['total_brut']):>10,.2f}"
            f" IR {d(r['total_ir']):>9,.2f} net {d(r['total_net']):>10,.2f} employeur {d(r['total_employeur']):>10,.2f}"
            f" | ecriture={r['entry_id']} paiement={r['paiement_entry_id']}"
        )
    bloc()
    bloc("Bulletins (payslips) :")
    for r in q(
        conn,
        """
        select p.id, p.periode, e.matricule, e.nom, p.brut, p.ir, p.net, p.cout_employeur, p.entry_id
        from payslips p join employees e on e.id = p.employee_id
        where p.company_id=? order by p.periode, e.matricule
        """,
        (cid,),
    ):
        bloc(
            f"  {r['periode']} {r['matricule']:<8} {r['nom'][:24]:<24} brut {d(r['brut']):>9,.2f}"
            f" IR {d(r['ir']):>8,.2f} net {d(r['net']):>9,.2f} cout {d(r['cout_employeur']):>9,.2f}"
            f" entry={r['entry_id']}"
        )
    bloc()
    bloc("Salaries et contrats :")
    for r in q(
        conn,
        """
        select e.matricule, e.nom, e.date_entree, e.date_sortie, e.actif, c.salaire_base,
               c.prime_transport, c.prime_logement, c.autres_primes, c.date_effet
        from employees e left join pay_contracts c on c.employee_id = e.id
        where e.company_id=? order by e.matricule
        """,
        (cid,),
    ):
        bloc(
            f"  {r['matricule']:<8} {r['nom'][:24]:<24} entree {r['date_entree']} sortie {r['date_sortie'] or '-'}"
            f" actif={r['actif']} base {d(r['salaire_base']):>9,.2f} transport {d(r['prime_transport']):>7,.2f}"
            f" logement {d(r['prime_logement']):>7,.2f} autres {d(r['autres_primes']):>7,.2f}"
            f" (contrat du {r['date_effet'] or '-'})"
        )
    bloc()
    bloc("Declarations fiscales (registre) :")
    for r in q(
        conn,
        "select id,type,periode,regime,mode_depot,statut,montant,nb_lignes,fiscal_year_id,"
        "fichier_nom from tax_declarations where company_id=? order by id",
        (cid,),
    ):
        bloc(
            f"  #{r['id']} {r['type']} {r['periode']} regime={r['regime']} mode={r['mode_depot']}"
            f" statut={r['statut']} montant={d(r['montant']):,.2f} lignes={r['nb_lignes']}"
            f" exercice={r['fiscal_year_id']} fichier={r['fichier_nom']}"
        )


def situation_comptable(cid: int, annee: int) -> None:
    """Situation comptable de reference (avant / apres) : CPC, ESG, bilan, IS."""
    from app.db.session import SessionLocal
    from app.models import Company
    from app.services.etats_synthese import bilan_normal, etat_soldes_gestion
    from app.services.fiscal_liasse import calculer_is
    from app.services.reporting import income_statement

    db = SessionLocal()
    try:
        company = db.get(Company, cid)
        bloc()
        bloc(f"Situation comptable de reference ({annee}) :")
        debut, fin = date(annee, 1, 1), date(annee, 12, 31)
        cpc = income_statement(db, cid, debut, fin)
        bloc(
            f"  Resultat comptable (CPC) : {money_fmt(cpc['resultat'])} DH "
            f"({cpc['nature_resultat']})"
        )
        bloc(f"  Total charges : {money_fmt(cpc['total_charges'])} | total produits : "
             f"{money_fmt(cpc['total_produits'])}")
        esg = etat_soldes_gestion(db, cid, debut, fin)
        bloc(
            f"  ESG : marge brute {money_fmt(esg['marge_brute'])} | valeur ajoutee "
            f"{money_fmt(esg['valeur_ajoutee'])} | EBE {money_fmt(esg['ebe'])} | "
            f"resultat net {money_fmt(esg['resultat_net'])} | coherent CPC {esg['coherent_avec_cpc']}"
        )
        bilan = bilan_normal(db, cid, debut, fin)
        bloc(
            f"  Bilan : actif net {money_fmt(bilan['ecran_total_actif'])} | passif avec resultat "
            f"{money_fmt(bilan['total_passif_avec_resultat'])} | equilibre {bilan['equilibre']}"
        )
        try:
            fiscal = calculer_is(db, company, annee)
            bloc(
                f"  Fiscal : resultat avant impot {money_fmt(fiscal['resultat_avant_impot'])} | "
                f"resultat fiscal {money_fmt(fiscal['resultat_fiscal'])} | IS du "
                f"{money_fmt(fiscal['impot_du'])} | acomptes {money_fmt(fiscal['acomptes_verses'])} | "
                f"solde a payer {money_fmt(fiscal['solde_a_payer'])}"
            )
        except Exception as exc:  # exercice non clos, etc.
            bloc(f"  Fiscal : non calculable ({type(exc).__name__}) : {exc}")
    finally:
        db.close()


def money_fmt(valeur) -> str:
    return f"{Decimal(str(valeur or 0)):,.2f}"


def totaux_comptes(conn: sqlite3.Connection, cid: int, annee: str) -> None:
    bloc()
    bloc(f"Totaux par compte (ecritures de l'exercice {annee}) :")
    for r in q(
        conn,
        """
        select l.account_number, a.label, sum(l.debit) as debit, sum(l.credit) as credit
        from entry_lines l join entries e on e.id=l.entry_id
        left join accounts a on a.number=l.account_number
        where e.company_id=? and strftime('%Y', e.entry_date)=?
          and (l.account_number like '617%' or l.account_number like '443%'
               or l.account_number like '444%' or l.account_number like '4452%'
               or l.account_number in ('5141','5161'))
        group by l.account_number order by l.account_number
        """,
        (cid, annee),
    ):
        solde = d(r["debit"]) - d(r["credit"])
        bloc(
            f"  {r['account_number']:<8} {(r['label'] or '')[:38]:<38} debit {d(r['debit']):>12,.2f}"
            f" credit {d(r['credit']):>12,.2f} solde {solde:>12,.2f}"
        )


def main() -> int:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    cid = q(conn, "select id from companies order by id limit 1")[0][0]
    societe = q(conn, "select name,ice,fiscal_id,vat_regime from companies where id=?", (cid,))[0]
    bloc(
        f"Base : {DB.name} | societe : {societe['name']} "
        f"(ICE {societe['ice']}, IF {societe['fiscal_id']}, TVA {societe['vat_regime']})"
    )
    bloc(
        "Exercices : "
        + str(
            [
                tuple(r)
                for r in q(
                    conn,
                    "select year,status from fiscal_years where company_id=? order by year",
                    (cid,),
                )
            ]
        )
    )

    titre("A. ECRITURES DE PAIE 2026 (a neutraliser : seed PAIE26-xx + ecriture du module)")
    ecritures_paie(conn, cid, "2026")
    totaux_comptes(conn, cid, "2026")

    titre("B. ECRITURES DE PAIE 2025 (exercice CLOS - hors perimetre)")
    ecritures_paie(conn, cid, "2025")

    titre("C. CYCLES, BULLETINS, SALARIES ET DECLARATIONS")
    cycles_et_bulletins(conn, cid)

    titre("D. SITUATION COMPTABLE AVANT REINITIALISATION")
    situation_comptable(cid, 2026)
    situation_comptable(cid, 2025)

    texte = "\n".join(SORTIE)
    (BASE / "P1_INVENTAIRE_PAIE.txt").write_text(texte + "\n", encoding="utf-8")
    print(f"{len(SORTIE)} lignes ecrites dans P1_INVENTAIRE_PAIE.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
