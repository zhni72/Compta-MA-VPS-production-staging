# PG5B — Exécution réelle de la suite de tests sur PostgreSQL

| Élément | Valeur |
|---|---|
| Projet | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` |
| Interpréteur | `.venv\Scripts\python.exe` — Python **3.13.16** |
| SQLAlchemy / psycopg / Alembic | **2.0.54** / **3.3.6** / **1.20.0** |
| PostgreSQL | **18.1** (`localhost:5432`), timezone `Africa/Casablanca`, encoding `UTF8` |
| Base de tests | `compta_ma_test` — rôle `compta_ma_migrator` (schéma), rôle `compta_ma_test_runner` (exécution) |
| Base staging | `compta_ma_staging` — **jamais ouverte, jamais utilisée par les tests** |
| Révision Alembic | `p1c1a2b3d4e5` (**head**, identique des deux côtés) |
| Domaine | **PG5B** |
| **Verdict** | **PG5B STOP — CORRECTION APPLICATIVE POSTGRESQL REQUISE** |

> **Synthèse.** L'infrastructure de test multi-dialecte est **validée** : isolation
> transactionnelle fiable (SAVEPOINT), 461 tests **exécutés réellement sous PostgreSQL**
> (454 PASS), 0 donnée métier résiduelle, SQLite inchangé (461 PASS). **Mais** 6 tests
> `liasse` échouent sur un **bug applicatif PostgreSQL** (`regime` = 33 caractères écrit
> dans une colonne `VARCHAR(20)`), et 1 test porte une hypothèse d'ID propre à SQLite.
> Conformément aux §10-C / §16 / §17, **aucun code métier, modèle ou migration n'a été
> modifié** : PG5B s'arrête et documente.

---

## 1. Garde-fou (§0)

Vérification **unique** effectuée avant toute écriture, via `.venv\Scripts\python.exe`,
`psql 18.1` (`-w`, jamais d'invite de mot de passe) et `Get-FileHash`.

| Contrôle | Attendu | Constaté | Statut |
|---|---|---|---|
| cwd | `…\chat\compta_ma` | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` | ✅ |
| Python | 3.13.16 | `3.13.16` | ✅ |
| SQLAlchemy | 2.0.54 | `2.0.54` | ✅ |
| psycopg | 3.3.6 | `3.3.6` | ✅ |
| Alembic | 1.20.0 | `1.20.0` | ✅ |
| Client psql | 18.x | `18.1` (`PostgreSQL\18\bin\psql.exe`) | ✅ |
| Service PostgreSQL | actif | `postgresql-x64-18` = **Running** | ✅ |
| SHA-256 golden SQLite | `E18B8981…B7F0` | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` | ✅ |
| `compta_ma_test` existe | oui | `pg_database.datname = compta_ma_test` | ✅ |
| `compta_ma_staging` existe | oui (interdite) | `pg_database.datname = compta_ma_staging` (non utilisée) | ✅ |
| Rôle `compta_ma_migrator` | existe | `pg_roles` : présent | ✅ |
| Rôle `compta_ma_test_runner` | existe | `pg_roles` : présent | ✅ |
| `compta_ma_migrator → compta_ma_test` | OK | `current_user=compta_ma_migrator`, `current_database=compta_ma_test` | ✅ |
| `compta_ma_test_runner → compta_ma_test` | OK | `current_user=compta_ma_test_runner`, `current_database=compta_ma_test` | ✅ |
| Timezone | `Africa/Casablanca` | `current_setting('TimeZone')` = `Africa/Casablanca` | ✅ |
| Encoding | `UTF8` | `current_setting('server_encoding')` = `UTF8` | ✅ |

**Secrets.** Aucun mot de passe n'a été affiché, écrit dans le code, dans un rapport, dans
`.env` ou dans Git : l'authentification passe uniquement par
`%APPDATA%\postgresql\pgpass.conf` (lu par le processus). Aucune variable `PGPASSWORD`
n'est définie ; aucun fichier `.env` n'existe. Le rôle `postgres` n'a **jamais** été utilisé.

### 1.1 Incident de garde-fou (résolu par l'utilisateur, §1)

Au premier contrôle, `pgpass.conf` ne contenait **que 2 entrées**, toutes pour
`compta_ma_staging` (`compta_ma_migrator`, `compta_ma_app`) — **aucune pour `compta_ma_test`**.
Les deux connexions de garde-fou restaient bloquées sur une invite de mot de passe.
Conformément au §1 (« si pgpass ne permet pas l'authentification sur `compta_ma_test` :
STOP et demander à l'utilisateur »), PG5B a été **suspendu** et l'ajout des entrées a été
demandé (aucun mot de passe saisi de mon côté). Après ajout par l'utilisateur, le fichier
contient **4 entrées** : `compta_ma_staging` (migrator, app) + **`compta_ma_test`
(migrator, test_runner)**. Le garde-fou a alors été rejoué et **entièrement validé**.

---

## 2. État initial de `compta_ma_test` (§2)

Inspection préalable (rôle `compta_ma_migrator`, lectures seules) :

| Contrôle | Constaté |
|---|---|
| Tables `public` | **0** |
| Table `alembic_version` | absente (`to_regclass` = NULL) |
| Données métier | **0** (base vide) |

La base ne contenant pas le schéma applicatif, préparation **unique** exigée par le §2 :

```
DATABASE_URL=postgresql+psycopg://compta_ma_migrator@localhost:5432/compta_ma_test
python -m alembic upgrade head
```

Alembic (`alembic/env.py` lit `app.core.config.settings.database_url`) a appliqué **9/9**
migrations, chaîne linéaire `91754af8ef74 → … → p1c1a2b3d4e5`. **`create_all` n'a jamais
été utilisé sur PostgreSQL** (le modèle `app/db/base.py::creer_tables_dev` le refuserait de
toute façon).

État obtenu : **44 tables** (43 tables métier + `alembic_version`), révision
**`p1c1a2b3d4e5`**, **0 ligne métier**.

---

## 3. Architecture de la fixture SQLite / PostgreSQL (§3, §4)

Un **seul** point d'entrée de configuration : la variable d'environnement **`TEST_DATABASE_URL`**.

| `TEST_DATABASE_URL` | Backend de test | Schéma |
|---|---|---|
| **absent** (défaut) | SQLite `sqlite://` en mémoire (`StaticPool`, `check_same_thread=False`) | `Base.metadata.create_all(engine)` |
| `postgresql+psycopg://compta_ma_test_runner@localhost:5432/compta_ma_test` | **PostgreSQL réel** | **pré-créé par Alembic** (aucun `create_all`) |

Le `DATABASE_URL` *runtime* de l'application n'est **pas** détourné : `pytest` reste SQLite
par défaut ; seul `TEST_DATABASE_URL` active PostgreSQL.

### Garde-fou dur intégré à la fixture

`tests/conftest.py` valide l'URL **avant** toute connexion :

* le backend doit être `postgresql` ;
* `url.database` doit être **exactement** `compta_ma_test`, sinon `RuntimeError` immédiate.

Ainsi, aucune exécution ne peut viser `compta_ma_staging`, `postgres` ou toute autre base.

### Branche PostgreSQL

* **Interdits respectés** : pas de `create_all`, pas de `drop_all`, pas de `DROP DATABASE`,
  pas de `DROP SCHEMA`, pas de re-création Alembic par test.
* Le schéma pré-créé par Alembic est **réutilisé tel quel**.

---

## 4. Stratégie transaction / SAVEPOINT (§5)

Les tests appellent eux-mêmes `db.commit()` (et parfois `db.rollback()`). L'isolation repose
sur le mécanisme natif SQLAlchemy 2.0 `join_transaction_mode="create_savepoint"` :

1. **une connexion dédiée par test** : `connection = engine.connect()` ;
2. **une transaction externe ouverte avant le test** : `transaction = connection.begin()` ;
3. **une Session attachée à cette connexion**, en `create_savepoint` :
   `Session(bind=connection, join_transaction_mode="create_savepoint")` ;
4. les `db.commit()` du test deviennent des **`RELEASE SAVEPOINT`** : ils ne valident jamais
   la transaction externe. Les `db.rollback()` du test reviennent au savepoint courant ;
5. au teardown : `session.close()` puis **`transaction.rollback()`** → **toutes** les lignes
   du test sont annulées, puis `connection.close()` / `engine.dispose()`.

Aucun `commit()` n'est remplacé par un mock : **les vrais commits SQLAlchemy sont exécutés**
(les tests `test_period_locks_transactions.py` continuent de compter les `after_commit`).

### Séquences PostgreSQL (§6)

Les séquences ne sont **pas** transactionnelles : un `rollback` retire les lignes mais
laisse les séquences avancées. C'est un **comportement normal de PostgreSQL**, pas une fuite
métier. Le contrôle des tests a montré qu'**aucun** test ne dépend d'une valeur de PK fixe
`id == 1` (les occurrences `== 1` sont des comptages, des **numéros de période**, des ordres
ou des codes DGI) — à l'exception notable signalée au §9 (classe B). Aucun mécanisme de reset
de séquence n'a donc été ajouté, et aucun privilège supplémentaire n'a été accordé.

---

## 5. Fichiers modifiés (§15)

| Fichier | Nature | Détail |
|---|---|---|
| `tests/conftest.py` | **modifié** | Ajout de la branche PostgreSQL + garde-fou d'URL. La branche SQLite est **inchangée** (mêmes `sqlite://`, `StaticPool`, `check_same_thread=False`, `create_all`). |

**Aucun autre fichier de code n'a été modifié.** En particulier : `app/` (métier, modèles,
services), `alembic/`, `compta_ma.db`, `requirements*`, `.env`, `compta_ma_staging` : **intacts**.
Aucun package installé ou mis à jour. Aucune migration créée.

Artefacts de preuve produits (à la racine du projet) : `pg5b_batch_pg.xml`,
`pg5b_pg_full.xml`, `pg5b_pg_full.log`, `pg5b_sqlite_full.xml`, `pg5b_sqlite_full.log`.

---

## 6. Lot PostgreSQL ciblé (§8)

Exécution ciblée (max 2 exécutions autorisées) sur un lot représentatif, via
`TEST_DATABASE_URL=…compta_ma_test_runner…` :

`tests/test_period_locks_transactions.py`, `test_accounting.py` (CRUD), `test_api.py`
(client FastAPI), `test_payroll.py` (paie), `test_fiscal_liasse.py` (fiscalité/liasse),
`test_greffe.py` (Greffe).

| Tentative | Commande | Résultat |
|---|---|---|
| 1 | `pytest <lot> -q` | 91 tests, **0 échec** (côté tests), mais crash **après** les tests dans le ménage Windows de `tmp_path` (`PermissionError` sur la jonction `pytest-current`) → pas de ligne de synthèse, exit 1 |
| 2 | `pytest <lot> -q --basetemp=.pytest_tmp --junitxml=pg5b_batch_pg.xml` | **tests=91, failures=0, errors=0, skipped=0**, `EXITCODE=0` |

**Conclusion du lot ciblé** : fixture PostgreSQL **opérationnelle**, `commit`/`rollback`
internes neutralisés, client FastAPI fonctionnel, seeds OK, isolation OK. Aucune correction
de fixture n'a été nécessaire (le crash de la tentative 1 est un défaut de l'environnement
pytest/Windows, **sans rapport avec les tests** ; il est évité par `--basetemp`).

---

## 7. Résultats de la suite PostgreSQL complète (§9)

Exécution **unique** de la suite complète contre PostgreSQL (après validation du lot ciblé) :

```
TEST_DATABASE_URL=postgresql+psycopg://compta_ma_test_runner@localhost:5432/compta_ma_test
python -m pytest -q --basetemp=.pytest_tmp --junitxml=pg5b_pg_full.xml
```

| Métrique (JUnit `pg5b_pg_full.xml`) | Valeur |
|---|---|
| **tests** | **461** |
| **failures** | **7** |
| errors | 0 |
| skipped | 0 |
| time | 726.384 s |

**PostgreSQL : 454 PASS / 7 FAIL** — et **SQLite : 461 PASS / 0 FAIL** (cf. §12).
Les 461 tests SQLite ne sont **pas** comptés comme preuve PostgreSQL : les 454 PASS
ci-dessus sont issus d'une exécution **réelle** sur `compta_ma_test`.

### Liste des 7 échecs PostgreSQL

| # | Test | Cause immédiate |
|---|---|---|
| 1 | `test_audit_trail.py::test_sceller_ecritures_reprises_de_dossier` | `assert [323, 324] == [1, 2]` (hypothèse d'ID de PK) |
| 2 | `test_liasse.py::test_enregistrer_liasse_persiste_cellules_et_registre` | `StringDataRightTruncation` (`regime`) |
| 3 | `test_liasse.py::test_liasse_enregistree_absente_et_declaration_figee` | `StringDataRightTruncation` (`regime`) |
| 4 | `test_liasse.py::test_enregistrer_liasse_avec_fichier_hash_et_validation` | `StringDataRightTruncation` (`regime`) |
| 5 | `test_liasse.py::test_soumettre_declaration_depot_rejet_puis_figeage` | `StringDataRightTruncation` (`regime`) |
| 6 | `test_liasse.py::test_soumettre_declaration_accuse_de_reception_accepte` | `StringDataRightTruncation` (`regime`) |
| 7 | `test_liasse.py::test_dossier_liasse_et_registre` | `StringDataRightTruncation` (`regime`) |

---

## 8. Tests PostgreSQL spécifiques (§11)

**Non créés.** Le §11 conditionne leur ajout à la « réussite de l'infrastructure **et de la
suite compatible** ». La suite n'étant pas entièrement compatible (6 échecs applicatifs,
cf. §9 classe C), et le §17 imposant « si erreur applicative PostgreSQL : STOP », PG5B
s'arrête **avant** l'étape §11. Aucun fichier `tests/test_postgresql.py` n'a donc été ajouté,
et il n'y a **pas** de test spécifique PostgreSQL à rapporter (PG-T1 … PG-T4 non exécutés).

> Note : ces tests (FOR UPDATE, UNIQUE/IntegrityError, numérotation concurrente, verrouillage
> de période) sont **indépendants** du bug liasse ; ils pourront être ajoutés lors de la
> reprise PG5B dédiée, après correction applicative.

---

## 9. Classification des écarts (§10)

### Aucun écart de classe A (infrastructure)

L'isolation transactionnelle, le client FastAPI, les seeds et le garde-fou de base sont
**validés** (91/91 au lot ciblé, 0 ligne résiduelle après chaque exécution). Aucune correction
d'infrastructure n'a été requise.

### Classe B — Test spécifique à SQLite (1 test)

**`test_audit_trail.py::test_sceller_ecritures_reprises_de_dossier`**, ligne 245 :

```python
assert avant["non_scellees"] == [1, 2]
```

Le test **suppose que les identifiants d'écritures valent `1` et `2`**. Sous SQLite, chaque
test part d'une base neuve (séquence = 1, 2) ; sous PostgreSQL, les séquences sont globales et
ont été avancées par les tests précédents → `[323, 324]`. C'est exactement le cas prévu au §6
(« tests qui supposent une valeur exacte d'ID »).

* **Correction recommandée (à faire dans une passe dédiée)** : rendre l'assertion indépendante
  de la valeur arbitraire de PK, p. ex. comparer aux identifiants réellement présents en base :
  `ids = sorted(r for r in db.execute(select(Entry.id)).scalars())` puis
  `assert avant["non_scellees"] == ids`. Cela **améliore la portabilité sans réduire la valeur**
  du test (elle reste l'ordre des écritures).
* **Non appliquée dans PG5B** : la campagne est arrêtée par la classe C ci-dessous (§17).

### Classe C — Bug applicatif PostgreSQL (6 tests) → **STOP**

Les 6 tests `test_liasse.py` échouent tous sur la même cause :

```
psycopg.errors.StringDataRightTruncation: valeur trop longue pour le type character varying(20)
[SQL: INSERT INTO tax_declarations (… regime … ) VALUES (…)]
[parameters: {… 'regime': 'liasse_modele_comptable simplifié' …}]
```

Chaîne causale identifiée :

| Élément | Fichier / ligne | Valeur |
|---|---|---|
| Colonne du modèle | `app/models/declaration.py:79` | `regime: Mapped[str | None] = mapped_column(String(20))` → **VARCHAR(20)** |
| Constante applicative | `app/services/liasse_edi.py:68` | `MODELE_COMPTABLE_SIMPLIFIE = "liasse_modele_comptable simplifié"` → **33 caractères** |
| Écriture | `app/services/liasse_edi.py:1384-1395` | `TaxDeclaration(regime=liasse["modele"])` / `declaration.regime = liasse["modele"]` |

Sur **SQLite**, la longueur `VARCHAR(20)` n'est **pas** contrôlée : l'insertion de 33
caractères réussit silencieusement. Sur **PostgreSQL**, la contrainte est appliquée →
`StringDataRightTruncation` → l'application **ne peut pas enregistrer une liasse** (modèle
comptable simplifié) sous PostgreSQL. C'est une **incompatibilité de type/longueur** entre le
modèle et le code métier : **classe C**.

> **§10-C / §16 / §17 : NE PAS CORRIGER LE CODE MÉTIER DANS PG5B.** Aucune modification n'a
> été faite sur `app/models/declaration.py`, `app/services/liasse_edi.py`, ni aucune migration.
> Une **correction dédiée** est nécessaire (voir §15).

### Classe D — Différence métier

**Aucune.** Aucun écart de résultat comptable/fiscal constaté (tous les tests de calcul
fiscal/liasse et de réconciliation réussissent ; seul le stockage de la liasse échoue).

---

## 10. Contrôle d'isolation (§5, §7)

### Isolation transactionnelle (0 fuite métier)

Vérifié **après le lot ciblé** puis **après la suite complète** PostgreSQL, par comptage
exact de **toutes** les tables métier (via `SELECT count(*)` table par table) :

| Contrôle | Résultat |
|---|---|
| Tables métier contrôlées | **43** |
| **Total lignes métier résiduelles** | **0** |
| Tables non vides | **aucune** |

→ Malgré les `db.commit()` internes des tests, **aucune ligne métier ne subsiste** après
chaque test : la transaction externe est bien annulée au teardown.

### Sessions hors fixture (§7)

Recherche ciblée de `SessionLocal()` / `session_scope()` / `create_engine()` / `StaticPool`
dans `tests/` et `app/` :

| Emplacement | Constat | Impact |
|---|---|---|
| `tests/*.py` | aucune occurrence réelle (2 commentaires mentionnant SQLite) | aucun |
| `tests/conftest.py` | seule définition d'engine/session de test | — |
| `app/db/session.py` | `engine` / `SessionLocal` / `session_scope` (runtime applicatif) | neutralisé par `app.dependency_overrides[get_db]` du client de test |
| `app/db/seed.py:234` | `SessionLocal()` **uniquement** dans `main()` (CLI `__main__`) | non utilisé par les tests |

→ **Aucun** test ou service sollicité par la suite ne crée de seconde connexion contournant
l'isolation. Aucune documentation d'exception nécessaire.

---

## 11. État final de `compta_ma_test` (§12)

| Contrôle final | Résultat |
|---|---|
| Tables | **44** (43 métier + `alembic_version`) |
| Révision Alembic | **`p1c1a2b3d4e5`** (inchangée) |
| Lignes métier résiduelles | **0** |
| Lignes `alembic_version` | 1 (la révision) |
| Séquences | **avancées** (comportement PostgreSQL normal, non transactionnel) |
| `DROP DATABASE` / `DROP SCHEMA` | **jamais exécuté** |
| `compta_ma_staging` | **jamais ouverte ni modifiée** |

La base de test est **propre** (aucune donnée métier) ; seul l'avancement des séquences est
constaté, ce qui est documenté comme comportement normal de PostgreSQL.

---

## 12. Non-régression SQLite (§13)

Exécution **unique** de la suite normale, `TEST_DATABASE_URL` **absent** (donc SQLite) :

```
python -m pytest -q --basetemp=.pytest_tmp --junitxml=pg5b_sqlite_full.xml
```

| Métrique (JUnit `pg5b_sqlite_full.xml`) | Valeur |
|---|---|
| **tests** | **461** |
| failures | **0** |
| errors | 0 |
| skipped | 0 |
| time | 357.503 s |

→ **461 PASS / 0 failure** : la modification de `tests/conftest.py` **ne régresse pas** SQLite.
La branche SQLite est identique à l'origine. (Aucun test PostgreSQL dédié n'ayant été ajouté,
il n'y a pas de test en SKIPPED sous SQLite — cf. §8.)

---

## 13. SHA golden final (§14)

```
Get-FileHash -Algorithm SHA256 -LiteralPath '.\compta_ma.db'
```

| Attendu | Constaté | Statut |
|---|---|---|
| `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` | ✅ **inchangé** |

La golden SQLite n'a **jamais** été ouverte par les tests PostgreSQL (fixture `db` distincte).

---

## 14. Avertissements non bloquants (§12)

1. **Ménage `tmp_path` sous Windows** — lors de la 1re exécution du lot ciblé, pytest a levé
   `PermissionError` sur la jonction `…\Temp\pytest-of-ali\pytest-current` **après** les tests
   (ménage des répertoires numérotés). Défaut d'environnement, sans rapport avec les tests :
   évité de façon reproductible par `--basetemp`. **Aucun impact** sur les résultats.
2. **`StarletteDeprecationWarning`** — `Using httpx with starlette.testclient is deprecated`.
   Avertissement de dépendance, préexistant.
3. **Séquences PostgreSQL avancées** — normal (non transactionnel), pas une fuite métier.
4. **Séquence des tests** — sous PostgreSQL, la valeur des PK dépend de l'ordre des tests
   (séquences globales). C'est la cause de l'unique échec de classe B.

---

## 15. Verdict

# **PG5B STOP — CORRECTION APPLICATIVE POSTGRESQL REQUISE**

### Ce qui est validé

* Garde-fou complet (versions, SHA golden, service, bases, rôles, timezone, encoding, auth).
* Préparation de `compta_ma_test` **exclusivement** par Alembic (`p1c1a2b3d4e5`, 44 tables).
* Infrastructure de test **multi-dialecte** : SQLite par défaut, PostgreSQL via
  `TEST_DATABASE_URL`, garde-fou d'URL interdisant toute base ≠ `compta_ma_test`.
* Isolation transactionnelle **fiable** malgré les `commit()` internes (SAVEPOINT) : **0 ligne
  métier résiduelle**, aucune fuite, aucune modification de code métier.
* Lot ciblé PostgreSQL : **91/91**.
* Suite PostgreSQL **réelle** : **461 exécutés, 454 PASS, 7 FAIL**.
* Non-régression SQLite : **461/461 PASS**.
* SHA golden SQLite : **inchangé**.

### Pourquoi STOP

Un **bug applicatif PostgreSQL** (classe C) empêche l'enregistrement d'une liasse :

* **Colonne** : `tax_declarations.regime` = `VARCHAR(20)` — `app/models/declaration.py:79`.
* **Valeur écrite** : `"liasse_modele_comptable simplifié"` (33 caractères) —
  `app/services/liasse_edi.py:68` (`MODELE_COMPTABLE_SIMPLIFIE`), écrite en
  `app/services/liasse_edi.py:1384-1395`.
* SQLite ignore la longueur, PostgreSQL la fait respecter → `StringDataRightTruncation`
  sur 6 tests `test_liasse.py`.

Conformément aux §10-C / §16 / §17, **le code métier et le modèle n'ont pas été modifiés**.

### Correction dédiée requise (hors PG5B — mandat séparé)

Deux options, à trancher dans une passe dédiée :

1. **Élargir la colonne** `tax_declarations.regime` (p. ex. `String(50)`) via **une nouvelle
   migration Alembic** ; ou
2. **Stocker un code court** (p. ex. `"simplifie"`) dans `regime` et conserver le libellé long
   dans un mapping applicatif.

Puis relancer PG5B (le lot ciblé et la suite complète) pour confirmer les 6 tests liasse.

### Suites recommandées lors de la reprise

* Corriger l'unique échec de classe B (`test_audit_trail.py:245`) pour le rendre indépendant
  de la valeur de PK (portabilité, sans perte de valeur).
* Ajouter alors les tests PostgreSQL spécifiques (§11 : PG-T1 … PG-T4) — non réalisés ici car
  PG5B s'arrête avant cette étape.

**PG5B STOP — CORRECTION APPLICATIVE POSTGRESQL REQUISE. FIN.**