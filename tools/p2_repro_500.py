"""P2 — reproduction des erreurs serveur (HTTP 500) sur la **base de recette**.

Le script est **en lecture seule** : il n'ecrit rien en base (aucune ecriture
comptable, aucune transition d'etat, aucun utilisateur cree). Il interroge les
deux routes signalees par la recette avec la base courante et affiche, pour
chaque cas, le **traceback complet** de l'exception serveur.

Usage :
    python tools/p2_repro_500.py [/etats/etic /activite ...]
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models import User
from app.web.deps import COMPANY_COOKIE, SESSION_COOKIE  # noqa: E402

ROUTES_DEFAUT = ["/etats/etic", "/activite"]


def _utilisateurs() -> list[User]:
    with SessionLocal() as db:
        return list(db.query(User).order_by(User.id))


def _client(user: User) -> tuple[TestClient, dict[str, str]]:
    """Client authentifie par cookie de session (comme un navigateur reel)."""
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(SESSION_COOKIE, create_access_token(user.id, extra={"email": user.email}))
    return client, {}


def _appeler(entete: str, client: TestClient, url: str) -> None:
    print(f"\n{'=' * 78}\n{entete} -> GET {url}\n{'=' * 78}")
    try:
        reponse = client.get(url)
    except Exception:  # noqa: BLE001 - on veut le traceback serveur complet
        print("EXCEPTION SERVEUR (traceback complet) :")
        traceback.print_exc()
        return
    print(f"HTTP {reponse.status_code} - {len(reponse.content)} octets")
    if reponse.status_code >= 400:
        extrait = reponse.text[:2000]
        print(extrait)


def main(argv: list[str]) -> int:
    urls = argv[1:] or ROUTES_DEFAUT
    utilisateurs = _utilisateurs()
    if not utilisateurs:
        print("Aucun utilisateur en base : impossible de reproduire.")
        return 1
    for user in utilisateurs:
        codes = ",".join(sorted(user.role_codes)) or "—"
        print(f"- utilisateur {user.id} : {user.email} (roles : {codes})")

    for user in utilisateurs:
        client, _ = _client(user)
        for url in urls:
            _appeler(f"[session {user.email} - roles {','.join(sorted(user.role_codes))}]", client, url)

    for url in urls:
        anonyme = TestClient(app, raise_server_exceptions=False)
        reponse = anonyme.get(url, follow_redirects=False)
        print(f"\n[SANS SESSION] GET {url} -> HTTP {reponse.status_code} (redirection : {reponse.headers.get('location', '—')})")

    print(f"\n(cookie de dossier courant : {COMPANY_COOKIE} ; base : {SessionLocal.kw['bind'].url})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
