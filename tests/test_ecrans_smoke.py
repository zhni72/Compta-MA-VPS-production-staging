"""Balayage permanent de TOUS les ecrans GET de l'interface (non-regression P0.1).

Motif : les ecrans `/audit` et `/stocks` etaient interceptes par l'API (401) ;
une fois l'isolation corrigee, `/stocks` a revele une **500** (`AttributeError:
VALUATION_METHOD_LABELS`) restee invisible jusque-la. Ce test garantit qu'aucun
ecran accessible de l'interface ne peut « casser » silencieusement : chaque
chemin GET sans parametre doit repondre 200 ou 303 (jamais 5xx).
"""

from __future__ import annotations

import pytest

from app.web import routes as web

CONNEXION = {"email": "admin@test.ma", "password": "MotDePasse123"}

ECRANS_SANS_PARAMETRE = sorted(
    {
        getattr(route, "path", "")
        for route in web.router.routes
        if "GET" in (getattr(route, "methods", None) or set())
        and "{" not in getattr(route, "path", "")
    }
)


def test_balayage_complet_des_ecrans(client, db, ctx):
    """Chaque ecran GET repond 200 (ou 303 pour les redirections prevues)."""
    client.post("/connexion", data=CONNEXION, follow_redirects=False)
    assert len(ECRANS_SANS_PARAMETRE) >= 35, ECRANS_SANS_PARAMETRE
    anomalies: list[str] = []
    for chemin in ECRANS_SANS_PARAMETRE:
        reponse = client.get(chemin, follow_redirects=False)
        if reponse.status_code in (200, 303):
            continue
        anomalies.append(f"{chemin} -> {reponse.status_code} {reponse.text[:90]}")
    assert anomalies == [], "ecrans en anomalie :\n" + "\n".join(anomalies)


@pytest.mark.parametrize(
    "chemin",
    ["/audit", "/audit/export", "/stocks", "/etats/journal", "/rapprochement", "/paie", "/greffe"],
)
def test_ecrans_metier_accessibles(client, db, ctx, chemin):
    """Les ecrans metier (dont ceux autrefois masques) sont bien servis."""
    client.post("/connexion", data=CONNEXION, follow_redirects=False)
    reponse = client.get(chemin, follow_redirects=False)
    assert reponse.status_code == 200, f"{chemin} -> {reponse.status_code}"
