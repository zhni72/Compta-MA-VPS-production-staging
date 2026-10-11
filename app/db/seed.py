"""Amorcage (seed) : plan comptable CGNC, taux de TVA, roles, societe, utilisateur.

Idempotent : la commande peut etre relancee sans creer de doublons.

Utilisation (phase 1, mono-utilisateur) :
    python -m app.db.seed --create-tables
"""

from __future__ import annotations

import argparse
import csv
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rates_ma import VAT_RATES_2026
from app.core.security import hash_password
from app.db.base import creer_tables_dev
from app.db.session import SessionLocal, engine
from app.models import (
    DEFAULT_JOURNALS,
    ROLE_CODES,
    ROLE_LABELS,
    Account,
    Company,
    FiscalYear,
    Journal,
    Role,
    User,
    VatRate,
)

PLAN_CSV = settings.data_dir / "plan_comptable_cgnc.csv"


def _find_one(db: Session, model, **filters):  # noqa: ANN001, ANN202
    """Cherche une ligne unique (retourne None si elle est absente)."""
    return db.execute(select(model).filter_by(**filters)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Referentiels
# ---------------------------------------------------------------------------
def load_plan_comptable(db: Session, csv_path=None) -> int:  # noqa: ANN001
    """Charge le plan comptable depuis un CSV (number;label;is_collectif)."""
    path = csv_path or PLAN_CSV
    created = 0
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            number = (row.get("number") or "").strip()
            if not number:
                continue
            if db.execute(
                select(Account).where(Account.number == number)
            ).scalar_one_or_none():
                continue
            db.add(
                Account(
                    number=number,
                    label=(row.get("label") or "").strip() or f"Compte {number}",
                    account_class=int(number[0]),
                    is_collectif=(row.get("is_collectif") or "0").strip() == "1",
                )
            )
            created += 1
    db.flush()
    return created


def seed_vat_rates(db: Session) -> int:
    """Insere les taux de TVA (bareme 2026 : 20 % et 10 %)."""
    created = 0
    for item in VAT_RATES_2026:
        if _find_one(db, VatRate, code=item["code"]) is not None:
            continue
        db.add(
            VatRate(
                code=item["code"],
                rate=item["rate"],
                label=item["label"],
                valid_from=date.fromisoformat(item["valid_from"]),
                is_deductible=item["is_deductible"],
            )
        )
        created += 1
    db.flush()
    return created


def seed_roles(db: Session) -> int:
    """Insere les roles RBAC (administrateur, expert-comptable, comptable...)."""
    created = 0
    for code in ROLE_CODES:
        if _find_one(db, Role, code=code) is not None:
            continue
        db.add(Role(code=code, name=ROLE_LABELS[code]))
        created += 1
    db.flush()
    return created


def get_or_create_fiscal_year(db: Session, company: Company, year: int) -> FiscalYear:
    """Exercice comptable d'annee civile (creation a la volee)."""
    fiscal_year = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company.id, FiscalYear.year == year
        )
    ).scalar_one_or_none()
    if fiscal_year is not None:
        return fiscal_year
    fiscal_year = FiscalYear(company_id=company.id, **FiscalYear.for_year(year))
    db.add(fiscal_year)
    db.flush()
    return fiscal_year


def create_default_journals(db: Session, company: Company) -> list[Journal]:
    """Cree les journaux standards (AC, VE, BQ, CA, OD)."""
    journals: list[Journal] = []
    for code, label, journal_type in DEFAULT_JOURNALS:
        journal = db.execute(
            select(Journal).where(
                Journal.company_id == company.id, Journal.code == code
            )
        ).scalar_one_or_none()
        if journal is None:
            journal = Journal(
                company_id=company.id,
                code=code,
                label=label,
                journal_type=journal_type,
            )
            db.add(journal)
            db.flush()
        journals.append(journal)
    return journals


def create_company(db: Session, name: str, year: int | None = None, **fields) -> Company:  # noqa: ANN003
    """Cree un dossier comptable complet (societe + exercice + journaux)."""
    company = Company(name=name, **fields)
    db.add(company)
    db.flush()
    get_or_create_fiscal_year(db, company, year or date.today().year)
    create_default_journals(db, company)
    return company


def create_user(
    db: Session,
    email: str,
    password: str,
    full_name: str | None = None,
    roles: tuple[str, ...] = ("ADMIN",),
    company: Company | None = None,
    is_superadmin: bool = False,
) -> User:
    """Cree un utilisateur et lui attribue ses roles."""
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            full_name=full_name or email,
            password_hash=hash_password(password),
            is_superadmin=is_superadmin,
        )
        db.add(user)
        db.flush()
    for code in roles:
        role = db.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role inconnu : {code}")
        if role not in user.roles:
            user.roles.append(role)
    if company is not None and company not in user.companies:
        user.companies.append(company)
    db.flush()
    return user


def bootstrap(
    db: Session,
    company_name: str = "Societe Demo",
    year: int | None = None,
    admin_email: str = "admin@compta.ma",
    admin_password: str = "Admin@2026",
    ice: str | None = None,
    vat_regime: str = "trimestriel",
) -> dict:
    """Amorcage complet : referentiels + societe + administrateur."""
    plan = load_plan_comptable(db)
    rates = seed_vat_rates(db)
    roles = seed_roles(db)
    company = create_company(
        db, company_name, year=year, ice=ice, vat_regime=vat_regime
    )
    user = create_user(
        db,
        admin_email,
        admin_password,
        full_name="Administrateur",
        roles=("ADMIN", "EXPERT_COMPTABLE"),
        company=company,
        is_superadmin=True,
    )
    db.commit()
    return {
        "comptes_crees": plan,
        "taux_tva_crees": rates,
        "roles_crees": roles,
        "company_id": company.id,
        "user_id": user.id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Amorcage de Compta MA")
    parser.add_argument("--create-tables", action="store_true", help="creer les tables")
    parser.add_argument("--company", default="Societe Demo", help="nom de la societe")
    parser.add_argument("--ice", default=None, help="ICE de la societe")
    parser.add_argument("--year", type=int, default=None, help="exercice comptable")
    parser.add_argument("--email", default="admin@compta.ma", help="email admin")
    parser.add_argument("--password", default="Admin@2026", help="mot de passe admin")
    parser.add_argument("--plan", default=None, help="CSV du plan comptable a importer")
    args = parser.parse_args()

    if args.create_tables:
        creer_tables_dev(engine)
        print("Tables creees (ou deja presentes).")

    with SessionLocal() as db:
        if args.plan:
            created = load_plan_comptable(db, csv_path=args.plan)
            db.commit()
            print(f"{created} comptes importes depuis {args.plan}")
        result = bootstrap(
            db,
            company_name=args.company,
            year=args.year,
            admin_email=args.email,
            admin_password=args.password,
            ice=args.ice,
        )
    print("Amorcage termine :", result)
    print(f"Base utilisee : {settings.database_url}")


if __name__ == "__main__":
    main()