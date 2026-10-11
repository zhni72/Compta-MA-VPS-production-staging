# Régularisation **P1 — suite** : dossier de validation

**Date** : 23/09/2026 · **Périmètre** : les 5 chantiers demandés après validation de la paie 2026.
**Aucune écriture 2025 n'a été touchée** (les écritures 2025 restent intactes) : la séquence 2025
n'est engagée qu'après validation du présent dossier et des pré-requis manquants (§ 6).

## 1. Réouverture d'exercice **sécurisée** (anomalie A10)

| Exigence demandée | Mise en œuvre | Test |
|---|---|---|
| Interdiction d'un simple changement de statut | La route web `POST /parametres/exercices/{year}/{statut}` passe **exclusivement** par les services `closing.reouvrir_exercice` / `cloturer_exercice` / `verrouiller_exercice` ; plus aucune écriture directe de `status` | `test_ecran_refuse_la_reouverture_sans_motif` |
| Motif obligatoire | `motif` ≥ 10 caractères exigé (réouverture **et** verrouillage), tracé dans la piste d'audit | `test_reouverture_refusee_sans_motif`, `test_verrouillage_exige_motif_et_exercice_clos` |
| Utilisateur + horodatage + piste d'audit | `FISCAL_YEAR_REOPENED` / `FISCAL_YEAR_LOCKED` / `OPENING_REGENERATED` avec motif, utilisateur, statut avant, impact N+1, instantané des à-nouveaux | `test_cycle_complet_...` |
| Contrôle de l'existence de N+1 | `apercu_reouverture()` restitue statut de N+1, nombre d'écritures, état des à-nouveaux ; N+1 **verrouillé** ⇒ refus | `test_reouverture_refusee_si_n_plus_1_verrouille` |
| Verrous de période | réouverture refusée tant qu'une période de l'exercice est verrouillée | `test_reouverture_refusee_si_periode_verrouillee` |
| Comparaison / régénération contrôlée des à-nouveaux | `regenerer_a_nouveaux()` : instantané **avant**, suppression tracée, régénération, **écarts par compte** (avant / après / écart) ; à-nouveaux régénérés **équilibrés** | `test_cycle_complet_reouverture_correction_recloture_regeneration` |
| Démonstration du cycle complet | Réouverture encadrée → correction → re-clôture → régénération : à-nouveaux 2026 recalculés, écart +500 DH isolé sur `1199` | idem (test dédié) |

## 2. Soldes bancaires créditeurs → trésorerie-passif

- **Contrôle** : `services.tresorerie.controler_tresorerie(db, company_id, year)` détecte tout
  compte de trésorerie **débiteur** présentant un solde créditeur (concours bancaire).
- **Reclassement CGNC** : `reclasser_solde_crediteur()` crée une **écriture OD tracée**
  (source `reclass_tresorerie`, référence unique `RECLASS-TRESO-<année>-<compte>`) —
  `5141/5143/5146 → 5541` (Banques, solde créditeur), `5148 → 5548` (autres établissements).
  Idempotent (refus explicite d'un second passage) et **motivé**.
- **Reclassement automatique** : `reclasser_soldes_crediteurs()` traite tous les comptes éligibles
  d'un exercice et **isole** les anomalies non reclassables : une **caisse créditrice** est une
  erreur de saisie (aucun compte de caisse créditeur au CGNC).
- **État de la base de recette (contrôle exécuté)** :
  `2025 : conforme=True, 0 solde créditeur` · `2026 : conforme=True, 0 solde créditeur`
  (le solde de `5141` est **débiteur** de 223 003,12 DH ; la mention « solde créditeur » du premier
  rapport P1 a été **corrigée** dans `P1_AVANT_APRES.md`, `REGULARISATION_P1.md` et README § 19).
- Tests : `tests/test_tresorerie.py` (5) — détection, reclassement vers `5541`/`5548`, idempotence,
  caisse non reclassable, reclassement automatique multi-comptes.

## 3. Garde-fou Paie **affiné** (doublons réels uniquement)

- **Règle** : `payroll.controle_doublon_paie()` distingue
  **bloquant** — écriture hors module portant la **numérotation de paie** (`PAIE…`) **ou**
  mouvementant un **compte de dette de paie** (`4432`, `4434`, `4441`, `4443`, `4445`, `4448`,
  `4452`) ;
  **avertissement** — charges `617x` hors module sans numérotation de paie ni dette de paie
  (OD légitime : régularisation, provision, avantage en nature).
- Les **OD légitimes en 617x sont désormais autorisées** (la paie du module se comptabilise), avec
  signalement à l'utilisateur ; seuls les **doublons réels** bloquent.
- Tests : `tests/test_paie_source_unique.py` (4) — OD légitime acceptée avec avertissement,
  doublon par référence `PAIE`, doublon par comptes de dette de paie, refus historical conservé.

## 4. Exonération de cotisation minimale sur les **dates réelles**

- **Nouvelles données société** : `date_constitution` et `date_debut_exploitation`
  (migration alembic `p1c1a2b3d4e5`, appliquée à la base de recette le 23/09/2026).
- **Calcul** : `fiscal_liasse.date_debut_activite()` retient, dans l'ordre,
  `date_debut_exploitation` → `date_constitution` → **début du premier exercice** (aucune date
  inventée) ; `mois_activite_effectif()` en déduit le nombre de mois d'activité cumulés et
  `exoneration_cotisation_minimale()` l'état d'exonération (début, fin = début + 36 mois).
- `calculer_is()` **n'a plus de `mois_activite = 12` par défaut** : la durée vient des dates
  réelles (la valeur reste saisissable par l'expert-comptable, et la source est restituée :
  `"saisie"` ou `"dates reelles de la societe…"`).
- Base de recette : `date_debut_exploitation = 2025-01-01` ⇒ 2025 : 12 mois (exonérée, fin
  2028-01-01) ; 2026 : 24 mois (exonérée) → cotisation minimale 2026 = **0,00 DH**, IS = 0 (perte).
- Tests : `tests/test_is_exercice_et_exoneration.py` (7) — mois calculés depuis les dates,
  exonération en cours, expiration après 36 mois (plancher 3 000 DH **dû malgré un déficit**),
  repli sur le premier exercice, priorité à la saisie explicite.

## 5. Recalcul fiscal d'un exercice antérieur au **taux de l'exercice**

- **Registre historisé** : `IS_RATES_BY_YEAR` (`app/core/rates_ma.py`) — chaque exercice porte ses
  taux ; `is_rates(annee)` et `compute_is(bnf, category, annee)` appliquent le **taux de
  l'exercice** et **refusent** un exercice non paramétré (message indiquant où fournir le barème) :
  aucun taux n'est deviné, aucune année n'emprunte le taux d'une autre.
- Les paramètres de cotisation minimale sont également historisés (`COTISATION_MINIMALE_BY_YEAR`).
- `calculer_is()` restitue désormais `taux_is_exercice`, `mois_activite` et
  `exoneration_cotisation_minimale` (dont la **source** du nombre de mois) : le dossier fiscal est
  auto-explicatif pour l'expert-comptable.
- Tests : `tests/test_is_exercice_et_exoneration.py` — taux 2026 appliqué via l'exercice ;
  **refus explicite pour 2025** tant que la loi de finances 2025 n'est pas paramétrée.

## 6. Pré-requis manquants pour la séquence 2025 (à fournir)

`P1B_SIMULATION_2025.md` (lecture seule, **aucune écriture créée**) mesure l'état actuel et les
blocages :

| Pré-requis | État | Conséquence |
|---|---|---|
| Barème de paie **2025** (`BAREMES_PAIE`) | **À FOURNIR** | la paie 2025 ne peut pas être **régénérée par le module** (IR/CNSS/AMO 2025) |
| Taux d'**IS 2025** (`IS_RATES_BY_YEAR`) | **À FOURNIR** | le recalcul fiscal 2025 est **refusé** tant que le taux de l'exercice n'est pas paramétré |
| Paramètres de **cotisation minimale 2025** | **À FOURNIR** | taux 0,25 %, plancher 3 000 DH, exonération 36 mois à confirmer |
| Réouverture encadrée + régénération des à-nouveaux | **OK** (livré et testé) | — |

**État 2025 actuel** : statut `closed`, aucun verrou, 12 écritures de paie synthétiques
(144 000 DH), résultat 73 600 DH, à-nouveaux 2026 = 387 520 DH (11 lignes, équilibrés).
**Impact projeté** (illustration avec le coût mensuel constaté en 2026) : charges de personnel
144 000 → **365 947,20 DH** ; résultat 73 600 → **−148 347,20 DH** ; à-nouveaux 2026 ajustés de
**+221 947,20 DH**, puis recalcul complet de 2026.

## 7. Tests et fichiers

- **Tests ajoutés (+22)** : `test_reouverture_exercice.py` (7), `test_tresorerie.py` (5),
  `test_is_exercice_et_exoneration.py` (7), `test_paie_source_unique.py` (+2) ;
  `test_audit_trail.py` et `test_api.py` **mis à jour** (la réouverture n'est plus bloquée en
  bloc : elle est **encadrée** ; l'API exige `motif`).
- **Suite complète** : **348/348 tests verts** (`PREUVE_P1SUITE_TESTS.log`, code de sortie **0**).
- **Fichiers modifiés** : `app/services/closing.py`, `app/services/payroll.py`,
  `app/services/fiscal_liasse.py`, `app/core/rates_ma.py`, `app/models/company.py`,
  `app/api/routers/audit.py`, `app/web/routes.py`,
  `app/web/templates/parametres_exercices.html`, `README.md`, `CAHIER_DES_CHARGES_GLOBAL.md`.
- **Fichiers créés** : `app/services/tresorerie.py`,
  `alembic/versions/p1c1a2b3d4e5_dates_societe_constitution_exploitation.py`,
  `tests/test_reouverture_exercice.py`, `tests/test_tresorerie.py`,
  `tests/test_is_exercice_et_exoneration.py`, `tools/p1b_simulation_2025.py`,
  `P1B_SIMULATION_2025.md`, `PREUVE_P1SUITE_TESTS.log`, le présent dossier.

## 8. Déclaration de fin de phase (suite P1)

**PASS** — les 5 chantiers sont livrés, testés (348/348) et démontrés : réouverture encadrée,
contrôle/reclassement des soldes créditeurs de trésorerie, garde-fou Paie ciblé sur les doublons
réels, exonération de cotisation minimale calculée sur les dates réelles, recalcul fiscal au taux
de l'exercice. **La séquence 2025 attend votre validation** et les trois paramétrages ci-dessus
(barème de paie 2025, taux d'IS 2025, paramètres de cotisation minimale 2025) ; les écritures 2025
sont **intactes**.
