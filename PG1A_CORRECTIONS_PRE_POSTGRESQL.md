# PG1A — CORRECTIONS PRÉ-POSTGRESQL CIBLÉES

**Portée** : adaptations code-level sécurisables avant PG2, **sans** PostgreSQL,
sans migration, sans écriture métier en base.

**Verdict : PG1A PASS — PG2 AUTORISÉ**

---

## 1. Garde-fou base de données

| Mesure | Valeur |
|---|---|
| SHA-256 `compta_ma.db` **avant** | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| SHA-256 `compta_ma.db` **après** | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| Résultat | **strictement identique** |

Aucune donnée métier n'a été écrite (PG1A n'exécute aucune écriture sur `compta_ma.db`).

---

## 2. Fichiers modifiés

| Fichier | Nature |
|---|---|
| `app/services/period_locks.py` | **Correction A** — `_tracer_refus` n'ouvre plus de seconde session et ne fait plus de `commit()` caché. |
| `app/db/base.py` | **Correction B** — ajout du garde-fou `creer_tables_dev(engine)` (create_all réservé à SQLite). |
| `app/db/seed.py` | **B** — usage de `creer_tables_dev` à la place de `Base.metadata.create_all`. |
| `tools/charger_plan_comptable.py` | **B** — usage de `creer_tables_dev`. |
| `tools/import_achats_fournisseurs.py` | **B** — usage de `creer_tables_dev`. |
| `tests/test_period_locks_transactions.py` | **Nouveau** — tests ciblés de la correction A. |
| `PG1A_CORRECTIONS_PRE_POSTGRESQL.md` | **Livrable** (ce fichier). |

Aucun autre fichier applicatif, aucune révision Alembic, aucune dépendance,
aucun `DATABASE_URL` n'a été touché.

---

## 3. Correction `period_locks.py` (A — HIGH)

**Problème PG1 (H1)** : `_tracer_refus` ouvrait une **seconde session**
(`SessionClass(bind=bind)`) et y faisait un `session.commit()` alors que la
transaction métier appelante pouvait déjà tenir des verrous → risque
d'attente de verrou / d'interblocage sous PostgreSQL, et `commit()` caché
dans un service appelé au sein d'une transaction plus large.

**Correction appliquée** (`app/services/period_locks.py:57-88`) :

- la trace `PERIOD_LOCK_REJECTED` est désormais écrite **dans la session métier
  existante** (`log_action(db, ...)`) ;
- **aucune seconde session** n'est créée ;
- **aucun `commit()` implicite** n'est exécuté dans le service ;
- le **commit reste à la charge de l'appelant** (`log_action` fait un `flush`,
  pas un `commit` — conforme au contrat documenté de `app/core/audit.py`) ;
- l'appelant décide seul de **valider** (persister la trace) ou d'**annuler** la
  transaction.

La branche « base fichier » et la branche « base mémoire » sont **unifiées** :
le comportement fonctionnel exercé par les tests (SQLite en mémoire) est
**strictement conservé** (mêmes traces, même exception levée).

---

## 4. Traitement des `create_all` (B)

Les **3** usages non-tests recensés par PG1 ont été vérifiés une seule fois :

| Emplacement | Avant | Après |
|---|---|---|
| `app/db/seed.py:231` | `Base.metadata.create_all(bind=engine)` | `creer_tables_dev(engine)` |
| `tools/charger_plan_comptable.py:94` | `Base.metadata.create_all(bind=engine)` | `creer_tables_dev(engine)` |
| `tools/import_achats_fournisseurs.py:497` | `Base.metadata.create_all(bind=engine)` | `creer_tables_dev(engine)` |

**Garde-fou ajouté** (`app/db/base.py:27-39`) :

```python
def creer_tables_dev(engine: Engine) -> None:
    if not str(engine.url).startswith("sqlite"):
        raise RuntimeError(
            "create_all est reserve au developpement SQLite. Sur PostgreSQL, le "
            "schema est cree par Alembic : executez « alembic upgrade head »."
        )
    Base.metadata.create_all(bind=engine)
```

- **DEV / tests SQLite** : `create_all` reste autorisé (comportement inchangé) ;
- **production / staging PostgreSQL** : `create_all` est **refusé** (RuntimeError)
  → le schéma ne peut plus être créé hors Alembic ;
- **`tests/conftest.py:31`** : laissé **inchangé** (usage requis par les tests,
  base SQLite en mémoire) — conformément à la consigne.

Vérification du garde-fou (moteurs réels non connectés) :
`sqlite://` → `create_all` exécuté ; `postgresql+psycopg://…` → **RuntimeError**.

---

## 5. Tests ciblés

**Nouveau fichier** : `tests/test_period_locks_transactions.py` (5 tests) —
couvre les points demandés qui n'étaient pas déjà testés :

1. `test_creation_de_verrou_et_refus_trace` — **création de verrou** + refus tracé ;
2. `test_verrou_existant_refuse_le_doublon` — **verrou existant** ;
3. `test_trace_de_refus_suit_la_transaction_appelante` — **transaction appelante** ;
4. `test_rollback_appelant_annule_la_trace_de_refus` — **rollback** ;
5. `test_aucun_commit_implicite_dans_la_trace_de_refus` — **absence de double commit
   implicite** (écoute `after_commit` sur `Session` : aucun commit déclenché,
   transaction appelante toujours ouverte).

Couvrages préexistants réutilisés (non dupliqués) :
`tests/test_audit_trail.py` (verrou mensuel/annuel, doublon, déverrouillage),
`tests/test_stocks.py` (mouvement refusé + trace).

Commande :
```
.\.venv\Scripts\python.exe -m pytest tests/test_period_locks_transactions.py ^
    tests/test_audit_trail.py tests/test_stocks.py tests/test_reouverture_exercice.py -q
```
**Résultat : 44 PASS / 0 échec.**

---

## 6. Suite complète (une seule exécution)

```
.\.venv\Scripts\python.exe -m pytest -q
```

**Résultat : 461 PASS / 0 échec** (baseline 456 + 5 nouveaux tests).

---

## 7. Points reportés vers PG2 / PG3

| # | Point | Phase |
|---|---|---|
| 1 | **Survie de la trace de refus au `rollback` de l'appelant** : la trace appartient désormais à la transaction métier ; au niveau des routes (qui font `db.rollback()` sur `AccountingError`), elle ne sera persistée que si l'appelant valide. Décider de la politique (commit explicite de la trace par le gestionnaire de route, ou file différée). **Aucune preuve sans PostgreSQL : À VALIDER PG2.** | PG2 |
| 2 | Pool PostgreSQL (`pool_size` / `max_overflow` / `pool_recycle`) — H1 à rejouer sous concurrence réelle. | PG2 |
| 3 | Fuseau horaire PostgreSQL. | PG2 |
| 4 | Fixtures PostgreSQL, `ILIKE` (6 usages), politique de reprise sur `IntegrityError`/interblocage (M7). | PG2 |
| 5 | `setval()` des 41 séquences après import ; schéma via `alembic upgrade head` ; démarrage PG n'exécutant jamais `create_all` (le garde-fou B est désormais en place côté code). | PG3 |
| 6 | Types `TEXT` / types PostgreSQL. | PG3 |

Aucune autre anomalie détectée dans le périmètre ; rien hors périmètre n'a été corrigé.

---

## 8. Verdict

**PG1A PASS — PG2 AUTORISÉ.**