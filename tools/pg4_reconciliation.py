"""PG4 - Reconciliation exhaustive SQLite <-> PostgreSQL (100 % lecture seule).

Objectif : prouver que SQLite et PostgreSQL contiennent les MEMES donnees metier
apres normalisation des differences de dialecte, sans modifier aucune base.

Garanties :
  * SQLite ouverte en `mode=ro` (URI file:...?mode=ro) - toute ecriture refusee ;
  * PostgreSQL ouvert en session `READ ONLY` (SET SESSION CHARACTERISTICS) ;
  * aucun `setval`, aucun `INSERT/UPDATE/DELETE/DROP/CREATE`, aucun Alembic ;
  * aucune connexion reseau hors PostgreSQL local ; aucune installation.

Sortie : rapport texte deterministe (empreintes SHA-256 par table, ecarts
classes en `dialectal` / `representation` / `metier`).
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

PROJECT = Path(r"C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma")
DB_PATH = PROJECT / "compta_ma.db"
EXPECTED_SHA = "E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0"
PG_URL = "postgresql+psycopg://compta_ma_migrator@localhost:5432/compta_ma_staging"

os.chdir(PROJECT)
sys.path.insert(0, str(PROJECT))

# Toute session applicative ouverte pendant l'import sera elle aussi en lecture seule.
SQLITE_RO_URI = f"sqlite:///file:{DB_PATH.as_posix()}?mode=ro&uri=true"
os.environ["DATABASE_URL"] = SQLITE_RO_URI

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import types as sqltypes  # noqa: E402

from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  (charge les 43 tables dans Base.metadata)

SEP = "\x1f"  # unit separator : jamais present dans un texte metier
RS = "\x1e"   # record separator a l'interieur d'une ligne


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def dec_canon(d) -> str:
    """Canonicalisation NUMERIQUE exacte : deux Decimal egaux -> meme chaine."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    if d.is_nan() or d.is_infinite():
        return str(d)
    if d == 0:
        return "0"
    sign, digits, exp = d.as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exp += 1
    return ("-" if sign else "") + "".join(str(x) for x in digits) + "e" + str(exp)


def norm_dt(v: datetime) -> str:
    """Timestamp normalise sans perte (microsecondes toujours explicites)."""
    base = v.strftime("%Y-%m-%dT%H:%M:%S.%f")
    if v.tzinfo is not None:
        base += v.strftime("%z")
    return base


def token(value, ctype) -> str:
    """Jeton canonique d'une valeur, selon le type SQLAlchemy de la colonne."""
    if value is None:
        return "N"
    if isinstance(ctype, sqltypes.Boolean):
        return "B1" if value else "B0"
    if isinstance(ctype, sqltypes.DateTime):
        return "T" + (norm_dt(value) if isinstance(value, datetime) else str(value))
    if isinstance(ctype, sqltypes.Date):
        return "D" + value.isoformat()
    if isinstance(ctype, sqltypes.Time):
        return "t" + value.isoformat()
    if isinstance(ctype, sqltypes.Float):
        return "f" + repr(float(value))
    if isinstance(ctype, sqltypes.Numeric):
        return "d" + dec_canon(value)
    if isinstance(ctype, sqltypes.Integer):
        return "i" + str(int(value))
    if isinstance(ctype, sqltypes.Enum):
        return "e" + str(getattr(value, "value", value))
    if isinstance(ctype, sqltypes.String):
        return "s" + value
    if isinstance(ctype, sqltypes.LargeBinary):
        return "x" + bytes(value).hex()
    return "?" + type(value).__name__ + ":" + repr(value)


def row_tokens(table, row) -> tuple:
    m = row._mapping
    return tuple(token(m[c.name], c.type) for c in table.columns)


def pk_tokens(table, row) -> tuple:
    m = row._mapping
    return tuple(token(m[c.name], c.type) for c in table.primary_key.columns)


def read_table(conn, table) -> dict:
    """Lit une table et renvoie {pk_canon: {"tokens": t, "raw": {colname: val}}}."""
    out: dict = {}
    dup_pk = []
    for row in conn.execute(sa.select(table)):
        pk = pk_tokens(table, row)
        key = SEP.join(pk)
        raw = {c.name: row._mapping[c.name] for c in table.columns}
        if key in out:
            dup_pk.append(key)
        out[key] = {"tokens": row_tokens(table, row), "raw": raw, "pk": pk}
    return {"rows": out, "dup_pk": dup_pk}


def fingerprint(table, rows: dict) -> str:
    """Fingerprint SHA-256 deterministe : tri par PK, serialisation canonique."""
    header = table.name + "|" + "|".join(
        f"{c.name}:{str(c.type)}" for c in table.columns
    )
    lines = [header]
    for key in sorted(rows):
        lines.append(SEP.join(rows[key]["pk"]) + RS + SEP.join(rows[key]["tokens"]))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def classify(coltype, a, b) -> str:
    """Classe une difference de valeur (quand les jetons different)."""
    if isinstance(coltype, sqltypes.Boolean):
        return "dialectal"
    if isinstance(coltype, sqltypes.Numeric):
        try:
            if Decimal(str(a)) == Decimal(str(b)):
                return "representation"
        except Exception:  # noqa: BLE001
            pass
        return "metier"
    if isinstance(coltype, (sqltypes.DateTime, sqltypes.Date, sqltypes.Time)):
        return "representation"
    if isinstance(coltype, sqltypes.String):
        if a is not None and b is not None and str(a).strip() == str(b).strip():
            return "representation"
        return "metier"
    return "metier"


def diff_tables(table, a_rows: dict, b_rows: dict) -> dict:
    """Compare deux lectures d'une table et classe les ecarts."""
    keys_a, keys_b = set(a_rows), set(b_rows)
    value_diffs = []
    for key in sorted(keys_a & keys_b):
        ta, tb = a_rows[key]["tokens"], b_rows[key]["tokens"]
        if ta == tb:
            continue
        cols = []
        for i, c in enumerate(table.columns):
            if ta[i] != tb[i]:
                cols.append({
                    "col": c.name,
                    "cls": classify(c.type, a_rows[key]["raw"][c.name],
                                    b_rows[key]["raw"][c.name]),
                })
        value_diffs.append({"pk": a_rows[key]["pk"], "cols": cols})
    return {
        "missing_a": sorted(keys_b - keys_a),  # presentes en PG seulement
        "missing_b": sorted(keys_a - keys_b),  # presentes en SQLite seulement
        "value_diffs": value_diffs,
    }


def fk_checks(a_read: dict, b_read: dict) -> list:
    """Verifie chaque FK (modele) : orphelines en SQLite et en PostgreSQL."""
    results = []
    for tname in sorted(Base.metadata.tables):
        table = Base.metadata.tables[tname]
        for fk in table.foreign_key_constraints:
            ev = list(fk.elements)
            child = [c.name for c in fk.columns]
            parent = ev[0].column.table
            pcols = [e.column.name for e in ev]

            def vals(reading, tbl, cols):
                out = set()
                for r in reading[tbl.name]["rows"].values():
                    tup = tuple(token(r["raw"][c], tbl.columns[c].type)
                                for c in cols)
                    # MATCH SIMPLE : une FK dont une colonne est NULL n'est pas
                    # verifiee (ce n'est donc pas une orpheline).
                    if "N" in tup:
                        continue
                    out.add(tup)
                return out

            ca = vals(a_read, table, child)
            cb = vals(b_read, table, child)
            pa = vals(a_read, parent, pcols)
            pb = vals(b_read, parent, pcols)
            results.append({
                "child": tname, "cols": child, "parent": parent.name, "pcols": pcols,
                "orph_a": len(ca - pa), "orph_b": len(cb - pb),
            })
    return results


NUM_COLS = {
    "entry_lines": ["debit", "credit", "vat_rate"],
    "payslips": ["brut", "net", "ir", "cout_employeur", "cnss_salariale",
                 "amo_salariale", "cotisations_salariales", "cnss_patronale"],
    "payslip_lines": ["base", "gain", "retenue"],
    "tax_declarations": ["montant"],
}


def _sum_col(reading: dict, tname: str, col: str) -> Decimal:
    tbl = Base.metadata.tables[tname]
    if col not in tbl.columns:
        return Decimal("0")
    total = Decimal("0")
    for r in reading[tname]["rows"].values():
        v = r["raw"][col]
        if v is not None:
            total += Decimal(str(v))
    return total


def compute_aggregates(reading: dict) -> dict:
    """Agregats metier deterministes, communs aux deux bases."""
    ag: dict = {}
    counts = {t: len(reading[t]["rows"]) for t in reading}
    ag["tables_metier"] = str(len(counts))
    ag["lignes_total"] = str(sum(counts.values()))
    for t in sorted(counts):
        ag[f"count.{t}"] = str(counts[t])
    for t, cols in NUM_COLS.items():
        for c in cols:
            ag[f"sum.{t}.{c}"] = str(_sum_col(reading, t, c))

    ent = reading["entries"]["rows"]
    lins = reading["entry_lines"]["rows"]
    fy_by_entry = {r["raw"]["id"]: r["raw"]["fiscal_year_id"] for r in ent.values()}
    debit_by_fy: dict = {}
    credit_by_fy: dict = {}
    for r in lins.values():
        fy = fy_by_entry.get(r["raw"]["entry_id"])
        debit_by_fy[fy] = debit_by_fy.get(fy, Decimal("0")) + Decimal(
            str(r["raw"]["debit"] or 0))
        credit_by_fy[fy] = credit_by_fy.get(fy, Decimal("0")) + Decimal(
            str(r["raw"]["credit"] or 0))
    for fy in sorted(debit_by_fy, key=lambda x: (x is None, x)):
        ag[f"fy{fy}.debit"] = str(debit_by_fy[fy])
        ag[f"fy{fy}.credit"] = str(credit_by_fy[fy])

    an_ids = {r["raw"]["id"] for r in ent.values()
              if r["raw"].get("source") == "opening"}
    ag["a_nouveaux.entries"] = str(len(an_ids))
    d = c = Decimal("0")
    for r in lins.values():
        if r["raw"]["entry_id"] in an_ids:
            d += Decimal(str(r["raw"]["debit"] or 0))
            c += Decimal(str(r["raw"]["credit"] or 0))
    ag["a_nouveaux.debit"] = str(d)
    ag["a_nouveaux.credit"] = str(c)
    ag["paie.runs"] = str(counts.get("payroll_runs", 0))
    ag["paie.bulletins"] = str(counts.get("payslips", 0))
    ag["paie.lignes"] = str(counts.get("payslip_lines", 0))
    return ag


def print_focus(reading: dict) -> None:
    """Preuves ciblees sur les domaines explicitement demandes (SQLite)."""
    print("== FOCUS ==")
    td = reading["tax_declarations"]["rows"]
    for k in sorted(td):
        r = td[k]["raw"]
        print(f"FOCUS tax_declarations id={r['id']} type={r['type']} "
              f"periode={r['periode']} mode_depot={r['mode_depot']} "
              f"statut={r['statut']} montant={r['montant']} nb_lignes={r['nb_lignes']}")
    for k in sorted(reading["activity_events"]["rows"]):
        r = reading["activity_events"]["rows"][k]["raw"]
        print(f"FOCUS activity_events id={r['id']} type={r['type']} "
              f"date_effet={r['date_effet']} regime_tva={r['regime_tva']} "
              f"declaration_id={r['declaration_id']}")
    for k in sorted(reading["vat_rates"]["rows"]):
        r = reading["vat_rates"]["rows"][k]["raw"]
        print(f"FOCUS vat_rates code={r['code']} rate={r['rate']} "
              f"valid_from={r['valid_from']} valid_to={r['valid_to']} "
              f"is_deductible={r['is_deductible']}")
    for k in sorted(reading["entries"]["rows"]):
        r = reading["entries"]["rows"][k]["raw"]
        if r.get("source") == "opening":
            print(f"FOCUS a_nouveaux id={r['id']} ref={r['reference']} "
                  f"label={r['label']} fy={r['fiscal_year_id']} "
                  f"status={r['status']} entry_hash={r['entry_hash']}")
    al = reading["audit_log"]["rows"]
    ids = [r["raw"]["id"] for r in al.values()]
    print(f"FOCUS audit_log count={len(al)} min_id={min(ids)} max_id={max(ids)}")


def main() -> int:
    print("== GARDE-FOU ==")
    print("cwd:", os.getcwd())
    sha_before = sha256_file(DB_PATH)
    print("sha_before:", sha_before)
    print("sha_attendu:", EXPECTED_SHA)
    print("sha_match:", sha_before == EXPECTED_SHA)

    sqlite_engine = sa.create_engine(SQLITE_RO_URI)
    pg_engine = sa.create_engine(
        PG_URL, connect_args={"options": "-c default_transaction_read_only=on"}
    )

    # Preuve lecture seule SQLite (connexion dediee, jetable).
    with sqlite_engine.connect() as sc:
        try:
            sc.exec_driver_sql("CREATE TABLE zz_pg4_probe(x int)")
            print("sqlite_readonly: ALLOWED")
        except Exception as exc:  # noqa: BLE001
            print("sqlite_readonly: REFUSED", type(exc).__name__)

    # Preuve lecture seule PostgreSQL (connexion dediee, jetable).
    with pg_engine.connect() as pc:
        pc.exec_driver_sql("SELECT 1")
        try:
            pc.exec_driver_sql("CREATE TABLE zz_pg4_probe(x int)")
            print("pg_readonly: ALLOWED")
        except Exception as exc:  # noqa: BLE001
            print("pg_readonly: REFUSED", type(exc).__name__)
            pc.rollback()

    meta_tables = sorted(Base.metadata.tables)
    with sqlite_engine.connect() as sc:
        sq_tables = sorted(
            r[0] for r in sc.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"))
        rev_sqlite = sc.exec_driver_sql(
            "SELECT version_num FROM alembic_version").scalar()
    with pg_engine.connect() as pc:
        pg_tables = sorted(
            r[0] for r in pc.exec_driver_sql(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"))
        rev_pg = pc.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
        who = pc.exec_driver_sql("SELECT current_user, current_database()").fetchone()
    print("meta_tables:", len(meta_tables))
    print("sqlite_tables:", len(sq_tables))
    print("pg_tables:", len(pg_tables))
    print("alembic_sqlite:", rev_sqlite, "alembic_pg:", rev_pg)
    print("pg_user_db:", who[0], who[1])

    a_read: dict = {}
    b_read: dict = {}
    with sqlite_engine.connect() as sc, pg_engine.connect() as pc:
        for tname in meta_tables:
            table = Base.metadata.tables[tname]
            a_read[tname] = read_table(sc, table)
            b_read[tname] = read_table(pc, table)

    return reconcile(meta_tables, a_read, b_read, sha_before)


def reconcile(meta_tables, a_read, b_read, sha_before) -> int:
    mismatch = 0
    fp_a_all = hashlib.sha256()
    fp_b_all = hashlib.sha256()
    print("== TABLES ==")
    for tname in meta_tables:
        table = Base.metadata.tables[tname]
        ra, rb = a_read[tname]["rows"], b_read[tname]["rows"]
        fpa, fpb = fingerprint(table, ra), fingerprint(table, rb)
        diff = diff_tables(table, ra, rb)
        ok = (fpa == fpb and not diff["missing_a"] and not diff["missing_b"]
              and not diff["value_diffs"] and not a_read[tname]["dup_pk"]
              and not b_read[tname]["dup_pk"])
        if not ok:
            mismatch += 1
        print(f"TABLE {tname} sqlite={len(ra)} pg={len(rb)} "
              f"fp_sqlite={fpa} fp_pg={fpb} {'MATCH' if ok else 'DIFF'}")
        for lbl, lst in (("MISSING_PG", diff["missing_b"]),
                         ("MISSING_SQLITE", diff["missing_a"])):
            for k in lst[:20]:
                print(f"  {lbl} {tname} pk={k!r}")
        for vd in diff["value_diffs"][:20]:
            classes = ",".join(f"{c['col']}:{c['cls']}" for c in vd["cols"])
            print(f"  VALUE_DIFF {tname} pk={vd['pk']} {classes}")
        if a_read[tname]["dup_pk"] or b_read[tname]["dup_pk"]:
            print(f"  DUP_PK {tname} sqlite={len(a_read[tname]['dup_pk'])} "
                  f"pg={len(b_read[tname]['dup_pk'])}")
        fp_a_all.update(f"{tname}:{fpa}\n".encode())
        fp_b_all.update(f"{tname}:{fpb}\n".encode())

    print("== FK ==")
    fk_bad = 0
    fks = fk_checks(a_read, b_read)
    for f in fks:
        if f["orph_a"] or f["orph_b"]:
            fk_bad += 1
            print(f"FK_ORPHAN {f['child']}.{f['cols']} -> {f['parent']}.{f['pcols']} "
                  f"sqlite={f['orph_a']} pg={f['orph_b']}")
    print("fk_count:", len(fks), "fk_bad:", fk_bad)

    print("== AGGREGATS ==")
    ag_a = compute_aggregates(a_read)
    ag_b = compute_aggregates(b_read)
    agg_bad = 0
    for label in sorted(set(ag_a) | set(ag_b)):
        va, vb = ag_a.get(label), ag_b.get(label)
        ok = va == vb
        if not ok:
            agg_bad += 1
        if label.startswith(("sum.", "fy", "a_nouveaux", "paie", "lignes", "tables")):
            print(f"AGG {label} sqlite={va} pg={vb} {'OK' if ok else 'DIFF'}")

    print_focus(a_read)
    total_a = sum(len(a_read[t]["rows"]) for t in meta_tables)
    total_b = sum(len(b_read[t]["rows"]) for t in meta_tables)
    print("== SUMMARY ==")
    print("tables:", len(meta_tables), "total_sqlite:", total_a, "total_pg:", total_b)
    print("fp_global_sqlite:", fp_a_all.hexdigest())
    print("fp_global_pg:", fp_b_all.hexdigest())
    print("tables_mismatch:", mismatch, "fk_bad:", fk_bad, "agg_bad:", agg_bad)

    ok_all = (mismatch == 0 and fk_bad == 0 and agg_bad == 0
              and total_a == total_b and sha_before == EXPECTED_SHA)
    print("VERDICT:", "PG4_PASS" if ok_all else "PG4_STOP")

    sha_after = sha256_file(DB_PATH)
    print("== SHA SQLITE ==")
    print("sha_before:", sha_before)
    print("sha_after:", sha_after)
    print("sha_unchanged:", sha_before == sha_after)
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())