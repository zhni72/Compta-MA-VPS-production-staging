"""Numerotation sequentielle des documents comptables.

Regle fiscale marocaine : la numerotation des factures doit etre **continue et
sans trou**, par societe et par exercice. Consequence appliquee ici :
- le numero est attribue a la **validation** du document (pas a la creation du
  brouillon) ;
- un document annule **conserve son numero**, qui n'est jamais reutilise ;
- la sequence est verrouillee en base (`SELECT ... FOR UPDATE`) pour resister a
  deux utilisateurs simultanes en phase 2.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.numbering import NumberingSequence

DOC_PREFIXES: dict[str, str] = {
    "FACTURE_VENTE": "FV",
    "FACTURE_ACHAT": "FA",
    "AVOIR_VENTE": "AV",
    "AVOIR_ACHAT": "AA",
    "ECRITURE": "EC",
}


def next_document_number(
    db: Session, company_id: int, doc_type: str, year: int
) -> str:
    """Retourne le prochain numero de document, format PREFIX + ANNEE + NNNNN.

    Exemple : FV202600001
    """
    prefix = DOC_PREFIXES.get(doc_type, doc_type[:2].upper())

    if db.get_bind().dialect.name == "postgresql":
        stmt = (
            pg_insert(NumberingSequence)
            .values(
                company_id=company_id,
                doc_type=doc_type,
                year=year,
                last_number=1,
            )
            .on_conflict_do_update(
                constraint="uq_numbering_sequences_scope",
                set_={
                    "last_number": NumberingSequence.last_number + 1,
                },
            )
            .returning(NumberingSequence.last_number)
        )

        last_number = db.execute(stmt).scalar_one()
        return f"{prefix}{year}{last_number:05d}"

    stmt = (
        select(NumberingSequence)
        .where(
            NumberingSequence.company_id == company_id,
            NumberingSequence.doc_type == doc_type,
            NumberingSequence.year == year,
        )
        .with_for_update()  # ignore par SQLite (mono-utilisateur), actif sur PostgreSQL
    )
    sequence = db.execute(stmt).scalar_one_or_none()
    if sequence is None:
        sequence = NumberingSequence(
            company_id=company_id, doc_type=doc_type, year=year, last_number=0
        )
        db.add(sequence)
        db.flush()
    sequence.last_number += 1
    db.flush()
    return f"{prefix}{year}{sequence.last_number:05d}"


def peek_next_number(db: Session, company_id: int, doc_type: str, year: int) -> str:
    """Apercu du prochain numero, sans consommer la sequence."""
    prefix = DOC_PREFIXES.get(doc_type, doc_type[:2].upper())
    stmt = select(NumberingSequence).where(
        NumberingSequence.company_id == company_id,
        NumberingSequence.doc_type == doc_type,
        NumberingSequence.year == year,
    )
    sequence = db.execute(stmt).scalar_one_or_none()
    last = 0 if sequence is None else sequence.last_number
    return f"{prefix}{year}{last + 1:05d}"