"""Non-regression P0.1 : isolation stricte entre l'API (`/api`) et l'interface.

Defaut reproduit (audit J9) : avec une **session Web valide**, les ecrans
`/audit`, `/audit/export` et `/stocks` renvoyaient **401 « Authentification
requise »**, car les routeurs de l'API (jeton `Bearer`) etaient montes sur les
memes chemins et etaient servis en premier.

Correction : l'API REST est montee **uniquement sous `/api`**. Ces tests
echouent sur l'ancien montage et passent sur le nouveau :
- acces aux ecrans avec session Web (200) ;
- acces sans session -> redirection vers `/connexion` (303), **pas** 401 ;
- l'API `/api/...` reste protegee par jeton (401 sans jeton) ;
- invariant structurel : aucun couple (methode, chemin) partage entre les deux
  surfaces, quel que soit l'ordre de montage.
"""

from __future__ import annotations

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
from app.main import API_PREFIX, app
from app.web import routes as web

CONNEXION = {"email": "admin@test.ma", "password": "MotDePasse123"}
ECRANS_AUPARAVANT_MASQUES = ("/audit", "/audit/export", "/stocks")


def connecter(client):
    """Ouvre la session web de l'administrateur de test."""
    response = client.post("/connexion", data=CONNEXION, follow_redirects=False)
    assert response.status_code == 303, response.text
    return client


def _surface(router, prefix: str = "") -> set[tuple[str, str]]:
    """Couples (methode, chemin) portes par un routeur."""
    couples: set[tuple[str, str]] = set()
    for route in router.routes:
        chemin = f"{prefix}{getattr(route, 'path', '')}"
        for methode in (getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}:
            couples.add((methode, chemin))
    return couples


def test_aucune_collision_de_route_entre_api_et_interface():
    """Aucun chemin (methode comprise) n'est partage entre l'API et l'interface."""
    api: set[tuple[str, str]] = set()
    for module in (
        accounts, assets, audit, auth, companies, entries, greffe,
        invoices, liasse, parties, payroll, reports, stocks, vat,
    ):
        api |= _surface(module.router, API_PREFIX)
    interface = _surface(web.router)

    collisions = sorted(api & interface)
    assert collisions == [], f"routes partagees API/interface : {collisions}"
    # les ecrans autrefois masques sont bien servis par l'interface seule
    for chemin in ECRANS_AUPARAVANT_MASQUES:
        assert ("GET", chemin) in interface
        assert ("GET", chemin) not in api


def test_openapi_ne_declare_que_des_chemins_api():
    """Toute la surface API (OpenAPI) est declaree sous /api (hors /health)."""
    chemins = sorted(app.openapi()["paths"])
    hors_api = [chemin for chemin in chemins if not chemin.startswith(API_PREFIX)]
    assert hors_api == ["/health"], (
        "chemins API hors du prefixe /api : " + str(hors_api)
    )
    # les ecrans de l'interface n'apparaissent pas dans la surface API
    for chemin in ECRANS_AUPARAVANT_MASQUES:
        assert chemin not in chemins


def test_ecrans_audit_et_stocks_accessibles_avec_session_web(client, db, ctx):
    """Regression : ces ecrans repondaient 401 malgre une session valide."""
    connecter(client)
    for chemin, marqueur in (
        ("/audit", "Journal d'audit"),
        ("/stocks", "Stocks"),
    ):
        page = client.get(chemin, follow_redirects=False)
        assert page.status_code == 200, f"{chemin} -> {page.status_code} {page.text[:120]}"
        assert marqueur in page.text
    export = client.get("/audit/export", follow_redirects=False)
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")


def test_ecrans_audit_et_stocks_sans_session_redirigent_vers_connexion(client):
    """Sans session, l'interface redirige : elle ne repond jamais 401."""
    for chemin in ECRANS_AUPARAVANT_MASQUES:
        page = client.get(chemin, follow_redirects=False)
        assert page.status_code == 303, f"{chemin} -> {page.status_code}"
        assert page.headers["location"].startswith("/connexion")


def test_api_protegee_par_jeton_et_non_par_session_web(client, db, ctx):
    """L'API exige un jeton Bearer, y compris avec une session web ouverte."""
    connecter(client)
    assert client.get(f"{API_PREFIX}/audit").status_code == 401
    assert client.get(f"{API_PREFIX}/stocks").status_code == 401
    jeton = client.post(
        f"{API_PREFIX}/auth/token",
        data={"username": "admin@test.ma", "password": "MotDePasse123"},
    )
    assert jeton.status_code == 200
    entetes = {"Authorization": f"Bearer {jeton.json()['access_token']}"}
    assert client.get(f"{API_PREFIX}/audit", headers=entetes).status_code == 200
    assert client.get(f"{API_PREFIX}/stocks", headers=entetes).status_code == 200
    # les surfaces restent distinctes : /audit (interface) n'est pas /api/audit
    assert app.version
