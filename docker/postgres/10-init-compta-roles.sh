#!/bin/sh
# ============================================================
# Compta MA - initialisation des roles PostgreSQL (PG6E2)
# ============================================================
# Ce script est execute UNIQUEMENT lors de la PREMIERE initialisation du cluster
# (repertoire PGDATA vide), par l'entrypoint officiel de l'image PostgreSQL via
# /docker-entrypoint-initdb.d/ (monte en lecture seule par docker-compose.yml).
# Aux demarrages suivants, PGDATA contient deja une base : le script est ignore.
#
# Roles crees :
#   compta_ma_owner     NOLOGIN : proprietaire de la base et du schema public.
#   compta_ma_migrator  LOGIN   : role des migrations Alembic (membre de
#                                 l'owner), JAMAIS le superutilisateur bootstrap.
#   compta_ma_app       LOGIN   : role applicatif (CONNECT + USAGE sur public,
#                                 AUCUN droit CREATE), pour
#                                 SELECT/INSERT/UPDATE/DELETE et l'usage des
#                                 sequences.
#
# Secrets : aucun mot de passe n'est ecrit en dur. Ils sont lus depuis les
# variables d'environnement COMPTA_MA_APP_PASSWORD et COMPTA_MA_MIGRATOR_PASSWORD
# par psql lui-meme (`\getenv`) puis injectes sous forme de litteraux SQL
# (`:'variable'`), psql se chargeant de l'echappement : aucune concatenation de
# mot de passe dans du SQL non cite. `\getenv` exige psql >= 15 (image
# postgres:18-alpine : psql 18).
#
# Remarque : le script n'active ni `set -e` ni `set -u`. L'entrypoint execute un
# `*.sh` executable, mais le SOURCE lorsqu'il ne l'est pas (mode Git 100644 sur
# Windows) ; ces options modifieraient alors l'environnement de l'entrypoint
# lui-meme. Les echecs sont geres explicitement ci-dessous.
# ============================================================

if [ -z "${POSTGRES_DB:-}" ]; then
    echo "PG6E2: POSTGRES_DB (base applicative) est requis." >&2
    exit 1
fi
if [ -z "${POSTGRES_USER:-}" ]; then
    echo "PG6E2: POSTGRES_USER (superutilisateur bootstrap) est requis." >&2
    exit 1
fi
if [ -z "${COMPTA_MA_APP_PASSWORD:-}" ]; then
    echo "PG6E2: COMPTA_MA_APP_PASSWORD est requis pour creer compta_ma_app." >&2
    exit 1
fi
if [ -z "${COMPTA_MA_MIGRATOR_PASSWORD:-}" ]; then
    echo "PG6E2: COMPTA_MA_MIGRATOR_PASSWORD est requis pour creer compta_ma_migrator." >&2
    exit 1
fi

# `ON_ERROR_STOP=1` : la moindre erreur SQL interrompt l'initialisation (jamais
# de cluster demi-configure). Connexion locale (socket) en tant que
# superutilisateur bootstrap ; PGPASSWORD est deja positionne par l'entrypoint.
psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
-- Les mots de passe ne transitent jamais par la ligne de commande : psql les
-- relit directement dans l'environnement du conteneur.
\getenv app_db POSTGRES_DB
\getenv app_password COMPTA_MA_APP_PASSWORD
\getenv migrator_password COMPTA_MA_MIGRATOR_PASSWORD

\echo 'PG6E2 : creation des roles compta_ma_owner / compta_ma_migrator / compta_ma_app'

-- 1. Roles ---------------------------------------------------------------
-- NOSUPERUSER explicite : le role de migration ne doit jamais etre le
-- superutilisateur bootstrap de l'instance.
CREATE ROLE compta_ma_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE compta_ma_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    PASSWORD :'migrator_password';
CREATE ROLE compta_ma_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    PASSWORD :'app_password';

-- Le migrator herite des privileges de l'owner (Alembic cree le schema) sans
-- disposer des droits de superutilisateur.
GRANT compta_ma_owner TO compta_ma_migrator;

-- 2. Base de donnees -----------------------------------------------------
ALTER DATABASE :"app_db" OWNER TO compta_ma_owner;
REVOKE ALL ON DATABASE :"app_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"app_db" TO compta_ma_app;
GRANT CONNECT ON DATABASE :"app_db" TO compta_ma_migrator;

-- 3. Schema public -------------------------------------------------------
-- CREATE est retire a PUBLIC *et* a compta_ma_app : l'application ne doit
-- jamais pouvoir modifier la structure du schema.
ALTER SCHEMA public OWNER TO compta_ma_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM compta_ma_app;
GRANT USAGE ON SCHEMA public TO compta_ma_app;
GRANT USAGE, CREATE ON SCHEMA public TO compta_ma_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM compta_ma_app;

-- 4. Privileges par defaut des objets crees par le migrator --------------
-- Tables, sequences et types des migrations Alembic deviennent utilisables par
-- compta_ma_app sans lui accorder de CREATE sur le schema.
ALTER DEFAULT PRIVILEGES FOR ROLE compta_ma_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO compta_ma_app;
ALTER DEFAULT PRIVILEGES FOR ROLE compta_ma_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO compta_ma_app;
ALTER DEFAULT PRIVILEGES FOR ROLE compta_ma_migrator IN SCHEMA public
    GRANT USAGE ON TYPES TO compta_ma_app;

\echo 'PG6E2 : roles et privileges initialises'
EOSQL

if [ "$?" -ne 0 ]; then
    echo "PG6E2: echec de l'initialisation des roles compta_ma." >&2
    exit 1
fi

echo "PG6E2 : initialisation des roles compta_ma terminee."