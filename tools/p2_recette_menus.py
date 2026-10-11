"""P2 — recette **reelle** des ecrans de menu (ADMIN, LECTEUR, sans session).

Le script copie la base de recette dans un fichier temporaire : l'utilisateur
`LECTEUR` de recette est cree **dans la copie**, jamais dans la base reelle. Il
imprime l'empreinte SHA-256 de la base de recette avant et apres execution pour
prouver qu'aucune donnee de recette n'a ete modifiee.

Pour chaque session (ADMIN, LECTEUR), il ouvre la page d'accueil, extrait **les
liens reellement affiches dans le menu**, puis appelle chacun d'eux : un code
4xx/5xx est un **echec de recette**, un traceback serveur est imprime.

Enfin il controle le **contenu metier** attendu des deux ecrans qui ont echoue
en recette : `/etats/etic` (notes ETIC + ligne Total) et `/activite` (evenements
du journal d'audit et libelle utilisateur).

Usage :
    python tools/p2_recette_menus.py
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

RECETTE = RACINE / "compta_ma.db"
COPIE = Path(tempfile.gettempdir()) / "p2_recette_compta_ma.db"
COURRIEL_LECTEUR = "lecteur.recette@test.ma"
MOT_DE_PASSE = "MotDePasse123"

# Ecrans ajoutes par P2 (controle sans session : redirection attendue).
ECRANS_P2 = [
    "/etats/esg",
    "/etats/etic",
    "/stocks/mouvements",
    "/stocks/inventaire",
    "/stocks/provisions",
    "/parametres/a-nouveaux",
    "/parametres/journaux",
    "/parametres/referentiels",
    "/audit/integrite",
    "/e-facturation",
    "/activite",
]
IGNORES = {"/deconnexion"}


def empreinte(chemin: Path) -> str:
    """Empreinte SHA-256 d'un fichier (preuve d'absence de mutation)."""
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def preparer_base_de_travail() -> None:
    """Copie la base de recette (la base reelle n'est jamais modifiee)."""
    shutil.copy2(RECETTE, COPIE)
    os.environ["DATABASE_URL"] = f"sqlite:///{COPIE.as_posix()}"


def _creer_lecteur() -> None:
    """Utilisateur LECTEUR **dans la copie** de la base de recette."""
    with SessionLocal() as db:
        if db.query(User).filter(User.email == COURRIEL_LECTEUR).one_or_none():
            return
        societe = db.query(Company).order_by(Company.id).first()
        lecteur = seed_module.create_user(
            db,
            COURRIEL_LECTEUR,
            MOT_DE_PASSE,
            full_name="Lecteur Recette",
            roles=("LECTEUR",),
            company=societe,
        )
        db.commit()
        db.refresh(lecteur)


preparer_base_de_travail()

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db import seed as seed_module  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditLog, Company, User  # noqa: E402
from app.web.deps import COMPANY_COOKIE, SESSION_COOKIE  # noqa: E402


def session(client: TestClient, user: User, company: Company) -> None:
    """Ouvre une session web reelle (cookies de session et de dossier)."""
    client.cookies.set(
        SESSION_COOKIE, create_access_token(user.id, extra={"email": user.email})
    )
    client.cookies.set(COMPANY_COOKIE, str(company.id))


def liens_du_menu(client: TestClient) -> list[str]:
    """Liens affiches dans le menu de la page d'accueil (rendu reel)."""
    page = client.get("/")
    if page.status_code != 200:
        raise SystemExit(f"Accueil indisponible : HTTP {page.status_code}")
    trouves = re.findall(r'href="(/[^"#]*)"', page.text)
    return sorted({lien for lien in trouves if lien not in IGNORES})


def appeler(client: TestClient, url: str) -> tuple[int, int, str]:
    """Appelle une URL et retourne (code, taille, traceback eventuel)."""
    try:
        reponse = client.get(url)
    except Exception:  # noqa: BLE001 - traceback serveur attendu en recette
        return 500, 0, traceback.format_exc()
    return reponse.status_code, len(reponse.content), ""


def balayer(etiquette: str, client: TestClient) -> list[str]:
    """Balaye toutes les entrees du menu et retourne la liste des echecs."""
    liens = liens_du_menu(client)
    print(f"\n{'-' * 78}\n{etiquette} : {len(liens)} entree(s) de menu\n{'-' * 78}")
    echecs: list[str] = []
    for url in liens:
        code, taille, erreur = appeler(client, url)
        if code >= 400 and code != 405:
            marque = f"[ECHEC {code}]"
            echecs.append(f"{etiquette} {url} -> HTTP {code}")
        elif code == 405:
            marque = "[POST   ]"
        elif code == 303:
            marque = "[303    ]"
        else:
            marque = "[OK     ]"
        print(f"{marque} {url:38s} {taille:>8} octets")
        if erreur:
            print(erreur)
    return echecs


def controle_contenu(client: TestClient) -> list[str]:
    """Controle du **contenu metier** des ecrans ayant echoue en recette."""
    anomalies: list[str] = []

    # ETIC : les notes et la ligne de total doivent etre rendues avec les montants.
    etic = client.get("/etats/etic")
    print(f"\n{'=' * 78}\nControle de contenu /etats/etic -> HTTP {etic.status_code}\n{'=' * 78}")
    for marqueur in ["Note 1 —", "Note 10", "Total", "Capitaux propres"]:
        present = marqueur in etic.text
        print(f"{'[OK ]' if present else '[KO ]'} marqueur « {marqueur} »")
        if not present:
            anomalies.append(f"/etats/etic : marqueur absent « {marqueur} »")
    montants = re.findall(r'<td class="right">[\d ]+,\d\d</td>', etic.text)
    print(f"[{'OK ' if montants else 'KO '}] montants formates rendus : {len(montants)}")
    if not montants:
        anomalies.append("/etats/etic : aucun montant formate rendu")

    # Activite : les evenements reels du journal d'audit doivent apparaitre.
    activite = client.get("/activite")
    print(f"\n{'=' * 78}\nControle de contenu /activite -> HTTP {activite.status_code}\n{'=' * 78}")
    with SessionLocal() as db:
        derniers = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(5).all()
        actions = sorted({entree.action for entree in derniers})
        entites = sorted(
            {(entree.entity, entree.entity_id) for entree in derniers if entree.entity_id}
        )
        utilisateur = db.query(User).order_by(User.id).first()
        # Le service `utilisateurs_journal` libelle un utilisateur par son nom
        # complet, a defaut son courriel : le controle applique la meme regle.
        libelle_utilisateur = (
            (utilisateur.full_name or utilisateur.email) if utilisateur is not None else ""
        )
    for action in actions:
        present = action in activite.text
        print(f"{'[OK ]' if present else '[KO ]'} action « {action} »")
        if not present:
            anomalies.append(f"/activite : action absente « {action} »")
    for entite, identifiant in entites:
        present = f"{entite} {identifiant}" in activite.text
        print(f"{'[OK ]' if present else '[KO ]'} entite « {entite} {identifiant} »")
        if not present:
            anomalies.append(f"/activite : entite absente « {entite} {identifiant} »")
    if utilisateur is not None:
        present = libelle_utilisateur in activite.text
        print(f"{'[OK ]' if present else '[KO ]'} utilisateur « {libelle_utilisateur} »")
        if not present:
            anomalies.append(f"/activite : utilisateur absent « {libelle_utilisateur} »")
    return anomalies


def main() -> int:
    avant = empreinte(RECETTE)
    print(f"Base de recette   : {RECETTE} (SHA-256 {avant[:16]}...)")
    print(f"Copie de travail  : {COPIE}")

    _creer_lecteur()
    with SessionLocal() as db:
        societe = db.query(Company).order_by(Company.id).first()
        admin = db.query(User).order_by(User.id).first()
        lecteur = db.query(User).filter(User.email == COURRIEL_LECTEUR).one()
        assert societe is not None and admin is not None

    echecs: list[str] = []
    for etiquette, utilisateur in (
        (f"[ADMIN   {admin.email}]", admin),
        (f"[LECTEUR {lecteur.email}]", lecteur),
    ):
        client = TestClient(app, raise_server_exceptions=True)
        session(client, utilisateur, societe)
        echecs += balayer(etiquette, client)
        if utilisateur is lecteur:
            echecs += controle_contenu(client)

    print(f"\n{'-' * 78}\nSans session (redirection /connexion attendue)\n{'-' * 78}")
    anonyme = TestClient(app, raise_server_exceptions=False)
    for url in ECRANS_P2:
        reponse = anonyme.get(url, follow_redirects=False)
        location = reponse.headers.get("location", "—")
        attendu = reponse.status_code == 303 and "/connexion" in location
        print(f"{'[OK ]' if attendu else '[KO ]'} {url:28s} HTTP {reponse.status_code} -> {location}")
        if not attendu:
            echecs.append(f"{url} sans session : HTTP {reponse.status_code}")

    apres = empreinte(RECETTE)
    print(f"\n{'=' * 78}")
    print(
        f"Base de recette inchangee : {avant == apres} "
        f"(avant {avant[:16]}... / apres {apres[:16]}...)"
    )
    if echecs:
        print(f"ECHECS DE RECETTE ({len(echecs)}) :")
        for echec in echecs:
            print(f"  - {echec}")
        return 1
    print("P2 — recette des ecrans de menu : OK (aucun echec)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
