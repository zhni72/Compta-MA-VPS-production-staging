"""PG6E2 - tests statiques du durcissement Docker (reference de production).

Ces tests lisent les fichiers de deploiement (Dockerfile, docker-compose.yml,
script d'initialisation PostgreSQL, .dockerignore, .env.example, .gitattributes)
SANS lancer Docker : aucun conteneur n'est construit ou demarre, aucune
dependance n'est ajoutee (pas de PyYAML pour lire le compose) et aucune base
(SQLite locale ou PostgreSQL) n'est touchee.

Invariants verifies :
  A. image applicative : verrou requirements-prod.lock.txt, Python 3.13,
     utilisateur non privilegie
  B. service db : PostgreSQL 18, volume persistant PG 18, aucun port publie,
     healthcheck, script d'initialisation monte en lecture seule
  C. secrets obligatoires : aucun repli faible, aucun secret d'exemple,
     aucun mot de passe litteral
  D. isolation : le service app ne recoit jamais les identifiants de migration,
     et le service migrate est un one-shot (compta_ma_migrator, alembic)
  E. service app : ENVIRONMENT=production, DEBUG=false, port lie a localhost
  F. script d'initialisation des roles : owner / migrator / app, REVOKE CREATE
  G. scripts shell en LF + .gitattributes limite aux `*.sh`
  H. .dockerignore (secrets, bases, venv) et .env.example (placeholders)
"""

from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

DOCKERFILE = RACINE / "Dockerfile"
COMPOSE = RACINE / "docker-compose.yml"
DOCKERIGNORE = RACINE / ".dockerignore"
GITATTRIBUTES = RACINE / ".gitattributes"
ENV_EXEMPLE = RACINE / ".env.example"
INIT_ROLES = RACINE / "docker" / "postgres" / "10-init-compta-roles.sh"
VERROU_PROD = RACINE / "requirements-prod.lock.txt"

# Secrets qui doivent etre OBLIGATOIRES dans le deploiement Docker.
VARIABLES_REQUISES = (
    "POSTGRES_PASSWORD",
    "COMPTA_MA_APP_PASSWORD",
    "COMPTA_MA_MIGRATOR_PASSWORD",
    "SECRET_KEY",
)

# Ancien secret d'exemple du depot : interdit dans le compose de production.
SECRET_EXEMPLE = "__REQUIRED_SECRET_KEY__"


def _lire(chemin: Path) -> str:
    """Contenu texte d'un fichier de deploiement (echec explicite si absent)."""
    assert chemin.is_file(), f"fichier attendu manquant : {chemin}"
    return chemin.read_text(encoding="utf-8")


def _service(nom: str) -> str:
    """Bloc YAML du service `nom` de docker-compose.yml (indentation 2 espaces).

    Lecture textuelle volontairement minimale : le fichier est maitrise par le
    projet, ce qui evite d'introduire PyYAML uniquement pour ces tests.
    """
    lignes = _lire(COMPOSE).splitlines()
    entete = re.compile(rf"^  {re.escape(nom)}:\s*$")
    # Fin du service : service frere (2 espaces) ou cle YAML de premier niveau.
    fin_service = re.compile(r"^  [A-Za-z0-9_.-]+:\s*$")
    premier_niveau = re.compile(r"^\S")
    for index, ligne in enumerate(lignes):
        if not entete.match(ligne):
            continue
        bloc = [ligne]
        for suivante in lignes[index + 1:]:
            if suivante.strip() and (
                fin_service.match(suivante) or premier_niveau.match(suivante)
            ):
                break
            bloc.append(suivante)
        return "\n".join(bloc)
    raise AssertionError(f"service '{nom}' absent de docker-compose.yml")


# ---------------------------------------------------------------------------
# A. Image applicative
# ---------------------------------------------------------------------------
def test_a_dockerfile_installe_le_verrou_de_production():
    """A. L'image installe requirements-prod.lock.txt (et non requirements.txt)."""
    dockerfile = _lire(DOCKERFILE)
    assert VERROU_PROD.is_file(), "requirements-prod.lock.txt est introuvable"
    assert "COPY requirements-prod.lock.txt" in dockerfile

    installations = [
        ligne for ligne in dockerfile.splitlines() if "pip install" in ligne
    ]
    assert installations, "aucune installation pip trouvee dans le Dockerfile"
    for ligne in installations:
        assert "requirements-prod.lock.txt" in ligne
        assert "requirements.txt" not in ligne


def test_a_python313_et_utilisateur_non_privilegie_conserves():
    """A (bis). Python 3.13 et utilisateur applicatif non root conserves."""
    dockerfile = _lire(DOCKERFILE)
    assert re.search(r"^FROM python:3\.13", dockerfile, re.M), "Python 3.13 attendu"
    assert re.search(r"^USER compta\s*$", dockerfile, re.M)
    assert not re.search(r"^USER root\s*$", dockerfile, re.M)


def test_a_dockerfile_sans_instruction_dupliquee():
    """A (ter). Les instructions de fin d'image ne sont pas dupliquees."""
    dockerfile = _lire(DOCKERFILE)
    for instruction in ("EXPOSE 8000", "HEALTHCHECK", 'CMD ["uvicorn"'):
        assert dockerfile.count(instruction) == 1, (
            f"instruction dupliquee dans le Dockerfile : {instruction}"
        )


# ---------------------------------------------------------------------------
# B. Base de donnees (PostgreSQL 18)
# ---------------------------------------------------------------------------
def test_b_postgresql_18_sans_port_publie_et_volume_persistant():
    """B. Service db : PostgreSQL 18, volume PG 18, aucun port publie."""
    db = _service("db")
    assert re.search(r"^\s+image:\s*postgres:18", db, re.M), "PostgreSQL 18 attendu"
    assert "postgres:16" not in db
    # Cibles de montage reelles du service (commentaires exclus) : PG 18 a
    # deplace le volume officiel vers /var/lib/postgresql (et non .../data).
    cibles = re.findall(r"^\s+- [^\s:]+:(/[^\s]+)", db, re.M)
    assert "/var/lib/postgresql" in cibles, f"volume PG 18 attendu, montees : {cibles}"
    assert not any(cible.startswith("/var/lib/postgresql/data") for cible in cibles)
    assert not re.search(r"^\s+ports:", db, re.M), "la base ne publie aucun port"
    assert "healthcheck" in db and "pg_isready" in db
    assert "-h 127.0.0.1" in db
    assert "./docker/postgres:/docker-entrypoint-initdb.d:ro" in db


def test_b_postgresql_password_obligatoire_pour_l_initialisation():
    """B (bis). Le mot de passe bootstrap est obligatoire (aucun repli)."""
    db = _service("db")
    assert re.search(r"^\s+POSTGRES_PASSWORD:\s*\$\{POSTGRES_PASSWORD:\?", db, re.M)
    # Seuls les identifiants necessaires a l'initialisation sont transmis.
    assert "COMPTA_MA_APP_PASSWORD" in db
    assert "COMPTA_MA_MIGRATOR_PASSWORD" in db
    assert not re.search(r"^\s+DATABASE_URL:", db, re.M)
    assert not re.search(r"^\s+MIGRATION_DATABASE_URL:", db, re.M)
    assert not re.search(r"^\s+SECRET_KEY:", db, re.M)


# ---------------------------------------------------------------------------
# C. Secrets : aucun repli, aucune valeur d'exemple
# ---------------------------------------------------------------------------
def test_c_secrets_obligatoires_sans_repli_faible():
    """C. Chaque secret utilise ${VAR:?message} : aucune valeur par defaut."""
    compose = _lire(COMPOSE)
    for variable in VARIABLES_REQUISES:
        assert f"${{{variable}:?" in compose, (
            f"{variable} doit utiliser la syntaxe obligatoire ${{VAR:?message}}"
        )
        # Repli interdit : `$${VAR:-valeur}` n'a pas sa place dans ce fichier.
        motif_repli = re.compile(r"\$\{" + re.escape(variable) + r":-")
        assert not motif_repli.search(compose), (
            f"valeur de repli interdite pour {variable}"
        )
    assert ":-compta}" not in compose
    assert SECRET_EXEMPLE not in compose


def test_c_aucun_mot_de_passe_litteral_dans_docker_compose():
    """C (bis). Tout identifiant d'URL provient d'une variable obligatoire."""
    compose = _lire(COMPOSE)
    # Mot de passe en clair (non ${...}) dans une URL : interdit.
    litteraux = re.findall(r"://[^/\s:\"']+:(?!\$\{[^}]*\})([^@\s\"']+)@", compose)
    assert litteraux == [], (
        f"mot de passe en clair dans docker-compose.yml : {litteraux}"
    )

    identifiants = re.findall(r"://[^/\s:\"']+:(\$\{[^}]*\})@", compose)
    assert identifiants, "les URL doivent contenir un identifiant sous forme de variable"
    for valeur in identifiants:
        assert re.fullmatch(r"\$\{[A-Z0-9_]+:\?[^}]*\}", valeur), (
            f"identifiant sans syntaxe obligatoire : {valeur}"
        )


# ---------------------------------------------------------------------------
# D. Isolation des identifiants app / migration
# ---------------------------------------------------------------------------
def test_d_application_isolee_des_identifiants_de_migration():
    """D. Le service app ne recoit JAMAIS les identifiants de migration."""
    app = _service("app")
    assert "MIGRATION_DATABASE_URL" not in app
    assert "compta_ma_migrator" not in app
    assert "COMPTA_MA_MIGRATOR_PASSWORD" not in app
    # DATABASE_URL cible uniquement le role applicatif.
    assert re.search(r"^\s+DATABASE_URL:", app, re.M)
    assert "compta_ma_app:${COMPTA_MA_APP_PASSWORD:?" in app


def test_d_service_de_migration_one_shot_avec_role_dedie():
    """D (bis). Le service migrate applique Alembic avec compta_ma_migrator."""
    migrate = _service("migrate")
    assert "build: ." in migrate, "meme image applicative que le service app"
    assert "MIGRATION_DATABASE_URL" in migrate
    assert "compta_ma_migrator" in migrate
    assert "COMPTA_MA_MIGRATOR_PASSWORD" in migrate
    assert re.search(
        r'^\s+command:\s*\["python",\s*"-m",\s*"alembic",\s*"upgrade",\s*"head"\]',
        migrate,
        re.M,
    ), "invocation Alembic validee attendue"
    assert re.search(r'^\s+restart:\s*"?no"?\s*$', migrate, re.M), "service one-shot"
    assert "service_healthy" in migrate
    assert not re.search(r"^\s+ports:", migrate, re.M), "aucun port publie"


# ---------------------------------------------------------------------------
# E. Application web en production
# ---------------------------------------------------------------------------
def test_e_application_en_production_et_port_lie_a_localhost():
    """E. Service app : production, DEBUG=false, port publie sur localhost only."""
    app = _service("app")
    assert re.search(r"^\s+ENVIRONMENT:\s*production\s*$", app, re.M)
    assert re.search(r'^\s+DEBUG:\s*"?false"?\s*$', app, re.M)
    assert re.search(r"^\s+SECRET_KEY:\s*\$\{SECRET_KEY:\?", app, re.M)
    assert '"127.0.0.1:8000:8000"' in app
    assert re.search(r"^\s+- media:/app/media\s*$", app, re.M), "volume media attendu"
    # L'application ne demarre qu'apres le succes des migrations.
    assert "service_completed_successfully" in app
    assert re.search(r"^\s+migrate:", app, re.M)


# ---------------------------------------------------------------------------
# F. Initialisation des roles PostgreSQL
# ---------------------------------------------------------------------------
def test_f_script_initialisation_des_roles_postgresql():
    """F. Le script cree owner / migrator / app et borne l'application."""
    script = _lire(INIT_ROLES)
    for role in ("compta_ma_owner", "compta_ma_migrator", "compta_ma_app"):
        assert role in script, f"role {role} absent du script d'initialisation"

    assert re.search(r"CREATE ROLE compta_ma_owner NOLOGIN", script)
    assert re.search(r"CREATE ROLE compta_ma_migrator LOGIN NOSUPERUSER", script)
    assert re.search(r"CREATE ROLE compta_ma_app LOGIN NOSUPERUSER", script)
    # Le migrator herite de l'owner : proprietaire du schema sans etre superuser.
    assert "GRANT compta_ma_owner TO compta_ma_migrator" in script


def test_f_mots_de_passe_uniquement_en_variables_psql_citees():
    """F (bis). Aucun mot de passe en dur : variables psql citees uniquement."""
    script = _lire(INIT_ROLES)
    assert "\\getenv app_password COMPTA_MA_APP_PASSWORD" in script
    assert "\\getenv migrator_password COMPTA_MA_MIGRATOR_PASSWORD" in script
    assert "PASSWORD :'app_password'" in script
    assert "PASSWORD :'migrator_password'" in script
    # Aucun litteral de mot de passe (une quote collee a PASSWORD).
    assert not re.search(r"PASSWORD\s+'", script), "mot de passe litteral interdit"
    # Echec immediat en cas d'erreur SQL.
    assert "ON_ERROR_STOP=1" in script


def test_f_privileges_app_et_migrator():
    """F (ter). L'app n'a aucun CREATE ; le migrator a les droits de schema."""
    script = _lire(INIT_ROLES)
    assert re.search(r'ALTER DATABASE :"app_db" OWNER TO compta_ma_owner', script)
    assert re.search(r'GRANT CONNECT ON DATABASE :"app_db" TO compta_ma_app', script)
    assert re.search(r"GRANT USAGE ON SCHEMA public TO compta_ma_app", script)
    assert re.search(r"GRANT USAGE, CREATE ON SCHEMA public TO compta_ma_migrator", script)
    # RETRAIT EXPLICITE de CREATE pour PUBLIC et pour l'application.
    assert re.search(r"REVOKE CREATE ON SCHEMA public FROM PUBLIC", script)
    assert re.search(r"REVOKE CREATE ON SCHEMA public FROM compta_ma_app", script)
    # Objets crees ensuite par le migrator : utilisables par l'application.
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE compta_ma_migrator" in script
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO compta_ma_app" in script
    assert "GRANT USAGE, SELECT ON SEQUENCES TO compta_ma_app" in script
    assert "GRANT USAGE ON TYPES TO compta_ma_app" in script


# ---------------------------------------------------------------------------
# G. Fins de ligne des scripts shell
# ---------------------------------------------------------------------------
def test_g_script_shell_en_lf_et_gitattributes():
    """G. Scripts shell stockes en LF (executables dans les conteneurs Linux)."""
    brut = INIT_ROLES.read_bytes()
    assert b"\r\n" not in brut, "le script d'initialisation doit etre en LF"
    assert brut.startswith(b"#!/bin/sh")
    gitattributes = _lire(GITATTRIBUTES)
    assert "*.sh text eol=lf" in gitattributes


# ---------------------------------------------------------------------------
# H. Contexte de construction et documentation
# ---------------------------------------------------------------------------
def test_h_dockerignore_exclut_secrets_bases_et_environnements_virtuels():
    """H. Le contexte de construction exclut secrets, bases, venv et caches."""
    entrees = {ligne.strip() for ligne in _lire(DOCKERIGNORE).splitlines()}
    attendus = {
        ".git/",
        ".env",
        ".env.*",
        "!.env.example",
        ".venv/",
        ".venv-*/",
        "__pycache__/",
        ".pytest_cache/",
        "*.db",
        "*.sqlite*",
        "*.bak*",
        "media/",
        "backups/",
        "*.log",
    }
    manquants = attendus - entrees
    assert not manquants, f"exclusions manquantes dans .dockerignore : {sorted(manquants)}"

    # Le code, les migrations, les tests de validation, le verrou de production
    # et les referentiels metier ne doivent jamais etre exclus.
    indispensables = {
        "app/",
        "alembic/",
        "tests/",
        "referentiels/",
        "requirements-prod.lock.txt",
    }
    interdits = indispensables & entrees
    assert not interdits, f"exclusions interdites dans .dockerignore : {sorted(interdits)}"


def test_h_env_exemple_documente_le_docker_sans_secret_reel():
    """H (bis). .env.example documente le Docker avec placeholders uniquement."""
    texte = _lire(ENV_EXEMPLE)
    for nom in (
        "POSTGRES_PASSWORD",
        "COMPTA_MA_APP_PASSWORD",
        "COMPTA_MA_MIGRATOR_PASSWORD",
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "SECRET_KEY",
    ):
        assert nom in texte, f"{nom} doit etre documente dans .env.example"
    assert "compta_ma_app" in texte and "compta_ma_migrator" in texte

    # Les secrets du bloc Docker restent commentes (placeholders uniquement).
    for nom in (
        "POSTGRES_PASSWORD",
        "COMPTA_MA_APP_PASSWORD",
        "COMPTA_MA_MIGRATOR_PASSWORD",
    ):
        assert not re.search(rf"^{nom}=", texte, re.M), f"{nom} doit rester commente"
    assert "MOT_DE_PASSE_A_GENERER" in texte
    assert "A_GENERER_EXTERIEUREMENT_ET_NE_PAS_COMMITTER" in texte

    # Les valeurs par defaut de developpement restent utilisables.
    assert re.search(r"^ENVIRONMENT=development\s*$", texte, re.M)
    assert re.search(r"^DATABASE_URL=sqlite:///\./compta_ma\.db\s*$", texte, re.M)