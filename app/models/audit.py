"""Journal d'audit (append-only).

On n'ecrit jamais dans cette table depuis l'interface : uniquement via
`app.core.audit.log_action`, dans la meme transaction que l'operation tracee.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), default=None, index=True
    )
    action: Mapped[str] = mapped_column(String(40), index=True)
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(40), default=None)
    payload_json: Mapped[str | None] = mapped_column(Text, default=None)
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action} {self.entity}#{self.entity_id}>"