"""Piste d'audit (journal inalterable des operations comptables).

Obligatoire en comptabilite marocaine : on doit pouvoir dire QUI a fait QUOI et
QUAND. Implemente des la phase 1 (mono-utilisateur) car une piste d'audit ne se
reconstitue pas a posteriori.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def log_action(
    db: Session,
    action: str,
    entity: str,
    entity_id: int | str | None = None,
    user_id: int | None = None,
    company_id: int | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Ajoute une entree d'audit a la session courante (sans commit).

    L'appelant est responsable du commit, afin que l'audit soit enregistre dans
    la meme transaction que l'operation qu'il decrit.
    """
    entry = AuditLog(
        action=action,
        entity=entity,
        entity_id=None if entity_id is None else str(entity_id),
        user_id=user_id,
        company_id=company_id,
        payload_json=None if payload is None else _to_json(payload),
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    return entry


def _to_json(payload: dict[str, Any]) -> str:
    import json

    def default(obj: Any) -> str:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    return json.dumps(payload, ensure_ascii=False, default=default)