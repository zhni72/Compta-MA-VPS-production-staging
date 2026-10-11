"""Socle de l'interface web (Jinja2) : session par cookie, filtres, aides.

L'interface graphique s'appuie sur les MEMES services que l'API
(`app/services`) : aucune logique metier n'est dupliquee, seule la presentation
change. Le style vise les standards des logiciels de gestion (Sage, Ciel) :
bandeau, navigation laterale, fil d'Ariane, tableaux denses, format francais.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, decode_token
from app.db.session import get_db
from app.models import Company, User

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_COOKIE = "compta_session"
COMPANY_COOKIE = "compta_company"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Filtres d'affichage (format marocain : espace pour les milliers, virgule)
# ---------------------------------------------------------------------------
def format_money(value: Any, currency: str = "DH") -> str:
    """1234567.5 -> '1 234 567,50 DH'."""
    if value is None:
        return f"0,00 {currency}"
    montant = Decimal(str(value))
    rendu = f"{montant:,.2f}".replace(",", " ").replace(".", ",")
    return f"{rendu} {currency}"


def format_amount(value: Any) -> str:
    """Montant sans devise (tableaux)."""
    if value is None:
        return "0,00"
    return f"{Decimal(str(value)):,.2f}".replace(",", " ").replace(".", ",")


def format_date(value: Any) -> str:
    """18/09/2026."""
    if not value:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def format_quantity(value: Any) -> str:
    if value is None:
        return "0"
    texte = f"{Decimal(str(value)):,.3f}".rstrip("0").rstrip(".")
    return texte.replace(",", " ").replace(".", ",") or "0"


templates.env.filters["money"] = format_money
templates.env.filters["amount"] = format_amount
templates.env.filters["date_fr"] = format_date
templates.env.filters["qte"] = format_quantity


# ---------------------------------------------------------------------------
# Libelles des statuts (interface 100 % francaise)
# ---------------------------------------------------------------------------
STATUS_LABELS = {
    "draft": "Brouillon",
    "validated": "Validée",
    "partially_paid": "Partiellement réglée",
    "paid": "Réglée",
    "cancelled": "Annulée",
    "open": "Ouvert",
    "closed": "Clôturé",
    "locked": "Verrouillé",
}
STATUS_BADGES = {
    "draft": "badge-grey",
    "validated": "badge-blue",
    "partially_paid": "badge-orange",
    "paid": "badge-green",
    "cancelled": "badge-red",
    "open": "badge-green",
    "closed": "badge-orange",
    "locked": "badge-red",
}
ROLE_LABELS_WEB = {
    "ADMIN": "Administrateur",
    "EXPERT_COMPTABLE": "Expert-comptable",
    "COMPTABLE": "Comptable",
    "CAISSIER": "Caissier",
    "COMMERCIAL": "Commercial",
    "LECTEUR": "Lecteur / Auditeur",
}
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.globals["STATUS_BADGES"] = STATUS_BADGES
templates.env.globals["ROLE_LABELS_WEB"] = ROLE_LABELS_WEB


# ---------------------------------------------------------------------------
# Authentification web (cookie HttpOnly contenant le jeton JWT)
# ---------------------------------------------------------------------------
class NotAuthenticated(Exception):
    """Levee lorsqu'aucune session web valide n'est presente."""


class NotAuthorized(Exception):
    """Levee lorsqu'un utilisateur n'a pas le role requis."""


def login_user(response: HTMLResponse, user: User) -> None:
    """Ouvre la session web (cookie HttpOnly, SameSite=Lax)."""
    token = create_access_token(user.id, extra={"email": user.email})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        max_age=settings.access_token_expire_minutes * 60,
    )


def logout_user(response: HTMLResponse) -> None:
    response.delete_cookie(SESSION_COOKIE)


def get_web_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Utilisateur connecte (cookie de session) ; sinon redirection /connexion."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise NotAuthenticated()
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", 0))
    except Exception as exc:  # jeton invalide ou expire
        raise NotAuthenticated() from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise NotAuthenticated()
    return user


def get_web_company(request: Request, db: Session = Depends(get_db)) -> Company | None:
    """Dossier courant (cookie de selection, sinon premiere societe active)."""
    company_id = request.cookies.get(COMPANY_COOKIE)
    company: Company | None = None
    if company_id and company_id.isdigit():
        company = db.get(Company, int(company_id))
    if company is None:
        company = db.execute(
            select(Company).where(Company.is_active.is_(True)).order_by(Company.id)
        ).scalars().first()
    return company


def require_role(user: User, *codes: str) -> None:
    if user.is_superadmin or user.role_codes.intersection(codes):
        return
    raise NotAuthorized()


def render(
    request: Request,
    template: str,
    *,
    user: User | None = None,
    company: Company | None = None,
    title: str = "",
    active: str = "",
    **context: Any,
) -> HTMLResponse:
    """Rend un gabarit avec le contexte commun (utilisateur, dossier, messages)."""
    message = context.pop("msg", None) or request.query_params.get("msg")
    level = context.pop("level", None) or request.query_params.get("level", "success")
    return templates.TemplateResponse(
        request,
        template,
        {
            "app_name": settings.app_name,
            "devise": settings.currency,
            "user": user,
            "company": company,
            "title": title,
            "active": active,
            "msg": message,
            "level": level,
            **context,
        },
    )