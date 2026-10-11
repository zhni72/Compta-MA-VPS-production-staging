# P1B V8 — SIMULATION FINALE 2025 — READ-ONLY

**Projet** : `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Interpréteur** : `.venv\Scripts\python.exe` (exclusif). **Aucune écriture DB, aucun code modifié, aucun salarié/crédit/cycle créé, aucune écriture supprimée, aucune migration, aucun package, aucun Web Fetch, aucun Stage 3.**

## 0. Garde-fou
| Contrôle | État |
|---|---|
| cwd = `compta_ma` exact | OK |
| `compta_ma.db` existe | OK |
| `app/` existe | OK |
| `tests/` existe | OK |
| `.venv\Scripts\python.exe` existe | OK |
| Baseline déclarée | 456 tests PASS (V7B — non relancée, anti-boucle) |

## 1. Pré-check frais professionnels (unique, runtime 2025)
Chemin runtime réel : `calculer_bulletin()` (`app/services/payroll.py` l.443) → `frais_professionnels_mensuels()` (`app/core/rates_ma.py` l.157-164) → `compute_professional_expenses()` (l.498-512) → `BAREMES_PAIE[2025]["frais_professionnels"] = IR_PROFESSIONAL_EXPENSES_2025`.

| Attendu | Constaté | État |
|---|---|---|
| seuil = 78 000 DH | `gross_threshold = 78000` (l.76) | OK |
| taux 35 % puis 25 % | `rate_below = 0.35`, `rate_above = 0.25` (l.77/79) | OK |
| plafond annuel réellement utilisé = 35 000 DH | `cap_above = 35000` (l.80) — seul plafond opposable | OK |

**ANOMALIE BLOQUANTE §3 (non corrigée en V8, interdit)** : la branche runtime consomme encore **30 000 DH** — fichier **`app/core/rates_ma.py`**, constante **`IR_PROFESSIONAL_EXPENSES_2025["cap_below"]` ligne 78**, lue à la **ligne 511** de **`compute_professional_expenses()`** (branche `brut ≤ 78 000` : `min(brut × 0,35, 30000)`).
- Opposabilité arithmétique : **néant** — `78 000 × 35 % = 27 300 < 30 000` (branche jamais contraignante ; réserve déjà documentée V7B §11.2).
- Valeurs réellement utilisées dans le scénario (aucun plafond n'atteint) : SAL-2025-A FP annuel **25 200,00** (2 100,00/mois) ; SAL-2025-B **24 780,00** (2 065,00/mois) — soit 35 % du brut.
- Conformément à §3, la simulation est poursuivie avec ces valeurs réellement utilisées, et **le verdict final est NON PRÊT POUR STAGE 3**.

## 2. Paramètres réellement utilisés (appels réels, aucun taux saisi en dur)
- **IR 2025** : tranches 40 000/60 000/80 000/100 000/180 000/∞ — 0/10/20/30/34/**37 %** (SAD 27 400) ; déduction charges de famille **500 DH/personne, max 6** (`IR_BRACKETS_2025`, `IR_FAMILY_DEDUCTION_BY_YEAR[2025]`).
- **CNSS 2025** : salarié 4,48 % / employeur 8,98 % / plafond 6 000 DH. **AMO 2025** : salarié 2,26 % / employeur 4,11 %, sans plafond. **PF 6,40 %** / **TFP 1,60 %** (`CNSS_2025`).
- **IS 2025** : standard 20 %, small_profit **17,5 %** (BNF ≤ 300 000), grandes entreprises 31,25 % (`IS_RATES_BY_YEAR[2025]`).
- **CM 2025** : 0,25 %, plancher 3 000 DH, exonération **36 mois**, butée **60 mois** (`COTISATION_MINIMALE_BY_YEAR[2025]`).
- `parametres_paie_manquants(2025)` = **[]** ; `bareme_paie(2025)` / `compute_cnss` / `compute_ir_monthly` : **aucun `BaremeIndisponible`** ; exercices disponibles : 2025, 2026.

## 3. Calcul mensuel par salarié (scénario recette V4, exécution unique)
| Rubrique | SAL-2025-A | SAL-2025-B | Entreprise |
|---|---|---|---|
| Brut mensuel | 6 000,00 | 5 900,00 | 11 900,00 |
| CNSS salarié 4,48 % (pl. 6 000) | 268,80 | 264,32 | 533,12 |
| AMO salarié 2,26 % | 135,60 | 133,34 | 268,94 |
| Cotisations salariales | 404,40 | 397,66 | 802,06 |
| Frais professionnels (35 %) | 2 100,00 | 2 065,00 | 4 165,00 |
| Base imposable | 3 495,60 | 3 437,34 | 6 932,94 |
| IR mensuel (annualisation, 0/1 charge) | 16,23 | 0,00 (500 > 124,81) | 16,23 |
| **Net à payer** | **5 579,37** | **5 502,34** | **11 081,71** |
| CNSS employeur 8,98 % | 538,80 | 529,82 | 1 068,62 |
| AMO employeur 4,11 % | 246,60 | 242,49 | 489,09 |
| Prestations familiales 6,40 % | 384,00 | 377,60 | 761,60 |
| TFP 1,60 % | 96,00 | 94,40 | 190,40 |
| Charges patronales | 1 265,40 | 1 244,31 | 2 509,71 |
| **Coût employeur** | **7 265,40** | **7 144,31** | **14 409,71** |

Profils EMP001/EMP002/EMP003 exclus ; aucun salarié créé (DB : `employees` inchangée, `payroll_runs` = 12 cycles 2026 uniquement).

## 4. Consolidation mensuelle
Brut 11 900,00 — cotisations salariales 802,06 — FP 4 165,00 — base imposable 6 932,94 — IR 16,23 — net 11 081,71 — charges patronales 2 509,71 — **coût employeur 14 409,71**.

## 5. Consolidation annuelle (12 mois)
Brut 142 800,00 — CNSS s. 6 397,44 — AMO s. 3 227,28 — cotisations s. 9 624,72 — FP 49 980,00 — IR 194,76 — **nets 132 980,52** — CNSS p. 12 823,44 — AMO p. 5 869,08 — PF 9 139,20 — TFP 2 284,80 — charges patronales 30 116,52 — **coût employeur annuel 172 916,52**.

## 6. Écart avec les anciennes écritures synthétiques
- Ancien : 12 × (6171 D 10 000 + 6174 D 2 000 / 5141 C 12 000) = **144 000,00/an** (PAIE25-01…12, journal BQ, toutes `validated`).
- Nouveau coût paie : **172 916,52/an** → **impact = 172 916,52 − 144 000,00 = +28 916,52** (impact résultat avant IS : **−28 916,52**).
- **Coût vs cible historique 14 400,00** : mensuel **+9,71** (+0,07 %), annuel **+116,52** — aucun montant forcé.

## 7. Écritures simulées (mapping réel du module, en mémoire)
**Mensuelle — journal OD (`lignes_ecriture_paie`) :**
| Compte | Libellé | Débit | Crédit |
|---|---|---|---|
| 61711 | Salaire de base | 11 900,00 | |
| 61741 | Cotisations patronales CNSS/AMO | 1 557,71 | |
| 61744 | Prestations familiales | 761,60 | |
| 61768 | Taxe de formation professionnelle | 190,40 | |
| 4432 | Rémunérations dues au personnel | | 11 081,71 |
| 4441 | CNSS/AMO (salariale + patronale + PF + TFP) | | 3 311,77 |
| 4452 | État — IR retenu | | 16,23 |
| **Total** | | **14 409,71** | **14 409,71** |

**Mensuelle paiement — journal BQ (`payer_paie`) :** 4432 D 11 081,71 / 5141 C 11 081,71 (équilibré).
**Annuelles (×12) :** 61711 142 800,00 D ; 61741 18 692,52 D ; 61744 9 139,20 D ; 61768 2 284,80 D ; 4432 132 980,52 C puis soldé 132 980,52 D par les paiements ; 4441 39 741,24 C ; 4452 194,76 C ; 5141 132 980,52 C. **Totaux D = C = 172 916,52 (paie) et 132 980,52 (paiements)** — contrôle D = Crédit OK mensuel comme annuel.
**Journal simulé** : 89 → **101** écritures 2025 (−12 synthétiques BQ, +12 OD paie, +12 BQ paiement).

## 8. Résultat comptable final simulé (remplacement effectué en mémoire, PAIE25 physiquement intactes)
- Journal : équilibré (voir 7). **Balance simulée : 1 701 416,65 D = 1 701 416,65 C** (avant 1 546 880,00).
- **CPC** : produits 360 000,00 — charges **307 956,13** dont IS 11 039,61 → charges hors IS **296 916,52** → **résultat avant IS = 63 083,48** (avant 92 000,00). Charges de personnel 617x = **172 916,52** (avant 144 000,00 ; 6171/6174 ramenés à 0 — aucun double compte de paie).
- **Bilan simulé : Actif 386 539,48 = Passif 386 539,48** (dont résultat 52 043,87) ; avant 375 520,00.
- **ESG/ETIC** : cohérents — résultat avant IS 63 083,48 / IS 11 039,61 / **résultat net 52 043,87**, identiques CPC = Bilan = ESG.
- **Absence de double paie** : `entries.source='payroll'` 2025 = 0 ; `payroll_runs` 2025 = 0 ; PAIE25-* = **12 physiques, intactes** ; retrait simulé uniquement.

## 9. Résultat fiscal / IS / CM (moteur V7B, session réelle sqlite `mode=ro`)
- **Résultat comptable avant IS = 63 083,48** ; réintégrations **0,00** (`charges_non_deductibles()` réel → propositions **[]** ; comptes catalogue 6581/6582/6583/65831/65833, 6195/6196/6197, 1515, 1555 absents des mouvements 2025) ; déductions **0,00** ; report déficitaire 0,00.
- **Résultat fiscal = 63 083,48** (le résultat net n'est jamais utilisé comme base fiscale ; IS comptabilisé exclu via « avant impôt »).
- **IS 2025 = 17,5 % × 63 083,48 = 11 039,61** (`compute_is(annee=2025)`, small_profit ≤ 300 000).
- **CM 2025** : assiette **hors TVA = 360 000,00** (racines 71 = 360 000 ; 74/75/76/77 = 0 ; TVA exclue — V7B CM-1) ; taux 0,25 % → 900 < plancher **3 000** ; **exonérée** : 12 mois d'activité < 36 (fin exonération 2028-01-01 ; butée 60 mois depuis constitution → 2030-01-01) → **CM = 0,00** (hors exonération : 3 000,00).
- **IS vs CM** : impôt dû = max(11 039,61 ; 0,00) = **11 039,61**.
- **IS comptabilisé historiquement = 18 400,00** (EC202500089) → **régularisation théorique = −7 360,39** (reprise 6701/4453, à entériner).
- État actuel réel (`calculer_is()` appelé) : résultat avant impôt 92 000,00, IS théorique 16 100,00 (taux effectif 17,50 %), CM 0,00 — cohérent avec les bases connues.

## 10. Résultat net final simulé
**63 083,48 − 11 039,61 = 52 043,87 DH** (vs 73 600,00 actuel — **Δ −21 556,13**).

## 11. Impact à-nouveaux 2026 (simulé, aucun à-nouveau régénéré)
| Compte | Ouverture actuelle 2026 | Ouverture simulée | Δ (D−C) |
|---|---|---|---|
| 5141 Banque | 228 320,00 D | **239 339,48 D** | **+11 019,48** |
| 4441 CNSS/AMO | absent | **39 741,24 C** | **−39 741,24** |
| 4452 IR | absent | **194,76 C** | **−194,76** |
| 4453 IS dû | 18 400,00 C | **11 039,61 C** | **+7 360,39** |
| 1191 Report à nouveau | 73 600,00 C | **52 043,87 C** | **+21 556,13** |
| 1111/2340/2834/3111/3421/34552/4411/4455 | inchangés | inchangés | 0,00 |
| **Total AN** | **387 520,00** | **398 539,48** | **delta global = 0,00 (équilibré)** |

**Correction vs V4** : V4 indiquait 5141 = 217 300,52 (sens inversé) ; le recalcul V8 donne **239 339,48** — décaissement net plus faible (132 980,52 au lieu de 144 000,00) ⇒ solde banque **supérieur** de 11 019,48. Le tableau V8 est équilibré (Δ global 0,00).

## 12. Impact 2026
- **Report à nouveau (1191)** : −21 556,13 (73 600,00 → 52 043,87).
- **Dette IS (4453)** : −7 360,39 (18 400,00 → 11 039,61).
- **Banque (5141)** : +11 019,48 à l'ouverture.
- **Dettes sociales/IR** : 4441 +39 741,24 et 4452 +194,76 (nouvelles, hypothèse : réglées en 2026 — comme V4).
- **Équilibre d'ouverture** : Δ global 0,00. **Paie 2026 inchangée** : 12 cycles 2026 et 36 bulletins intacts, aucune modification 2026.

## 13. Impact Greffe 2025
Documents à régénérer après une future régularisation contrôlée : **Bilan 2025**, **CPC 2025**, **ESG/ETIC 2025** (résultat et charges de personnel), **rapport de gestion**, **PV AG** (résultat à affecter : 73 600,00 → 52 043,87), **bordereau/dossier Greffe**. Aucun PDF Greffe régénéré dans V8. Dossier actuel **provisoire**.

## 14. Anomalies / réserves restantes
1. **BLOQUANTE (§3)** : `IR_PROFESSIONAL_EXPENSES_2025["cap_below"] = 30000` toujours consommé en runtime (`app/core/rates_ma.py` l.78 / l.511, `compute_professional_expenses`) — non corrigé en V8 (interdit), non opposable arithmétiquement (27 300 < 30 000) mais sa présence déclenche §3 → **NON PRÊT**. *Note d'arbitrage pour le validateur humain : V7B §11.2 l'a déjà qualifié « sans impact arithmétique » ; tous les autres contrôles finaux sont au vert.*
2. Écart coût vs cible 14 400 : +9,71/mois — non forcé, découle des taux réglementaires.
3. Hypothèse assumée : 4441/4452 non réglés en 2025 (règlement CNSS/IR en 2026), comme V4.
4. Scénario SAL-2025-A/B fictif de recette : identités réelles (CIN, n° CNSS) à valider avant Stage 3.
5. IS historique 18 400,00 > théorique 11 039,61 : reprise 7 360,39 à entériner par l'expert-comptable.
6. 2025 `closed` (reclôture 2026-09-23) et dossier Greffe « approuvé » : toute régularisation exige validation humaine + réouverture tracée (Stage 3).
7. Réserves V6/V7B inchangées : segment OCR AMO, exclusions assiette CNSS (arrêté 1314-25), seuil IS `>` vs `≥`, outils `tools/` historiques — hors périmètre V8.

## 15. Preuve DB READ-ONLY — `compta_ma.db`
| Grandeur | Avant | Après |
|---|---|---|
| SHA-256 | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` | **identique** |
| Taille | 1 163 264 octets | **identique** |
| Dernière modification (UTC) | 2026-09-24T00:55:05.9193365Z | **identique** |

Strictement identiques. Toutes les lectures DB ont été faites en SQLite `file:…?mode=ro` ; la session fiscale réelle roulait sur une connexion `mode=ro`.

## 16. Verdict final
> ## **NON PRÊT POUR STAGE 3**

**Unique motif** : garde-fou §3 au pied de la lettre — une branche runtime consomme encore **30 000 DH** (`app/core/rates_ma.py`, `IR_PROFESSIONAL_EXPENSES_2025["cap_below"]` l.78, lu par `compute_professional_expenses()` l.511), non corrigé dans V8 par interdiction.
**Tous les autres contrôles finaux sont satisfaits** : barèmes 2025 disponibles ; aucun `BaremeIndisponible` ; aucun paramètre manquant ; paie mensuelle et annuelle équilibrées ; écritures simulées D = C ; cohérence comptable (balance 1 701 416,65 = 1 701 416,65 ; Actif = Passif = 386 539,48 ; CPC/ESG/Bilan/ETIC cohérents ; aucune double paie) ; cohérence fiscale (résultat fiscal 63 083,48 ; IS 11 039,61 ; CM 0,00 correctement calculée) ; à-nouveaux simulés équilibrés (Δ global 0,00) ; aucun impact inattendu sur la paie 2026 ; DB strictement inchangée.
**V8 ne lance aucun Stage 3.**

*Généré en lecture seule, une seule exécution du scénario, un seul recalcul consolidé, rapport rédigé une seule fois à la fin.*


