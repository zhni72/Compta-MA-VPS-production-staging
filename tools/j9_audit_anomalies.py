"""Audit des anomalies signalees (J9) - LECTURE SEULE.

Cet outil ne modifie RIEN : il collecte les preuves dans la base et dans le code
pour documenter chaque anomalie (cause racine, portee, impact comptable).

Usage :
    .\\.venv\\Scripts\\python.exe tools\\j9_audit_anomalies.py
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "compta_ma.db"

SORTIE: list[str] = []


def titre(texte: str) -> None:
    SORTIE.append("")
    SORTIE.append("=" * 100)
    SORTIE.append(texte)
    SORTIE.append("=" * 100)


def bloc(texte: str) -> None:
    SORTIE.append(texte)


def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def d(value) -> Decimal:
    return Decimal(str(value or 0))


def a2_paie(conn: sqlite3.Connection, cid: int) -> None:
    titre("A2/A8 — DOUBLE ALIMENTATION DE LA PAIE 2026")
    lignes = q(
        conn,
        """
        select e.entry_number, e.entry_date, j.code as journal, e.reference, e.label, e.source,
               l.account_number, l.debit, l.credit
        from entries e
        join journals j on j.id = e.journal_id
        join entry_lines l on l.entry_id = e.id
        where e.company_id=? and e.entry_date >= '2026-01-01'
          and (l.account_number like '617%' or l.account_number like '443%' or l.account_number like '444%')
        order by e.entry_date, e.entry_number, l.position
        """,
        (cid,),
    )
    bloc(f"{len(lignes)} ligne(s) de charges de personnel / dettes sociales en 2026 :")
    for r in lignes:
        bloc(
            f"  {r['entry_date']} {r['entry_number']:<14} {r['journal']} ref={r['reference'] or '-':<14}"
            f" src={r['source'] or '-':<12} {r['account_number']:<6} D {d(r['debit']):>10,.2f}"
            f" C {d(r['credit']):>10,.2f}  {r['label'][:52]}"
        )
    tot: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for r in lignes:
        tot[r["account_number"]][0] += d(r["debit"])
        tot[r["account_number"]][1] += d(r["credit"])
    bloc("Totaux 2026 par compte :")
    for compte in sorted(tot):
        bloc(f"  {compte:<8} debit {tot[compte][0]:>12,.2f}  credit {tot[compte][1]:>12,.2f}")

    bulletins = q(
        conn,
        """
        select p.id, p.periode, p.date_paie, p.brut, p.net, p.cout_employeur, r.statut, r.entry_id,
               (select count(*) from payslip_lines pl where pl.payslip_id=p.id) as lignes,
               (select nom from employees e where e.id=p.employee_id) as salarie
        from payslips p
        left join payroll_runs r on r.id=p.run_id
        where p.company_id=? order by p.periode, p.id
        """,
        (cid,),
    )
    bloc(f"\n{len(bulletins)} bulletin(s) de paie :")
    for r in bulletins:
        bloc(
            f"  id={r['id']} periode={r['periode']} {str(r['salarie'])[:26]:<26} brut {d(r['brut']):>10,.2f}"
            f" net {d(r['net']):>10,.2f} cout employeur {d(r['cout_employeur']):>10,.2f}"
            f" statut={r['statut']} entry_id={r['entry_id']} ({r['lignes']} lignes)"
        )
    cycles = q(
        conn,
        """
        select periode, statut, total_brut, total_ir, total_net, total_employeur, entry_id,
               paiement_entry_id
        from payroll_runs where company_id=? order by periode
        """,
        (cid,),
    )
    bloc(f"\n{len(cycles)} cycle(s) de paie :")
    for r in cycles:
        bloc(
            f"  periode {r['periode']} statut={r['statut']} brut {d(r['total_brut']):>10,.2f}"
            f" IR {d(r['total_ir']):>9,.2f} net {d(r['total_net']):>10,.2f}"
            f" employeur {d(r['total_employeur']):>10,.2f} ecriture={r['entry_id']} paiement={r['paiement_entry_id']}"
        )


def a3_tva(conn: sqlite3.Connection, cid: int) -> None:
    titre("A3/A4 — FACTURES : COHERENCE LIGNES / ENTETE (base du releve XML DGI)")
    for numero in ("FA26-08", "FA26-09", "FA26-12", "FA26-01", "FA25-01"):
        rows = q(
            conn,
            """
            select i.number, i.invoice_date, i.total_ht, i.total_vat, i.total_ttc, i.status,
                   l.position, l.designation, l.quantity, l.unit_price, l.vat_rate,
                   l.line_ht, l.line_vat, l.line_ttc, l.account_number
            from invoices i left join invoice_lines l on l.invoice_id = i.id
            where i.company_id=? and i.number=? order by l.position
            """,
            (cid, numero),
        )
        if not rows:
            bloc(f"\n{numero} : ABSENTE de la base")
            continue
        i0 = rows[0]
        bloc(
            f"\n{numero} du {i0['invoice_date']} statut={i0['status']} : entete "
            f"HT {d(i0['total_ht']):,.2f} TVA {d(i0['total_vat']):,.2f} TTC {d(i0['total_ttc']):,.2f}"
        )
        somme_ht = Decimal(0)
        somme_tva = Decimal(0)
        for r in rows:
            if r["position"] is None:
                bloc("  >>> AUCUNE ligne de detail : montants saisis au niveau de l'entete uniquement")
                continue
            somme_ht += d(r["line_ht"])
            somme_tva += d(r["line_vat"])
            bloc(
                f"  L{r['position']} {r['designation'][:30]:<30} qte {d(r['quantity']):>8,.3f}"
                f" PU {d(r['unit_price']):>10,.2f} taux {d(r['vat_rate']):>5,.2f}"
                f" -> HT {d(r['line_ht']):>10,.2f} TVA {d(r['line_vat']):>9,.2f}"
                f" TTC {d(r['line_ttc']):>10,.2f} cpt {r['account_number']}"
            )
        bloc(
            f"  => lignes : HT {somme_ht:,.2f} / TVA {somme_tva:,.2f}"
            f"  |  ecart entete : HT {d(i0['total_ht'])-somme_ht:,.2f}"
            f" / TVA {d(i0['total_vat'])-somme_tva:,.2f}"
        )

    rows = q(
        conn,
        """
        select i.number, i.invoice_type, i.total_ht, i.total_vat, i.total_ttc,
               coalesce(sum(l.line_ht),0) as s_ht, coalesce(sum(l.line_vat),0) as s_tva,
               coalesce(sum(l.line_ttc),0) as s_ttc, count(l.id) as nb
        from invoices i left join invoice_lines l on l.invoice_id=i.id
        where i.company_id=?
        group by i.id
        having abs(i.total_ht - coalesce(sum(l.line_ht),0)) > 0.009
            or abs(i.total_vat - coalesce(sum(l.line_vat),0)) > 0.009
        order by i.number
        """,
        (cid,),
    )
    bloc(f"\n{len(rows)} facture(s) dont les lignes ne reconcilient pas l'entete :")
    for r in rows:
        bloc(
            f"  {r['number']:<10} {r['invoice_type']:<6} entete HT {d(r['total_ht']):>10,.2f}"
            f" TVA {d(r['total_vat']):>9,.2f} TTC {d(r['total_ttc']):>10,.2f} | lignes HT {d(r['s_ht']):>10,.2f}"
            f" TVA {d(r['s_tva']):>9,.2f} TTC {d(r['s_ttc']):>10,.2f} ({r['nb']} ligne(s))"
        )


def a5_immos(conn: sqlite3.Connection, cid: int) -> None:
    titre("A6 — CLASSEMENT COMPTABLE DES IMMOBILISATIONS (2340 vs outillage / informatique)")
    bloc("Comptes du plan comptable utilises par les fiches :")
    for r in q(
        conn,
        "select number,label,account_class from accounts where number in "
        "('2310','2320','2330','2333','2340','2341','2350','2351','2355','2830','2834') order by number",
    ):
        bloc(f"  {r['number']:<6} {r['label']}  (classe {r['account_class']})")
    fiches = q(
        conn,
        "select code,label,account_number,valeur_origine,acquisition_date from assets "
        "where company_id=? order by code",
        (cid,),
    )
    bloc(f"\n{len(fiches)} fiche(s) d'immobilisation :")
    for r in fiches:
        libelle = q(conn, "select label from accounts where number=?", (r["account_number"],))
        bloc(
            f"  {r['code']:<10} {r['label'][:40]:<40} compte {r['account_number']:<6}"
            f" « {libelle[0]['label'] if libelle else 'INCONNU'} »"
            f" valeur {d(r['valeur_origine']):>12,.2f} acquis le {r['acquisition_date']}"
        )
    bloc("\nEcritures au compte 2340 (grand livre) :")
    for r in q(
        conn,
        """
        select e.entry_date, e.entry_number, e.reference, e.label, l.account_number, l.debit, l.credit
        from entry_lines l join entries e on e.id=l.entry_id
        where e.company_id=? and l.account_number like '234%' order by e.entry_date
        """,
        (cid,),
    ):
        bloc(
            f"  {r['entry_date']} {r['entry_number']:<10} {r['account_number']} D {d(r['debit']):>12,.2f}"
            f" C {d(r['credit']):>12,.2f} {r['label'][:48]}"
        )


def a6_etic(conn: sqlite3.Connection, cid: int, year: int = 2026) -> None:
    titre(f"A7 — ETIC : CHARGES DE PERSONNEL (comptes 61x) ALORS QUE LE CPC PORTE DES 617 — {year}")
    rows = q(
        conn,
        """
        select l.account_number, a.label as libelle, sum(l.debit) as debit, sum(l.credit) as credit
        from entry_lines l
        join entries e on e.id=l.entry_id
        left join accounts a on a.number=l.account_number
        where e.company_id=? and e.entry_date between ? and ?
          and l.account_number like '61%'
        group by l.account_number order by l.account_number
        """,
        (cid, f"{year}-01-01", f"{year}-12-31"),
    )
    for r in rows:
        bloc(
            f"  {r['account_number']:<8} {(r['libelle'] or '')[:32]:<32} debit {d(r['debit']):>12,.2f}"
            f" credit {d(r['credit']):>12,.2f} solde {d(r['debit'])-d(r['credit']):>12,.2f}"
        )


def a7_exercices(conn: sqlite3.Connection, cid: int) -> None:
    titre("A9/A10 — OUVERTURE ET REOUVERTURE D'EXERCICES")
    for r in q(
        conn,
        "select year,status,start_date,end_date,closed_at from fiscal_years where company_id=? order by year",
        (cid,),
    ):
        nb = q(
            conn,
            "select count(*) from entries where company_id=? and entry_date between ? and ?",
            (cid, r["start_date"], r["end_date"]),
        )[0][0]
        bloc(
            f"  {r['year']} statut={r['status']:<7} du {r['start_date']} au {r['end_date']}"
            f" cloture={r['closed_at'] or '-'} : {nb} ecriture(s)"
        )


def a9_edi(conn: sqlite3.Connection) -> None:
    titre("A3 — RELEVE DES DEDUCTIONS TVA : CONTENU REEL DES LIGNES (2026-08 et 2026-12)")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from datetime import date

    from app.db.session import SessionLocal
    from app.models import Company
    from app.services.edi_tva import (
        BASE_PERIODE_FACTURE,
        BASE_PERIODE_PAIEMENT,
        collect_rd_lines,
    )

    db = SessionLocal()
    try:
        company = db.get(Company, q(conn, "select id from companies order by id limit 1")[0][0])
        for debut, fin, libelle in (
            (date(2026, 8, 1), date(2026, 8, 31), "aout 2026"),
            (date(2026, 12, 1), date(2026, 12, 31), "decembre 2026"),
        ):
            for base in (BASE_PERIODE_PAIEMENT, BASE_PERIODE_FACTURE):
                res = collect_rd_lines(db, company, debut, fin, base_periode=base)
                bloc(f"\n-- {libelle} | base_periode={base} : {len(res['lignes'])} ligne(s) --")
                for l in res["lignes"]:
                    attendu = (l.mht * l.taux / Decimal("100")).quantize(Decimal("0.01"))
                    alerte = "" if abs(attendu - l.tva) < Decimal("0.01") else f"  <<< ECART {attendu - l.tva:+,.2f}"
                    bloc(
                        f"   ord={l.ordre:<3} {l.num:<12} mht {l.mht:>10,.2f} tva {l.tva:>9,.2f}"
                        f" ttc {l.ttc:>10,.2f} tx {l.taux:>4} %  dpai={l.date_paiement} dfac={l.date_facture}{alerte}"
                    )
                bloc(f"   totaux : {res['totaux']['mht']:,.2f} / {res['totaux']['tva']:,.2f}")
                for a in res["anomalies"]:
                    bloc(f"   ! {a['reference']} : {a['motif']} (bloquant={a['bloquant']})")
    finally:
        db.close()


def a10_pdf_facture(conn: sqlite3.Connection, numero: str = "FA26-12") -> None:
    titre(f"A4 — DOCUMENT PDF DE LA FACTURE {numero} (contenu des lignes)")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from app.db.session import SessionLocal
    from app.models import Company, Invoice
    from app.services import pdf as moteur
    from app.services import pdf_documents as documents

    capture: dict = {}
    original = moteur.rendre_pdf

    def rendre_pdf_capture(document, *args, **kwargs):  # noqa: ANN001
        capture["document"] = document
        return original(document, *args, **kwargs)

    db = SessionLocal()
    try:
        company = db.get(Company, q(conn, "select id from companies order by id limit 1")[0][0])
        facture = (
            db.query(Invoice)
            .filter(Invoice.company_id == company.id, Invoice.number == numero)
            .one()
        )
        moteur.rendre_pdf = rendre_pdf_capture
        documents.rendre_pdf = rendre_pdf_capture
        try:
            documents.pdf_facture(db, facture)
        finally:
            moteur.rendre_pdf = original
            documents.rendre_pdf = original
        document = capture.get("document")
        if document is None:
            bloc("  (document non capture)")
            return
        bloc(f"  titre : {document.titre} | sous-titre : {document.sous_titre}")
        for table in document.tableaux:
            bloc(f"  -- tableau {table.titre or '(sans titre)'} --")
            bloc("     " + " | ".join(c.titre for c in table.colonnes))
            for ligne in table.lignes:
                bloc("     " + " | ".join(ligne))
            if table.total:
                bloc("     TOTAL : " + " | ".join(table.total))
    finally:
        db.close()


def a8_greffe(conn: sqlite3.Connection, cid: int) -> None:
    titre("A5 — DOSSIER GREFFE : DEPOTS, PIECES ET CONTENU")
    tables = {r[0] for r in q(conn, "select name from sqlite_master where type='table'")}
    for table in sorted(t for t in tables if t.startswith("greffe")):
        bloc(f"  table {table} : {q(conn, f'select count(*) from {table}')[0][0]} ligne(s)")
    for table in sorted(t for t in tables if t.startswith("greffe")):
        bloc(f"\n  -- {table} --")
        for r in q(conn, f"select * from {table} limit 12"):
            bloc("   " + " | ".join(f"{k}={r[k]}" for k in r.keys() if k not in ("content", "html")))


def a11_html_facture(conn: sqlite3.Connection, numero: str = "FA26-12") -> None:
    titre(f"A4 bis — ECRANS HTML : OU APPARAISSENT DES ZEROS POUR {numero}")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    import re

    from fastapi.testclient import TestClient

    from app.core.security import create_access_token
    from app.main import app

    admin = q(conn, "select id,email from users order by id limit 1")[0]
    facture = q(
        conn,
        "select id,number,invoice_type,total_ht,total_vat,total_ttc from invoices where number=?",
        (numero,),
    )
    if not facture:
        bloc(f"  {numero} absente")
        return
    fid = facture[0]["id"]
    jeton = create_access_token(admin["id"], extra={"email": admin["email"]})
    pages = [
        ("/factures/%d" % fid, "detail"),
        ("/factures/%d/impression" % fid, "impression"),
        ("/factures?type=achat&year=2026", "liste achats"),
        ("/tva?year=2026&month=12", "declaration TVA 12/2026"),
        ("/tva/edi?year=2026&month=12", "releve EDI 12/2026"),
        ("/etats/grand-livre?year=2026&month=12", "grand livre 12/2026"),
    ]
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("compta_session", jeton)
        for chemin, libelle in pages:
            rep = client.get(chemin, follow_redirects=False)
            texte = rep.text
            trouves = [
                l.strip()
                for l in re.split(r"<(?:tr|div)[^>]*>", texte)
                if numero in l or numero in l.replace("&nbsp;", " ")
            ]
            bloc(f"\n  {libelle} ({chemin}) -> HTTP {rep.status_code}, {len(trouves)} bloc(s) contenant {numero}")
            for t in trouves[:6]:
                nettoye = re.sub(r"<[^>]+>", " | ", t)
                nettoye = re.sub(r"\s+", " ", nettoye).strip(" |")
                bloc(f"     {nettoye[:230]}")


def a12_collisions_routes() -> None:
    titre("A1 bis — COLLISIONS DE ROUTES API / INTERFACE (pages masquees)")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from app.api.routers import (
        accounts,
        assets,
        audit,
        auth,
        companies,
        entries,
        greffe,
        invoices,
        liasse,
        parties,
        payroll,
        reports,
        stocks,
        vat,
    )
    from app.web import routes as web

    def cles(router, origine: str) -> dict[tuple[str, str], str]:
        resultat: dict[tuple[str, str], str] = {}
        for route in router.routes:
            chemin = getattr(route, "path", "")
            for methode in sorted((getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}):
                resultat[(methode, chemin)] = f"{origine}:{getattr(route, 'name', '?')}"
        return resultat

    api: dict[tuple[str, str], str] = {}
    prefixe = __import__("app.main", fromlist=["API_PREFIX"]).API_PREFIX
    for module in (
        accounts, assets, audit, auth, companies, entries, greffe, invoices,
        liasse, parties, payroll, reports, stocks, vat,
    ):
        origine = f"api.{module.__name__.split('.')[-1]}"
        for cle, valeur in cles(module.router, origine).items():
            methode, chemin = cle
            api.setdefault((methode, f"{prefixe}{chemin}"), valeur)
    interface = {}
    for route in web.router.routes:
        chemin = getattr(route, "path", "")
        for methode in sorted((getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}):
            interface[(methode, chemin)] = f"interface:{getattr(route, 'name', '?')}"

    collisions = sorted(set(api) & set(interface))
    bloc(
        f"{len(api)} route(s) API + {len(interface)} route(s) d'interface ; "
        f"{len(collisions)} collision(s) : l'API etant montee en premier (app/main.py), "
        "elle masque l'ecran."
    )
    for methode, chemin in collisions:
        bloc(f"  {methode:<5} {chemin:<38} gagnant : {api[(methode, chemin)]}")
        bloc(f"                                          masque : {interface[(methode, chemin)]}")


def a14_sweep_ecrans(conn: sqlite3.Connection) -> None:
    titre("A1 ter — BALAYAGE DE TOUS LES ECRANS GET (statut HTTP reel avec session)")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token
    from app.main import app
    from app.web import routes as web

    admin = q(conn, "select id,email from users order by id limit 1")[0]
    jeton = create_access_token(admin["id"], extra={"email": admin["email"]})
    ecrans: list[str] = []
    for route in web.router.routes:
        chemin = getattr(route, "path", "")
        methodes = getattr(route, "methods", None) or set()
        if "GET" in methodes and "{" not in chemin and chemin not in ecrans:
            ecrans.append(chemin)
    anomalies: list[tuple[str, int, str]] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("compta_session", jeton)
        for chemin in sorted(ecrans):
            try:
                rep = client.get(chemin, follow_redirects=False)
                if rep.status_code != 200:
                    anomalies.append((chemin, rep.status_code, rep.text[:120].replace("\n", " ")))
            except Exception as exc:  # pragma: no cover
                anomalies.append((chemin, 0, f"{type(exc).__name__}: {exc}"))
    bloc(f"{len(ecrans)} ecran(s) GET testé(s) ; {len(anomalies)} en anomalie :")
    for chemin, etat, extra in anomalies:
        bloc(f"  {chemin:<34} HTTP {etat}   {extra}")


def a15_scan_edi(conn: sqlite3.Connection) -> None:
    titre("A3 bis — SCAN DE TOUTES LES PERIODES 2025-2026 : COHERENCE mht / taux / tva DU RELEVE")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from datetime import date as _date

    from app.db.session import SessionLocal
    from app.models import Company
    from app.services.edi_tva import BASE_PERIODE_FACTURE, BASE_PERIODE_PAIEMENT, collect_rd_lines

    db = SessionLocal()
    try:
        company = db.get(Company, q(conn, "select id from companies order by id limit 1")[0][0])
        total_periodes = 0
        total_incoherentes = 0
        par_base: dict[str, int] = {BASE_PERIODE_FACTURE: 0, BASE_PERIODE_PAIEMENT: 0}
        for annee in (2025, 2026):
            for mois in range(1, 13):
                debut = _date(annee, mois, 1)
                fin = _date(annee, mois, 28) if mois == 2 else _date(
                    annee, mois, 30 if mois in (4, 6, 9, 11) else 31
                )
                for base in (BASE_PERIODE_FACTURE, BASE_PERIODE_PAIEMENT):
                    res = collect_rd_lines(db, company, debut, fin, base_periode=base)
                    total_periodes += 1
                    incoherentes = [
                        l
                        for l in res["lignes"]
                        if abs((l.mht * l.taux / Decimal("100")).quantize(Decimal("0.01")) - l.tva)
                        >= Decimal("0.01")
                    ]
                    if incoherentes:
                        total_incoherentes += len(incoherentes)
                        par_base[base] = par_base.get(base, 0) + len(incoherentes)
                        bloc(
                            f"  {annee}-{mois:02d} base={base} : {len(res['lignes'])} ligne(s),"
                            f" {len(incoherentes)} incoherente(s)"
                        )
                        for l in incoherentes:
                            bloc(
                                f"      {l.id if hasattr(l, 'id') else ''}{l.num:<12}"
                                f" mht {l.mht:>10,.2f} tx {l.taux:>5} tva {l.tva:>9,.2f}"
                                f" ttc {l.ttc:>10,.2f} (attendu {l.mht * l.taux / Decimal('100'):,.2f})"
                            )
        bloc(
            f"\n  Bilan du scan : {total_periodes} periode(s) analysees, "
            f"{total_incoherentes} ligne(s) incoherente(s)."
        )
        bloc(f"     base = date de facture : {par_base[BASE_PERIODE_FACTURE]} ligne(s)")
        bloc(f"     base = date de paiement (defaut) : {par_base[BASE_PERIODE_PAIEMENT]} ligne(s)")
    finally:
        db.close()


def a13_is(conn: sqlite3.Connection) -> None:
    titre("A8 — IS 2025 / 2026 CALCULE SUR LE RESULTAT COMPTABLE")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from app.db.session import SessionLocal
    from app.models import Company
    from app.services.fiscal_liasse import calculer_is

    db = SessionLocal()
    try:
        company = db.get(Company, q(conn, "select id from companies order by id limit 1")[0][0])
        for annee in (2025, 2026):
            try:
                res = calculer_is(db, company, annee)
            except Exception as exc:  # exercice non clos, etc.
                bloc(f"  {annee} : non calculable -> {type(exc).__name__}: {exc}")
                continue
            bloc(f"  {annee} :")
            for cle in (
                "resultat_comptable", "resultat_avant_impot", "total_reintegrations",
                "total_deductions", "resultat_fiscal", "chiffre_affaires", "taux_is",
                "is", "cotisation_minimale", "impot_du", "acomptes", "solde",
            ):
                if cle in res:
                    bloc(f"     {cle:<22} {res[cle]}")
            bloc(f"     (autres cles : {[k for k in res if k not in ('resultat_comptable','resultat_avant_impot','total_reintegrations','total_deductions','resultat_fiscal','chiffre_affaires','taux_is','is','cotisation_minimale','impot_du','acomptes','solde')]})")
    finally:
        db.close()


def a1_http(conn: sqlite3.Connection) -> None:
    titre("A1 — ECRANS : ACCESSIBILITE HTTP (session, role, erreurs 500)")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.core.security import create_access_token
    from app.main import app
    from app.web.deps import SESSION_COOKIE

    admin = q(conn, "select id,email,full_name,is_active,is_superadmin from users order by id limit 1")[0]
    bloc(
        f"Duree de vie de session : {settings.access_token_expire_minutes} minute(s) "
        f"(cookie {SESSION_COOKIE}, HttpOnly) | utilisateur teste : {admin['email']}"
    )
    jeton = create_access_token(admin["id"], extra={"email": admin["email"]})
    pages = [
        "/", "/etats/journal", "/audit", "/audit/export", "/stocks", "/rapprochement",
        "/etats/balance", "/etats/grand-livre", "/etats/cpc", "/etats/bilan",
        "/tva", "/tva/edi", "/immobilisations", "/paie", "/greffe", "/liasse",
        "/reglements", "/ecritures", "/comptes", "/tiers", "/factures",
        "/parametres/societe", "/parametres/exercices", "/parametres/utilisateurs",
        "/provisions", "/etats/provisions",
    ]
    with TestClient(app, raise_server_exceptions=False) as client:
        bloc("\n-- SANS session (attendu : 303 vers /connexion) --")
        for chemin in ("/etats/journal", "/audit", "/stocks", "/"):
            rep = client.get(chemin, follow_redirects=False)
            bloc(f"  {chemin:<22} {rep.status_code}  ->  {rep.headers.get('location', '')}")
        client.cookies.set("compta_session", jeton)
        bloc("\n-- AVEC session administrateur --")
        for chemin in pages:
            try:
                rep = client.get(chemin, follow_redirects=False)
                etat = rep.status_code
                indice = ""
                if etat >= 500:
                    indice = f"  <<< ERREUR SERVEUR : {rep.text[:150].replace(chr(10), ' ')}"
                elif etat in (301, 302, 303):
                    indice = f"  -> {rep.headers.get('location', '')}"
                elif etat == 403:
                    indice = "  <<< ACCES REFUSE (role)"
                bloc(f"  {chemin:<26} {etat}{indice}")
            except Exception as exc:  # pragma: no cover
                bloc(f"  {chemin:<26} EXCEPTION {type(exc).__name__}: {exc}")


def main() -> int:
    if not DB.exists():
        print(f"Base introuvable : {DB}")
        return 2
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    soc = q(conn, "select * from companies order by id limit 1")[0]
    cid = soc["id"]
    bloc(f"SOCIETE : {soc['name']} | ICE {soc['ice']} | IF {soc['fiscal_id']} | TVA {soc['vat_regime']}")
    a2_paie(conn, cid)
    a3_tva(conn, cid)
    a9_edi(conn)
    a10_pdf_facture(conn)
    a5_immos(conn, cid)
    a6_etic(conn, cid)
    a7_exercices(conn, cid)
    a8_greffe(conn, cid)
    a15_scan_edi(conn)
    a13_is(conn)
    a11_html_facture(conn)
    a12_collisions_routes()
    a14_sweep_ecrans(conn)
    a1_http(conn)
    texte = "\n".join(SORTIE)
    print(texte)
    (BASE / "AUDIT_ANOMALIES_J9.txt").write_text(texte, encoding="utf-8")
    print(f"\n>>> Rapport ecrit : {BASE / 'AUDIT_ANOMALIES_J9.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())



