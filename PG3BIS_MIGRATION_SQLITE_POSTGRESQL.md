# PG3bis — REPRISE MIGRATION SQLITE → POSTGRESQL APRÈS PG3A

| Élément | Valeur |
|---|---|
| Projet (unique) | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` |
| Nature | Reprise **de la seule migration des données** SQLite → `compta_ma_staging` + contrôles PG3 restants |
| Date | 2026-10-10 |
| Interpréteur | `.venv\Scripts\python.exe` — Python **3.13.16** |
| PostgreSQL | **18.1** (`localhost:5432`), timezone `Africa/Casablanca`, encoding `UTF8` |
| DB cible | `compta_ma_staging` — rôle d'import `compta_ma_migrator`, rôle runtime `compta_ma_app` |
| DB source | `compta_ma.db` (lecture **mode=ro** uniquement) |
| Révision Alembic | `p1c1a2b3d4e5` (**inchangée**) |
| **Verdict** | **PG3bis PASS — MIGRATION SQLITE → POSTGRESQL TERMINÉE** |

> **Résumé.** Le garde-fou est PASS. Le schéma PostgreSQL déjà créé par Alembic
> (`p1c1a2b3d4e5`, 44 tables, 41 séquences, 0 vue) a été **conservé tel quel** : aucun
> `DROP`, aucune recréation, **aucune nouvelle migration Alembic**, aucun changement de
> modèle. L'import des données a été rejoué **une seule fois**, en **transaction
> atomique**, dans l'ordre des FK, avec IDs explicites, `Decimal` exacts, dates et
> timestamps typés, booléens typés, `NULL` conservés, **aucune transformation métier**.
> Résultat : **3 131 lignes** importées sur les 43 tables métier, **égalité stricte des
> comptages** SQLite/PostgreSQL table par table, **0 FK orpheline, 0 violation UNIQUE,
> 0 violation NOT NULL, 0 dépassement VARCHAR, 0 dépassement NUMERIC, 0 anomalie de
> type**. `tax_declarations.id = 2 . mode_depot = 'EDI'` et **plus aucune valeur
> `simulation`**. Les **41 séquences** ont été resynchronisées (`setval`), **0 collision**.
> La réconciliation métier est **exacte au centime** (2025, 2026, à-nouveaux), l'audit est
> **208/208 scellées, 0 rupture**, la comptabilité est **équilibrée** (D = C) et les états
> **cohérents** (CPC = ESG = Bilan). Les métadonnées Greffe sont conformes (**aucun PDF
> régénéré**). Le runtime a été testé **avec `compta_ma_app`** : connexion, lectures,
> permissions tables (44×CRUD) et séquences (41/41 USAGE), **aucune erreur de privilège**.
> Le SHA de la base SQLite est **strictement identique** avant et après.

---

## 1. Garde-fou (exécuté **une seule fois**, avant toute écriture PostgreSQL)

| Contrôle | Attendu | Mesuré | État |
|---|---|---|---|
| cwd exact | `…\chat\compta_ma` | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` | ✅ |
| Interpréteur | Python 3.13.16 | `…\.venv\Scripts\python.exe` — **3.13.16** | ✅ |
| `psycopg` disponible | oui | **psycopg 3.3.6** (SQLAlchemy 2.0.54, Alembic 1.20.0) | ✅ |
| SHA-256 SQLite | `E18B8981…B7F0` | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` | ✅ |
| SQLite en lecture seule | `mode=ro` | connexion `file:…?mode=ro` — `CREATE TABLE` **refusé** par le moteur | ✅ |
| PostgreSQL / `compta_ma_migrator` | accessible | `current_user=compta_ma_migrator`, `current_database=compta_ma_staging` | ✅ |
| Timezone PostgreSQL | `Africa/Casablanca` | `Africa/Casablanca` | ✅ |
| Encoding | `UTF8` | `UTF8` | ✅ |
| Alembic courant | `p1c1a2b3d4e5` | `p1c1a2b3d4e5` | ✅ |
| Tables publiques | 44 (= 43 métier + `alembic_version`) | **44** (vues : **0**) | ✅ |
| Séquences publiques | 41 | **41** | ✅ |
| Données métier PostgreSQL **avant import** | **0 ligne** | **0 ligne** (`alembic_version` = 1 ligne, hors métier) | ✅ |

**Tous les critères du garde-fou sont satisfaits.** Le schéma étant **conforme et vide**,
aucun `DROP`, aucune recréation et **aucun `alembic upgrade`** n'a été exécuté
(conformément au § 0 : « si le schéma est conforme et vide : NE PAS DROP / NE PAS
RECRÉER / NE PAS RELANCER ALEMBIC »). Les mots de passe n'ont été ni affichés, ni
journalisés, ni enregistrés : ils proviennent uniquement du fichier `pgpass` lu par le
processus.

---

## 2. SHA de la source SQLite

| Mesure | Valeur |
|---|---|
| SHA-256 **avant** phase | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| SHA-256 **après** phase | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| Résultat | **strictement identique** — golden DB **non modifiée** |

Toutes les lectures SQLite ont utilisé l'URI `file:…/compta_ma.db?mode=ro` (`uri=True`).
Aucun `UPDATE` / `DELETE` / `INSERT` / `VACUUM` n'a été émis sur la source.

> L'ancien SHA `4E2C9EC3…9101` est **obsolète** pour PG3bis (il correspondait à la golden
> antérieure à la correction PG3A). La référence PG3bis est la **nouvelle golden
> officielle `E18B8981…B7F0`**.

---

## 3. État Alembic existant (conservé, **non relancé**)

| Élément | Valeur |
|---|---|
| `alembic_version` PostgreSQL | **`p1c1a2b3d4e5`** = HEAD attendu = valeur SQLite | ✅ |
| Révisions présentes dans `alembic/versions/` | 9 (chaîne linéaire `91754af8ef74 → … → p1c1a2b3d4e5`) |
| Commande Alembic exécutée pendant PG3bis | **aucune** |
| `create_all` appelé sur PostgreSQL | **jamais** (garde-fou PG1A `creer_tables_dev` actif) |
| Tables / séquences / vues | 44 / 41 / 0 — **identiques à l'état laissé par PG3** |

---

## 4. Inventaire avant import

PostgreSQL était **vide hors `alembic_version`** (1 ligne). Aucune table SQLite absente
de PostgreSQL, aucune table PostgreSQL hors modèle.

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
| **TOTAL métier** | **3 131** | **0** |

**Pré-contrôle source (lecture seule, avant import)** — comparaison de **chaque valeur**
SQLite aux types réellement déclarés côté PostgreSQL (`information_schema`) :

| Contrôle pré-import | Résultat |
|---|---|
| `PRAGMA integrity_check` | **ok** |
| `PRAGMA foreign_key_check` (source) | **0 FK orpheline** |
| Dépassements `VARCHAR(n)` | **0** (sur 3 132 lignes) |
| Dépassements `NUMERIC(p,s)` (partie entière et échelle) | **0** |
| Plages `INTEGER` / `BIGINT` / `SMALLINT` | **0** hors plage |
| `BOOLEAN` hors domaine (0/1) | **0** |
| `DATE` / `TIMESTAMP` non interprétables | **0** |
| `NULL` sur colonne `NOT NULL` | **0** |

> C'est ce pré-contrôle qui confirme la **résorption de l'anomalie PG3** : plus aucune
> valeur hors longueur déclarée sur les 43 tables.

---

## 5. Import (une seule tentative, transaction atomique)

**Stratégie reprise de PG3, sans écart** : ordre des FK via `Base.metadata.sorted_tables` ;
IDs explicites (aucun `nextval` consommé) ; `Decimal` exacts ; dates et timestamps typés ;
booléens typés ; `NULL` conservés ; **aucune transformation métier** ; **aucune FK
désactivée** ; transaction unique validée par un `COMMIT` final (contrôle de comptage
effectué **dans** la transaction, avant `COMMIT`).

**Ordre FK appliqué (43 tables) :**

```
 1 accounts          12 stock_items        23 greffe_documents   34 invoice_lines
 2 companies         13 third_parties      24 greffe_events      35 liasse_cells
 3 roles             14 user_companies     25 greffe_payments    36 payments
 4 users             15 user_roles         26 invoices           37 payslips
 5 vat_rates         16 entries            27 liasse_tables      38 stock_movements
 6 audit_log         17 greffe_deposits    28 payroll_runs       39 asset_depreciation_lines
 7 bank_statements   18 pay_contracts      29 stock_counts       40 asset_events
 8 employees         19 period_locks       30 stock_provisions   41 bank_reconciliations
 9 fiscal_years      20 tax_declarations   31 assets             42 payslip_lines
10 journals          21 activity_events    32 bank_statement_lines 43 stock_count_lines
11 numbering_sequences 22 entry_lines      33 e_invoice_documents
```

**Lignes importées : 3 131** (43 tables métier). `alembic_version` (1 ligne) **non
touchée**. `ROLLBACK` : **non déclenché** (aucune anomalie). `COMMIT` : **OK**.

**Vérification spécifique de `tax_declarations` (dans la transaction, avant `COMMIT`) :**

| id | `mode_depot` | État |
|---|---|---|
| 2 | **`EDI`** | ✅ (corrigé en PG3A : `simulation` → `EDI`) |
| 3 | `EDI` | ✅ |

| Contrôle | Résultat |
|---|---|
| `mode_depot = 'simulation'` | **0 ligne** |
| `mode_depot` hors domaine `(EDI, EFI)` | **0 ligne** |

> L'anomalie bloquante de PG3 **ne se reproduit pas** : la valeur de recette
> `'simulation'` (10 caractères dans un `VARCHAR(5)`) a été **corrigée à la source** lors
> de PG3A, sur la golden DB SQLite elle-même (nouveau SHA officiel `E18B8981…B7F0`).

---

## 6. Contrôles après import (AVANT `setval`)

| Contrôle | Méthode | Résultat |
|---|---|---|
| Égalité du **nombre de lignes** SQLite/PostgreSQL, table par table | `count(*)` sur les 44 tables | **0 écart** (43 métier + `alembic_version`) |
| **FK orphelines** | 102 FK du catalogue, `LEFT JOIN` parent sur chaque FK | **0** |
| Violations **UNIQUE** | 64 index uniques (`pg_index` + prédicats partiels) | **0** |
| Violations **NOT NULL** | 359 colonnes `is_nullable='NO'` | **0** |
| Dépassements **VARCHAR** | 158 colonnes bornées, `length(col) > max` | **0** |
| Dépassements **NUMERIC** | 90 colonnes, partie entière `< 10^(p-s)` et échelle `= round(col, s)` | **0** |
| Anomalies de **type** | `pg_typeof()` distinct par colonne (523 colonnes) | **0** |

**Aucune anomalie ⇒ `setval` autorisé** (conformément au § 2 : « Toute anomalie = STOP
avant `setval` »).

| table | lignes SQLite | lignes PG | état |
|---|---|---|---|
| accounts | 895 | 895 | ✅ |
| activity_events | 1 | 1 | ✅ |
| alembic_version | 1 | 1 | ✅ |
| asset_depreciation_lines | 3 | 3 | ✅ |
| assets | 2 | 2 | ✅ |
| audit_log | 593 | 593 | ✅ |
| bank_reconciliations | 10 | 10 | ✅ |
| bank_statement_lines | 54 | 54 | ✅ |
| bank_statements | 10 | 10 | ✅ |
| companies | 1 | 1 | ✅ |
| e_invoice_documents | 8 | 8 | ✅ |
| employees | 5 | 5 | ✅ |
| entries | 208 | 208 | ✅ |
| entry_lines | 622 | 622 | ✅ |
| fiscal_years | 2 | 2 | ✅ |
| greffe_deposits | 1 | 1 | ✅ |
| greffe_documents | 5 | 5 | ✅ |
| greffe_events | 2 | 2 | ✅ |
| greffe_payments | 1 | 1 | ✅ |
| invoice_lines | 74 | 74 | ✅ |
| invoices | 74 | 74 | ✅ |
| journals | 6 | 6 | ✅ |
| liasse_cells / liasse_tables | 0 | 0 | ✅ |
| numbering_sequences | 2 | 2 | ✅ |
| pay_contracts | 8 | 8 | ✅ |
| payments | 142 | 142 | ✅ |
| payroll_runs | 24 | 24 | ✅ |
| payslip_lines | 240 | 240 | ✅ |
| payslips | 60 | 60 | ✅ |
| period_locks | 0 | 0 | ✅ |
| roles | 6 | 6 | ✅ |
| stock_count_lines | 33 | 33 | ✅ |
| stock_counts | 11 | 11 | ✅ |
| stock_items | 3 | 3 | ✅ |
| stock_movements | 12 | 12 | ✅ |
| stock_provisions | 0 | 0 | ✅ |
| tax_declarations | 2 | 2 | ✅ |
| third_parties | 4 | 4 | ✅ |
| user_companies | 1 | 1 | ✅ |
| user_roles | 2 | 2 | ✅ |
| users | 1 | 1 | ✅ |
| vat_rates | 3 | 3 | ✅ |

---

## 7. Séquences — resynchronisation (`setval`)

**41 séquences** resynchronisées. Méthode : `setval(seq, MAX(id), true)` si la table
contient des lignes (⇒ prochaine valeur = `MAX(id) + 1`), sinon `setval(seq, 1, false)`
(⇒ prochaine valeur = `1`). La **prochaine valeur est lue** par
`SELECT last_value, is_called FROM seq` (aucun `nextval()` consommé pour le contrôle), puis
comparée à la table : **0 collision**. **Aucune ligne métier n'a été créée pour tester.**

| table | séquence | MAX(id) | setval | prochaine valeur | collision |
|---|---|---|---|---|---|
| accounts | `accounts_id_seq` | 895 | 895,true | 896 | 0 |
| activity_events | `activity_events_id_seq` | 1 | 1,true | 2 | 0 |
| asset_depreciation_lines | `asset_depreciation_lines_id_seq` | 3 | 3,true | 4 | 0 |
| asset_events | `asset_events_id_seq` | *(vide)* | 1,false | 1 | 0 |
| assets | `assets_id_seq` | 2 | 2,true | 3 | 0 |
| audit_log | `audit_log_id_seq` | 593 | 593,true | 594 | 0 |
| bank_reconciliations | `bank_reconciliations_id_seq` | 11 | 11,true | 12 | 0 |
| bank_statement_lines | `bank_statement_lines_id_seq` | 54 | 54,true | 55 | 0 |
| bank_statements | `bank_statements_id_seq` | 10 | 10,true | 11 | 0 |
| companies | `companies_id_seq` | 1 | 1,true | 2 | 0 |
| e_invoice_documents | `e_invoice_documents_id_seq` | 8 | 8,true | 9 | 0 |
| employees | `employees_id_seq` | 5 | 5,true | 6 | 0 |
| entries | `entries_id_seq` | 234 | 234,true | 235 | 0 |
| entry_lines | `entry_lines_id_seq` | 712 | 712,true | 713 | 0 |
| fiscal_years | `fiscal_years_id_seq` | 2 | 2,true | 3 | 0 |
| greffe_deposits | `greffe_deposits_id_seq` | 1 | 1,true | 2 | 0 |
| greffe_documents | `greffe_documents_id_seq` | 5 | 5,true | 6 | 0 |
| greffe_events | `greffe_events_id_seq` | 2 | 2,true | 3 | 0 |
| greffe_payments | `greffe_payments_id_seq` | 1 | 1,true | 2 | 0 |
| invoice_lines | `invoice_lines_id_seq` | 74 | 74,true | 75 | 0 |
| invoices | `invoices_id_seq` | 74 | 74,true | 75 | 0 |
| journals | `journals_id_seq` | 6 | 6,true | 7 | 0 |
| liasse_cells | `liasse_cells_id_seq` | *(vide)* | 1,false | 1 | 0 |
| liasse_tables | `liasse_tables_id_seq` | *(vide)* | 1,false | 1 | 0 |
| numbering_sequences | `numbering_sequences_id_seq` | 2 | 2,true | 3 | 0 |
| pay_contracts | `pay_contracts_id_seq` | 8 | 8,true | 9 | 0 |
| payments | `payments_id_seq` | 142 | 142,true | 143 | 0 |
| payroll_runs | `payroll_runs_id_seq` | 24 | 24,true | 25 | 0 |
| payslip_lines | `payslip_lines_id_seq` | 240 | 240,true | 241 | 0 |
| payslips | `payslips_id_seq` | 60 | 60,true | 61 | 0 |
| period_locks | `period_locks_id_seq` | *(vide)* | 1,false | 1 | 0 |
| roles | `roles_id_seq` | 6 | 6,true | 7 | 0 |
| stock_count_lines | `stock_count_lines_id_seq` | 33 | 33,true | 34 | 0 |
| stock_counts | `stock_counts_id_seq` | 11 | 11,true | 12 | 0 |
| stock_items | `stock_items_id_seq` | 3 | 3,true | 4 | 0 |
| stock_movements | `stock_movements_id_seq` | 12 | 12,true | 13 | 0 |
| stock_provisions | `stock_provisions_id_seq` | *(vide)* | 1,false | 1 | 0 |
| tax_declarations | `tax_declarations_id_seq` | 3 | 3,true | 4 | 0 |
| third_parties | `third_parties_id_seq` | 4 | 4,true | 5 | 0 |
| users | `users_id_seq` | 1 | 1,true | 2 | 0 |
| vat_rates | `vat_rates_id_seq` | 3 | 3,true | 4 | 0 |

**41 séquences recalées · 0 collision.** (Les écarts `MAX(id)` vs nombre de lignes —
`entries` 234/208, `entry_lines` 712/622, `bank_reconciliations` 11/10 — sont **normaux** :
des identifiants ont été consommés par des écritures supprimées/contrepassées ; la
resynchronisation utilise bien le `MAX(id)` réel.)

> Le contrôle du runtime (rôle `compta_ma_app`) a consommé **une** valeur de
> `entries_id_seq` lors d'un appel `nextval()` **de test de privilège** (aucune ligne
> créée). La séquence a été **immédiatement restaurée** : `setval(entries_id_seq, 234,
> true)` ⇒ prochaine valeur **235**. Vérifié après restauration : `last_value=234,
> is_called=true`, **0 collision**.

---

## 8. Réconciliation PG3 (mesurée **sur PostgreSQL**, via les services de l'application)

Toutes les valeurs sont lues par les **services métier de l'application** (`app/services/…`),
connectés à `compta_ma_staging` — **même source que l'écran**, aucune valeur recalculée à la
main, **aucun recalcul d'écriture, aucune régénération**. Dialecte vérifié :
`engine.dialect.name = postgresql`.

### 8.1 Exercice 2025 (clos)

| Contrôle | Attendu | Mesuré | État |
|---|---|---|---|
| Statut `fiscal_years` | `closed` | `closed` | ✅ |
| Résultat net | **52 043,87 DH** | `52043.87` | ✅ |
| Résultat fiscal | **63 083,48 DH** | `63083.48` | ✅ |
| IS (impôt dû) | **11 039,61 DH** | `11039.61` | ✅ |
| Cotisation minimale (CM) | **0,00 DH** | `0.00` | ✅ |
| Paie : cycles | **12** | `12` | ✅ |
| Paie : bulletins | **24** | `24` | ✅ |
| Paie : coût employeur | **172 916,52 DH** | `172916.52` | ✅ |

### 8.2 Exercice 2026 (ouvert)

| Contrôle | Attendu | Mesuré | État |
|---|---|---|---|
| Statut `fiscal_years` | `open` | `open` | ✅ |
| Résultat net | **−113 307,20 DH** | `-113307.20` | ✅ |
| Paie : cycles | **12** | `12` | ✅ |
| Paie : bulletins | **36** | `36` | ✅ |

*(Comptages complémentaires : `payroll_runs` 12 (2025) + 12 (2026) = 24 ; `payslips`
24 (2025) + 36 (2026) = 60 — conformes à l'inventaire.)*

### 8.3 À-nouveaux 2026 (arrêtés au 01/01/2026, écriture `EC202600120`)

| Compte | Attendu | Mesuré | État |
|---|---|---|---|
| 5141 | 239 339,48 | `239339.48` | ✅ |
| 4441 | 39 741,24 **C** | `-39741.24` | ✅ |
| 4452 | 194,76 **C** | `-194.76` | ✅ |
| 4453 | 11 039,61 **C** | `-11039.61` | ✅ |
| 1191 | 52 043,87 **C** | `-52043.87` | ✅ |

**(Convention : signe négatif = solde créditeur.)** Les 5 comptes cibles sont **exacts au
centime** ; valeurs lues par `closing.soldes_a_la_date(db, 1, 2026-01-01)`.

---

## 9. Audit & traçabilité (PostgreSQL)

| Contrôle | Attendu | Mesuré | État |
|---|---|---|---|
| Écritures (validées) | **208** | `208` | ✅ |
| Écritures **scellées** | **208** | `208` | ✅ |
| **Ruptures** de chaîne | **0** | `0` | ✅ |
| `integre` (chaîne d'audit) | `true` | `true` | ✅ |
| `entries` (total) | 208 | `208` | ✅ |
| `audit_log` (journal) | 593 | `593` | ✅ |

Mesuré par `audit_trail.verifier_chainage(db, company_id=1)` : recalcul de l'empreinte de
**chaque** écriture (`empreinte_ecriture`) et vérification du chaînage `previous_hash` —
**aucune** écriture non scellée, **aucune** rupture, **aucun** contenu altéré. Les
empreintes traversent la migration **à l'identique** : la piste d'audit reste vérifiable
après passage en PostgreSQL.

---

## 10. Comptabilité (PostgreSQL)

| Exercice | Contrôle | Attendu | Mesuré | État |
|---|---|---|---|---|
| 2025 | Balance D = C | 1 716 137,43 | D = C = `1716137.43` | ✅ |
| 2025 | Balance équilibrée | `true` | `true` | ✅ |
| 2025 | CPC = ESG (résultat net) | 52 043,87 | `52043.87` | ✅ |
| 2025 | `coherent_avec_cpc` | `true` | `true` | ✅ |
| 2025 | Bilan équilibré | `true` | `true` | ✅ |
| 2025 | Bilan cohérent avec l'écran | `true` | `true` | ✅ |
| 2026 | Balance D = C | 2 605 123,56 | D = C = `2605123.56` | ✅ |
| 2026 | Balance équilibrée | `true` | `true` | ✅ |
| 2026 | CPC = ESG (résultat net) | −113 307,20 | `-113307.20` | ✅ |
| 2026 | `coherent_avec_cpc` | `true` | `true` | ✅ |
| 2026 | Bilan équilibré | `true` | `true` | ✅ |
| 2026 | Bilan cohérent avec l'écran | `true` | `true` | ✅ |

Détail Bilan CGNC (brut − amortissements = net = passif + résultat) :

| Exercice | Actif brut | Amort./prov. | Actif net | Passif + résultat |
|---|---|---|---|---|
| 2025 | 398 539,48 | 12 000,00 | **386 539,48** | **386 539,48** |
| 2026 | 407 822,60 | 27 000,00 | **380 822,60** | **380 822,60** |

> **Aucun recalcul ni régénération** : aucun `generer_a_nouveaux`,
> aucun `regenerer_a_nouveaux`, aucune `cloturer_exercice` / `reouvrir_exercice`, aucun PDF
> Greffe, aucune écriture créée. Les états sont **lus**
> (`reporting.balance_generale`, `etats_synthese.etat_soldes_gestion`,
> `etats_synthese.bilan_normal`, `closing.resultat_de_l_exercice`).

---

## 11. Greffe — métadonnées DB (aucun PDF régénéré)

Conformément au § 5 : **aucun PDF n'a été régénéré** ; seules les **métadonnées en base**
ont été vérifiées (elles doivent être identiques à celles de la recette).

| Contrôle | Attendu | Mesuré | État |
|---|---|---|---|
| Dossier de dépôt `id` | 1 | `1` | ✅ |
| Forme juridique | `SARL` | `SARL` | ✅ |
| Statut | `approuve` | `approuve` | ✅ |
| Exercice | 2025 | `2025` | ✅ |
| Date AG | `2026-01-08` | `2026-01-08` | ✅ |
| `date_depot` | `null` (aucun dépôt réel) | `None` | ✅ |
| `certificat_path` | `null` (aucun certificat) | `None` | ✅ |
| `montant_taxes` | 1 000,00 | `1000.00` | ✅ |
| Documents | **5** | `5` | ✅ |
| Aucune pièce vide | `taille > 1000` | `true` | ✅ |
| Empreintes toutes distinctes | 5 / 5 | `5` | ✅ |
| Paiements | 1 | `1` | ✅ |
| Total payé | 1 000,00 | `1000.00` | ✅ |
| Solde taxes | 0,00 | `0.00` | ✅ |
| Complétude des pièces obligatoires | **5/5** | `5/5` | ✅ |

**Les 5 pièces** (métadonnées base, identiques à la recette SQLite) :

| Pièce | Fichier | Taille (o) | SHA-256 |
|---|---|---|---|
| etats_synthese | Etats_synthese_2025.pdf | 15 347 | `70eb474f…c1b2d` |
| rapport_gestion | Rapport_gestion_2025.pdf | 5 328 | `735a7efa…93b8b` |
| pv_ag | PV_AG_2025.pdf | 4 930 | `ae2f1937…f2cec` |
| etat_complementaire | Bordereau_depot_greffe_2025.pdf | 4 791 | `6c73fd3c…186a2f` |
| justificatif_paiement | Attestation_paiement_taxes_2025.pdf | 2 312 | `5cf536b4…56f2ff` |

*(Empreintes tronquées à l'affichage ; valeurs complètes vérifiées en base, toutes
distinctes.)*

---

## 12. Runtime APP — rôle `compta_ma_app` (PostgreSQL)

Test du **runtime applicatif** avec le rôle **limité** `compta_ma_app` (et non
`compta_ma_migrator`) : `DATABASE_URL = postgresql+psycopg://compta_ma_app@localhost:5432/compta_ma_staging`.

### 12.1 Connexion et lectures principales (via `app/services/…`)

| Contrôle | Mesuré | État |
|---|---|---|
| `current_user` / `current_database` | `compta_ma_app` / `compta_ma_staging` | ✅ |
| Dialecte | `postgresql` | ✅ |
| `companies` | 1 | ✅ |
| `accounts` | 895 | ✅ |
| `entries` | 208 | ✅ |
| `employees` | 5 | ✅ |
| Balance 2025 (D / C / équilibre) | `1716137.43` / `1716137.43` / `True` | ✅ |
| Résultat 2025 / 2026 | `52043.87` / `-113307.20` | ✅ |
| Paie 2025 (périodes / coût employeur) | `12` / `172916.52` | ✅ |
| Audit (`verifier_chainage`) | 208 écritures, 208 scellées, 0 rupture, `integre=True` | ✅ |

### 12.2 Permissions

| Objet | SELECT | INSERT | UPDATE | DELETE | État |
|---|---|---|---|---|---|
| `accounts`, `entries`, `entry_lines`, `payroll_runs`, `greffe_deposits`, `users` | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tables publiques couvertes | **44 / 44** (CRUD accordé par défaut `compta_ma_migrator → compta_ma_app`) | | | | ✅ |
| Séquences — `USAGE` | **41 / 41** | | | | ✅ |
| `nextval('entries_id_seq')` | autorisé (séquence restaurée ensuite) | | | | ✅ |
| Écriture de test `INSERT` en transaction **annulée** (`INSERT` d'une ligne sonde puis `ROLLBACK`) | INSERT autorisé ; **ROLLBACK effectué ; 0 trace persistée** (vérifié : `action='PG3BIS_PROBE'` = **0 ligne**) | | | | ✅ |

**Aucune erreur de privilège** (`permission denied`) sur toute la campagne runtime. Le
rôle `compta_ma_app` **n'exécute aucun `create_all`** : le schéma reste géré par Alembic.

---

## 13. Tests — distinction **explicite** SQLite / PostgreSQL

### 13.1 Tests **réellement exécutés contre PostgreSQL**

Les contrôles suivants ont été exécutés **contre `compta_ma_staging`**, en **lecture
seule**, en appelant les **services métier de l'application** (aucun test du dépôt n'a été
modifié) :

| Campagne | Contenu | Contrôles | Résultat |
|---|---|---|---|
| `recon` | garde-fous d'exercice, résultat net, résultat fiscal, IS, CM, paie 2025/2026, à-nouveaux 2026 | **17** | **17 PASS / 0 FAIL** |
| `recon2` | audit/chaînage, comptabilité 2025 & 2026 (balance, CPC, ESG, Bilan), comptages `payroll_runs`/`payslips` | **25** | **25 PASS / 0 FAIL** |
| `greffe_meta` | métadonnées du dossier Greffe (dépôt, 5 pièces, paiement, complétude) | **16** | **16 PASS / 0 FAIL** |
| `runtime_app2` | runtime avec `compta_ma_app` : connexion, lectures, privilèges tables, séquences, `INSERT` sonde annulé | **12** | **12 PASS / 0 FAIL** |

**Total : 70 contrôles PostgreSQL, 0 échec.** Chaque campagne imprime
`engine.dialect.name = postgresql` et s'exécute sous le rôle attendu
(`compta_ma_migrator` pour l'import/contrôles, `compta_ma_app` pour le runtime).

### 13.2 Tests restant **basés sur la fixture SQLite** (non modifiés)

- La suite automatisée du projet utilise une **fixture SQLite en mémoire** :
  `tests/conftest.py` (`create_engine("sqlite://", …, poolclass=StaticPool)` +
  `Base.metadata.create_all`). Aucun test du dépôt ne pointe vers PostgreSQL
  (vérifié : aucune référence `postgres`/`psycopg`/`DATABASE_URL` dans `tests/`).
- Exécution : `.\.venv\Scripts\python.exe -m pytest -q` sur **37 fichiers de test**.

| Mesure | Valeur |
|---|---|
| Tests exécutés | **461** |
| Réussis | **461** |
| Échecs | **0** |
| Erreurs | **0** |
| Ignorés | **0** |
| Rapport | `--junitxml` (`testsuite tests="461" failures="0" errors="0" skipped="0"`) |
| Base touchée | SQLite **en mémoire** — `compta_ma.db` **non touchée** (SHA inchangé) |
| Tests modifiés | **aucun** |

> ⚠️ **Les 461 PASS ne sont PAS une preuve PostgreSQL.** Ils s'exécutent sur SQLite en
> mémoire. La **preuve PostgreSQL** de PG3bis est constituée par les **70 contrôles** du
> § 13.1 (§ 8 à § 12), exécutés sur `compta_ma_staging` avec les services réels.
>
> *Note technique : le processus `pytest` se termine avec un code ≠ 0 dû à une erreur de
> nettoyage **interne à pytest** sur Windows (`PermissionError` sur le lien
> `pytest-current` du dossier temporaire `pytest-of-*`), **sans lien** avec les tests : le
> rapport JUnit atteste **461 tests, 0 échec, 0 erreur, 0 ignoré** (les 461 points de
> progression sont des `.` = succès).*

---

## 14. SHA SQLite final

| Mesure | Valeur |
|---|---|
| SHA-256 attendu | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| SHA-256 mesuré en fin de PG3bis | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| Conclusion | **identique — SQLite strictement inchangée** ✅ |

---

## 15. Anomalies

### 15.1 Anomalies bloquantes

**Aucune.** L'anomalie bloquante de PG3 (`tax_declarations.mode_depot = 'simulation'` dans
un `VARCHAR(5)`) est **résorbée à la source** (corrigée en PG3A sur la golden DB, nouveau
SHA officiel). L'import typé s'est déroulé **sans aucune violation** : 0 FK orpheline,
0 UNIQUE, 0 NOT NULL, 0 dépassement `VARCHAR`, 0 dépassement `NUMERIC`, 0 anomalie de type.

### 15.2 Points constatés (non bloquants)

| # | Constat | Statut |
|---|---|---|
| 1 | `MAX(id)` ≠ nombre de lignes sur `entries` (234/208), `entry_lines` (712/622), `bank_reconciliations` (11/10) | **normal** — identifiants consommés par des écritures supprimées/contrepassées ; `setval` calé sur `MAX(id)` |
| 2 | Une valeur de `entries_id_seq` consommée par le test `nextval()` du runtime | **corrigé** — séquence restaurée (`setval(…, 234, true)`) ; vérifié, 0 collision |
| 3 | Écart du nombre d'index SQLite/PostgreSQL | **dialectal**, sans impact sur les données |
| 4 | Suite automatisée exécutée sur fixture **SQLite** (461 PASS) | **connu** — ne constitue pas une preuve PostgreSQL (§ 13.2) |
| 5 | Fin de processus `pytest` en code ≠ 0 (nettoyage temporaire interne pytest/Windows) | **sans impact** — rapport JUnit : 461/0/0/0 |
| 6 | Recherche `ILIKE`/accents, concurrence/`IntegrityError`, pool, fuseau (hors périmètre PG3bis) | **reportés** PG4/PG5 |

### 15.3 État laissé après PG3bis

| Élément | État |
|---|---|
| PostgreSQL `compta_ma_staging` | schéma Alembic `p1c1a2b3d4e5` (44 tables, 41 séquences, 0 vue) **+ 3 131 lignes métier** importées ; 41 séquences resynchronisées |
| Base SQLite `compta_ma.db` | **inchangée** (SHA `E18B8981…B7F0`) |
| Modèles / migrations Alembic / `.env` / `requirements` | **non modifiés** |
| Droits du rôle `compta_ma_app` | **non modifiés** (CRUD 44 tables + `USAGE` 41 séquences, déjà en place) |
| PDF Greffe | **aucun régénéré** |
| Nouveau fichier projet | **1 seul** : ce livrable `PG3BIS_MIGRATION_SQLITE_POSTGRESQL.md` |

Scripts et sorties d'exécution : **hors projet**, dans `%TEMP%\compta_ma_pg3bis\` (aucun
outil permanent créé dans `tools/`).

### 15.4 Anti-boucle — respecté

| Règle | Respect |
|---|---|
| Ne pas refaire Alembic si HEAD correct | ✅ **aucun** `alembic upgrade` (HEAD `p1c1a2b3d4e5` déjà conforme) |
| Ne pas `DROP` le schéma | ✅ **aucun** `DROP` |
| Une seule tentative d'import | ✅ **1 seule**, réussie (aucun retry) |
| Une seule correction technique maximum si script pur | ✅ **aucune correction nécessaire** (import réussi au 1er essai) |
| Anomalie données/type/FK = STOP | ✅ aucune anomalie déclenchée |
| Pas de retry destructif / pas de modification SQLite / modèle / migration Alembic | ✅ |
| Pas de `pip install` / pas de Web | ✅ |

---

## 16. Verdict

> # PG3bis PASS — MIGRATION SQLITE → POSTGRESQL TERMINÉE

**Justification.** Le garde-fou est PASS ; le schéma PostgreSQL existant
(`p1c1a2b3d4e5`, 44 tables, 41 séquences) a été **conservé sans `DROP` ni recréation** et
**sans nouvelle migration Alembic**. L'import a été rejoué **une seule fois**, en
**transaction atomique**, dans l'ordre des FK, avec IDs explicites et types stricts :
**3 131 lignes**, **égalité des comptages table par table**, **0 FK orpheline, 0 UNIQUE,
0 NOT NULL, 0 dépassement VARCHAR/NUMERIC, 0 anomalie de type**. `mode_depot = 'EDI'`
(plus aucune valeur `simulation`). Les **41 séquences** sont resynchronisées
(**0 collision**). La réconciliation est **exacte au centime** :

| Élément | Valeur vérifiée en base |
|---|---|
| 2025 — exercice | `closed` |
| 2025 — résultat net | **52 043,87 DH** |
| 2025 — résultat fiscal | **63 083,48 DH** |
| 2025 — IS | **11 039,61 DH** |
| 2025 — CM | **0,00 DH** |
| 2025 — paie | **12 cycles / 24 bulletins** · coût employeur **172 916,52 DH** |
| 2026 — exercice | `open` |
| 2026 — résultat net | **−113 307,20 DH** |
| 2026 — paie | **12 cycles / 36 bulletins** |
| À-nouveaux 2026 | 5141 **239 339,48** · 4441 **39 741,24 C** · 4452 **194,76 C** · 4453 **11 039,61 C** · 1191 **52 043,87 C** |
| Audit | **208 écritures · 208 scellées · 0 rupture** |
| Comptabilité | **Débit = Crédit** (2025 : 1 716 137,43 · 2026 : 2 605 123,56) · **CPC / ESG / Bilan cohérents** |

Les métadonnées Greffe sont conformes (**aucun PDF régénéré**). Le runtime a été testé
**avec `compta_ma_app`** : **aucune erreur de privilège**. Le SHA de la base SQLite est
**strictement identique** avant et après.

**Ce qui est acquis :** migration SQLite → PostgreSQL **complète et fidèle** ; cible
`compta_ma_staging` peuplée et cohérente ; séquences opérationnelles ; runtime applicatif
validé avec le rôle limité ; source de référence intacte.

**Ce qui reste (hors périmètre PG3bis, phases ultérieures) :** fixtures PostgreSQL réelles
dans la suite automatisée, `ILIKE`/accents, concurrence/`IntegrityError`, pool et fuseau
(PG4/PG5).

### FIN — PG3bis — PASS (MIGRATION SQLITE → POSTGRESQL TERMINÉE)

**STOP.**