# Régularisation **P0** (audit J9) — dossier de validation

**Date** : 23/09/2026 · **Périmètre** : P0 uniquement (P1/P2 **non entamés**, conformément à la
règle « ne pas passer à P1 avant démonstration PASS de P0 »).
**Aucune donnée métier modifiée** : `compta_ma.db` porte toujours son horodatage du **23/09/2026 04:07**
(antérieur à tous les correctifs) — audit, preuve et balayages sont en **lecture seule**.

## 1. Fichiers modifiés (9)

| Fichier | Modification |
|---|---|
| `app/main.py` | API REST montée **exclusivement sous `/api`** (`API_PREFIX`), interface en `include_in_schema=False` : isolation structurelle API / UI |
| `app/services/edi_tva.py` | Base HT **et** TVA calculées sur la **même fraction éligible** (cumuls plafonnés au TTC) ; nouvelle fonction `verifier_lignes()` (**contrôles bloquants** `HT + TVA = TTC`, `TVA = base × taux × prorata`) remontée dans `collect_rd_lines` et **bloquante dans `build_rd_xml`** |
| `app/services/etats_synthese.py` | `detail()` / `total()` : comparaison par **préfixe** de compte (`startswith`) → notes 9 (617) et 4 (619) alimentées |
| `app/services/invoicing.py` | Nouveau `controles_coherence_facture()` (lignes ↔ totaux, lignes à zéro) et **contrôle bloquant à la validation** |
| `app/services/pdf_documents.py` | `DocumentIncoherentError` + **refus d'émission** d'un PDF de facture dont les lignes / la ventilation TVA ne réconcilient pas les totaux |
| `app/web/routes.py` | Détail et aperçu reçoivent `incoherences` ; téléchargement PDF **refusé avec message** ; import des labels de valorisation (`VALUATION_METHOD_LABELS`) — corrige la **500** de `/stocks` révélée par l'isolation |
| `app/web/templates/factures_detail.html` | Alerte « **Document incohérent** » (liste des anomalies) |
| `app/web/templates/factures_impression.html` | Idem sur l'aperçu avant impression |
| `CAHIER_DES_CHARGES_GLOBAL.md` · `README.md` | CDC **v2.11** : § 8 bis (écarts A25-A28), § 10.5 (validation P0), plancher de tests 300 → 324 ; README § 7 (préfixe `/api`, rupture d'interface documentée) et **§ 18** (régularisation P0) |

## 2. Tests de non-régression ajoutés (24 → total **324**)

| Fichier | Nb | Ce qu'ils reproduisent / verrouillent |
|---|---|---|
| `tests/test_routing_isolation.py` | 5 | **aucun** couple (méthode, chemin) partagé API/interface ; surface OpenAPI sous `/api` ; `/audit`, `/audit/export`, `/stocks` en **200** avec session ; **303** sans session ; API en **401** sans jeton et 200 avec |
| `tests/test_ecrans_smoke.py` | 8 | balayage de **tous** les écrans GET (aucune 5xx) + 7 écrans métier clés (dont les 3 autrefois masqués) |
| `tests/test_edi_tva.py` | +2 | facture partiellement réglée : base **proratisée** (49,17 / 9,84 / 59,01), XML cohérent ; **refus de génération** sur la signature exacte du défaut J9 (mht complet + TVA fractionnée) |
| `tests/test_etic_notes.py` | 3 | note 9 = 617x (4 comptes, total 17 700) ; note 4 porte `6193` ; non-régression des racines à 2 caractères |
| `tests/test_facture_document.py` | 6 | cas nominal ; **ligne à 0 refusée à la validation** ; **PDF refusé** si ligne à 0 ; facture sans ligne refusée ; écrans avertis ; téléchargement refusé avec message |

Deux tests existants ont été **mis à jour** (comportement erroné devenu interdit) :
`test_facture_partiellement_reglee_deduction_par_reglement` (base désormais proratisée) et
l'alignement des appels API sur le préfixe `/api` (`tests/test_api.py`, `tests/conftest.py`).

## 3. Résultat complet de la suite

`PREUVE_P0_TESTS.log` : **324 tests, 100 %, aucune erreur ni échec**, code de sortie **0**
(324 tests collectés, vérifié par `--collect-only`). Avant P0 : 300 tests verts
(insuffisants : les 4 anomalies P0 n'étaient pas couvertes).

## 4. Preuve fonctionnelle avant / après

`PREUVE_P0.md` (généré par `tools/p0_preuve_avant_apres.py`, lecture seule) :

| Item | Avant (reproduit) | Après (mesuré) |
|---|---|---|
| P0.1 `/audit`, `/audit/export`, `/stocks` (session Web valide) | **HTTP 401** | **HTTP 200** (303 vers `/connexion` sans session, `/api/audit` 401 sans jeton / 200 avec) |
| P0.2 ligne EDI FA26-12 (9 000 / 1 800 / 10 800, réglée 4 320) | mht **9 000** / tva 720 / ttc 9 720 → taux/base **NON** respecté | **3 600 / 720 / 4 320** → cohérent |
| P0.2 scan des 48 périodes 2025-2026 | **45** lignes incohérentes | **0** |
| P0.3 note 9 ETIC (617x) | **0 compte**, note vide | **6 comptes**, total **203 295,60 DH** |
| P0.4 documents de facture | aucune vérification (document transmis) | **74 factures** balayées : 0 incohérence produite ; toute incohérence → **validation et émission refusées** avec message (`tools/scan_documents_facture.py`) |

## 5. Portée et suites

- **Rupture d'interface assumée et documentée** : les consommateurs de l'API doivent utiliser
  `/api/...` (README § 7). Aucune fonctionnalité retirée ; l'interface graphique est inchangée.
- **Non traité en P0 (par construction)** : double alimentation Paie / IS (P1), réouverture
  d'exercice (P1), workflow Greffe (P1), immobilisations 2340, TVA immo, écran Provisions,
  menu Journal, colonne Pièce, formulaire d'exercice, `payments.entry_id`, DTS/liasse (P2).
- **P0 = PASS** : les 4 items sont corrigés à la racine, chacun couvert par un test qui échouait
  avant, avec preuve avant/après mesurée et **aucune donnée hors périmètre modifiée**.
