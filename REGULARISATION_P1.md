# Régularisation **P1** — paie : **source unique** · dossier de validation

**Date** : 23/09/2026 · **Méthode autorisée par le donneur d'ordre** : **réinitialisation
contrôlée du jeu de recette** (pas de suppression silencieuse, pas de correction manuelle de
montant) · **Périmètre** : paie de l'exercice **2026** (ouvert).

> **Les chantiers Greffe et réouverture d'exercice ne sont pas démarrés** : la consigne est de ne
> les engager qu'après **PASS** de cette chaîne (voir la déclaration en fin de document).

## 1. Pré-requis exécutés avant toute modification

| Exigence | Réalisation |
|---|---|
| Sauvegarde de la base | **`compta_ma.db.bak-p1-20260923-150952`** (1 064 Ko) — *vérifiée automatiquement par l'outil*, refus d'exécuter sans elle |
| Liste exacte des écritures concernées | **`P1_INVENTAIRE_PAIE_AVANT.txt`** : 13 écritures 2026 — 12 synthétiques `PAIE26-01` … `PAIE26-12` (source `import_jeu_j9` : 6171 = 144 000 / 6174 = 28 800, contrepartie 5141) **et** l'écriture du module `EC202600094` (source `payroll`, 30 495,60) — + 1 cycle, 3 bulletins, 1 DTS de recette ; baseline comptable complète (résultat, ESG, bilan, IS) |
| Cible fonctionnelle | **le module Paie devient l'unique source** : les écritures synthétiques du seed sont **retirées** (pas seulement l'écriture du module) et les paies sont **régénérées par le module** |
| Contrôles de sûreté | exercice 2026 ouvert, aucun verrou de période, aucune écriture hors 2026, aucune déclaration déposée supprimée, sauvegarde présente |

## 2. Ce qui a été fait (traçé, réversible par restauration de la sauvegarde)

1. **Retrait des 13 écritures de paie 2026** — chaque retrait inscrit dans la **piste d'audit**
   (`PAYROLL_RESET_SUPPRESSION`) avec l'**instantané complet** (numéro, date, pièce, source,
   libellé, toutes les lignes compte/débit/crédit).
2. **Retrait du cycle de paie 2026-01** (3 bulletins + lignes) et de la **DTS de recette**
   (`PAYROLL_RESET_CYCLE`, `PAYROLL_RESET_DECLARATION`).
3. **Rescellement de la piste** après suppression : **171 écritures scellées, 0 rupture**,
   `integre = True` ; journal de nouveau équilibré (3 505 760,00 = 3 505 760,00).
4. **Régénération par le module** : 12 cycles `2026-01` → `2026-12` (préparer → valider → payer)
   = **36 bulletins**, **24 écritures** (`EC202600096` … `EC202600119`), **DTS 2026** régénérée
   depuis les bulletins (IR 27 607,92 DH, 3 salariés, XML 3 037 octets avec empreinte SHA-256).
5. **Recalcul intégral de la chaîne** — Paie → Journal → Balance → CPC → ESG → Bilan → ETIC →
   résultat fiscal → IS — **sans aucune correction manuelle de montant**.

## 3. Avant / après (détail complet : `P1_AVANT_APRES.md`)

| Indicateur (2026) | Avant | Après |
|---|---|---|
| Écritures de paie / cycles / bulletins | 13 / 1 / 3 | **24 / 12 / 36** |
| `6171` + `6174` (écritures synthétiques du seed) | 172 800,00 | **0,00** |
| `61711` appointements | 26 000,00 | **312 000,00** |
| `61741` / `61744` / `61768` | 4 495,60 | **53 947,20** |
| Total charges de personnel (ETIC note 9) | 203 295,60 | **365 947,20** |
| `4432` nets à payer | −22 439,74 | **0,00** (soldé : tout est payé) |
| `4441` CNSS/AMO patronale | −5 755,20 | **−69 062,40** |
| `4452` IR retenu (à verser) | −2 300,66 | **−27 607,92** |
| `5141` banque | 319 480,00 | 223 003,12 |
| Journal (Σ débit = Σ crédit) | équilibré | **équilibré** (4 140 984,08) |
| Résultat comptable (CPC) | 49 344,40 | **−113 307,20** |
| ESG (EBE / résultat net) | 84 304,40 / 49 344,40 | **−78 347,20 / −113 307,20** |
| Bilan (actif net = passif + résultat) | équilibré | **équilibré** (369 803,12) |
| CPC = ESG = Bilan | vrai | **vrai** |
| Résultat fiscal / IS | 69 304,40 / 13 860,88 | **−93 347,20 / 0,00** |
| Cotisation minimale | 0,00 | 0,00 (exonération 36 mois, art. 20 CGI) |

**Explication des écarts (aucune correction manuelle)** : la masse salariale **réelle** du module
(26 000 DH de brut, 30 495,60 DH de coût employeur par mois) remplace la paie **synthétique** du
jeu (14 400 DH/mois) ; à chiffre d'affaires constant (432 000 DH), l'exercice devient déficitaire.
La trésorerie bancaire reste **débiteure** (223 003,12 DH) : aucun reclassement en
trésorerie-passif n'est nécessaire (contrôle et reclassement CGNC `5541`/`5548` livrés en P1 —
voir `REGULARISATION_P1_SUITE.md`).

## 4. Tests, garde-fou et fichiers

- **Contrôle bloquant ajouté (cause racine)** : `payroll.ecritures_paie_hors_module()` — avant de
  comptabiliser une paie, toute charge de personnel `617x` de **source non `payroll`** sur la
  période provoque un refus motivé (`PayrollError` citant numéro, date, pièce et source).
- **Tests de non-régression** : `tests/test_paie_source_unique.py` (2 tests) — refus reproduisant
  A2 (écriture externe `PAIE26-03`) et acceptation après régularisation, avec vérification des
  comptes `61711`, `4432`, `444x`, `4452` et de l'équilibre de l'écriture du module.
- **Suite complète** : **326/326 tests verts** (`PREUVE_P1_TESTS.log`, code de sortie **0**).
- **Fichiers modifiés** : `app/services/payroll.py`, `README.md` (§ 19),
  `CAHIER_DES_CHARGES_GLOBAL.md` (§ 8 ter, § 10.6, plancher 326).
- **Fichiers créés** : `tests/test_paie_source_unique.py`, `tools/p1_inventaire_paie.py`,
  `tools/p1_reinitialiser_paie.py`, `tools/p1_rapport_avant_apres.py`,
  `P1_INVENTAIRE_PAIE_AVANT.txt`, `P1_INVENTAIRE_PAIE_APRES.txt`, `P1_AVANT_APRES.md`,
  `P1_REINITIALISATION_PAIE.txt`, `PREUVE_P1_TESTS.log`, le présent dossier.

## 5. Déclaration de fin de phase

**Chaîne P1 : PASS** — Paie (module, source unique) → Journal → Balance → CPC → ESG → Bilan →
ETIC → résultat fiscal → IS sont **réconciliés de bout en bout**, sans correction manuelle, avec
tests de non-régression et preuve avant/après recalculée par les services de l'application.

**Réserve documentée (P1-b)** : la paie **2025** (12 écritures synthétiques, exercice **clos**,
à-nouveaux déjà générés) n'a pas été régularisée : l'étendre imposerait de rejouer la clôture
2025, les à-nouveaux et la réouverture contrôlée de 2025 (chantier P2), ce qui touche un exercice
clos — à décider explicitement.

