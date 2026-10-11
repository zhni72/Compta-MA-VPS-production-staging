"""Traduction des erreurs metier en erreurs HTTP."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.services.accounting import AccountingError, ComplianceError, NotFoundError


def http_error(exc: Exception) -> HTTPException:
    """Convertit une erreur metier en reponse HTTP explicite.

    422 : non-respect d'une obligation legale (ex. ICE manquant).
    404 : ressource inexistante. 400 : regle de gestion violee.
    """
    if isinstance(exc, NotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ComplianceError):
        # 422 : la requete est bien formee mais viole une obligation legale.
        code = 422
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def ensure(condition: bool, detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> None:
    """Leve une erreur HTTP si la condition n'est pas remplie."""
    if not condition:
        raise HTTPException(status_code=code, detail=detail)


__all__ = ["http_error", "ensure", "AccountingError"]