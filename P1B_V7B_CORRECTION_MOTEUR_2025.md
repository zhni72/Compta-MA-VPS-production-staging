# P1B V7B — CORRECTION DU MOTEUR RÉGLEMENTAIRE 2025 + TESTS

**Projet** : Compta MA — `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Date** : 06/10/2026 — **Mode** : correction moteur/référentiels ciblés uniquement (aucune donnée comptable, aucune DB, aucune migration, aucun Web Fetch, aucune installation)
**Références** : `P1B_REFERENTIELS_PAIE_2025_V6_LOCAL.md` (index V6), `P1B_V7A_ARBITRAGE_AMO_CM_2025.md`, `P1B_V7A_CORRECTIF_AMO_2025.md`
**Python** : `.venv\Scripts\python.exe` du projet (seul venv utilisé)

---

## 0. Garde-fou (avéré avant toute modification)

| Élément | État |
|---|---|
| cwd exact = `compta_ma` | OK |
| `compta_ma.db` existe | OK |
| `app/` existe | OK |
| `tests/` existe | OK |
| `.venv\Scripts\python.exe` existe | OK |
| Baseline | **448 tests — PASS** (collecte 448, exécution exit 0) |

---

## 1. Fichiers modifiés

### Moteur / référentiels (Python, versionnés dans le code)

| Fichier | Nature |
|---|---|
| `app/core/rates_ma.py` | Taux IS 2025, jeu CNSS/AMO 2025, frais pro 2025, `BAREMES_PAIE[2025]`, paramètres CM (butee 60), docstrings/sources CM, signature `compute_cotisation_minimale` |
| `app/services/fiscal_liasse.py` | Nouvelle `assiette_cotisation_minimale()` (hors TVA), exonération CM avec butée 60 mois, `calculer_is` sur assiette hors TVA, clés de retour CM |
| `app/services/payroll.py` | `calculer_bulletin` : barème de l'exercice transmis à `compute_cnss` / `frais_professionnels_mensuels` |
| `app/web/templates/liasse.html` | Libellé KPI : « (CA TTC …) » → « (base CM hors TVA …) » |

### Tests

| Fichier | Nature |
|---|---|
| `tests/test_v7b_corrections_2025.py` | **NOUVEAU** — 8 tests réglementaires ciblés 2025 |
| `tests/test_rates_ma_2025.py` | 7 tests mis à jour/renommés (IS, CM, paie 2025, sources) |
| `tests/test_fiscal_liasse.py` | Docstring CM-4 (CA TTC n'est plus la base CM) |
| `tests/test_is_exercice_et_exoneration.py` | Docstring CM-4 |
| `tests/test_rates_ma.py` | Commentaire CM-4 |

### Documentation

| Fichier | Nature |
|---|---|
| `P1B_V7B_CORRECTION_MOTEUR_2025.md` | Le présent rapport (créé une seule fois, à la fin) |

**Aucun autre fichier touché** : ni `compta_ma.db`, ni migrations Alembic, ni schéma, ni données, ni bulletins, ni écritures, ni `.venv`, ni corpus `Documentation`, ni rapports V4/V5/V6/V7A.

---

## 2. Valeurs avant → après

### IS 2025 (`rates_ma.IS_RATES_BY_YEAR[2025]`)

| Catégorie | Avant | Après (réf. V6 / CGI 2025 art. 247-XXXVII p. 470-472) |
|---|---|---|
| `large_company` (BNF ≥ 100 M DH) | 0.35 (35 %) | **0.3125 (31,25 %)** |
| `financial` (crédit/assurances/BAM/CDG) | 0.40 (40 %) | **0.3925 (39,25 %)** |
| `cfc` (CFC/ZAI) | 0.20 (20 %) | **0.1875 (18,75 %)** |
| `small_profit` (≤ 300 000 DH) | 0.175 (17,5 %) | **inchangé (conforme)** |
| `standard` | 0.20 (20 %) | **inchangé (conforme)** |
| `IS_RATES_BY_YEAR[2026]` (toutes) | 20/35/40 % | **inchangé — 2026 non affecté** |

### Cotisation minimale (CM)

| Élément | Avant | Après |
|---|---|---|
| Base de calcul | `chiffre_affaires_ttc` = CA HT (71x) **+ TVA collectée (4455)** | **`assiette_cotisation_minimale().base_hors_tva`** = 71x + 75x + 76x + 74x/77x **hors TVA** (TVA exclue) |
| Contenu d'assiette | uniquement 71x | **+ autres produits d'exploitation (75x), produits financiers (76x), subventions/dons (74x/77x)** |
| Exonération | 36 mois d'activité | **36 mois d'activité + butée 60 mois depuis la constitution** (`exemption_butee_months = 60`) |
| Paramètre d'entrée | `compute_cotisation_minimale(ca_ttc, …)` | `compute_cotisation_minimale(assiette, …)` |
| Taux / plancher / 36 mois | 0,25 % / 3 000 DH / 36 | **inchangés (conformes V7A)** |
| Clés de retour `calculer_is` | — | **+ `base_cotisation_minimale`, `detail_base_cotisation_minimale`, `butee_constitution_mois`, `fin_butee_constitution`** |

### Paie 2025 (`BAREMES_PAIE[2025]`)

| Paramètre | Avant | Après |
|---|---|---|
| `frais_professionnels` | `None` (calcul **refusé**) | **`IR_PROFESSIONAL_EXPENSES_2025`** : 35 % ≤ 78 000 DH, 25 % au-delà, plafond 35 000 DH (CGI 2025 art. 59) |
| `cnss` | `None` (calcul **refusé**) | **`CNSS_2025`** : 4,48 %/8,98 % (plafond 6 000 DH), AMO 2,26 %/4,11 %, PF 6,40 %, TFP 1,60 % |
| `parametres_paie_manquants(2025)` | 2 entrées | **`[]`** |
| `referentiel_complet(2025)` | `False` | **`True`** |
| `IR_BRACKETS_2025` / charges de famille | 37 % tranche haute / 500 DH × 6 | **inchangés (conformes V6)** |
| `calculer_bulletin` | `compute_cnss`/frais pro appelés **sans année** (défaut 2026) | **année de la période transmise** (barème historisé de l'exercice) |
| Refus des années non paramétrées | 2027 refusé | **2027 refusé (conservé)** |

### Sources 2025 (`SOURCES_REFERENTIELS[2025]`)

- Frais professionnels / CNSS-AMO / PF-TFP : statut `a_fournir` → **`documenté`** (sources V6) ;
- IS 2025 : valeurs actualisées à 31,25 % / 39,25 % / 18,75 % (CGI 2025 p. 470-472) ;
- CM 2025 et CM 2026 : terminologie **« hors TVA »** + butée 60 mois (CM-4).

---

## 3. Corrections CM réalisées (d'après V7A + CGI 2025 local)

- **CM-1 — TVA** : suppression de tout calcul ajoutant la TVA à la base CM. `calculer_is` n'utilise plus `chiffre_affaires_ttc` ; la nouvelle fonction `assiette_cotisation_minimale()` exclut `4455` et somme uniquement les comptes de produits (racines 71/74/75/76/77), soldes créditeurs inversés. Test : `test_base_cm_hors_tva` (assiette 333 333,33 ≠ TTC 400 000).
- **CM-2 — Assiette** : complétée selon CGI 2025 art. 144-I-B (rappel art. 9-I) avec les catégories démontrées en V7A : autres produits d'exploitation (75x), produits financiers (76x), subventions/dons (74x/77x). Aucune catégorie non prouvée ajoutée. Test : `test_assiette_cm_complete_produits_financiers_subventions`.
- **CM-3 — Exonération** : règle des 36 mois conservée **et** butée maximale **60 mois depuis la constitution** implémentée (art. 144-I-C-1°) : `fin_exoneration = min(début exploitation + 36 mois, constitution + 60 mois)` ; si l'exercice finit après la butée, `exoneree = False` et la CM devient exigible (`mois_cm` transmis au barème). Tests : `test_exoneration_36_mois_et_butee_60_mois`, extension de `test_exoneration_cotisation_minimale_par_dates_reelles`.
- **CM-4 — Terminologie** : paramètre `ca_ttc` → `assiette` ; docstrings/commentaires/sources « 0,25 % du CA TTC » → « 0,25 % des produits hors TVA » ; libellé écran liasse « (CA TTC …) » → « (base CM hors TVA …) ». Le nom `chiffre_affaires_ttc` subsiste comme **figure comptable informationnelle** (plus jamais base CM).
- Taux 0,25 %, plancher 3 000 DH, exonération 36 mois : **aucune valeur modifiée** (conformes).

---

## 4. Corrections IS 2025 réalisées (d'après tableau V6)

- `large_company` 35 % → **31,25 %** ; `financial` 40 % → **39,25 %** ; `cfc` 20 % → **18,75 %** (CGI 2025 art. 247-XXXVII, p. 470-472, index V6 §6.4).
- Non modifiés : `small_profit` **17,5 %** (≤ 300 000 DH), `standard` **20 %** (déjà conformes), toute la grille **2026** (inchangée et vérifiée par tests).
- Protection conservée : `is_rates(annee)` **refuse** une année sans barème (`ValueError`, ex. 2024) — aucun taux deviné ni extrapolé.

---

## 5. Autres paramètres 2025 corrigés

- **Frais professionnels 2025** : barème alimenté (35 %/25 %, seuil 78 000 DH, plafond 35 000 DH) — écart « paie 2025 bloquée » explicitement identifié en V6 §6.1.
- **CNSS/AMO/PF/TFP 2025** : jeu `CNSS_2025` alimenté (valeurs V6/V7A-CORR : 4,48/8,98 %, plafond 6 000, AMO 2,26/4,11 %, PF 6,40 %, TFP 1,60 %).
- **`calculer_bulletin`** : transmission de l'exercice aux calculs CNSS/frais pro (aucune application implicite des taux 2026 pour une paie 2025).
- **IR 2025** : tranche haute 37 % et charges de famille 500 DH × max 6 **déjà conformes** — non réécrits.

---

## 6. Confirmation AMO inchangée

Aucune valeur AMO modifiée. Le jeu moteur reste **2,26 % salarié / 4,11 % employeur / 6,37 % total**, assiette brute sans plafond (conformes au décret 2-14-707, BO 6314 p. 4770-4771 — V7A-CORR). Test de non-régression ajouté : `test_amo_2025_non_regression_totaux`.

---

## 7. Tests ajoutés / mis à jour

**Nouveau fichier `tests/test_v7b_corrections_2025.py` — 8 tests :**

1. `test_amo_2025_non_regression_totaux` — 2,26 % / 4,11 % / 6,37 %, sans plafond, 2026 identique ;
2. `test_base_cm_hors_tva` — TVA exclue de l'assiette CM ;
3. `test_assiette_cm_complete_produits_financiers_subventions` — assiette complète 71/75/76/77 ;
4. `test_cm_2025_taux_et_plancher_via_calculer_is` — taux 0,25 %, plancher 3 000 DH ;
5. `test_exoneration_36_mois_et_butee_60_mois` — exonération 36 mois + butée 60 mois ;
6. `test_cm_non_exigible_societe_recente` — cas société actuelle (début 2025-01-01) : CM = 0 ;
7. `test_is_2025_cas_courant_conforme_via_calculer_is` — cas courant 2025 conforme, bornes 17,5 %/20 %, CM due en déficit ;
8. `test_paie_2025_parametres_corriges_en_memoire` — frais pro/CNSS/AMO/IR 2025, refus 2027 (aucune paie en DB).

**`tests/test_rates_ma_2025.py` mis à jour (9 tests)** : grille IS corrigée (31,25/39,25/18,75 % + 2026 inchangé), CM 2025 (butee 60), paie 2025 calculable (renommé `test_paie_2025_calculee_avec_ses_propres_taux`), référentiel complet (renommé `test_parametres_2025_documentes_sont_complets`), `compute_is(200M, 2025) = 62 500 000` (31,25 %) + refus 2024, exonération avec butée, sources sans `a_fournir` (renommé `test_sources_2025_documentees`).

**Docstrings/comments CM-4** mis à jour : `test_fiscal_liasse.py`, `test_is_exercice_et_exoneration.py`, `test_rates_ma.py`.

**Aucune création de vraie paie ni d'écriture en DB réelle** : toutes les écritures V7B passent par le fixture SQLite **en mémoire** (compta_ma.db jamais ouvert par les tests).

---

## 8. Résultat des tests ciblés V7B

```
pytest tests/test_v7b_corrections_2025.py tests/test_rates_ma_2025.py
-> 17 tests — PASS (exit 0)
```

## 9. Résultat de la suite complète

| Étape | Périmètre | Résultat |
|---|---|---|
| 1. Tests ciblés V7B | `test_v7b_corrections_2025.py` + `test_rates_ma_2025.py` | **17 PASS** |
| 2. Fiscalité/paie concernés | `test_rates_ma`, `test_fiscal_liasse`, `test_is_exercice_et_exoneration`, `test_payroll`, `test_paie_source_unique`, `test_liasse`, `test_vat` | **91 PASS** |
| 3. Suite complète | `pytest tests` | **456 tests collectés — exit 0 (0 échec, 0 régression)** |

Baseline 448 → **456** (+8 tests V7B). **0 régression.**

---

## 10. Preuve DB (avant / après — identiques)

| Mesure | Avant V7B | Après V7B |
|---|---|---|
| SHA-256 `compta_ma.db` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` |
| Taille | 1 163 264 o | 1 163 264 o |
| Date de modification | 2026-09-24 02:55:05 | 2026-09-24 02:55:05 |

**Strictement identiques.** Aucun correctif n'a nécessité de migration, de modification de données, de schéma ou de données de dossier : **rien à signaler** à ce titre (§7 du cahier).

---

## 11. Éléments non corrigés (faute de preuve ou hors périmètre — non bloquants)

1. **Seuil IS « ≥ 100 M DH » vs comparateur `>`** (V6 §6.4) : `IS_LARGE_COMPANY_THRESHOLD` est un paramètre **unique partagé 2025/2026** ; seul l'écart 2025 est documenté par le corpus (CGI 2025 p. 471). Corriger le comparateur reviendrait à extrapoler une règle non documentée à 2026 → **laissé inchangé** (impact unique : BNF exactement = 100 000 000 DH, frontière).
2. **Plafond frais pro tranche basse 30 000 DH** : non prouvé par le corpus (V6 §6.6) — conservé identique au jeu 2026 (sans impact arithmétique : 35 % × 78 000 = 27 300 < 30 000).
3. **Outils de simulation** `tools/p1b_simulation_2025_v3.py`, `tools/_nouveau_rapport.txt`, `tools/p1_rapport_avant_apres.py` : affichent encore la base « CA TTC » des livrables V3/V4 — **hors périmètre « moteur »** (§7/§11/§12 du cahier) : non modifiés. Le moteur (`calculer_is`) et ses sorties sont corrigés.
4. **Documentation historique** (`CAHIER_DES_CHARGES.md`, `CAHIER_DES_CHARGES_GLOBAL.md`, `README.md`, rapports V3/V4/V6/V7A) : exigences/historique antérieurs, non réécrits (documents historiques ≠ documentation V7B).
5. **Exclusions d'assiette CNSS (arrêté 1314-25)** : non modélisées (V6 réserve 3 — détail côté simulation, aucun taux concerné) — hors périmètre V7B.
6. **AMO — segment OCR « répartis à parts égales »** (V7A-CORR) : réserve purement documentaire, moteur inchangé.

---

## 12. Verdict

> ## **MOTEUR 2025 PRÊT POUR SIMULATION FINALE READ-ONLY**

Tous les écarts réglementaires 2025 démontrés en V6 et V7A/V7A-CORR (CM-1/2/3/4, taux IS sectoriels 2025, paie 2025 bloquée) sont corrigés et couverts par tests ; AMO inchangée (non-régression) ; 2026 inchangé ; 456/456 tests PASS ; DB strictement inchangée. Les réserves du §11 restent documentées (aucune n'est un écart de taux démontré sur une année documentée).

**Ce verdict n'autorise toujours pas Stage 3** — validation humaine requise avant toute simulation finale ou écriture 2025.




