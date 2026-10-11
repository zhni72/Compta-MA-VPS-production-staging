"""Verrouillage de periode (P1.6).

Un verrou couvre un **mois** (`periode = 1..12`) ou un **exercice entier**
(`periode = None`). Il produit un **refus dur** de toute ecriture — y compris les
outils d'import — et toute tentative refusee est **journalisee** (CDC § 3.6,
controle bloquant n° 1).

Reference : CGNC, « organisation de la comptabilite » (livres sans blanc ni
alteration, presentables a tout controle).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.models import PeriodLock
from app.services.accounting import AccountingError, PeriodLockedError, get_fiscal_year


class PeriodLockError(AccountingError):
    """Erreur de gestion des verrous (doublon, verrou inexistant...)."""


_PERIOD_LOCK_UNIQUE_CONSTRAINTS = {
    "uq_period_locks_company_year_period",
    "uq_period_locks_company_year_annual",
}


def _is_period_lock_unique_violation(exc: IntegrityError) -> bool:
    """Vrai si PostgreSQL signale un doublon de verrou de periode."""
    diag = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    return constraint_name in _PERIOD_LOCK_UNIQUE_CONSTRAINTS


def verrou_de_la_periode(db: Session, company_id: int, jour: date) -> PeriodLock | None:
    """Verrou couvrant une date : mois verrouille ou exercice verrouille (None si libre)."""
    verrous = db.execute(
        select(PeriodLock).where(
            PeriodLock.company_id == company_id,
            or_(
                PeriodLock.periode.is_(None),
                PeriodLock.periode == jour.month,
            ),
        )
    ).scalars().all()
    for verrou in verrous:
        if verrou.periode is None:
            return verrou
    if not verrous:
        return None
    exercice = get_fiscal_year(db, company_id, jour.year)
    for verrou in verrous:
        # Le verrou mensuel ne s'applique qu'au sein de son propre exercice.
        if verrou.fiscal_year_id == exercice.id:
            return verrou
    return None


def est_verrouillee(db: Session, company_id: int, jour: date) -> bool:
    """Vrai si la periode contenant la date est verrouillee."""
    return verrou_de_la_periode(db, company_id, jour) is not None


def _tracer_refus(
    db: Session,
    *,
    company_id: int,
    jour: date,
    user_id: int | None,
    operation: str,
    verrou: PeriodLock | None,
) -> None:
    """Trace la tentative refusee dans la **transaction metier courante**.

    La trace est ecrite dans la session de l'appelant : **aucune seconde session**
    n'est ouverte et **aucun `commit()` cache** n'est effectue. C'est l'appelant
    qui decide de valider (persister la trace d'audit) ou d'annuler la transaction.

    Ce choix evite, sous PostgreSQL, la seconde transaction susceptible d'attendre
    un verrou de la transaction principale, voire de produire un interblocage.
    """
    log_action(
        db,
        action="PERIOD_LOCK_REJECTED",
        entity="PeriodLock",
        entity_id=None if verrou is None else verrou.id,
        user_id=user_id,
        company_id=company_id,
        payload={
            "operation": operation,
            "date": jour,
            "periode": None if verrou is None else verrou.periode,
            "verrou_id": None if verrou is None else verrou.id,
        },
    )


def controler_periode(
    db: Session,
    company_id: int,
    jour: date,
    *,
    user_id: int | None = None,
    operation: str = "ecriture",
    journaliser: bool = True,
) -> None:
    """Refuse l'operation si la periode est verrouillee (et trace la tentative)."""
    verrou = verrou_de_la_periode(db, company_id, jour)
    if verrou is None:
        return
    if journaliser:
        _tracer_refus(
            db,
            company_id=company_id,
            jour=jour,
            user_id=user_id,
            operation=operation,
            verrou=verrou,
        )
    raise PeriodLockedError(
        f"Periode verrouillee ({verrou.libelle}, exercice {jour.year}) : {operation} "
        f"refusee le {jour.strftime('%d/%m/%Y')}. Le deverrouillage est reserve a "
        "l'ADMIN / l'EXPERT_COMPTABLE (avec motif)."
    )


def verrouiller_periode(
    db: Session,
    *,
    company_id: int,
    year: int,
    periode: int | None = None,
    motif: str | None = None,
    user_id: int | None = None,
) -> PeriodLock:
    """Verrouille un mois (1-12) ou l'exercice entier (``periode = None``)."""
    if periode is not None and not 1 <= periode <= 12:
        raise PeriodLockError("Le mois verrouille doit etre compris entre 1 et 12")

    exercice = get_fiscal_year(db, company_id, year)

    requete = select(PeriodLock).where(
        PeriodLock.company_id == company_id,
        PeriodLock.fiscal_year_id == exercice.id,
    )
    requete = requete.where(
        PeriodLock.periode.is_(None)
        if periode is None
        else PeriodLock.periode == periode
    )

    if db.execute(requete).scalar_one_or_none() is not None:
        libelle = "l'exercice entier" if periode is None else f"le mois {periode:02d}"
        raise PeriodLockError(
            f"Verrou deja pose sur {libelle} de l'exercice {year}."
        )

    verrou = PeriodLock(
        company_id=company_id,
        fiscal_year_id=exercice.id,
        periode=periode,
        motif=motif,
        locked_by=user_id,
    )

    try:
        with db.begin_nested():
            db.add(verrou)
            db.flush()
    except IntegrityError as exc:
        if not _is_period_lock_unique_violation(exc):
            raise

        libelle = "l'exercice entier" if periode is None else f"le mois {periode:02d}"
        raise PeriodLockError(
            f"Verrou deja pose sur {libelle} de l'exercice {year}."
        ) from exc

    log_action(
        db,
        action="PERIOD_LOCKED",
        entity="PeriodLock",
        entity_id=verrou.id,
        user_id=user_id,
        company_id=company_id,
        payload={"exercice": year, "periode": periode, "motif": motif},
    )

    return verrou


def deverrouiller_periode(
    db: Session,
    verrou: PeriodLock,
    *,
    motif: str | None = None,
    user_id: int | None = None,
) -> dict:
    """Retire un verrou : operation reservee, **tracee avec son motif**."""
    if not motif or not motif.strip():
        raise PeriodLockError("Le deverrouillage exige un motif (piste d'audit)")
    trace = {
        "verrou_id": verrou.id,
        "company_id": verrou.company_id,
        "periode": verrou.periode,
        "motif_verrou": verrou.motif,
        "motif_deverrouillage": motif.strip(),
    }
    db.delete(verrou)
    db.flush()
    log_action(
        db,
        action="PERIOD_UNLOCKED",
        entity="PeriodLock",
        entity_id=trace["verrou_id"],
        user_id=user_id,
        company_id=verrou.company_id,
        payload=trace,
    )
    return trace


def periodes_verrouillees(
    db: Session, company_id: int, *, year: int | None = None
) -> list[PeriodLock]:
    """Verrous actifs d'un dossier (tous exercices ou un exercice donne)."""
    requete = select(PeriodLock).where(PeriodLock.company_id == company_id)
    if year is not None:
        exercice = get_fiscal_year(db, company_id, year)
        requete = requete.where(PeriodLock.fiscal_year_id == exercice.id)
    return list(
        db.execute(
            requete.order_by(PeriodLock.fiscal_year_id, PeriodLock.periode)
        ).scalars()
    )


def resume_verrouillages(db: Session, company_id: int, year: int) -> dict:
    """Synthese des verrous d'un exercice (mois verrouilles et verrou annuel)."""
    exercice = get_fiscal_year(db, company_id, year)
    verrous = periodes_verrouillees(db, company_id, year=year)
    annuel = next((v for v in verrous if v.periode is None), None)
    mois = sorted(v.periode for v in verrous if v.periode is not None)
    return {
        "exercice": year,
        "fiscal_year_id": exercice.id,
        "annuel": annuel,
        "mois": mois,
        "nb_verrous": len(verrous),
    }
