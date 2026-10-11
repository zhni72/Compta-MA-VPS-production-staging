# PG4 — RÉCONCILIATION EXHAUSTIVE SQLITE ↔ POSTGRESQL

| Élément | Valeur |
|---|---|
| Projet (unique) | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` |
| Nature | Réconciliation **100 % lecture seule** SQLite ↔ PostgreSQL, table par table |
| Date | 2026-10-10 |
| Interpréteur | `.venv\Scripts\python.exe` — Python **3.13.16** |
| Pilotes | SQLAlchemy **2.0.54**, psycopg **3.3.6** |
| Baseline SQLite officielle | `compta_ma.db` — SHA-256 `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| PostgreSQL | **18.1** (`localhost:5432`), base `compta_ma_staging`, rôle `compta_ma_migrator` |
| Révision Alembic | `p1c1a2b3d4e5` (**identique** des deux côtés) |
| Outil | `tools/pg4_reconciliation.py` (nouveau, lecture seule) |
| **Verdict** | **PG4 PASS — FIDÉLITÉ SQLITE/POSTGRESQL VALIDÉE** |

> **Résumé.** Les **43 tables métier** (3 131 lignes) ont été lues **intégralement** en
> `mode=ro` côté SQLite et en transaction `READ ONLY` côté PostgreSQL, puis comparées
> **ligne par ligne, valeur par valeur**, après sérialisation canonique. Les
> **empreintes SHA-256 par table sont identiques 43/43**, le comptage est identique
> **table par table** (3 131 = 3 131), les **PK** et les **FK** (102 contraintes) sont
> identiques et **sans orpheline** (0 des deux côtés), les **agrégats métier** sont
> identiques (écritures, paie, fiscalité, TVA, à-nouveaux), et l'**empreinte globale**
> est identique. **Aucune anomalie métier, aucune différence dialectale résiduelle,
> aucune différence de représentation** : **0 écart** sur les deux bases. La base
> SQLite est **bit-à-bit inchangée**. Aucune écriture, aucun `setval`, aucun Alembic,
> aucun `DROP`, aucun recalcul, aucun changement de code n'a été effectué.

---

## 1. Garde-fou (lecture seule, avant toute lecture métier)

| Contrôle | Attendu | Mesuré | État |
|---|---|---|---|
| cwd exact | `…\chat\compta_ma` | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` | ✅ |
| Interpréteur | Python 3.13.16 | `3.13.16` (`.venv\Scripts\python.exe`) | ✅ |
| sqlite3 / SQLAlchemy / psycopg | disponibles | SQLAlchemy `2.0.54`, psycopg `3.3.6` | ✅ |
| SHA-256 SQLite **avant** | `E18B8981…B7F0` | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` | ✅ |
| SQLite **lecture seule** | écriture refusée | `CREATE TABLE` → `OperationalError` (**REFUSED**) | ✅ |
| PostgreSQL **lecture seule** | écriture refusée | `default_transaction_read_only=on` + `CREATE TABLE` → `InternalError` (**REFUSED**) | ✅ |
| PostgreSQL rôle / base | `compta_ma_migrator` / `compta_ma_staging` | `compta_ma_migrator` / `compta_ma_staging` | ✅ |
| Révision Alembic | identique | SQLite `p1c1a2b3d4e5` = PostgreSQL `p1c1a2b3d4e5` | ✅ |
| Tables métier (modèle) | 43 | **43** | ✅ |
| Tables publiques | 43 métier + `alembic_version` | SQLite **44**, PostgreSQL **44** | ✅ |

La connexion SQLite utilise l'URI `sqlite:///file:…/compta_ma.db?mode=ro&uri=true` ;
une tentative d'écriture a été émise puis **rejetée par le moteur SQLite**.
La connexion PostgreSQL ouvre chaque transaction en **lecture seule**
(`options=-c default_transaction_read_only=on`) ; une tentative de `CREATE TABLE` a
été émise puis **rejetée par le serveur**.

---

## 2. Interdictions — respect intégral

| Interdiction | Respect | Preuve |
|---|---|---|
| Aucune écriture SQLite | ✅ | URI `mode=ro` ; `CREATE TABLE` refusé ; SHA inchangé |
| Aucune écriture PostgreSQL | ✅ | `default_transaction_read_only=on` ; `CREATE TABLE` refusé |
| Aucun `setval` | ✅ | jamais émis (aucune séquence touchée) |
| Aucun Alembic | ✅ | aucune commande Alembic exécutée ; révision lue seule |
| Aucun `DROP` | ✅ | aucune instruction DDL émise en lecture |
| Aucun recalcul | ✅ | seules des lectures + agrégations en mémoire |
| Aucun changement de code | ✅ | aucun fichier de `app/` ni de migration modifié |
| Aucun test destructif | ✅ | aucune écriture, même temporaire ; sonde créée en transaction avortée |
| Pas de web | ✅ | aucune requête réseau hors PostgreSQL local |
| Pas de package install | ✅ | seules les librairies déjà présentes sont importées |

---

## 3. Normalisation des différences de dialecte (avant comparaison)

Chaque valeur est convertie en un **jeton canonique** selon le type SQLAlchemy de la
colonne, identique pour les deux bases :

| Type | Normalisation canonique | Effet |
|---|---|---|
| `NULL` | jeton `N` | `NULL` identique à `NULL`, distinct de `''` |
| Booléen | `B1` / `B0` | absorbe `0/1` (SQLite) ↔ `true/false` (PostgreSQL) |
| `Numeric(p,s)` | `Decimal` **exact** puis forme numérique canonique (zéros de queue retirés) | `1000.00` ≡ `1000` ; comparaison **exacte**, jamais via `float` |
| `Date` | `YYYY-MM-DD` | date normalisée **sans perte** |
| `DateTime` | `YYYY-MM-DDTHH:MM:SS.ffffff` (+ décalage si présent) | horodatage normalisé **sans perte**, microsecondes toujours explicites |
| `Integer` | forme décimale | entier exact |
| `String` / `Text` | texte **UTF-8** brut (séparateur `\x1f` non présent dans les données) | comparaison caractère à caractère |

Après normalisation, **tout écart restant serait une anomalie métier**. Aucun écart
n'a été observé.

## 4. Empreintes déterministes par table

Sérialisation canonique : en-tête `table|col:type|…`, puis, **lignes triées par PK**,
`<PK canonique>` + `\x1e` + `<valeurs canoniques>`, encodage **UTF-8**, **SHA-256**.
Empreinte **identique** SQLite / PostgreSQL pour **chacune** des 43 tables.

| table | lignes SQLite | lignes PostgreSQL | empreinte SHA-256 (SQLite = PostgreSQL) |
|---|---|---|---|
| accounts | 895 | 895 | `d519ea3fce000abd4d0b06ea08ec69a4ddb5c682cb5d4ba5b51fc8a88aae1a78` |
| activity_events | 1 | 1 | `d3b7c54eeb7bb81d896b0564188959c84c1ca24814bd95178b61b382159155fa` |
| asset_depreciation_lines | 3 | 3 | `6c6fc4f3c1a1ccfa0eb47d163b5bf335edfb30daf45c044ded9048200ca3d96b` |
| asset_events | 0 | 0 | `a3a6076fb06f0517cbfaa216ef0f6e52f3aad7e1c06c4d7d182ac3c1034d02ae` |
| assets | 2 | 2 | `f33217864b278c3357d87336cfacd694703df53b7ccc334dd36666a6fa7ef514` |
| audit_log | 593 | 593 | `faaa04f730956423b6b57451b48b0aa6dcbfa2a5c800114acbd6bd643f79fb38` |
| bank_reconciliations | 10 | 10 | `d6b55392febb6454b38c50df132dc31d0351a1e64d928c055cfd2e2e11d460d0` |
| bank_statement_lines | 54 | 54 | `fbc293862640d20c4b54d3be3f7e400d433d9cb7515b0887cc10ba56a7874351` |
| bank_statements | 10 | 10 | `581bdb464274ed0281207cbdc28859be50269d04aaa549a105f10453fcde42cf` |
| companies | 1 | 1 | `a23aef242f20f6175fabe429b955c6c0d55586c43d7a57d78303d96ce281bc3b` |
| e_invoice_documents | 8 | 8 | `af67ae6a6ed17d25fb760ce32c3d9f4db94bec96f3d5894445f3052bf8d71982` |
| employees | 5 | 5 | `5c97b5bc5eb4f2ca1e97a27366c4186c7aeedd5f0bfa1834e76256313ef65836` |
| entries | 208 | 208 | `67cedf74215538907ab8ca0c619850df91f45d3627c3a24d0243064aa5dad27a` |
| entry_lines | 622 | 622 | `f471f95d443f3f8d081088601bf8b2cafb0b38c84b6610304410b1b3a727b75a` |
| fiscal_years | 2 | 2 | `5e2ba1bb345bc0b81fc4122df4f474051d6310405c39829e56a744e59e0a559b` |
| greffe_deposits | 1 | 1 | `175b6be043006462d5c9fba02968fdfd25ca29ea7449f7fb44f4b2494d9c29a4` |
| greffe_documents | 5 | 5 | `d2fe5f338e9cdee2c0496c7569248fb87b8dddf2fcb4fa98507cb622d145c37d` |
| greffe_events | 2 | 2 | `3b98fb23483e160a66070eb8ca18e551b82d0c164627dc5a546e7150df202847` |
| greffe_payments | 1 | 1 | `143474fde595ec80f2cee23c09036977ad4eb9caa2fef24c7957b6bd2428a2e4` |
| invoice_lines | 74 | 74 | `c6c0650ab604e896557e39ee8c976841847ecdbb6dbab928089df6a2f4c310fc` |
| invoices | 74 | 74 | `258c80b57746929a4d90bf377c9eaa33fb14da008e29504a40d81f3b4499105b` |
| journals | 6 | 6 | `e20f4615e828f31e2badd189f5dfc254a6dc5e3530e19814aea926ca465fc63b` |

| liasse_cells | 0 | 0 | `54fffcb42f6eec466641b6a24710633260a222e8254af0961417f253741994ab` |
| liasse_tables | 0 | 0 | `062cc45dff26dc2edba838498ef967f9e2e98b7da03a95ceb858abcf569d9b6d` |
| numbering_sequences | 2 | 2 | `396182129b5377c99c29b66a27d4a9fc6713a5fe5a982bcd78ba0215b25ed570` |
| pay_contracts | 8 | 8 | `9a849261de48668afa0eae0f79e1ca10e83ba20e6446629be2395cb3355a7b7f` |
| payments | 142 | 142 | `f270ba11e9ce83b8d5556aa358cd0861a984a135ccdb40d94ed9df637f296161` |
| payroll_runs | 24 | 24 | `5a4f5e7806764496b240c18169cbdc35260769d84cbe365b899cde17256f2e41` |
| payslip_lines | 240 | 240 | `4f31f1e195d9913d3b4e1963374ba1b39d96dbdcca504336c2a48961245230da` |
| payslips | 60 | 60 | `a7349587c06b55a14b13103415e5c9946af413db99ad5b071a897665c492c7d0` |
| period_locks | 0 | 0 | `dc7b35d938527939d136c14edd900c7cae42f9547bf76c5a40fb763ace188ddf` |
| roles | 6 | 6 | `76a19b516ba3fa829bcaca985ed96422cbf97e3494263c322e0be8118b5012a3` |
| stock_count_lines | 33 | 33 | `875af9b5345d42c61477891fbaef049f33e6d8e44b202c87729361419a0c87bd` |
| stock_counts | 11 | 11 | `45b22b8b7730a3ffc4e7d76c7778282d4fed85ce930039a9a5f6c23e072d4b54` |
| stock_items | 3 | 3 | `66c4505f21a3ccf3503920866cbbcd60650041ed9f1978623250136cd1782ecf` |
| stock_movements | 12 | 12 | `cce3f2fc845a47d0665ea105f4412d39d89bc18ab5a7dce6194c26e0f0a89008` |
| stock_provisions | 0 | 0 | `4e38da9e3e74a88a47217d1d2219017a0ddeaeab61607c5bbe3e398d6ce019a5` |
| tax_declarations | 2 | 2 | `1f47037f7d9330abe97791219829fd03b6a7a50131f0ee205779440373c63110` |
| third_parties | 4 | 4 | `b1a5227d46b95810ee7158f05b7af967d2e1708f0c502d1d30b666d3734ac898` |
| user_companies | 1 | 1 | `9c2c3d5912e0f348f4d853e140f2436ed3ea543f7ecd90d530b73814de4c299f` |
| user_roles | 2 | 2 | `35702d0bda64696b2e6cfc75e14fce370664f8f92a03d6e91b94ea513291a219` |
| users | 1 | 1 | `8ad8d9f6de99e002add82e2cb06ae699752e1b6f258a565c55ccf5e694efe721` |
| vat_rates | 3 | 3 | `6270eb3da8a38ee6078b0f18c1732436dd02d4b2ba5fad8914573c90cf9249ce` |

**Empreinte globale** (concaténation ordonnée `table:empreinte`) :

| Mesure | SQLite | PostgreSQL | Égalité |
|---|---|---|---|
| empreinte globale | `2c4fb8e82abc3c2cd818c9359a95a125fc8cca1098292a3c91aaf3c0d48a3a74` | `2c4fb8e82abc3c2cd818c9359a95a125fc8cca1098292a3c91aaf3c0d48a3a74` | ✅ |
| tables en correspondance | **43 / 43** | — | ✅ |
| lignes (total) | **3 131** | **3 131** | ✅ |

> **Conclusion § 4.** Les 43 empreintes sont deux à deux égales ⇒ après sérialisation
> canonique, **les deux bases contiennent exactement les mêmes lignes et les mêmes
> valeurs métier**.

## 5. Contrôles de structure et de valeurs

| Contrôle | Méthode | Résultat SQLite | Résultat PostgreSQL | Écart |
|---|---|---|---|---|
| **Nombre de lignes** | `count(*)` table par table | 3 131 (43 tables) | 3 131 (43 tables) | **0** |
| **Clés primaires** | ensemble des PK par table | 43/43 ensembles | 43/43 ensembles | **0** manquante, **0** doublon |
| **Clés étrangères** | 102 contraintes (modèle), soustraction d'ensembles | **0** orpheline | **0** orpheline | **0** |
| **Valeurs métier** | comparaison **ligne par ligne**, **colonne par colonne** | — | — | **0** valeur divergente |
| **`Decimal`** | comparaison **exacte** (jamais via `float`) | — | — | **0** |
| **Dates / horodatages** | ISO, microsecondes explicites | — | — | **0** |
| **Booléens** | `B1`/`B0` | — | — | **0** |
| **`NULL`** | jeton `N` (distinct de `''`) | — | — | **0** |
| **Textes UTF-8** | comparaison caractère à caractère | — | — | **0** |

**Mêmes PK** ✅ — **mêmes FK** ✅ (aucune orpheline, 102 contraintes) —
**mêmes valeurs métier** ✅ — **comparaison déterministe ligne par ligne** ✅.

## 6. Agrégats métier (recalcul en mémoire, identiques)

| Contrôle | SQLite | PostgreSQL | État |
|---|---|---|---|
| Tables métier | 43 | 43 | ✅ |
| Lignes totales | 3 131 | 3 131 | ✅ |
| **Écritures** — `entries` | 208 | 208 | ✅ |
| **Lignes d'écriture** — `entry_lines` | 622 | 622 | ✅ |
| Total **débit** `entry_lines` | 4 321 260,99 | 4 321 260,99 | ✅ |
| Total **crédit** `entry_lines` | 4 321 260,99 | 4 321 260,99 | ✅ |
| Exercice **2026** (fy id=1) — débit = crédit | 2 605 123,56 | 2 605 123,56 | ✅ |
| Exercice **2025** (fy id=2) — débit = crédit | 1 716 137,43 | 1 716 137,43 | ✅ |
| **À-nouveaux** — écritures `source='opening'` | 1 | 1 | ✅ |
| À-nouveaux — débit = crédit (`AN2025`) | 398 539,48 | 398 539,48 | ✅ |
| **Paie** — cycles `payroll_runs` | 24 | 24 | ✅ |
| Paie — bulletins `payslips` | 60 | 60 | ✅ |
| Paie — lignes `payslip_lines` | 240 | 240 | ✅ |
| Paie — coût employeur (Σ `payslips.cout_employeur`) | 538 863,72 | 538 863,72 | ✅ |
| Paie — net (Σ `payslips.net`) | 402 257,40 | 402 257,40 | ✅ |
| Paie — IR (Σ `payslips.ir`) | 27 802,68 | 27 802,68 | ✅ |
| Paie — CNSS salariale / AMO salariale | 14 461,44 / 10 278,48 | 14 461,44 / 10 278,48 | ✅ |
| **Fiscalité / TVA** — `tax_declarations` | 2 | 2 | ✅ |
| Fiscalité — Σ `tax_declarations.montant` | 96 727,92 | 96 727,92 | ✅ |
| **TVA** — `vat_rates` | 3 | 3 | ✅ |
| `payslip_lines` — Σ base / gain / retenue | 1 543 880,04 / 454 800,00 / 52 542,60 | idem | ✅ |

**Aucun agrégat ne diverge : 0 / 24.**

## 7. Domaines vérifiés en particulier

Toutes les tables ci-dessous ont une **empreinte identique** SQLite/PostgreSQL ;
leur contenu est reproduit ici à titre de preuve (valeurs lues, identiques des deux côtés).

**TVA / fiscalité — `tax_declarations` (2 lignes) :**

| id | type | période | `mode_depot` | statut | `montant` | `nb_lignes` |
|---|---|---|---|---|---|---|
| 2 | TVA | 2026 | **`EDI`** | brouillon | 69 120,00 | 2 |
| 3 | DTS | 2026 | **`EDI`** | brouillon | 27 607,92 | 3 |

> Aucune valeur `simulation` : la correction PG3A est bien propagée à l'identique
> dans les deux bases (`mode_depot = 'EDI'` partout). `vat_rates` : `TVA20` = 20,00 %,
> `TVA10` = 10,00 %, `TVA0` = 0,00 % (non déductible), valides depuis `2026-01-01`.

**`activity_events` (1 ligne) :** id=1, type `cessation`, `date_effet` `2026-12-31`,
`regime_tva` 4, `declaration_id` 2, `created_at` identique.

**Écritures / lignes d'écriture :** `entries` = 208 (`journal_id`, `fiscal_year_id`,
`entry_hash`, `previous_hash`, `status`, `validated_at` comparés ligne à ligne),
`entry_lines` = 622 (montants `debit`/`credit`/`vat_rate` comparés **exactement**).
Total débit = crédit = 4 321 260,99 des deux côtés.

**À-nouveaux :** 1 écriture `source='opening'` — id=234, `reference` `AN2025`,
libellé « A-nouveaux de l'exercice 2026 », `fiscal_year_id` 1, `status` `validated`,
`entry_hash` `a47571c2…` — **débit = crédit = 398 539,48**, identique des deux côtés.

**`audit_log` :** 593 lignes, `id` de 1 à 593, contenu (action, entité, horodatage,
`payload_json`) **intégralement identique** (empreinte `faaa04f7…`).

**Greffe :** `greffe_deposits` 1, `greffe_documents` 5, `greffe_events` 2,
`greffe_payments` 1 — métadonnées (nom, taille, SHA-256 des pièces, états, paiements)
**identiques** (aucun PDF régénéré : les empreintes en base sont les mêmes).

**Paie :** `employees` 5, `pay_contracts` 8, `payroll_runs` 24, `payslips` 60,
`payslip_lines` 240 — tous les montants (brut, net, IR, CNSS/AMO, coût employeur)
**identiques au centime**.

## 8. Classification des différences

Après normalisation (§ 3), **aucune différence n'a été détectée**. Le classement
ci-dessous est donc **vide** — ce qui est exactement le résultat attendu d'une
migration fidèle.

| Catégorie | Définition | Détectées | Détail |
|---|---|---|---|
| **Différence dialectale normale** | typage laxiste SQLite (`0/1`, `REAL`, dates texte) vs strict PostgreSQL (`boolean`, `NUMERIC`, `timestamp`) | **0** résiduelle | absorbée par la normalisation ; aucune non absorbée |
| **Différence de représentation sans impact** | même valeur, écriture différente (échelle décimale, format de date/timestamp) | **0** résiduelle | absorbée par la normalisation |
| **Anomalie métier** | valeur divergente, PK manquante, FK orpheline, `NULL` ≠ valeur, texte différent | **0** | — |

> **Aucune anomalie métier, aucune différence dialectale non normalisée, aucune
> différence de représentation résiduelle.**

## 9. Déterminisme

L'outil a été exécuté **deux fois de suite** ; les deux sorties sont **strictement
identiques** (comparaison ligne à ligne des deux journaux : *identiques*). Tri par PK,
sérialisation canonique fixe, aucune dépendance à l'ordre physique des lignes ⇒ les
empreintes sont **reproductibles**.

## 10. SHA SQLite (test final)

| Mesure | Valeur |
|---|---|
| SHA-256 **avant** la réconciliation | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| SHA-256 **après** la réconciliation | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| Baseline officielle attendue | `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0` |
| Résultat | **inchangée et conforme** ✅ |

La base SQLite de référence est **bit-à-bit identique** avant et après : aucune
écriture, aucun `VACUUM`, aucun `PRAGMA` persistant.

## 11. Reproductibilité

```powershell
cd C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma
.\.venv\Scripts\python.exe tools\pg4_reconciliation.py
```

- **SQLite** : `sqlite:///file:C:/…/compta_ma.db?mode=ro&uri=true` (lecture seule).
- **PostgreSQL** : `postgresql+psycopg://compta_ma_migrator@localhost:5432/compta_ma_staging`
  avec `options=-c default_transaction_read_only=on` (mot de passe fourni par le
  `pgpass.conf` du processus, **jamais écrit ni affiché**).
- Sortie déterministe : garde-fou, empreintes des 43 tables, FK, agrégats, focus,
  synthèse, verdict — code de sortie **0** si PASS.

---

## VERDICT

> ## ✅ PG4 PASS — FIDÉLITÉ SQLITE/POSTGRESQL VALIDÉE

- **43 / 43** tables métier : comptage, PK, FK, valeurs et **empreintes SHA-256**
  **identiques**.
- **3 131 = 3 131** lignes ; **0** valeur divergente ; **0** FK orpheline ;
  **0** anomalie de type.
- Empreinte globale **identique** : `2c4fb8e82abc3c2cd818c9359a95a125fc8cca1098292a3c91aaf3c0d48a3a74`.
- **0** différence dialectale non normalisée, **0** différence de représentation
  résiduelle, **0** anomalie métier.
- SHA SQLite **inchangé** : `E18B8981A475CE8AA05DBC79BBE4B82E463C0EFE88C7AE0C9F63B9258BB2B7F0`.

**STOP.**