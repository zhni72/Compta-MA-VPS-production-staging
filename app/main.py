"""Application FastAPI Compta MA - comptabilite marocaine (CGNC / CGI).

Deux interfaces sur la meme application :

1. **Interface graphique** (francais, Jinja2) : http://127.0.0.1:8000/
   Tableau de bord, factures, ecritures, etats comptables, TVA, parametres.
2. **API REST** (JSON) : http://127.0.0.1:8000/docs - pour les integrations.

Lancement :
    python -m app.db.seed --create-tables
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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
from app.core.config import settings
from app.web import routes as web
from app.web import ecrans_lecture as web_lecture
from app.web.deps import STATIC_DIR, NotAuthenticated, NotAuthorized, render

DESCRIPTION = """
Application de comptabilite marocaine (CGNC / PCGE) inspiree des logiciels de type Sage.

**Interface graphique** (en francais) : `/` - tableau de bord, clients et fournisseurs,
factures de vente et d'achat, reglements, saisie des ecritures, plan comptable,
balance generale, grand livre, CPC, bilan, declaration de TVA, parametres de la
societe et des exercices.

**API REST** documentee ici : authentification JWT, societes, comptes, tiers,
factures, ecritures, TVA et etats comptables, pour les integrations et les tests.
Elle est montee **sous le prefixe `/api`** (`/api/auth/token`, `/api/invoices`...)
afin de ne jamais entrer en collision avec les ecrans de l'interface.

**Multi-utilisateurs** : utilisateurs, roles (RBAC), exercices clotures ou
verrouilles et piste d'audit sont en place ; le passage de SQLite (mono-poste) a
PostgreSQL (serveur) se fait par la seule variable `DATABASE_URL`.
"""

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description=DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(NotAuthenticated)
async def _rediriger_vers_connexion(
    request: Request, exc: NotAuthenticated
) -> RedirectResponse:
    """Session absente ou expiree : retour a l'ecran de connexion."""
    destination = quote(request.url.path, safe="/")
    return RedirectResponse(f"/connexion?next={destination}", status_code=303)


@app.exception_handler(NotAuthorized)
async def _acces_refuse(request: Request, exc: NotAuthorized) -> HTMLResponse:
    """Role insuffisant pour l'operation demandee."""
    return render(
        request,
        "erreur.html",
        title="Accès refusé",
        code=403,
        message=(
            "Votre rôle ne permet pas cette opération. Contactez l'administrateur "
            "du dossier pour obtenir les droits nécessaires."
        ),
    )


@app.get("/api", tags=["systeme"], summary="Informations techniques sur l'application")
def api_info() -> dict:
    """Point d'entree de l'API : renvoie l'etat de l'application."""
    return {
        "application": settings.app_name,
        "version": app.version,
        "devise": settings.currency,
        "interface_graphique": "/",
        "documentation_api": "/docs",
        "base_de_donnees": "sqlite" if settings.is_sqlite else "postgresql",
    }


@app.get("/health", tags=["systeme"], summary="Etat de l'application (supervision)")
def health() -> dict:
    return {
        "status": "ok",
        "database": "sqlite" if settings.is_sqlite else "postgresql",
        "taux_tva_courant": settings.default_vat_rate,
    }


# ---------------------------------------------------------------------------
# Montage des routeurs : ISOLATION STRICTE API / INTERFACE
# ---------------------------------------------------------------------------
# L'API REST est montee **uniquement sous le prefixe `API_PREFIX` (/api)** :
# aucune route API ne peut donc se confondre avec un ecran de l'interface
# (`/audit`, `/stocks`...). Cette isolation est structurelle : elle ne depend ni
# de l'ordre de montage, ni du fait qu'une session Web soit presente ou non.
# Un test de non-regression (`tests/test_routing_isolation.py`) verifie qu'aucun
# couple (methode, chemin) n'est partage entre les deux surfaces.
API_PREFIX = "/api"

# 1) API REST (JSON) -> /api/...
for module in (
    auth,
    companies,
    accounts,
    parties,
    invoices,
    entries,
    vat,
    reports,
    assets,
    audit,
    stocks,
    greffe,
    payroll,
    liasse,
):
    app.include_router(module.router, prefix=API_PREFIX)

# 2) Interface graphique (HTML, francais) -> racine /
# `include_in_schema=False` : la documentation OpenAPI (/docs) ne decrit que
# l'API /api ; les ecrans HTML n'y apparaissent pas (isolation des surfaces).
app.include_router(web.router, include_in_schema=False)
# Ecrans **lecture seule** de la navigation P2 (aucune mutation comptable) :
# meme surface HTML, chemins distincts des routes metier existantes.
app.include_router(web_lecture.router, include_in_schema=False)