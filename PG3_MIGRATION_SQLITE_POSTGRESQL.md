# PG3 — MIGRATION CONTRÔLÉE SQLITE → POSTGRESQL

| Élément | Valeur |
|---|---|
| Projet (unique) | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` |
| Nature | Migration contrôlée de la golden DB SQLite vers `compta_ma_staging` (PostgreSQL 18) |
| Date | 2026-10-09 |
| Interpréteur | `.venv\Scripts\python.exe` — Python **3.13.16** |
| PostgreSQL | 18 (service `postgresql-x64-18`), `Africa/Casablanca`, `UTF8` |
| DB cible | `compta_ma_staging` — rôle d'import `compta_ma_migrator`, rôle runtime `compta_ma_app` |
| DB source | `compta_ma.db` (lecture **mode=ro** uniquement) |
| **Verdict** | **PG3 STOP — ANOMALIE DE MIGRATION** |

> **Résumé.** Le garde-fou est **PASS**, le schéma PostgreSQL a été créé par Alembic
> jusqu'à `p1c1a2b3d4e5` (44 tables, 41 séquences, 0 vue), la source SQLite a été lue
> intégralement en `mode=ro` (3 131 lignes, 43 tables). L'import typé a échoué **une seule
> fois** sur la table `tax_declarations` : la base golden contient
> `mode_depot = 'simulation'` (10 caractères) dans une colonne déclarée `VARCHAR(5)`.
> SQLite tolère cette valeur (typage laxiste) ; PostgreSQL la refuse
> (`StringDataRightTruncation`). La transaction a été **annulée** : PostgreSQL ne contient
> **aucune donnée métier**. Conformément aux § 6 et § 16, l'import **STOP** avant `setval`.
> La base SQLite de référence est **bit-à-bit inchangée**.

---

## 1. Garde-fou (exécuté une seule fois, avant toute écriture PostgreSQL)

| Contrôle | Attendu | Mesuré | État |
|---|---|---|---|
| cwd exact | `…\chat\compta_ma` | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` | ✅ |
| `.venv\Scripts\python.exe` | Python 3.13.16 | Python 3.13.16 | ✅ |
| psycopg disponible | oui | `psycopg 3.3.6` (SQLAlchemy 2.0.54, Alembic 1.20.0) | ✅ |
| SHA-256 SQLite | `4E2C9EC3…9101` | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` | ✅ |
| SQLite accessible en lecture seule | `mode=ro` | connexion `file:…?mode=ro` — écriture **refusée** (`create table` → erreur) | ✅ |
| PostgreSQL `compta_ma_staging` / `compta_ma_migrator` | accessible | connexion OK (`current_user=compta_ma_migrator`, `current_database=compta_ma_staging`) | ✅ |
| Timezone PostgreSQL | `Africa/Casablanca` | `Africa/Casablanca` | ✅ |
| Encoding | `UTF8` | `UTF8` | ✅ |
| Tables publiques PostgreSQL | **0** | **0** | ✅ |

**Tous les critères du garde-fou sont satisfaits.** Aucun critère d'arrêt (§ séparation des
identifiants) n'a été déclenché. Les mots de passe n'ont été ni écrits, ni affichés, ni
enregistrés : ils proviennent uniquement d'un fichier `pgpass` lu par le processus (variable
`PGPASSFILE`), et n'apparaissent dans aucun journal ni dans ce rapport.

---

## 2. SHA de la source SQLite

| Mesure | Valeur |
|---|---|
| SHA-256 avant phase | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| SHA-256 après phase | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| Résultat | **strictement identique** — la golden DB n'a pas été modifiée |

Toutes les lectures SQLite ont utilisé une connexion ouverte avec l'URI
`file:C:/…/compta_ma.db?mode=ro` (`uri=True`). Aucun `UPDATE` / `DELETE` / `INSERT` /
`VACUUM` / `PRAGMA` persistant n'a été émis. Une écriture-test (`CREATE TABLE`) a été
tentée et **rejetée par le moteur**, prouvant le caractère read-only de la connexion.

---

## 3. Schéma PostgreSQL (Alembic)

| Élément | Valeur |
|---|---|
| Rôle | `compta_ma_migrator` |
| `DATABASE_URL` (temporaire processus) | `postgresql+psycopg://compta_ma_migrator@localhost:5432/compta_ma_staging` (mot de passe via pgpass) |
| Commande | `python -m alembic upgrade head` (`alembic/env.py` lit `DATABASE_URL`) |
| Révisions appliquées | 9/9, chaîne linéaire `91754af8ef74 → … → p1c1a2b3d4e5` |
| `alembic_version` PG | **`p1c1a2b3d4e5`** = HEAD attendu = valeur SQLite | ✅ |
| Tables publiques | **44** = 43 métier + `alembic_version` | ✅ |
| Vues publiques | **0** | ✅ |
| Séquences publiques | **41** (attendu PG1 ≈ 41) | ✅ |
| `create_all` | **jamais appelé** (schéma 100 % Alembic ; garde-fou PG1A `creer_tables_dev` actif) | ✅ |
| Objets parasites | aucun (0 vue, 0 table hors modèle) | ✅ |

Le `.env` permanent n'a **pas** été modifié ; l'URL cible a été injectée uniquement dans
l'environnement du processus.

---

## 4. Inventaire source / cible (avant import)

PostgreSQL était **vide hors `alembic_version`** (1 ligne). L'inventaire PG1 (43 tables) a
servi de référence ; aucun re-scan complet du dépôt n'a été effectué.

| table | lignes SQLite | lignes PG avant |
|---|---|---|
| accounts | 895 | 0 |
| activity_events | 1 | 0 |
| alembic_version | 1 | 1 |
| asset_depreciation_lines | 3 | 0 |
| asset_events | 0 | 0 |
| assets | 2 | 0 |
| audit_log | 593 | 0 |
| bank_reconciliations | 10 | 0 |
| bank_statement_lines | 54 | 0 |
| bank_statements | 10 | 0 |
| companies | 1 | 0 |
| e_invoice_documents | 8 | 0 |
| employees | 5 | 0 |
| entries | 208 | 0 |
| entry_lines | 622 | 0 |
| fiscal_years | 2 | 0 |
| greffe_deposits | 1 | 0 |
| greffe_documents | 5 | 0 |
| greffe_events | 2 | 0 |
| greffe_payments | 1 | 0 |
| invoice_lines | 74 | 0 |
| invoices | 74 | 0 |
| journals | 6 | 0 |
| liasse_cells | 0 | 0 |
| liasse_tables | 0 | 0 |
| numbering_sequences | 2 | 0 |
| pay_contracts | 8 | 0 |
| payments | 142 | 0 |
| payroll_runs | 24 | 0 |
| payslip_lines | 240 | 0 |
| payslips | 60 | 0 |
| period_locks | 0 | 0 |
| roles | 6 | 0 |
| stock_count_lines | 33 | 0 |
| stock_counts | 11 | 0 |
| stock_items | 3 | 0 |
| stock_movements | 12 | 0 |
| stock_provisions | 0 | 0 |
| tax_declarations | 2 | 0 |
| third_parties | 4 | 0 |
| user_companies | 1 | 0 |
| user_roles | 2 | 0 |
| users | 1 | 0 |
| vat_rates | 3 | 0 |
| **TOTAL** | **3 132** | **1** (alembic_version) |

Tables SQLite absentes de PostgreSQL : **aucune**. Tables PostgreSQL hors modèle :
**aucune**. Tables PostgreSQL non vides avant import : **`alembic_version` uniquement**.

---

## 5. Ordre d'import (dépendances FK)

Ordre produit par `Base.metadata.sorted_tables` (tri topologique des FK), respecté pour
l'import — **aucune FK désactivée** :

```
 1 accounts              12 stock_items           23 greffe_documents      34 invoice_lines
 2 companies             13 third_parties         24 greffe_events         35 liasse_cells
 3 roles                 14 user_companies        25 greffe_payments       36 payments
 4 users                 15 user_roles            26 invoices              37 payslips
 5 vat_rates             16 entries               27 liasse_tables         38 stock_movements
 6 audit_log             17 greffe_deposits       28 payroll_runs          39 asset_depreciation_lines
 7 bank_statements       18 pay_contracts         29 stock_counts          40 asset_events
 8 employees             19 period_locks          30 stock_provisions      41 bank_reconciliations
 9 fiscal_years          20 tax_declarations      31 assets                42 payslip_lines
10 journals              21 activity_events       32 bank_statement_lines  43 stock_count_lines
11 numbering_sequences   22 entry_lines           33 e_invoice_documents
```

L'unique auto-référence (`entries.reversed_entry_id → entries.id`) est **entièrement
NULL** dans la golden DB (0 ligne non nulle) : aucun ordre intra-table particulier requis.

---

## 6. Résultat par table

**Phase 1 — lecture SQLite (aucune écriture PG) : OK.** Les 3 131 lignes des 43 tables ont
été lues et typées (voir § 7) **sans erreur** : cela prouve que **toutes** les valeurs de la
golden DB sont convertibles en types Python — la seule anomalie détectée est une **longueur
de chaîne** (§ 8, § 19).

**Phase 2 — écriture PostgreSQL (transaction unique, atomique) :**

| table | lignes | statut |
|---|---|---|
| accounts … pay_contracts (n° 1 → 18, hors tables vides) | 1 760 | insérées dans la transaction |
| period_locks | 0 | table vide — ignorée |
| **tax_declarations** | 2 | **ÉCHEC — `StringDataRightTruncation` (varchar(5))** |
| tables n° 21 → 43 | — | non atteintes (transaction annulée) |

Détail de l'erreur :

```
ECHEC IMPORT: DataError
(psycopg.errors.StringDataRightTruncation) valeur trop longue pour le type character varying(5)
INSERT INTO tax_declarations (…) VALUES (…)
row id=2 : mode_depot='simulation'  (10 caractères dans une column VARCHAR(5))
TRANSACTION ANNULEE (rollback) - STOP
```

L'import a été tenté **une seule fois** (une seule tentative par table, § 16). La transaction
a été annulée : **aucune donnée métier n'a été conservée** dans PostgreSQL.

---

## 7. Conversions de types (explicites et documentées)

L'import lit chaque table via `select(<table>)` sur **le moteur SQLite** puis insère via
`<table>.insert()` sur PostgreSQL. Les valeurs sont donc converties par **les processeurs de
type SQLAlchemy du dialecte SQLite** — exactement ceux utilisés par l'application en
production (c'est ce qui garantit que les valeurs relues sont identiques dans les deux
dialectes).

| Type déclaré | Stockage SQLite (brut) | Valeur Python obtenue | Type PostgreSQL cible |
|---|---|---|---|
| `Numeric(14,2)` / `Numeric(14,3)` / `Numeric(5,2)` | INTEGER **ou** REAL | **`decimal.Decimal`** (`%.2f`/`%.3f` du dialecte) — **jamais `float`** | `NUMERIC(p,s)` |
| `Date` | TEXT `'AAAA-MM-JJ'` | `datetime.date` | `DATE` |
| `DateTime` | TEXT `'AAAA-MM-JJ HH:MM:SS[.ffffff]'` | `datetime.datetime` (naïf) | `TIMESTAMP WITHOUT TIME ZONE` |
| `Boolean` | INTEGER `0` / `1` | `True` / `False` | `BOOLEAN` |
| `Integer` | INTEGER | `int` | `INTEGER` / `INTEGER` (PK) |
| `String(n)` / `Text` | TEXT | `str` (UTF-8) | `VARCHAR(n)` / `TEXT` |
| NULL | NULL | `None` | NULL |

Preuves d'échantillonnage (lecture seule) :

```
entries.entry_date   : RAW '2025-01-01' (str)   -> SA datetime.date(2025, 1, 1)
entries.validated_at : RAW '2026-09-23 03:07:24.518148' -> SA datetime(2026,9,23,3,7,24,518148)
invoices.total_ht    : RAW 60000 (int)          -> SA Decimal('60000.00')
companies.require_ice: RAW 1 (int)              -> SA True (bool)
```

- **Aucun passage par `float`** pour un montant : les colonnes `Numeric` sont rendues en
  `Decimal` avant d'être transmises à psycopg (qui encode `numeric` nativement).
- **Aucune transformation métier, aucune renumérotation** : les PK/ID explicites sont
  insérés tels quels (`ids conservés`), les dates deviennent de vrais `date`, les horodatages
  de vrais `timestamp`, les booléens de vrais `boolean`, les NULL restent NULL.
- Les formats de dates/heures TEXT de SQLite sont ceux produits par l'application elle-même
  (donc déjà en forme ISO) ; la conversion est identique à celle du runtime.

---

## 8. Contrôles FK / UNIQUE / NULL / type

Contrôles de types exécutés **exhaustivement** en lecture seule sur les 43 tables + les 44
tables PostgreSQL :

| Contrôle | Résultat |
|---|---|
| **FK orphelines** (SQLite) | **0** (confirmé PG1 ; ordre FK respecté à l'import) |
| **Violations UNIQUE** | **0** détectée (l'échec est survenu avant l'insertion complète ; transaction annulée) |
| **Violations NOT NULL** | **0** détectée |
| **Violations de type** | **1 — `tax_declarations.mode_depot` : `VARCHAR(5)` < `'simulation'` (10)** |
| Colonnes `VARCHAR(n)` en dépassement | **1 seule** sur 43 tables : `tax_declarations.mode_depot` (max_len = 10 > 5) |
| Précision `NUMERIC(p,s)` | **aucun** dépassement (toutes colonnes) |
| Plage `INTEGER` (int4) | **aucune** valeur > 2 147 483 647 |
| Nb lignes SQLite = PostgreSQL | **non atteint** (import interrompu → 0 ligne métier côté PG) |

**Une violation de type a été détectée ⇒ STOP avant `setval`** (conformément au § 6).

Structure comparée (schéma) :

| Élément | SQLite | PostgreSQL |
|---|---|---|
| Tables | 44 (43 métier + `alembic_version`) | 44 (43 métier + `alembic_version`) |
| Clés étrangères | 102 | 102 |
| Index | 123 (dont 23 uniques, incl. autoindex PK) | 164 |
| Contraintes UNIQUE | — (16 déclarées) | 16 |
| Séquences | aucune (AUTOINCREMENT non utilisé) | 41 |

Les écarts d'index (123 vs 164) sont **dialectaux** : PostgreSQL matérialise une relation
d'index pour chaque PK/UNIQUE/contrainte (`pg_indexes` recense aussi PK et UNIQUE, SQLite
les compte via les `sqlite_autoindex_*` différemment), et `VARCHAR`/`NUMERIC` n'engendrent pas
d'index supplémentaire. **Aucune différence de données métier** n'est en cause.

---

## 9. Séquences / `setval`

**NON EXÉCUTÉ — STOP avant `setval`** (le § 7 ordonne de n'ajuster les séquences
**qu'après import complet**). Les 41 séquences PostgreSQL existent (créées par Alembic, à
leur valeur initiale) mais **n'ont pas été recalées**, et **aucune ligne métier de test n'a
été créée**. Le tableau `table | sequence | max_id | valeur_sequence_apres` reste donc à
produire lors d'une prochaine exécution réussie.

---

## 10 → 15. Réconciliation métier, paie, fiscalité, audit, à-nouveaux, Greffe

**NON ATTEINT — STOP avant import complet.** Aucune de ces vérifications n'est présentée
comme un succès PostgreSQL : elle n'a **pas** été exécutée sur PostgreSQL (les données métier
n'ont pas été importées). Rappels des repères validés sur SQLite (baseline PG1, à re-vérifier
sur PostgreSQL après reprise) :

| Repère | Attendu (baseline SQLite) |
|---|---|
| 2025 — exercice | `closed` |
| 2025 — résultat net | `52 043,87 DH` |
| 2025 — résultat fiscal | `63 083,48 DH` |
| 2025 — IS | `11 039,61 DH` |
| 2025 — CM | `0` |
| 2025 — paie | 12 cycles / 24 bulletins, coût employeur `172 916,52 DH` |
| 2026 — exercice | `open` |
| 2026 — résultat | `−113 307,20 DH` |
| 2026 — paie | 12 cycles / 36 bulletins |
| Comptabilité | Débit = Crédit = `4 321 260,99` ; Actif = Passif ; CPC = Bilan = ESG |
| Audit | 208 écritures, 208 scellées, 0 rupture (empreinte `a47571c2…f0f5`) |
| À-nouveaux 2026 | ouverture unique ; `5141 = 239 339,48` ; `4441 = 39 741,24 Cr` ; `4452 = 194,76 Cr` ; `4453 = 11 039,61 Cr` ; `1191 = 52 043,87 Cr` |
| Greffe | dossier 2025 présent, statut `approuve`, références DB présentes (0 PDF régénéré) |

Ces repères restent **inchangés et vérifiables** dans la golden DB SQLite (SHA identique) ;
leur reproduction PostgreSQL devra être mesurée après reprise de l'import.

---

## 16. Test runtime avec le rôle `compta_ma_app`

**NON EXÉCUTÉ — STOP avant import complet.** Aucune donnée métier n'étant présente dans
PostgreSQL, le test de runtime avec le rôle limité `compta_ma_app` (connexion, lectures
principales, accès tables/séquences, absence d'erreur de permissions) n'a **pas** été
lancé. Aucun `create_all` n'a été exécuté. Droits de `compta_ma_app` : **non modifiés**.

---

## 17. Tests PostgreSQL réellement exécutés

**Aucun test PostgreSQL n'a été exécuté.**

- La suite existante utilise une **fixture SQLite en mémoire** : `tests/conftest.py`
  (`create_engine("sqlite://", …, poolclass=StaticPool)` + `Base.metadata.create_all`).
  Elle **ne peut pas** servir de preuve PostgreSQL.
- Les **461 tests SQLite** (baseline) ne sont **pas** présentés ici comme une preuve
  PostgreSQL : ils utilisent SQLite.
- **Aucun test n'a été modifié** (interdiction § 13). La recette complète multi-dialecte
  reste à finaliser (PG4/PG5).

---

## 18. SHA SQLite final

| Mesure | Valeur |
|---|---|
| SHA-256 attendu | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| SHA-256 final mesuré | `4E2C9EC37D8C8956D0D52199CA008BEE16B6A97ECF2115597364A3B7600B9101` |
| Conclusion | **identique — SQLite inchangée** ✅ |

---

## 19. Anomalies

### 19.1 Anomalie bloquante n° 1 — `tax_declarations.mode_depot` : valeur hors longueur déclarée

| Élément | Détail |
|---|---|
| Table.column | `tax_declarations.mode_depot` |
| Type déclaré | `VARCHAR(5)` — modèle `String(5)` (`app/models/declaration.py:80`) ; migration `sa.String(length=5)` (`alembic/versions/56d9985cc7ff_…py:96`) |
| Ligne fautive | `tax_declarations.id = 2` |
| Valeur | **`'simulation'`** (10 caractères) |
| Autre ligne | `id = 3` → `mode_depot = 'EDI'` (conforme) |
| Contrôle | `StringDataRightTruncation` PostgreSQL ; SQLite **tolère** (la longueur d'un `VARCHAR` n'est **pas** imposée par SQLite) |
| Portée | **unique** : c'est le **seul** dépassement de longueur détecté sur les 43 tables (aucun dépassement `NUMERIC`, aucune valeur hors plage `INTEGER`) |
| Classification | **ANOMALIE DE DONNÉES / DE TYPE** (bloquante) |

**Cause racine** (dans le projet, sans modification) : l'outil de construction de la base
golden `tools/j9_recette.py:815` enregistre la déclaration TVA de sortie avec
`mode_depot="simulation"` :

```python
# tools/j9_recette.py
enregistree = activity_events.enregistrer_declaration_tva(
    db, societe, evenement, declaration=declaration,
    mode_depot="simulation",     # <-- hors domaine ET > String(5)
    user_id=user_id,
)
```

`enregistrer_declaration_tva` (`app/services/activity_events.py:501,507`) recopie
`mode_depot` dans `TaxDeclaration.mode_depot`. Le domaine applicatif des modes de dépôt est
`DEPOT_MODES = ("EDI", "EFI")` (`app/models/declaration.py:56-58`) : la valeur
`"simulation"` est **hors domaine** — mais SQLite l'a acceptée car il n'applique pas la
longueur déclarée.

**Pourquoi c'est bloquant pour la migration fidèle** : stocker `'simulation'` dans
PostgreSQL exige soit une **colonne plus large** (`VARCHAR(10+)`), soit une **valeur
tronquée/normalisée**. Or PG3 interdit explicitement les deux :

- § 15 — « Ne pas modifier les modèles », « ne pas créer une nouvelle migration Alembic »,
  « modifier des résultats métier » ;
- § 5 — « Ne pas inventer de valeur manquante » ;
- § 6 — « Une violation [de type] = STOP avant `setval` » ;
- § 16 — « si erreur de données/FK/type : STOP et rapporter ».

→ Conformément à ces règles, l'import **STOP**, **sans** correction improvisée, **sans**
élargissement de colonne, **sans** troncature de valeur.

### 19.2 Anomalies / points constatés (non bloquants)

| # | Constat | Statut |
|---|---|---|
| 1 | La valeur `mode_depot='simulation'` est un artefact de l'outil de recette J9, hors domaine applicatif (`EDI`/`EFI`) | **à traiter avant reprise** (voir § 20) |
| 2 | Écart du nombre d'index SQLite/PostgreSQL (123 vs 164) | **dialectal**, sans impact données |
| 3 | Séquences PostgreSQL non recalées (`setval`) | **volontaire** (STOP avant `setval`, § 7) |
| 4 | Tests existants limités à la fixture SQLite | **connu**, reporté PG4/PG5 |
| 5 | Recherche `ILIKE`/accents, concurrence/`IntegrityError`, pool, fuseau | **hors périmètre PG3** (reportés PG2/PG4) |

### 19.3 État laissé après STOP (aucune destruction, aucune donnée métier)

| Élément | État |
|---|---|
| PostgreSQL `compta_ma_staging` | schéma Alembic présent (44 tables, 41 séquences, révision `p1c1a2b3d4e5`) ; **aucune donnée métier** ; `alembic_version` = 1 ligne |
| Import métier | annulé par `ROLLBACK` (transaction atomique) — **aucun état partiel** |
| SQLite `compta_ma.db` | **inchangée** (SHA `4E2C9EC3…9101`) |
| Fichiers applicatifs / modèles / migrations / `.env` / `requirements` | **non modifiés** |
| Rôle `compta_ma_app` (droits) | **non modifié** |
| PDF Greffe | **aucun régénéré** |
| Nouveau fichier projet | **1 seul** : ce livrable `PG3_MIGRATION_SQLITE_POSTGRESQL.md` |

Scripts et sorties d'exécution : hors projet, dans `%TEMP%\compta_ma_pg3\` (aucun outil
permanent créé dans `tools/`).

---

## 20. Verdict

> # PG3 STOP — ANOMALIE DE MIGRATION

**Justification.** Le garde-fou est PASS, le schéma PostgreSQL a été créé exclusivement par
Alembic (`p1c1a2b3d4e5`, 44 tables, 41 séquences, 0 vue, aucun `create_all`), la source
SQLite a été lue intégralement en `mode=ro` et **n'est pas modifiée**. L'import typé a
respecté l'ordre des FK et les IDs explicites, mais a rencontré **une anomalie de
données/type bloquante** : `tax_declarations.mode_depot = 'simulation'` (10 caractères) dans
une colonne `VARCHAR(5)`. Le § 6 (« 0 violation de type … 0 violation = STOP avant
`setval` ») et le § 16 (« erreur de données/FK/type → STOP ») imposent l'arrêt. La
transaction d'import a été annulée : PostgreSQL ne contient **aucune** donnée métier.

**Ce qui est acquis :** schéma cible conforme ; source intacte ; chaîne d'outillage
d'import validée jusqu'à `tax_declarations` ; golden DB inchangée.

**Ce qui reste à faire avant un PG3 PASS** (décision à autoriser **hors** des contraintes
PG3, l'une ou l'autre étant une modification interdite en PG3) :

1. **Corriger la donnée / l'outil de recette** — normaliser la valeur hors domaine
   (`mode_depot='simulation'` → une valeur du domaine `EDI`/`EFI`, ou retirer la ligne
   `id=2` si elle n'a pas de sens métier) **sur une copie** de la golden DB, puis rejouer
   l'import. *(Modifie la donnée → nécessite un mandat explicite.)*
2. **Élargir la colonne** — `tax_declarations.mode_depot` de `String(5)` à `String(20)` via
   le modèle **et** une **nouvelle révision Alembic** (alignée sur
   `activities_events`/`liasse` qui acceptent des libellés). *(Modifie modèle + migration →
   nécessite un mandat explicite.)*

Dans les deux cas, la reprise devra : réinitialiser proprement la base cible (schéma déjà en
place), rejouer l'import en transaction unique, contrôler FK/UNIQUE/NULL/type + égalité des
comptes, exécuter `setval` sur les 41 séquences, puis dérouler les § 9 → § 17.

**STOP.**

### FIN — PG3 — STOP (ANOMALIE DE MIGRATION)