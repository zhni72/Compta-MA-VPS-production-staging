# PG1 — AUDIT READ-ONLY DE COMPATIBILITÉ SQLITE → POSTGRESQL

| Élément | Valeur |
|---|---|
| Projet audité (unique) | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` |
| Nature de la phase | Audit **READ-ONLY** (aucune migration, aucune écriture DB, aucun fichier applicatif modifié) |
| Date | 2026-10-09 |
| Interpréteur utilisé | `.venv\Scripts\python.exe` — Python 3.13.9 |
| DB de référence | `compta_ma.db` (1 228 800 octets, 300 pages) |
| SHA-256 début | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| SHA-256 fin | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| Verdict | **PG1 PASS CONDITIONNEL — CORRECTIONS PRÉ-MIGRATION IDENTIFIÉES** |

---

## 1. Résumé exécutif

**Compta MA peut migrer de SQLite vers PostgreSQL sans changement fonctionnel.** L'audit
n'a trouvé **aucun BLOCKER** :

- le code applicatif (`app/`) **n'exécute aucun SQL spécifique SQLite** en dehors d'un
  unique `PRAGMA foreign_keys=ON` **déjà conditionné au dialecte** (`app/db/session.py:35`) ;
- **0** occurrence de `AUTOINCREMENT`, `WITHOUT ROWID`, `rowid`, `last_insert_rowid`,
  `INSERT OR …`, `REPLACE INTO`, `ON CONFLICT` dans le code, et **0** dans le DDL de la DB ;
- **0** fonction SQL `strftime` / `julianday` / `group_concat` / `json_extract` dans le
  runtime applicatif (seuls des usages Python `datetime.strftime` ou des scripts d'analyse) ;
- **0 contrainte CHECK**, **102 clés étrangères** réelles (48 `CASCADE`, 40 `SET NULL`,
  14 `NO ACTION`), **16 contraintes UNIQUE**, **104 index** — toutes portables ;
- **aucun type `Float` sur un montant** : 78 colonnes `Numeric(14,2)`, 7 `Numeric(14,3)`,
  5 `Numeric(5,2)` ; **0 ligne** de montant portant plus de 2 décimales ;
- la piste d'audit est **reproductible à l'identique** sous PostgreSQL : 208/208 écritures
  scellées, `verifier_chainage` = `integre: True`, 0 rupture (vérifié en lecture seule) ;
- les 9 migrations Alembic sont **indépendantes du dialecte** (aucun `sqlite`, `op.execute`
  ou SQL propriétaire) et `alembic_version` est déjà à `head` (`p1c1a2b3d4e5`).

Les **corrections pré-migration identifiées** (aucune n'empêche la migration, mais
plusieurs doivent être livrées **avant** l'ouverture en production) portent sur :

1. **Réalignement des séquences PostgreSQL** après import (`setval`, ~46 tables) — PG3 ;
2. **Import typé** des données : SQLite stocke dates/heures/booléens/montants en
   TEXT/INTEGER/REAL (typage dynamique) → conversion explicite obligatoire vers
   `date` / `timestamp` / `boolean` / `numeric(14,2)` — PG3 ;
3. **Fuseau horaire** : `server_default=func.now()` + serveur PG non-UTC produirait des
   `created_at` **incohérents** avec l'historique (stocké en UTC par SQLite) — PG2 ;
4. **`period_locks._tracer_refus`** ouvre une **seconde session** et `commit()` alors que la
   transaction refusée peut tenir des verrous : blocage/déinterblocage possible sur
   PostgreSQL — PG2 (à corriger puis prouver) ;
5. **Tests** : fixture unique `sqlite://` + `StaticPool` (`tests/conftest.py:26-30`) → aucune
   exécution possible sur PostgreSQL en l'état — PG2 ;
6. **Outils de sauvegarde/restauration par copie de fichier `.db`** (9 outils) et **schéma
   créé hors Alembic** (`Base.metadata.create_all` dans 2 outils + 1 script de seed) — PG2/PG3 ;
7. **Sémantique de recherche** `ilike` (6 usages) : équivalence ASCII assurée, comportement
   différent sur les caractères accentués — PG2 (validation de recette) ;
8. **Erreurs d'intégrité sous concurrence** (contraintes UNIQUE de numérotation) : SQLite
   sérialisait les écritures, PostgreSQL non → politique de reprise à définir — PG2.

Ces points sont détaillés et chiffrés dans les sections 14 à 16.

---

## 2. Garde-fou / hash

Contrôles effectués **une seule fois**, avant toute analyse :

| Contrôle | Attendu | Constaté | État |
|---|---|---|---|
| cwd exact | `…\chat\compta_ma` | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` | OK |
| Interpréteur | `.venv\Scripts\python.exe` | présent (Python 3.13.9) | OK |
| `app/` | présent | présent (`api`, `core`, `db`, `models`, `schemas`, `services`, `web`) | OK |
| `tests/` | présent | présent (36 fichiers `test_*.py` + `conftest.py`) | OK |
| `alembic/` | présent | présent (`env.py`, `versions/` : 9 révisions) | OK |
| `compta_ma.db` | présent | présent (1 228 800 o, 300 pages, UTF-8) | OK |
| SHA-256 DB | `4e2c9ec3…b9101` | `4E2C9EC3…B9101` (identique) | OK |

Le hash a été **revérifié après chaque script d'analyse** (7 contrôles intermédiaires) :
toujours `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101`.
Aucun arrêt d'audit n'a été nécessaire (garde-fou conforme).

**Méthode read-only employée** : tous les accès DB ont été faits par
`sqlite3.connect("file:…compta_ma.db?mode=ro", uri=True)` ou par l'ORM via
`DATABASE_URL=sqlite:///file:…?mode=ro&uri=true` (le pilote refuse structurellement toute
écriture). Les scripts d'analyse sont **hors projet**, dans `%TEMP%\pg1\`.

**Contrôles d'intégrité SQLite relevés** : `PRAGMA integrity_check` = `ok` ;
`PRAGMA foreign_key_check` = **0 violation** ; `journal_mode` = `delete` ;
`freelist_count` = 0 ; **aucune table `sqlite_sequence`** (aucune colonne `AUTOINCREMENT`) ;
0 vue, 0 trigger ; 44 tables (43 métier + `alembic_version`).

---

## 3. Architecture DB actuelle

### 3.1 Création de l'engine et sessions

| Fichier:ligne | Contenu | Classification |
|---|---|---|
| `app/db/session.py:16-18` | `_connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}` | compatible tel quel (déjà conditionnel) |
| `app/db/session.py:20-26` | `create_engine(database_url, echo=False, future=True, pool_pre_ping=True, connect_args=_connect_args)` | à compléter (pool — voir 3.4) |
| `app/db/session.py:29-36` | listener `@event.listens_for(Engine, "connect")` → `PRAGMA foreign_keys=ON`, **retour immédiat si non‑SQLite** | compatible tel quel |
| `app/db/session.py:39-45` | `sessionmaker(autoflush=False, expire_on_commit=False, future=True)` | compatible tel quel |
| `app/db/session.py:48-54` | `get_db()` : une session par requête FastAPI | compatible tel quel |
| `app/core/config.py:33` | `database_url` par défaut = `sqlite:///…/compta_ma.db` (surchargeable par env) | compatible tel quel |
| `app/core/config.py:129-130` | `is_sqlite` = `database_url.startswith("sqlite")` | compatible tel quel |
| `alembic/env.py:19` | `config.set_main_option("sqlalchemy.url", settings.database_url)` | compatible tel quel |
| `alembic/env.py:27` | `RENDER_AS_BATCH = settings.is_sqlite` | compatible tel quel (batch désactivé sur PG) |
| `alembic/env.py:49` | `poolclass=pool.NullPool` (migrations) | compatible tel quel |
| `alembic.ini:8` | `sqlalchemy.url = sqlite:///./compta_ma.db` (repli, écrasé par `env.py`) | LOW : à neutraliser/documenter |
| `.env.example:6` / `:9` | `DATABASE_URL=sqlite:///./compta_ma.db` / `# postgresql+psycopg://…` | compatible tel quel |
| `docker-compose.yml:29` | `postgresql+psycopg://…@db:5432/…` + image `postgres:16-alpine` | compatible tel quel |
| `app/main.py:105,113` | `/health` renvoie `sqlite` ou `postgresql` selon `is_sqlite` | compatible tel quel (diagnostic) |

### 3.2 Éléments SQLite explicitement absents (donc sans dette)

- aucun `StaticPool` dans `app/` (uniquement `tests/conftest.py:29`) ;
- aucun `NullPool` dans `app/` (uniquement `alembic/env.py:49`) ;
- aucune URI SQLite paramétrée (`mode=ro`, `uri=true`, `timeout=`) dans l'application ;
- aucun `ATTACH DATABASE`, aucun chemin `.db` dans le code métier ;
- aucune configuration conditionnelle par dialecte **autre** que `is_sqlite`.

### 3.3 Transactions

- une session par requête (`get_db`), `commit/rollback` explicites dans les routes web
  (`app/web/routes.py`, ~160 points de commit/rollback) ;
- deux **SAVEPOINT** (`app/services/assets.py:815`, `app/services/stocks.py:612,722`) ;
- une **seconde session indépendante** : `app/services/period_locks.py:79-109` (voir § 11) ;
- aucune configuration d'isolation (`isolation_level`, `SERIALIZABLE`) → PostgreSQL
  utilisera **READ COMMITTED** (SQLite sérialise les écritures) : à prescrire en PG2.

### 3.4 Pool

`create_engine` n'indique **ni `poolclass`, ni `pool_size`, ni `max_overflow`, ni
`pool_recycle`** → PostgreSQL utilisera le `QueuePool` par défaut (5 + 10). Avec
`pool_pre_ping=True`, l'usage mono-poste est sûr ; en multi-utilisateurs (PG3) il faudra
dimensionner le pool et ajouter `pool_recycle` (coupures d'`idle` côté serveur) — MEDIUM PG2.

---

## 4. Inventaire SQLite-specific

**Méthode** : un seul parcours ciblé du projet (motifs `sqlite|sqlite3|PRAGMA|rowid|
AUTOINCREMENT|WITHOUT ROWID|INSERT OR|REPLACE INTO|ON CONFLICT|strftime|julianday|
group_concat|json_extract|printf|text(…`), complété par un second parcours ciblé
(dialectes, SQL brut, fonctions SQL, upsert, tests). Les occurrences purement
documentaires (commentaires, `.md`, rapports) sont écartées ci‑dessous.

### 4.1 Occurrences runtime (code applicatif)

| Fichier:ligne | Fonction / contexte | Risque PostgreSQL | Correction potentielle |
|---|---|---|---|
| `app/db/session.py:17` | `check_same_thread` (connect_args) | **aucun** : déjà conditionnel `is_sqlite` | aucune (conserver) |
| `app/db/session.py:35` | `PRAGMA foreign_keys=ON` (listener `connect`) | **aucun** : retour anticipé si non‑SQLite | aucune (conserver) |
| `app/core/config.py:33` | URL SQLite par défaut | aucun (défaut local) | surcharge par `DATABASE_URL` |
| `app/core/numbering.py:43` | `.with_for_update()` (verrou de numérotation) | **positif** : ignoré par SQLite, actif sur PG | aucune (conserver) |
| `app/services/period_locks.py:80` | `"memory" in str(bind.url)` (détection base en mémoire) | **à rendre conditionnel** : sur PG la branche « session séparée » s'exécute (voir § 11) | tester le dialecte (`is_sqlite`) + transaction courte |
| `app/main.py:105,113` | `/health` : libellé `sqlite`/`postgresql` | aucun | aucune |

**Conclusion** : le seul SQL propriétaire exécuté par l'application est
`PRAGMA foreign_keys=ON`, déjà neutralisé pour PostgreSQL. **Aucun `text(...)` métier**,
**aucun `.execute("…")` en chaîne littérale** : l'application est 100 % ORM
(`app/db/session.py:35` est la seule exécution de SQL brut de `app/`).

### 4.2 Motifs SQLite **absents** (vérifié, par famille)

| Motif | Occurrences code `app/` | Occurrences DDL DB | Risque |
|---|---|---|---|
| `AUTOINCREMENT` | 0 | 0 | aucun (pas de `sqlite_sequence`) |
| `WITHOUT ROWID` | 0 | 0 | aucun |
| `rowid` / `last_insert_rowid` | 0 | 0 | aucun |
| `INSERT OR …` / `REPLACE INTO` | 0 | 0 | aucun |
| `ON CONFLICT` / upsert | 0 | 0 | aucun |
| `strftime` / `julianday` (SQL) | 0 (Python uniquement) | 0 | aucun |
| `group_concat` / `json_extract` | 0 | 0 | aucun |
| `printf(` SQL | 0 | 0 | aucun |
| `ATTACH DATABASE` / `VACUUM` | 0 | 0 | aucun |
| `COLLATE` / `CAST(` SQL | 0 | 0 | aucun |

### 4.3 Occurrences hors runtime (outils, scripts d'analyse, documentation)

Ces fichiers ne sont **pas** exécutés par l'application ; ils supposent en revanche que la
base est un **fichier SQLite** (voir § 12 « outils »).

| Fichier:ligne | Contexte | Impact PostgreSQL |
|---|---|---|
| `tools/j9_audit_anomalies.py:12,625` | `import sqlite3` + `sqlite3.connect(DB)` | outil à rendre PG‑aware ou bloqué sur PG |
| `tools/p1_inventaire_paie.py:14,54,217,233` | `import sqlite3`, SQL `strftime('%Y', e.entry_date)` | SQL non portable (PG : `EXTRACT` / `date_part`) ; outil d'analyse uniquement |
| `tools/p1_reinitialiser_paie.py:29` | `import sqlite3` | idem |
| `tools/p2_recette_menus.py:64-65` | `shutil.copy2` de la DB puis `DATABASE_URL=sqlite:///…` | recette locale SQLite |
| `tools/p1_rapport_avant_apres.py:96,98,329` | `text("… limit 1")`, `create_engine(sqlite:///…)` | `LIMIT` portable ; dépend d'un fichier `.bak` |
| `tools/p1b_stage3_regularisation.py:78-125` | SHA-256 du **fichier** DB + copie `.bak-<suffixe>-<horodatage>` | sauvegarde par copie de fichier |
| `tools/j9_purge_donnees.py:66-75`, `tools/normalize_fiscal_ids.py:48-53,99-103`, `tools/charger_plan_comptable.py:50,103-104`, `tools/import_achats_fournisseurs.py:87,191-192` | copie `.bak-<horodatage>` + `DATABASE_URL=sqlite:///…` | idem |
| `tools/*` (16 fichiers `compta_ma.db.bak-*`) | sauvegardes historiques présentes dans le dossier | à ne pas recopier tel quel en PG3 |
| `audit_env_local_compta_ma.ps1` | SHA-256 du fichier `compta_ma.db` | contrôle d'outillage P1 |

### 4.4 Configuration Alembic spécifique SQLite

| Fichier:ligne | Contexte | Risque PG |
|---|---|---|
| `alembic/env.py:27` | `render_as_batch = settings.is_sqlite` | **aucun** : désactivé sur PG (ALTER direct) |
| `alembic/env.py:37,56` | `compare_type=True` | aucun (utile au diagnostic) |
| `alembic/versions/*` (86 lignes) | `op.batch_alter_table(...)` partout | **aucun** : Alembic exécute l'ALTER direct sur PG |
| `alembic/versions/*` (~26 colonnes) | `server_default=sa.text('(CURRENT_TIMESTAMP)')` | **aucun** : `(CURRENT_TIMESTAMP)` est valide en PostgreSQL |

---

## 5. Modèles SQLAlchemy (audit sans modification)

**Méthode** : introspection de `Base.metadata` (43 tables déclarées) par script
d'analyse, plus confrontation avec les 44 tables réelles de la DB :
`metadata = 43`, `db = 44`, **écart = `alembic_version` uniquement** → **aucune dérive
de schéma** entre les modèles et la DB de référence.

### 5.1 Liste des 43 tables déclarées

`accounts, activity_events, asset_depreciation_lines, asset_events, assets, audit_log,
bank_reconciliations, bank_statement_lines, bank_statements, companies,
e_invoice_documents, employees, entries, entry_lines, fiscal_years, greffe_deposits,
greffe_documents, greffe_events, greffe_payments, invoice_lines, invoices, journals,
liasse_cells, liasse_tables, numbering_sequences, pay_contracts, payments, payroll_runs,
payslip_lines, payslips, period_locks, roles, stock_count_lines, stock_counts,
stock_items, stock_movements, stock_provisions, tax_declarations, third_parties,
user_companies, user_roles, users, vat_rates`

### 5.2 Répartition exacte des types (colonnes)

| Type déclaré | Nb colonnes | Remarque PostgreSQL |
|---|---|---|
| `Integer` | 163 | `INTEGER` (PK → `SERIAL`/`IDENTITY` par SQLAlchemy) |
| `Numeric(14,2)` | 78 | `NUMERIC(14,2)` — **montants en dirhams** (aucune perte) |
| `Numeric(14,3)` | 7 | `NUMERIC(14,3)` — quantités de stock |
| `Numeric(5,2)` | 5 | `NUMERIC(5,2)` — taux de TVA / remises |
| `String(n)` | 140 | `VARCHAR(n)` (n = 3,5,6,7,10,12,15,16,20,30,40,45,60,64,80,120,150,160,180,200,255) |
| `Text` | 20 | `TEXT` (notes, XML EDI, payload JSON **en texte**) |
| `Date` | 39 | `DATE` |
| `DateTime` | 37 | `TIMESTAMP WITHOUT TIME ZONE` (aucun `timezone=True`) |
| `Boolean` | 16 | `BOOLEAN` |
| `Float` | **0** | aucune valeur financière en flottant |
| `JSON` / `ARRAY` / `Enum` / `Interval` / `LargeBinary` | **0** | aucun type propriétaire |

**Points relevés (aucune modification effectuée)** :

- **PK** : 41 tables à clé `Integer` mono‑colonne `autoincrement='auto'` (→ séquence PG) ;
  2 tables à **PK composite** (`user_roles`, `user_companies`) → **pas de séquence** ;
- **FK** : 102 contraintes ; `ondelete` explicite (48 `CASCADE`, 40 `SET NULL`),
  `onupdate` **jamais** utilisé côté SQL (4 colonnes utilisent `onupdate=func.now()`
  côté Python/SQLAlchemy : `declaration.py:96-98`, `e_invoice.py:100-101`,
  `greffe.py:284-285`, `payroll.py:247-248`) ;
- **UNIQUE** : 16 contraintes (4 index uniques mono‑colonne — `accounts.number`,
  `roles.code`, `users.email`, `vat_rates.code` — et 12 `uq_<table>_<colonnes>` composites) ;
- **CHECK** : **0** → aucune contrainte de domaine à recréer/traduire ;
- **Index** : 104 (dont 16 uniques) → recréés par Alembic à l'identique ;
- **Boolean** : `default=` **côté Python uniquement** (`Boolean, default=False`) → les
  colonnes sont `NOT NULL` **sans** `server_default`. Comportement identique SQLite/PG :
  tout INSERT SQL direct doit fournir la valeur. Aucun écart de migration ;
- **server_default** : uniquement `func.now()` côté modèles (≈ 37 colonnes
  `created_at`/`updated_at`/`imported_at`/`locked_at`) et `(CURRENT_TIMESTAMP)` côté
  migrations — **équivalent fonctionnel** SQLite/PG (voir § 6.3 pour le fuseau) ;
- **Colonnes nullables** : cohérentes entre modèles, migrations et DDL (vérifié : aucune
  divergence de `NOT NULL` détectée entre `models.txt` et `db_columns.txt`) ;
- **JSON** : `audit_log.payload_json` est un `Text` (JSON sérialisé par
  `app/core/audit.py:46-54`), `e_invoice_documents.xml/accuse` sont des `Text` →
  **aucun besoin de type `JSONB`** (choix conservateur déjà portable) ;
- **Enums** : tous les statuts sont des `String(n)` contrôlés par des tuples Python
  (`ENTRY_STATUS_*`, `INVOICE_STATUS_*`, `PAYROLL_STATUS_*`, `DECLARATION_STATUTS`…) →
  aucune migration de type `ENUM` à prévoir.

**Conclusion § 5 : les modèles sont portables sans changement de type.**

---

## 6. Types / Decimal / dates

### 6.1 Décimaux et calculs financiers

| Élément | Fichier:ligne | Constat | Classification |
|---|---|---|---|
| Type monétaire partagé | `app/models/types.py:8-12` | `Money = Numeric(14,2, asdecimal=True)`, `Rate = Numeric(5,2)`, `Quantity = Numeric(14,3)` | compatible PG (type exact) |
| Arrondi canonique | `app/core/rates_ma.py:16-18` | `money()` = `Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)` | compatible (calcul Python) |
| Conversions | `app/services/*` (70+ usages) | systématiquement `Decimal(str(...))` — **jamais** `Decimal(float)` | compatible |
| `float()` en saisie web | `app/web/routes.py:140-146` (`safe_float`) + 22 appels (`:400,561-563,699,929-930,2117-2125,2293-2294,2523-2524,2794,2831-2832`) | les valeurs de formulaire passent par `float` **avant** d'alimenter des colonnes `Numeric` | **acceptable en affichage/saisie, à surveiller** : sur PostgreSQL la conversion `float8 → numeric(14,2)` arrondit à 2 décimales (comportement correct mais dépendant de la représentation binaire) → recommandation PG2 : parser en `Decimal(str(...))` |
| Colonnes `Float` | — | **0** (vérifié par introspection) | acceptable |
| Montants `float` en base | `db_types.txt` | SQLite stocke les montants en `INTEGER` (548 lignes) ou `REAL` (74–101 lignes selon colonne) → **typage dynamique** | à surveiller (PG3 : import typé, § 16) |
| Décimales excédentaires | contrôle SQL `ROUND(col,2) <> col` sur **toutes** les colonnes `Numeric` | **0 ligne** anormale sur 43 tables | OK — un import vers `NUMERIC(14,2)` ne perdra **aucun centime** |
| Fidélité du round-trip | ORM en lecture seule | `debit = Decimal('200000.00')` pour une valeur stockée en `INTEGER` (le processeur SQLAlchemy applique l'échelle 2) | **OK critique** : les valeurs relues sont identiques en SQLite et PostgreSQL |
| Agrégats | `SUM` SQL vs somme `Decimal` exacte | `SQL=Decimal('4321260.99')` = `exact=Decimal('4321260.99')` (`egal=True`) | OK |

**Conséquence importante (audit fiable)** : `app/services/audit_trail.py:61-62` calcule
l'empreinte SHA-256 sur `str(ligne.debit)` / `str(ligne.credit)`. Comme SQLAlchemy restitue
`Decimal('…00')` avec l'échelle 2 dans **les deux dialectes**, le **chaînage reste vérifiable
à l'identique** après migration. Preuve : 208/208 écritures scellées, `verifier_chainage`
= `integre: True`, 0 rupture, dernière empreinte
`a47571c2ff07817d0c37524d69b253a147ad3e035e1daba11a04056e8a30f0f5`.

### 6.2 Dates et heures stockées (typage réel SQLite)

| Table.colonne | Nombre | Formats observés en base | Impact PG3 |
|---|---|---|---|
| `entries.entry_date` | 208 | `AAAA-MM-JJ` (208/208) | conversion `text → date` |
| `entries.created_at` | 208 | `AAAA-MM-JJ HH:MM:SS` (208/208, **UTC**) | `text → timestamp` |
| `entries.validated_at` | 208 | `AAAA-MM-JJ HH:MM:SS.ffffff` (microsecondes) | `text → timestamp` |
| `audit_log.created_at` | 593 | `AAAA-MM-JJ HH:MM:SS` (UTC) | `text → timestamp` |
| `fiscal_years.start_date/end_date` | 2+2 | `AAAA-MM-JJ` | `text → date` |
| `fiscal_years.closed_at` | 1 | `AAAA-MM-JJ HH:MM:SS.ffffff` | `text → timestamp` |
| `invoices.invoice_date` | 74 | `AAAA-MM-JJ` | `text → date` |
| `payroll_runs.periode` | 24 | `AAAA-MM` — colonne `String(7)`, **pas une date** | aucune conversion |

PostgreSQL accepte nativement ces deux formats de texte pour `date` / `timestamp`, mais
**un `COPY` sans typage explicite échouerait** (charge en `text`). PG3 devra donc convertir
explicitement (table de transit `text` + `INSERT … SELECT …::date/::timestamp`, § 16).

### 6.3 Fuseau horaire

| Élément | Constat | Classification |
|---|---|---|
| Modèles | `DateTime` **naïf** partout (aucun `timezone=True`, aucun `TIMESTAMPTZ`) | compatible tel quel |
| Écritures applicatives | `datetime.now()` (heure locale du poste) : `accounting.py:207` (`validated_at`), `closing.py:253,417` (`closed_at`), `greffe.py:1688` | à surveiller |
| `server_default` | `func.now()` (modèles) / `(CURRENT_TIMESTAMP)` (DDL existant) → SQLite écrit **UTC** (`2026-09-23 01:07:24`) | **MEDIUM** |
| Aucun usage UTC explicite | 0 `utcnow()`, 0 `astimezone()`, 0 `ZoneInfo` dans `app/` | à prescrire |
| `date.today()` | très nombreux usages (défauts d'exercice/écran : `web/routes.py` ~25 appels, services EDI/paie/greffe) | compatible mais dépend du fuseau du **serveur** : à fixer (TZ=UTC ou Africa/Casablanca), à documenter en PG2 |

**Risque identifié (MEDIUM)** : PostgreSQL `now()` renvoie un `timestamptz` converti dans le
fuseau de **session** avant stockage dans une colonne `timestamp without time zone`. Si le
serveur est en `Africa/Casablanca` (UTC+1), les nouveaux `created_at` seraient **décalés
d'une heure** par rapport aux 801 lignes historiques stockées en UTC. Correction PG2 :
`TZ`/`PGTZ` = `UTC` sur le serveur PostgreSQL (ou passage ultérieur à `timezone=True`,
décision à porter en PG3, hors périmètre PG1).

### 6.4 Tris et comparaisons implicites

- tous les tris applicatifs passent par `ORDER BY` explicite (ORM) : aucune dépendance au
  format texte SQLite pour l'ordre chronologique ;
- `audit_trail.py:65` trie les lignes par `(position, id)` — portable ;
- `liasse.py:53` déclare `order_by="LiasseCell.id"` sur la relation — portable ;
- ⚠️ **MEDIUM (à tester en PG2)** : certaines listes sont rendues **sans `ORDER BY`**
  (ex. énumérations de référentiels) — l'ordre physique diffère entre SQLite et PostgreSQL ;
  la recette PG2 doit vérifier les écrans/états concernés (aucun impact comptable).

---

## 7. PK / FK / contraintes / index

### 7.1 Clés primaires et identifiants auto-générés

- **41 tables** : `id INTEGER PRIMARY KEY` (`autoincrement='auto'`) → PostgreSQL créera une
  **séquence** (`SERIAL`/`IDENTITY`) pour chacune : leur valeur devra être **resynchronisée**
  après import (§ 16) ;
- **2 tables à PK composite** : `user_roles (user_id, role_id)` et
  `user_companies (user_id, company_id)` → pas de séquence ;
- **hypothèses SQLite sur `INTEGER PRIMARY KEY`** : aucune (`AUTOINCREMENT` absent, aucun
  `last_insert_rowid`, aucun `sqlite_sequence`) → aucun risque de « rowid » implicite ;
- **IDs utilisés comme références métier** : les ID internes ne sont **jamais** utilisés comme
  référence légale ; les références métier sont des chaînes
  (`FV202600001` / `FA26-…` via `app/core/numbering.py:19-54`, `IM202600001` pour les
  immobilisations, `CL0001` pour les tiers) → **les ID peuvent être réattribués sans impact
  fiscal** *à condition* de conserver les relations FK (import avec ID explicites : voir PG3) ;
- **IDs injectés explicitement** : aucun dans `app/` (seulement `user_id=1` dans un outil de
  maintenance, `tools/p1_reinitialiser_paie.py:302,324,349,394-397`) ;
- **logique dépendant du dernier ID inséré** : aucune (`db.flush()` + ORM uniquement).

### 7.2 Intégrité référentielle et contraintes réellement présentes en base

| Contrôle | Résultat mesuré | Commentaire |
|---|---|---|
| Contraintes FK déclarées | **102** (modèles) / **88** exprimées avec `ON DELETE` dans le DDL | 48 `CASCADE` + 40 `SET NULL` + `NO ACTION` |
| `ON UPDATE` | **0** (jamais utilisé) | rien à traduire |
| `PRAGMA foreign_key_check` | **0 violation** | base intègre |
| Détection d'orphelins (balayage de **toutes** les FK, 1 requête `NOT EXISTS` par FK) | **aucune ligne orpheline** | controles.sqlite/PG équivalents |
| Contraintes `UNIQUE` | **16** | dont `uq_invoices_company_number`, `uq_payslips_run_employee`, `uq_fiscal_years_company_year`, `uq_numbering_sequences_scope`… |
| Contraintes `CHECK` | **0** | aucune valeur à « assainir » avant import |
| Index | **104** (16 uniques, 88 non uniques) | recréés par Alembic |

### 7.3 Types permissifs SQLite susceptibles d'être refusés par PostgreSQL

Contrôle de `typeof()` sur **toutes** les colonnes de **toutes** les tables
(sortie `db_types.txt`) : les seuls types stockés sont `integer`, `real`, `text`, `null`.
Aucune anomalie de type croisé (pas de texte dans une colonne numérique, pas de date illisible).
Les points sensibles relevés sont :

| Colonne | Déclaré | Types réellement stockés | Impact import PG |
|---|---|---|---|
| `entry_lines.debit` / `.credit` | `NUMERIC(14,2)` | `integer` 548 / `real` 74 (resp. 521/101) | import typé `::numeric(14,2)` — 0 décimale excédentaire (vérifié) |
| `payroll_runs.total_*`, `payslips.*` (12 colonnes) | `NUMERIC(14,2)` | `real` — parfois `integer` | idem |
| `payslip_lines.base/retenue`, `payslips.frais_professionnels`, `net_imposable`, `cotisations_salariales`, `ir`, `net`, `prestations_familiales`, `taxe_formation` | `NUMERIC(14,2)` | mix `integer`/`real` | idem |
| `fiscal_years.closed_at`, `entries.validated_at` | `DATETIME` | `text` (`… .ffffff`) | import `::timestamp` |
| `entries.notes`, `audit_log.payload_json`… | `TEXT` | `text`/`null` | direct |
| `accounts.is_collectif`, `is_active`, 14 autres `Boolean` | `BOOLEAN` | `integer` (0/1 uniforme) | import `::boolean` (`0/1/true/false` acceptés) |

**Aucune correction n'est requise dans les modèles** ; la vigilance porte sur la **procédure
d'import** (PG3).

### 7.4 Identifiants / séquences : liste des tables à `setval(...)`

**41 tables** ont une PK mono‑colonne entière : leur séquence PostgreSQL devra être
repositionnée sur `MAX(id)` (ou `1,false` si la table est vide). Liste complète (valeurs
relevées en lecture seule, `checks.txt`) :

```
accounts 895 | activity_events 1 | asset_depreciation_lines 3 | asset_events (vide)
assets 2 | audit_log 593 | bank_reconciliations 11 | bank_statement_lines 54
bank_statements 10 | companies 1 | e_invoice_documents 8 | employees 5
entries 234 | entry_lines 712 | fiscal_years 2 | greffe_deposits 1 | greffe_documents 5
greffe_events 2 | greffe_payments 1 | invoice_lines 74 | invoices 74 | journals 6
liasse_cells (vide) | liasse_tables (vide) | numbering_sequences 2 | pay_contracts 8
payments 142 | payroll_runs 24 | payslip_lines 240 | payslips 60 | period_locks (vide)
roles 6 | stock_count_lines 33 | stock_counts 11 | stock_items 3 | stock_movements 12
stock_provisions (vide) | tax_declarations 3 | third_parties 4 | users 1 | vat_rates 3
```

**Points d'attention** :

- `bank_reconciliations` : `MAX(id)=11` pour **10 lignes** → un ID a été supprimé ; `setval`
  doit utiliser le **MAX réel (11)**, jamais `COUNT(*)` ;
- `entries` : `MAX(id)=234` pour 208 lignes et `entry_lines` : `MAX(id)=712` pour 622 lignes
  (contre‑écritures supprimées/rejouées) → même remarque ; ces trous sont **normaux** et
  n'affectent ni la numérotation légale (`entry_number` = `EC…`) ni le chaînage
  (ordonné par `id`) ;
- `tax_declarations` : `MIN(id)=2` → la table démarre à 2 ;
- 5 tables vides (`asset_events`, `liasse_cells`, `liasse_tables`, `period_locks`,
  `stock_provisions`) → `setval(seq, 1, false)` ;
- sans `setval`, la **première insertion** post‑migration échouerait en `UniqueViolation`
  (contrainte de PK) → **BLOCKER opérationnel si oublié en PG3** (voir § 16).

**Aucun `setval` n'a été exécuté en PG1.**

---

## 8. SQL brut et fonctions SQL

**Périmètre** : uniquement le SQL **réellement exécuté par l'application**.

| Requête / construction | Fichier:ligne | Portable ? | Adaptation |
|---|---|---|---|
| `cursor.execute("PRAGMA foreign_keys=ON")` | `app/db/session.py:35` | **non** (SQLite) | déjà neutralisé (retour si non‑SQLite) |
| 386 points d'exécution ORM (`session.execute(select(...))`, `db.get()`, `db.flush()`) | `app/**` | **oui** (SQLAlchemy Core/ORM) | aucune |
| `func.now()` (server_default) | 37 colonnes | oui (`now()` PG / `CURRENT_TIMESTAMP` SQLite) | voir fuseau (§ 6.3) |
| `func.count()`, `func.sum(...)`, `func.abs(...)`, `func.distinct(...)`, `func.coalesce(...)` | `services/accounts.py:57`, `parties.py:27,75,125-126`, `reporting.py:37-38,169-170`, `vat.py:124-125`, `ecrans_lecture.py:516,653,657`, `closing.py:553`, `web/routes.py:273,1043,1497,1581,1590` | **oui** | aucune |
| `.limit(1)` / `.limit()` / `.offset()` (ORM) | `audit_trail.py:89`, listes paginées | oui | aucune |
| `LIMIT 1` en SQL texte | `tools/p1_rapport_avant_apres.py:96,98` (hors runtime) | oui | aucune |
| `LIKE` préfixe (`account.number`) | `services/reporting.py:52,117`, `services/accounts.py:59`, `services/payroll.py:1123,1462`, `web/routes.py:2045-2047,2491`, `api/routers/accounts.py:29` | oui | aucune |
| `ILIKE` (recherche) | `api/routers/accounts.py:33`, `api/routers/parties.py:32`, `services/audit_trail.py:237`, `web/routes.py:329,469,1030` | oui (émulé par SQLite, natif PG) | **MEDIUM** : sémantique de casse/accents à valider (§ 14) |
| `SAVEPOINT` (`db.begin_nested()`) | `services/assets.py:815`, `services/stocks.py:612,722` | oui (psycopg3) | à tester sous PG |
| `SELECT … FOR UPDATE` (`with_for_update()`) | `core/numbering.py:43` | oui (PG), ignoré par SQLite | comportement **nouveau** en PG (positif) à tester |
| `ORDER BY` explicites | nombreux | oui | aucune |
| Concaténation SQL `||`, `concat()` | **0 occurrence** | — | — |
| `CAST(...)` SQL | **0 occurrence** | — | — |
| UPSERT (`ON CONFLICT`, `INSERT OR REPLACE`, `pg_insert`) | **0 occurrence** | — | — |
| Fonctions de date SQL (`strftime`, `date()`, `datetime()`, `julianday`) | **0 occurrence** dans `app/` | — | — |
| `strftime` SQL dans un outil | `tools/p1_inventaire_paie.py:54,217` | non (SQLite) | outil d'analyse : à réécrire (`EXTRACT(YEAR FROM …)`) si nécessaire sur PG |
| `text(...)` ORM | `alembic/versions/*` (`(CURRENT_TIMESTAMP)`) ; `tools/p1_rapport_avant_apres.py:96,98` | oui | aucune |

**Conclusion § 8** : hors `PRAGMA` (neutralisé) et un `strftime` dans un outil hors runtime,
**il n'existe aucun SQL propriétaire exécuté**. Le schéma de requêtes reposera à l'identique
sur PostgreSQL.

---

## 9. Alembic

### 9.1 Configuration

| Élément | Fichier:ligne | Constat |
|---|---|---|
| `script_location`, `prepend_sys_path` | `alembic.ini:5-6` | OK |
| URL | `alembic.ini:8` (repli) **écrasée** par `alembic/env.py:19` (source unique : `DATABASE_URL`) | OK |
| Mode batch | `alembic/env.py:26-27` (`render_as_batch = settings.is_sqlite`) | **conditionnel** → sur PG : ALTER directs |
| `compare_type=True` | `alembic/env.py:36,55` | permet de détecter toute divergence de type |
| Connexion | `alembic/env.py:44-59`, `pool.NullPool` | OK |
| `target_metadata` | `alembic/env.py:24` (`Base.metadata` via `import app.models`) | identique à l'application |

### 9.2 Historique (9 révisions, chaîne linéaire unique)

```
91754af8ef74 (schema_initial_cgnc, down=None)
  → c1d801a10835 (immobilisations_p1_2)
  → 07e35b18ce2e (audit_p1_6: period_locks, banque, chainage)
  → 8cf2d7792aa2 (stocks_p1_3)
  → 9ee74a029f0a (greffe_p1_5)
  → 56d9985cc7ff (paie_p1_4)
  → a7f3c51d8b42 (liasse_p2_1)
  → c4b8e17f2d95 (j8 p2_2/p2_3: activity_events, e_invoice)
  → p1c1a2b3d4e5 (dates_societe_constitution_exploitation)  ← HEAD
```
`alembic_version` en base = `p1c1a2b3d4e5` = **HEAD** → le schéma de référence a bien été
produit par Alembic (aucun décalage de révision).

### 9.3 Compatibilité PostgreSQL des migrations

| Contrôle (script unique sur `alembic/versions/*.py`) | Résultat |
|---|---|
| Occurrences de `sqlite` / `sqlite3` | **0** |
| Occurrences de `op.execute` / SQL brut | **0** |
| Occurrences de `postgresql` / dialecte explicite | **0** |
| `sa.Enum` / types propriétaires | **0** |
| `op.batch_alter_table(...)` | 86 lignes (toutes les colonnes/index ajoutés après coup) → **portable** : Alembic bascule en ALTER direct hors SQLite |
| `server_default=sa.text('(CURRENT_TIMESTAMP)')` | accepté par PostgreSQL |
| Index nommés via `op.f('ix_…')` / `op.f('uq_…')` | conforme à la convention de nommage (`app/db/base.py:10-16`) |

➡️ **Les migrations sont rejouables telles quelles sur PostgreSQL.**

### 9.4 Créations de schéma **hors Alembic** (point de vigilance)

| Fichier:ligne | Contexte | Risque |
|---|---|---|
| `app/db/seed.py:231` | `Base.metadata.create_all(bind=engine)` (`python -m app.db.seed --create-tables`) | contourne l'historique Alembic → **à interdire sur PG** |
| `tools/charger_plan_comptable.py:94` | `create_all` avant import du plan comptable | outil |
| `tools/import_achats_fournisseurs.py:497` | `create_all` avant import | outil |
| `tests/conftest.py:31` | `Base.metadata.create_all(engine)` (base en mémoire) | acceptable pour les tests |

Aucune contrainte/index « hors Alembic » n'a été détectée dans la DB de référence : les
104 index et 102 FK correspondent à ceux des migrations (comparaison metadata ↔ DB = 0 écart).

### 9.5 Recommandation (détaillée en § 16)

**A. rejouer Alembic sur une base PostgreSQL vide (`alembic upgrade head`) puis importer les
données** — **recommandé** ;
**B.** `create_all` + `alembic stamp head` — **rejeté** (dérive de schéma possible, perte de
l'historique versionné, et `alembic_version` non prouvé).

---

## 10. Tests

**Aucun test n'a été modifié ni exécuté en écriture** (PG1 est read-only). Une **collecte**
(`pytest --collect-only -q -p no:cacheprovider`, sans exécution ni création de cache) a
toutefois été réalisée pour vérifier la baseline.

| Élément | Constat |
|---|---|
| Fichiers | 36 `tests/test_*.py` + `tests/conftest.py` |
| Tests collectés | **456** — conforme à la baseline annoncée (`456/456 PASS`) |
| Fixture principale | `tests/conftest.py:23-37` : `create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)` puis `Base.metadata.create_all(engine)` |
| Isolation | une base **en mémoire** par test (`engine.dispose()` en fin de fixture) |
| Client HTTP | `tests/conftest.py:69-80` : `TestClient(app)` + `app.dependency_overrides[get_db]` |
| Usage `sqlite3` (module) | **0 fichier de test** |
| Accès au fichier `compta_ma.db` | **aucun** (les docstrings le précisent : `test_v7b_corrections_2025.py:18`, `test_web.py:3`) |
| `DATABASE_URL` / `setenv` dans les tests | **aucun** (URL SQLite codée en dur dans `conftest.py:27`) |
| Hypothèses d'ordre d'ID | aucune assertion du type `id == 1` ; seules des relations par FK sont vérifiées (ex. `test_menu_p2.py:170,189`, `test_accounting.py:63`) |
| Hypothèses de verrouillage | les tests de verrous portent sur la **logique métier** (`period_locks`), pas sur le locking SQLite (`test_audit_trail.py:100-171`, `test_payroll.py:268`, `test_stocks.py:328-331`, `test_greffe.py:455`) |

**Points d'adaptation identifiés (PG2)** :

1. `conftest.py:26-30` : base **SQLite en mémoire + `StaticPool`** → non transposable à
   PostgreSQL (une base PG est un serveur). Il faudra un fixture **paramétrable** :
   `DATABASE_URL` de test (SQLite par défaut, PostgreSQL si fourni) avec, pour PG, un
   `schema` dédié créé par `create_all`/`alembic upgrade head` et **remise à zéro par
   test** (rollback de transaction ou `TRUNCATE`).
2. `test_v7b_corrections_2025.py`, `test_paie_source_unique.py`, `test_greffe_contenu.py`
   (tests d'égalité stricte de montants/chainages) doivent être **exécutés sur les deux
   dialectes** pour prouver l'invariance des résultats comptables (§ 6).
3. Les tests de **concurrence** absents aujourd'hui (numérotation simultanée, verrou de
   période pendant une écriture) devront être ajoutés côté PostgreSQL — un point de la dette
   ne peut pas être couvert par une base sérialisée comme SQLite.
4. `filterwarnings` de `pytest.ini:5-6` masque l'avertissement SQLAlchemy
   « does not support Decimal objects natively » (spécifique SQLite) : sur PostgreSQL
   l'avertissement disparaîtra ; le filtre peut rester sans effet de bord.

**Préconisation** : PG2 doit viser **456 PASS sur SQLite et 456 PASS sur PostgreSQL**
(ou, à défaut documenté, un jeu « PG‑only » strictement croissant pour les points 2 et 3).

---

## 11. Concurrence / transactions

| Point | Fichier:ligne | Analyse | Classification |
|---|---|---|---|
| Numérotation des documents | `app/core/numbering.py:36-54` (`.with_for_update()`), appelée par `services/accounting.py:210`, `services/invoicing.py`, `services/payroll.py` | sur SQLite le verrou est **ignoré** ; sur PostgreSQL il **fonctionnera réellement** (bonne protection) — à tester | à tester sous PostgreSQL |
| Numérotation des écritures | `services/accounting.py:208-210` (`EC…` via la même séquence) | même remarque ; les contraintes `UNIQUE` (`uq_numbering_sequences_scope`, `uq_invoices_company_number`) protègent des doublons | à tester sous PostgreSQL |
| Trace d'un refus de période | `services/period_locks.py:79-109` | **seconde session** sur le **même engine** + `commit()` pendant que la transaction principale peut tenir des verrous (ligne `period_locks`, `entries`) → risque de **blocage / interblocage** et de trace perdue ; sur SQLite (fichier) le comportement est également fragile mais sérialisé | **correction requise avant live** (PG2) |
| Clôture d'exercice | `services/closing.py:239-281` (statut `closed` + à‑nouveaux dans la même transaction) | aucun verrou de ligne sur `fiscal_years` : deux clôtures simultanées pourraient s'entrelacer (le statut est testé puis écrit) | à tester / à renforcer en PG2 |
| Clôture / réouverture | `services/closing.py:400-430` (`closed_at`) + `services/accounting.py` | idem ; la réouverture est gardée par les statuts applicatifs | à tester |
| Génération de paie | `services/payroll.py` (préparer/valider/payer un `payroll_run`) | une seule écriture globale par cycle ; `uq_payslips_run_employee` empêche les doublons ; écritures + paiement + DTS liés | à tester sous PostgreSQL |
| Références métier | `services/greffe.py` (codes pièces), `services/assets.py:947+` (codes `IM…`), `services/invoicing.py` | générées par compteur applicatif/`numbering_sequences` | à tester |
| Transactions imbriquées | `services/assets.py:815`, `services/stocks.py:612,722` (`begin_nested`) | SAVEPOINT supporté par psycopg3 ; une erreur est isolée par fiche | à tester sous PostgreSQL |
| `flush()`/`commit()` | ~160 `commit/rollback` dans `web/routes.py`, `get_db` par requête | modèle « une transaction par requête » inchangé | aucun risque |
| Isolation | aucune configuration (READ COMMITTED par défaut PG) | sur SQLite, les écritures sont sérialisées : des courses aujourd'hui **masquées** peuvent apparaître en PG | à tester + politique de reprise (`IntegrityError` → relance de l'opération) — PG2 |
| Verrous de période | `services/period_locks.py:112-138` (lecture puis refus) | lecture sans `FOR UPDATE` : deux transactions pourraient verrouiller/déverrouiller en parallèle | à tester sous PostgreSQL |

**Synthèse § 11** : aucun risque de **corruption** de données identifié ; trois points
exigent un test dédié et **un correctif avant mise en production** :
(i) la trace de refus par seconde session (`period_locks.py:79-109`),
(ii) la politique de reprise sur conflit d'unicité (numérotation),
(iii) le verrouillage de `fiscal_years` à la clôture.

---

## 12. Outils de sauvegarde / maintenance liés au fichier SQLite

Ces outils ne sont **pas** exécutés par l'application, mais ils portent l'hypothèse
« la base est un fichier ». **Aucun n'a été supprimé ni modifié** (interdiction PG1).

| Outil | Fichier:ligne | Fonction | À remplacer par (PG3) |
|---|---|---|---|
| Purge recette | `tools/j9_purge_donnees.py:64-77` (`sauvegarder_base`), `:69` (`database_url.replace("sqlite:///","")`), `:75` (`shutil.copy2`) | copie horodatée `…bak-j9-<horodatage>` avant purge | `pg_dump` avant purge ; la branche « non SQLite : sauvegarde manuelle » existe déjà (`:66-68`) |
| Normalisation IF | `tools/normalize_fiscal_ids.py:48-54` (`chemin_sqlite`), `:99-103` (copie `.bak-<horodatage>`) | copie avant réécriture | `pg_dump` |
| Chargement du plan comptable | `tools/charger_plan_comptable.py:50` (`DATABASE_URL=sqlite:///…`), `:94` (`create_all`), `:103-104` | copie avant import | `pg_dump` + suppression du `create_all` |
| Import achats/fournisseurs | `tools/import_achats_fournisseurs.py:87`, `:191-192`, `:497` | copie avant import | idem |
| Régularisation P1B | `tools/p1b_stage3_regularisation.py:78-79` (`sha256_fichier`), `:120-125` (copie + SHA **du fichier DB**) | point de restauration + intégrité par SHA de fichier | `pg_dump`/`pg_restore` ; intégrité vérifiée par requêtes (comptages, `SUM`, chainage) |
| Recette des menus | `tools/p2_recette_menus.py:59`, `:64-65` (`shutil.copy2` → `%TEMP%` puis `DATABASE_URL`) | recette sur copie | base/schéma PG de recette |
| Rapport avant/après | `tools/p1_rapport_avant_apres.py:62,327-329` (glob `compta_ma.db.bak-p1-*`, `create_engine(sqlite:///…)`) | compare base courante ↔ sauvegarde fichier | comparaison de deux schémas PG |
| Réinitialisation paie | `tools/p1_reinitialiser_paie.py:36,58-63` | exige `.bak-p1-*` avant écriture | exiger un `pg_dump` horodaté |
| Audit d'anomalies J9 | `tools/j9_audit_anomalies.py:625` (`sqlite3.connect`) | lecture directe du fichier | connexion PG (`psycopg`) |
| Inventaire paie | `tools/p1_inventaire_paie.py:21,54,217,233` | `sqlite3` + SQL `strftime` | connexion PG + `EXTRACT(YEAR FROM …)` |
| Contrôles greffe | `tools/p1_greffe_finaliser_2025.py:62-66`, `tools/p1_greffe_verif_2025.py:76` | SHA-256 des **pièces PDF** sur disque (hors base) | **inchangé** (pièces hors base) |
| Script d'audit local | `audit_env_local_compta_ma.ps1` | SHA du fichier `compta_ma.db` | à adapter |
| Lancement local | `lancer_compta.bat` | `uvicorn app.main:app --reload` | inchangé |
| Sauvegardes présentes | **16 fichiers** `compta_ma.db.bak-*` (339 Ko → 1,23 Mo, 19/09 → 09/10/2026) | points de restauration par copie | ne pas restaurer en PG3 ; conserver en archive |
| Ignorés par git | `.gitignore:16-20` (`*.db`, `*.sqlite`, `*.bak*`) | DB et sauvegardes non versionnées | prévoir une politique de conservation des `pg_dump` |
| Docker | `docker-compose.yml:13-14` (volume `postgres_data`), `Dockerfile` | volume PG déjà prévu | sauvegarde `pg_dump` planifiée |

**Recommandation PG3** : chaque « point de restauration par copie » devient
`pg_dump --format=custom` + `pg_restore` (ou `pg_basebackup` pour une sauvegarde physique) ;
les 16 `.bak-*` restent des **archives de l'ère SQLite** (non restaurées).

---

## 13. Inventaire DB (golden baseline)

**44 tables** (43 métier + `alembic_version`), **0 vue**, **0 trigger**,
`integrity_check = ok`, `foreign_key_check = 0 violation`, **3 132 lignes** au total
(dont 1 ligne `alembic_version`). Société : `SOCIETE RECETTE MAROC SARL AU`
(ICE `001234567000099`, IF `1234567`). Exercices : **2025 = closed**, **2026 = open**.
`journal_mode = delete`, `freelist_count = 0`, aucune table `sqlite_sequence`.

| Table | Lignes | MAX(id) | Commentaire |
|---|---|---|---|
| `accounts` (plan comptable CGNC) | 895 | 895 | référentiel partagé |
| `vat_rates` | 3 | 3 | barème TVA historisé |
| `roles` / `users` / `user_roles` / `user_companies` | 6 / 1 / 2 / 1 | — / 1 / PK comp. / PK comp. | RBAC |
| `companies` / `fiscal_years` | 1 / 2 | 1 / 2 | 1 dossier, 2025 + 2026 |
| `journals` | 6 | 6 | AC/VE/BQ/CA/OD + 1 |
| **`entries`** | **208** | **234** | 208/208 validées et scellées |
| **`entry_lines`** | **622** | **712** | débit = crédit = `4 321 260,99` |
| `numbering_sequences` | 2 | 2 | compteurs de numérotation |
| `audit_log` | 593 | 593 | journal append‑only |
| `third_parties` | 4 | 4 | tiers |
| `invoices` / `invoice_lines` / `payments` | 74 / 74 / 142 | 74 / 74 / 142 | ventes + achats + règlements |
| **`payroll_runs`** | **24** | 24 | 12 mois 2025 + 12 mois 2026 |
| **`payslips`** / **`payslip_lines`** | **60 / 240** | 60 / 240 | bulletins et rubriques |
| `employees` / `pay_contracts` | 5 / 8 | 5 / 8 | salariés et contrats |
| **`tax_declarations`** | **2** | 3 (`MIN=2`) | registre TVA/DTS/IS/LIASSE |
| `assets` / `asset_depreciation_lines` | 2 / 3 | 2 / 3 | immobilisations |
| `stock_items` / `stock_movements` / `stock_counts` / `stock_count_lines` | 3 / 12 / 11 / 33 | — | stocks |
| `bank_statements` / `bank_statement_lines` / `bank_reconciliations` | 10 / 54 / 10 | 10 / 54 / **11** | rapprochement (1 ID supprimé) |
| `greffe_deposits` / `greffe_documents` / `greffe_events` / `greffe_payments` | 1 / 5 / 2 / 1 | — | dossier greffe 2025 |
| `e_invoice_documents` | 8 | 8 | e‑facturation |
| `activity_events` | 1 | 1 | régime d'activité |
| `asset_events`, `liasse_tables`, `liasse_cells`, `period_locks`, `stock_provisions` | **0** | — | 5 tables vides |
| `alembic_version` | 1 | — | `p1c1a2b3d4e5` |

**Tables critiques identifiées** : sociétés (`companies`), exercices (`fiscal_years`),
comptes (`accounts`), écritures (`entries`), lignes d'écriture (`entry_lines`),
paie (`payroll_runs`, `payslips`, `payslip_lines`, `pay_contracts`), salariés (`employees`),
fiscalité (`tax_declarations`, `vat_rates`, `liasse_tables`, `liasse_cells`),
audit (`audit_log`), greffe (`greffe_*`), banque (`bank_*`), stocks (`stock_*`),
immobilisations (`assets`, `asset_*`), tiers (`third_parties`), e‑facturation
(`e_invoice_documents`), activité (`activity_events`), verrous (`period_locks`).

**Repères comptables vérifiés en lecture seule (ORM + filtre par exercice)** :

| Contrôle | Attendu (baseline) | Mesuré | État |
|---|---|---|---|
| Résultat net **2025** | `52 043,87 DH` | charges 307 956,13 − produits 360 000,00 → **+52 043,87** | ✅ |
| Résultat **2026** (relevé) | `−113 307,20 DH` | charges 545 307,20 − produits 432 000,00 → **−113 307,20** | ✅ |
| Écritures scellées | 208/208, 0 rupture | `nb_scellees=208`, `ruptures=[]`, `integre=True` | ✅ |
| Dernière empreinte | — | `a47571c2ff07817d0c37524d69b253a147ad3e035e1daba11a04056e8a30f0f5` | ✅ |
| Équilibre global | débit = crédit | `4 321 260,99 = 4 321 260,99` (= `SUM` SQL, = somme `Decimal` exacte) | ✅ |

**Aucune donnée n'a été exportée, copiée ou transformée en PG1.**

---

## 14. Classification des écarts

### 14.1 BLOCKER — **0 constat**

Aucun élément n'empêche la migration : aucun SQL propriétaire exécuté, aucune contrainte
SQLite non traduisible, aucune donnée non convertible, aucun type financier flottant,
`alembic_version` déjà à `head`.

### 14.2 HIGH — 2 constats (« risque d'altérer données/comptabilité »)

| # | Fichier:ligne | Problème | Raison | Correction recommandée | Phase |
|---|---|---|---|---|---|
| H1 | `app/services/period_locks.py:79-109` (appelé par `controler_periode`, routes web, outils d'import) | trace d'un refus de période écrite par une **seconde session** (`SessionClass(bind=bind)` + `session.commit()`) pendant que la transaction principale peut tenir des verrous | sur PostgreSQL la seconde transaction peut **attendre un verrou** ou produire un **interblocage** ; la trace peut aussi être perdue si la transaction principale est annulée/relancée. Sur SQLite (fichier) le risque était masqué par la sérialisation ; en cas d'échec, la **preuve d'audit du refus** (exigence CGNC) manque | écrire la trace **hors du chemin de refus** : dans la **même transaction** (et laisser l'appelant décider), ou via une **connexion dédiée en autocommit avec `statement_timeout`** et reprise sur erreur, ou par **file différée** ; ajouter un test de non‑interblocage | **PG2** |
| H2 | procédure PG3 (aucune ligne de code) | **absence de `setval()`** sur les 41 séquences après import | PostgreSQL refuserait la **première** insertion post‑migration (`UniqueViolation` sur la PK) : blocage total de la saisie (écritures, factures, paie) | exécuter le `setval` documenté (§ 7.4) **avant** l'ouverture applicative, puis tester la création d'une écriture | **PG3** |

### 14.3 MEDIUM — 8 constats (« adaptation nécessaire mais maîtrisable »)

| # | Fichier:ligne | Problème | Raison | Correction recommandée | Phase |
|---|---|---|---|---|---|
| M1 | procédure d'import (aucun code) | SQLite stocke dates/heures/booléens/montants en `TEXT`/`INTEGER`/`REAL` (typage dynamique) | un `COPY` brut chargerait des `text` dans des `date`/`timestamp`/`boolean`/`numeric` ; un cast implicite mal choisi pourrait arrondir un montant | import **en deux temps** (table de transit `text` + `INSERT … SELECT …::date/::timestamp/::boolean/::numeric(14,2)`), avec contrôle `ROUND(x,2)=x` et comptage des lignes rejetées (§ 16) | **PG3** |
| M2 | `app/db/session.py:20-26` | pool non configuré (défauts) | en multi‑utilisateurs : coupures d'`idle`, saturation (5+10) | ajouter `pool_size`, `max_overflow`, `pool_recycle`, `pool_timeout` conditionnés à `not is_sqlite` (`pool_pre_ping` déjà présent) | **PG2** |
| M3 | `app/core/config.py:33`, modèles (`func.now()`), serveur PG | fuseau : `CURRENT_TIMESTAMP` historique = **UTC** ; `now()` PG dépend du `TimeZone` de session ; `datetime.now()`/`date.today()` dépendent du serveur | `created_at`/`validated_at`/`closed_at` pourraient être **décalés d'une heure** ; `date.today()` peut changer de jour près de minuit (exercice par défaut, échéances EDI/DTS) | fixer **`TZ=UTC`** (ou `PGTZ`) sur PostgreSQL et le conteneur applicatif, documenter la règle ; option ultérieure : `timezone=True` (décision PG3) | **PG2** |
| M4 | `tests/conftest.py:23-37` | fixture mono‑dialecte (SQLite `:memory:` + `StaticPool`) | impossible d'exécuter les 456 tests sur PostgreSQL en l'état → aucune preuve de recette PG2 | fixture paramétrable par `DATABASE_URL` (SQLite par défaut, PG en opt‑in), schéma PG dédié, remise à zéro par test, schéma créé par `alembic upgrade head` | **PG2** |
| M5 | `app/db/seed.py:231` ; `tools/charger_plan_comptable.py:94` ; `tools/import_achats_fournisseurs.py:497` | création de schéma **hors Alembic** (`Base.metadata.create_all`) | risque de **dérive** entre le schéma PostgreSQL et l'historique versionné | interdire `create_all` hors tests ; sur PG, seul `alembic upgrade head` crée le schéma ; conserver `alembic_version = p1c1a2b3d4e5` | **PG3** |
| M6 | `api/routers/accounts.py:33`, `api/routers/parties.py:32`, `services/audit_trail.py:237`, `web/routes.py:329,469,1030` | `ILIKE` : SQLite l'émule par `lower() LIKE lower()` (ASCII), PostgreSQL utilise `ILIKE` natif (locale) | une recherche **accentuée** peut retourner des résultats **différents** (aucun impact comptable) | valider les recherches en recette PG2 ; au besoin normaliser (`unaccent` ou colonne normalisée) | **PG2** |
| M7 | `app/core/numbering.py:43-54` + contraintes `uq_*` | conflit d'unicité possible sous concurrence réelle (numérotation facture/écriture) | SQLite sérialisait les écritures ; PostgreSQL en `READ COMMITTED` peut produire `IntegrityError` (le `FOR UPDATE` protège la séquence **si** la ligne existe) | **politique de reprise** (retry borné sur `IntegrityError`/`DeadlockDetected`), documenter l'isolation retenue, test de concurrence PG | **PG2** |
| M8 | `app/web/routes.py:140-146` (`safe_float`) + 22 appels | valeurs de formulaire converties via `float` avant stockage `Numeric(14,2)` | arrondi binaire → `float8 → numeric(14,2)` : à la marge, un montant saisi avec 3+ décimales peut être arrondi différemment | parser en `Decimal(str(valeur))` puis `money(...)` ; garder `float` pour l'affichage | **PG2** |

### 14.4 LOW — améliorations / nettoyage / tests supplémentaires

| # | Sujet | Fichier:ligne | Recommandation | Phase |
|---|---|---|---|---|
| L1 | URL de repli SQLite dans la configuration Alembic | `alembic.ini:8` | neutraliser (valeur inutilisée : source unique = `DATABASE_URL`) | PG2 |
| L2 | Outils dépendant de `sqlite3` / SQL `strftime` | `tools/p1_inventaire_paie.py:14,54,217,233`, `tools/j9_audit_anomalies.py:12,625`, `tools/p1_reinitialiser_paie.py:29` | rendre PG‑aware ou refuser explicitement l'exécution hors SQLite | PG3 |
| L3 | Listes sans `ORDER BY` | écrans de référentiels | ajouter des tris explicites stables | PG2 |
| L4 | Sauvegardes par copie de fichier | § 12 (9 outils, 16 `.bak-*`) | remplacer par `pg_dump`/`pg_restore` ; archiver les `.bak-*` | PG3 |
| L5 | Filtre d'avertissement SQLite | `pytest.ini:5-6` | conserver (sans effet sur PG) ; documenter | PG2 |
| L6 | Scripts d'audit locaux | `audit_env_local_compta_ma.ps1` | version serveur PostgreSQL (contrôles par requêtes) | PG3 |
| L7 | Tests de concurrence | *(absents)* | ajouter : numérotation simultanée, clôture simultanée, verrou de période pendant écriture | PG2 |

### 14.5 OK — compatibles sans changement (éléments notables)

- `app/db/base.py` (convention de nommage) et **tous les modèles** (§ 5) et **tous les types** (§ 5.2) ;
- `app/db/session.py` : `check_same_thread` conditionnel, `PRAGMA foreign_keys=ON` gardé,
  `sessionmaker(autoflush=False, expire_on_commit=False)` ;
- `app/core/numbering.py:43` : `.with_for_update()` (devient **actif**, donc protecteur, sur PostgreSQL) ;
- `app/services/audit_trail.py` : chaînage SHA‑256 **invariant** (Decimal restitué à l'échelle 2) ;
- **9 migrations Alembic** (§ 9.3) et `alembic_version = p1c1a2b3d4e5 = HEAD` ;
- `docker-compose.yml` (service `db`, volume, healthcheck) et `Dockerfile` ;
- `requirements.txt` : `psycopg[binary]==3.3.6`, **installé** (version 3.3.6 vérifiée dans `.venv`),
  `sqlalchemy==2.0.54`, `alembic==1.20.0`, Python 3.13.9 ;
- SQLAlchemy 2.x **ORM intégral** (0 SQL brut métier), `SAVEPOINT`
  (`assets.py:815`, `stocks.py:612,722`), `func.now()` / `func.sum` / `func.abs` ;
- intégrité DB : base saine, **0 orphelin**, **0 violation FK**, **0 doublon** d'unicité.

### 14.6 Décompte global

| Classe | Nombre |
|---|---|
| BLOCKER | **0** |
| HIGH | **2** |
| MEDIUM | **8** |
| LOW | **7** |
| OK (familles vérifiées) | structure, modèles, types, contraintes, index, migrations, intégrité, agrégats |

---

## 15. Adaptations nécessaires pour PG2

PG2 = correction du **code et de l'outillage**, **sans migration de données**.

| Ordre | Action | Cible (fichier) | Critère de sortie (preuve) |
|---|---|---|---|
| 1 | Corriger la trace de refus de période (H1) : suppression de la seconde session bloquante, transaction courte/autonome avec `statement_timeout`, reprise bornée | `app/services/period_locks.py:79-109` | test PG : refus de période tracé **sans blocage** ; `audit_log` contient `PERIOD_LOCK_REJECTED` |
| 2 | Configurer le pool (M2) | `app/db/session.py:20-26` | création d'engine PG avec `pool_size`/`max_overflow`/`pool_recycle` conditionnels |
| 3 | Figer le fuseau (M3) : `TZ=UTC`/`PGTZ` serveur + conteneur ; documenter | `docker-compose.yml`, `.env.example`, doc | `created_at` d'une écriture PG **comparable** aux valeurs UTC historiques |
| 4 | Rendre les tests bi‑dialectes (M4) et ajouter les tests de concurrence (L7) | `tests/conftest.py`, nouveaux tests | **456 PASS sur SQLite** (non‑régression) **et** 456 PASS sur PostgreSQL |
| 5 | Politique de reprise sur conflit d'unicité / interblocage (M7) | `app/core/numbering.py`, couche routes/services | test de numérotation concurrente : aucun doublon, aucune erreur remontée à l'utilisateur |
| 6 | Saisie sans `float` (M8) | `app/web/routes.py:140-146` + appels | montants de formulaire convertis par `Decimal(str(...))` ; tests de montants à 3 décimales |
| 7 | Valider la sémantique de recherche (M6) | 6 appels `ilike` | jeu de recherche accentuée documenté (résultat attendu PG) |
| 8 | Interdire `create_all` sur PG (M5) | `app/db/seed.py:231`, `tools/*` | le démarrage PG n'exécute que `alembic upgrade head` |
| 9 | Nettoyages LOW (L1, L3, L5) | `alembic.ini`, écrans, `pytest.ini` | revue de code + tests verts |

**PG2 ne doit pas** : créer/écrire la base PostgreSQL de production, importer les données,
ni modifier les règles comptables, ni refaire la recette 2025‑2026 (déjà validée).

---

## 16. Stratégie recommandée pour PG3

### 16.1 Décision : option **A**

> **A. Rejouer les migrations Alembic sur une base PostgreSQL vide (`alembic upgrade head`),
> puis importer les données de `compta_ma.db` avec des types explicites, puis resynchroniser
> les séquences (`setval`) et enfin vérifier l'égalité comptable.**

Argumentaire :

1. **Les 9 migrations sont dialecte‑agnostiques** (§ 9.3 : 0 `sqlite`, 0 `op.execute`,
   0 type propriétaire) et **batch mode désactivé** hors SQLite (`alembic/env.py:27`) :
   rejouer Alembic produit un schéma PostgreSQL **rigoureusement identique** aux modèles
   (`compare_type=True` permet de le prouver par un `alembic check`).
2. `alembic_version` sera automatiquement positionné à `p1c1a2b3d4e5` (= état SQLite de
   référence) → **historique continu**, aucune révision « tamponnée » à la main.
3. L'alternative **B** (`Base.metadata.create_all` + `alembic stamp head`) est **rejetée** :
   elle mélange deux sources de vérité de schéma, ne prouve rien sur l'ordre des
   migrations, et laisse `alembic_version` non vérifiable (dérive future garantie : les
   ALTER de la révision `p1c1a2b3d4e5` ne seraient pas « rejouables »).
4. Le contrat de non‑régression est **mesurable** : les 456 tests + les repères de la
   baseline (§ 13 : 52 043,87 / −113 307,20 / 208 écritures scellées / 4 321 260,99).

### 16.2 Procédure PG3 (pas à pas, ordre impératif)

| Étape | Contenu | Contrôle de sortie |
|---|---|---|
| 1 | **Geler SQLite** : arrêt de l'application, SHA‑256 de `compta_ma.db` relevé et conservé (`4E2C9EC3…B9101`) + copie d'archive horodatée (hors du dossier projet) | SHA identique, aucun accès applicatif |
| 2 | **Créer une base PostgreSQL vide** + un rôle applicatif ; `TZ=UTC` / `PGTZ=UTC` ; encodage `UTF8`, `lc_collate` choisi et documenté | `SELECT version(), current_setting('TimeZone')` |
| 3 | **`alembic upgrade head`** sur cette base (avec `DATABASE_URL=postgresql+psycopg://…`) | `alembic_version = p1c1a2b3d4e5` ; `alembic check` sans écart ; 43 tables + `alembic_version` ; 104 index ; 102 FK |
| 4 | **Exporter SQLite en lecture seule** : un fichier CSV **par table** (`sqlite3 -readonly … ".mode csv" "SELECT * FROM …"`), **toutes** les colonnes en texte, ordre `Base.metadata.sorted_tables` | 43 fichiers, comptage de lignes = § 13 |
| 5 | **Table de transit** par table (`*_stage` en `text`) + `COPY` des CSV | `COUNT(*)` identique table par table (3131 lignes métier) |
| 6 | **Conversion typée** : `INSERT INTO <table> SELECT <col>::date | ::timestamp | ::boolean | ::numeric(14,2) | ::numeric(14,3) | ::numeric(5,2) | ::integer | ::varchar(n) | ::text … FROM <table>_stage` — **avec ID explicites** (les FK sont conservées) | 0 ligne rejetée ; `SUM` par table identique ; aucune valeur de trimestre/horodatage perdue |
| 7 | **Contrôles aval** : `SELECT` d'orphelins (mêmes requêtes `NOT EXISTS` que PG1) → 0 ; unicité des 16 contraintes → 0 doublon ; `COUNT(*)` par table | **0 orphelin**, **0 doublon**, comptages identiques |
| 8 | **`setval`** sur les 41 séquences (§ 7.4) — y compris les 5 tables vides | création d'une ligne de test **refusée par transaction annulée** (aucune écriture résiduelle) |
| 9 | **Vérification comptable** sur PostgreSQL : résultat 2025 = `52 043,87` ; 2026 = `−113 307,20` ; débit = crédit = `4 321 260,99` ; `verifier_chainage` → 208/208, `integre=True`, dernière empreinte `a47571c2…0f0f5` | **égalité stricte** au centime et au hash |
| 10 | **Recette PG2/BASELINE sur PostgreSQL** : 456 tests verts (après les adaptations M4/L7) + parcours applicatif (facture → écriture, paie → DTS, liasse, greffe, états de synthèse) | 456/456 PASS + captures de recette |
| 11 | **Bascule** : `DATABASE_URL` PostgreSQL, `alembic upgrade head` au déploiement (jamais `create_all`), sauvegardes `pg_dump` planifiées, **SQLite conservée en lecture seule** (archive légale) | runbook documenté + sauvegarde testée (`pg_restore` sur base de contrôle) |

### 16.3 Points de vigilance propres à l'import

- **Ne jamais importer `alembic_version`** depuis SQLite (laisser Alembic l'écrire) ;
- **Ordre** : `Base.metadata.sorted_tables` (parents avant enfants) pour que les FK
  immédiatement validées le soient sans `DISABLE TRIGGER` (évite un accès superutilisateur) ;
  en cas d'import en désordre, reporter l'ajout des FK après chargement ;
- **`bank_reconciliations`/`entries`/`entry_lines`** : utiliser `MAX(id)` réel (11 / 234 / 712),
  **jamais** `COUNT(*)` ;
- **`entries.entry_hash` / `previous_hash`** : ne jamais recalculer pendant l'import ;
  contrôler **après** par `verifier_chainage` (les empreintes dépendent de `str(Decimal)`,
  invariant SQLite↔PG : § 6.1) ;
- **Textes longs** : `Text` (XML EDI, notes) → `COPY` avec `ENCODING 'UTF8'` ;
- **`varchar(n)`** : contrôler les longueurs avant import (SQLite ne les applique pas) —
  option : `SELECT max(length(col))` par colonne `String(n)` (aucune anomalie détectée par
  les contrôles de type, mais le contrôle est trivial à ajouter en PG3) ;
- **Aucune écriture** ne doit être faite dans `compta_ma.db` : l'export se fait en
  `-readonly` et le SHA final de la DB SQLite doit rester `4E2C9EC3…B9101`.

---

## 17. Preuve d'absence de modification

### 17.1 Base de données

| Contrôle | Valeur |
|---|---|
| SHA‑256 `compta_ma.db` **avant** PG1 | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| SHA‑256 `compta_ma.db` **après** PG1 | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| Égalité | **OUI (strictement identique, 7 vérifications intermédiaires)** |
| Accès en écriture | **aucun** : toutes les connexions en `mode=ro` (URI SQLite) ; aucun `INSERT/UPDATE/DELETE`, aucun `VACUUM`, aucune restauration |
| Taille / pages | 1 228 800 octets / 300 pages (inchangé) |
| `alembic_version` | `p1c1a2b3d4e5` (inchangé) |

> **Note de méthode (relevé final)** : au moment du contrôle final, le fichier était ouvert
> par un **processus externe** (deux interpréteurs Python résiduels de la session
> précédente), ce qui fait échouer `Get-FileHash`/`certutil` (`ERROR_SHARING_VIOLATION`).
> Le hash final a donc été relu par un flux `FileStream` ouvert en **`FileShare.ReadWrite`**
> (lecture seule, aucun verrou posé) : résultat **identique** à la valeur attendue. Le
> fichier n'a **pas** été modifié (`Length` = 1 228 800 o, `LastWriteTime` = 09/10/2026
> 14:28:16, antérieur à PG1).

### 17.2 Fichiers du projet

| Contrôle | Résultat |
|---|---|
| Fichiers applicatifs modifiés | **aucun** (code, modèles, Alembic, migrations, tests, `.env`, `DATABASE_URL`, configuration : intacts) |
| Fichiers supprimés / déplacés | **aucun** |
| Nouveau fichier créé dans le projet | **1 seul** : `PG1_AUDIT_COMPATIBILITE_SQLITE_POSTGRESQL.md` (le livrable autorisé) |
| Base PostgreSQL | **aucune** créée, **aucun** serveur démarré, **aucune** installation, **aucune** connexion testée |
| Packages | **aucune** mise à jour (`requirements.txt` et `.venv` intacts) |
| Recette réglementaire / comptable | **non refaite** (aucune écriture, aucun recalcul d'audit) |

### 17.3 Artefacts temporaires (hors projet)

Tous les scripts d'analyse read-only ont été créés **en dehors du projet**, dans
`%TEMP%\pg1\` (`scan.py`, `scan2.py`, `db_inv_schema.py`, `db_inv_data.py`, `model_audit.py`,
`checks.py`, `ro_check.py`, `sum_check.py`, `date_check.py` + sorties texte).
Aucun de ces fichiers ne fait partie du projet et aucun n'est exécuté par l'application.

### 17.4 Points explicitement **NON VÉRIFIÉS** en PG1 (par conception)

| Point | Raison | Suite |
|---|---|---|
| Exécution effective de la suite de tests | PG1 interdit de refaire la recette ; seule la **collecte** (456 tests) a été faite | PG2 : exécuter 456/456 sur SQLite **et** PostgreSQL |
| Comportement réel du serveur PostgreSQL (verrous, isolation, fuseau, `ILIKE` accentué) | aucun serveur PG autorisé en PG1 | **À VALIDER EN PG2** |
| Import effectif des données (conversion de types, `setval`) | PG3 | **À VALIDER EN PG3** |
| Longueurs `varchar(n)` vs données SQLite | contrôle non exécuté (aucune anomalie de type détectée) | contrôle trivial à ajouter en PG3 (§ 16.3) |
| `pg_dump`/`pg_restore` et restauration | PG3 | **À VALIDER EN PG3** |

---

## 18. Verdict

**PG1 PASS CONDITIONNEL — CORRECTIONS PRÉ-MIGRATION IDENTIFIÉES**

Justification :

- **Aucun BLOCKER** : aucune dépendance SQLite dans le runtime applicatif au-delà d'un
  `PRAGMA` déjà conditionné ; aucun motif SQLite non portable ; schéma, types, contraintes
  et index entièrement transposables ; piste d'audit reproductible ; migrations Alembic
  dialecte‑agnostiques et déjà à `head` ; base saine (0 orphelin, 0 violation FK,
  0 centime perdu, 0 colonne flottante).
- **Corrections pré‑migration identifiées** (à traiter **avant** la bascule) :
  - **PG2 (code/outillage, sans données)** : H1 (trace de refus de période par seconde
    session), M2 (pool), M3 (fuseau), M4 (tests bi‑dialectes), M7 (reprise sur conflit
    d'unicité), M8 (saisie sans `float`), M6 (recherche accentuée), L1/L3/L5/L7 ;
  - **PG3 (données)** : H2 (`setval` des 41 séquences), M1 (import typé), M5 (schéma
    exclusivement par Alembic), L2/L4/L6 (outillage et sauvegardes `pg_dump`).
- **Baseline protégée** : la DB de référence est **bit‑à‑bit inchangée**
  (`4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101`) et les repères
  métier sont confirmés à l'identique (2025 = **+52 043,87 DH**, 2026 = **−113 307,20 DH**,
  208/208 écritures scellées, 0 rupture).

**PG2 est autorisé** (corrections code/outillage + recette bi‑dialecte), **PG3 ne démarre
qu'après** validation des critères de sortie du § 15.

### FIN — PG1 (READ-ONLY) — STOP