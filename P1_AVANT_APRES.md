# P1 — Régularisation de la double paie : résultat AVANT / APRÈS

Base de référence (AVANT) : `compta_ma.db.bak-p1-20260923-150952` ; base courante (APRÈS) : `compta_ma.db`. Chiffres recalculés par les services de l'application, **sans aucune correction manuelle**.

## 1. Écritures de paie (2026)

| Indicateur | AVANT | APRÈS |
|---|---|---|
| Écritures de paie (pièce `PAIE%`) | 13 | 24 |
| Écritures totales 2026 | 95 | 106 |
| Cycles de paie (module) | 1 | 12 |
| Bulletins de paie (module) | 3 | 36 |

## 2. Comptes de paie (2026, débit / crédit / solde)

| Compte | AVANT (D / C / solde) | APRÈS (D / C / solde) |
|---|---|---|
| `6171` | 144,000.00 / 0.00 / **144,000.00** | 0.00 / 0.00 / **0.00** |
| `61711` | 26,000.00 / 0.00 / **26,000.00** | 312,000.00 / 0.00 / **312,000.00** |
| `6174` | 28,800.00 / 0.00 / **28,800.00** | 0.00 / 0.00 / **0.00** |
| `61741` | 2,415.60 / 0.00 / **2,415.60** | 28,987.20 / 0.00 / **28,987.20** |
| `61744` | 1,664.00 / 0.00 / **1,664.00** | 19,968.00 / 0.00 / **19,968.00** |
| `61768` | 416.00 / 0.00 / **416.00** | 4,992.00 / 0.00 / **4,992.00** |
| `4432` | 0.00 / 22,439.74 / **-22,439.74** | 269,276.88 / 269,276.88 / **0.00** |
| `4441` | 0.00 / 5,755.20 / **-5,755.20** | 0.00 / 69,062.40 / **-69,062.40** |
| `4452` | 0.00 / 2,300.66 / **-2,300.66** | 0.00 / 27,607.92 / **-27,607.92** |
| `5141` | 764,000.00 / 444,520.00 / **319,480.00** | 764,000.00 / 540,996.88 / **223,003.12** |

## 3. Chaîne comptable et fiscale

| Indicateur | AVANT | APRÈS |
|---|---|---|
| Journal (Σ débit = Σ crédit) | 3,709,055.60 = 3,709,055.60 → **True** | 4,140,984.08 = 4,140,984.08 → **True** |
| Balance / CPC — total charges | 382,655.60 | 545,307.20 |
| Balance / CPC — total produits | 432,000.00 | 432,000.00 |
| **Résultat comptable (CPC)** | 49,344.40 (benefice) | -113,307.20 (perte) |
| ESG — marge brute / valeur ajoutée / EBE | 329,000.00 / 287,600.00 / 84,304.40 | 329,000.00 / 287,600.00 / -78,347.20 |
| **ESG = CPC** | True | **True** |
| Bilan — actif brut / déductions / **actif net** | 493,280.00 / 27,000.00 / **466,280.00** | 396,803.12 / 27,000.00 / **369,803.12** |
| Bilan — passif + résultat | 466,280.00 | 369,803.12 |
| **Bilan équilibré** | True | **True** |
| ETIC note 9 (charges de personnel) | 203,295.60 (6 comptes) | 365,947.20 (4 comptes) |
| Résultat avant impôt | 69,304.40 | -93,347.20 |
| **Résultat fiscal** | 69,304.40 | -93,347.20 |
| **IS calculé** | 13,860.88 | 0.00 |
| Cotisation minimale | 0.00 | 0.00 |
| Solde d'IS à payer | 13,860.88 | 0.00 |
| Statut de l'exercice 2026 | open | open |

## 4. Contrôles de cohérence exigés

| Contrôle | Résultat |
|---|---|
| Bilan équilibré (après) | **PASS** (actif net 369,803.12 = passif + résultat 369,803.12) |
| CPC = ESG = Bilan (après) | **PASS** (CPC -113,307.20 = ESG -113,307.20 = bilan -113,307.20) |
| Journal équilibré (après) | **PASS** |
| Module Paie = source unique (2026) | **PASS** (12 cycles, 36 bulletins, 24 écritures de paie) |

## 5. Analyse des écarts (aucune correction manuelle)

- **Charges de personnel** : 203,295.60 → 365,947.20 DH. L'écart (+162,651.60 DH) correspond exactement à la substitution de la paie synthétique du jeu (14 400 DH/mois pour 3 salariés) par la paie **réelle du module** (26 000 DH de brut, 30 495,60 DH de coût employeur/mois).
- **Total des charges** : 382,655.60 → 545,307.20 DH (+162,651.60 DH), à produits constants (432,000.00 DH).
- **Résultat** : 49,344.40 (benefice) → -113,307.20 (perte). La perte provient du **scénario de recette** (CA 432 000 DH pour une masse salariale réelle de 365 947,20 DH), **pas** d'une écriture manuelle : les paies sont exclusivement produites par le module.
- **Trésorerie (5141)** : 319,480.00 → 223,003.12 DH (solde **débiteur** dans les deux états : les nets payés par virement réduisent la trésorerie sans la rendre créditrice — aucun reclassement en trésorerie-passif n'est nécessaire ; le contrôle est disponible dans `services.tresorerie`).
- **Dettes sociales et fiscales** : 4441 69,062.40 DH (CNSS/AMO patronale) et 4452 27,607.92 DH (IR retenu) restent à verser : la DTS 2026 régénérée les déclare. 4432 est soldé (0.00 DH) : tous les nets sont payés.
- **IS** : 13,860.88 → 0.00 DH. En l'absence de bénéfice, l'IS théorique est nul et la **cotisation minimale** est elle aussi nulle : l'application applique l'**exonération des 36 premiers mois d'activité** (`COTISATION_MINIMALE_2026.exemption_months`, art. 20 CGI). Hors exonération, la CM serait `max(0,25 % × CA TTC ; 3 000 DH)`.
