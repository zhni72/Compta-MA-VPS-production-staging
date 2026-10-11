# P1B **v2** — Simulation (lecture seule) de la régularisation de la paie 2025

Généré par `tools/p1b_simulation_2025_v2.py` : **aucune écriture créée, modifiée ou supprimée**. Les calculs utilisent les **mêmes fonctions que le module** (`compute_cnss`, `frais_professionnels_mensuels`, `compute_ir_monthly`, `lignes_ecriture_paie`) ; tout paramètre non encore fourni est **signalé**.

## 0. Référentiel fiscal — sources de chaque taux, plafond et base

### Exercice 2026 — référentiel complet ✔

| Élément | Valeur | Base | Source | Statut |
|---|---|---|---|---|
| IS — taux standard (< 100 M DH de benefice net fiscal) | 20 % | benefice net fiscal | CGI (edition 2026 fournie au projet), convergence LF — tableau IS | ✔ documenté |
| IS — taux grandes entreprises (> 100 M DH) | 35 % | benefice net fiscal | CGI (edition 2026 fournie au projet) | ✔ documenté |
| IS — etablissements de credit / assurances / CFC | 40 % / 20 % | benefice net fiscal | CGI (edition 2026 fournie au projet) | ✔ documenté |
| Cotisation minimale — taux et plancher | 0,25 % du CA TTC ; plancher 3 000 DH | CA TTC (CA 71x + TVA collectee 4455) | CGI art. 144 (edition 2026 fournie au projet) | ✔ documenté |
| Cotisation minimale — exoneration | 36 mois | duree d'activite (dates reelles de la societe) | CGI art. 20 (exoneration des 36 premiers mois d'activite) | ✔ documenté |
| IR — bareme mensuel (annualisation DGI) | bareme progressif 6 tranches (0 % a 37 %) | net imposable mensuel | CGI art. 73 (bareme IR 2026) — `BAREMES_PAIE[2026]` | ✔ documenté |
| Frais professionnels | 35 % plafonne 2 500 DH/mois jusqu'a 55 000 DH, 25 % au-dela | brut imposable | CGI art. 59 (edition 2026 fournie au projet) | ✔ documenté |
| CNSS — part salariale / patronale, plafond | 4,48 % / 8,98 % — plafond 6 000 DH/mois | salaire brut plafonne | CNSS (regime general) — `CNSS_2026` ; a re-confirmer par le client | ✔ documenté |
| AMO — part salariale / patronale | 2,26 % / 4,11 % | salaire brut (sans plafond) | AMO (couverture medicale obligatoire) — `CNSS_2026` | ✔ documenté |
| Prestations familiales / taxe de formation professionnelle | 6,40 % / 1,60 % (part patronale) | salaire brut | CNSS / TFP — reglementation 2026 fournie au projet | ✔ documenté |

### Exercice 2025 — référentiel **INCOMPLET (à fournir)**

| Élément | Valeur | Base | Source | Statut |
|---|---|---|---|---|
| IS 2025 — taux standard et par tranche fiscale | **A FOURNIR** | benefice net fiscal 2025 | loi de finances 2025 (bareme IS applicable a l'exercice) | **à fournir** |
| IR 2025 — bareme mensuel | **A FOURNIR** | net imposable mensuel 2025 | CGI art. 73 dans sa version applicable en 2025 (bareme LF 2025) | **à fournir** |
| Frais professionnels 2025 | **A FOURNIR** | brut imposable 2025 | CGI art. 59 (version 2025) | **à fournir** |
| CNSS / AMO 2025 — taux et plafond | **A FOURNIR — aucune hypothese** | salaire brut 2025 | CNSS / AMO : textes applicables en 2025 (a fournir par le client) | **à fournir** |
| Cotisation minimale 2025 — taux, plancher, exoneration | **A FOURNIR** | CA TTC 2025 | CGI art. 144 / art. 20 dans leur version 2025 | **à fournir** |

Barèmes disponibles : paie [2026] ; IS [2026] ; cotisation minimale [2026]. **Conséquence : le calcul 2025 par le module est refusé (aucun taux deviné) ; la simulation ci-dessous applique les paramètres 2026 à titre d'illustration.**

## 1. Les 3 profils salariés du jeu de recette doivent-ils exister sur 2025 ?

| Matricule | Libellé du jeu | Entrée | Contrat | Coût employeur mensuel (paramètres 2026) |
|---|---|---|---|---|
| EMP001 | profil de test IR — « Seuil exonéré » | 2025-01-01 | 3000.00 base + 0.00 primes (effet 2026-01-01) | 3,632.70 DH |
| EMP002 | profil de test IR — « Tranche 30 % » | 2025-01-01 | 7000.00 base + 0.00 primes (effet 2026-01-01) | 8,386.50 DH |
| EMP003 | profil de test IR — « Tranche 37 % » | 2025-01-01 | 16000.00 base + 0.00 primes (effet 2026-01-01) | 18,476.40 DH |

- Coût employeur mensuel des 3 profils : **30,495.60 DH** → annuel **365,947.20 DH**.
- Paie **présente au grand livre 2025** (écritures synthétiques du jeu) : **144,000.00 DH** de charges (14 400 DH/mois de coût global).
- Conclusion : les 3 profils sont des **profils de test IR** (libellés « Seuil exonéré », « Tranche 30 % », « Tranche 37 % ») dont le coût réel (30 495,60 DH/mois) **ne correspond pas** à la paie du scénario (14 400 DH/mois). Les considérer comme salariés permanents de 2025 **créerait** une masse salariale de 365 947,20 DH, soit +221 947,20 DH de charges non prévues par le scénario.


## 2. Figures par salarié (12 mois, paramètres 2026 — illustration)

> Hypothèse d'illustration : **option C** (les 3 profils retenus 12 mois) avec les paramètres 2026, faute de référentiel 2025. Les montants changeront dès que le barème 2025 sera fourni.

| Salarié | Brut annuel | CNSS sal. | AMO sal. | IR | Net à payer | CNSS patr. | AMO patr. | Prest. fam. | TFP | Coût employeur |
|---|---|---|---|---|---|---|---|---|---|---|
| EMP001 | 36,000.00 | 1,612.80 | 813.60 | 0.00 | 33,573.60 | 3,232.80 | 1,479.60 | 2,304.00 | 576.00 | 43,592.40 |
| EMP002 | 84,000.00 | 3,225.60 | 1,898.40 | 0.00 | 78,876.00 | 6,465.60 | 3,452.40 | 5,376.00 | 1,344.00 | 100,638.00 |
| EMP003 | 192,000.00 | 3,225.60 | 4,339.20 | 27,607.92 | 156,827.28 | 6,465.60 | 7,891.20 | 12,288.00 | 3,072.00 | 221,716.80 |
| **Total 2025** | **312,000.00** | **8,064.00** | **7,051.20** | **27,607.92** | **269,276.88** | **16,164.00** | **12,823.20** | **19,968.00** | **4,992.00** | **365,947.20** |

Assiette CNSS plafonnée (EMP003, plafond 6000 DH) : 6,000.00 DH/mois ; barème IR appliqué : 6 tranches (paramètres 2026).

## 3. Écritures comptables qui seraient générées (par mois)

**Écriture de paie (journal OD, source `payroll`)**

| Compte | Libellé | Débit | Crédit |
|---|---|---|---|
| `61711` | Appointements et salaires | 26,000.00 | 0.00 |
| `61741` | Cotisations de securite sociale (patronales) | 2,415.60 | 0.00 |
| `61744` | Prestations familiales (patronales) | 1,664.00 | 0.00 |
| `61768` | Autres charges sociales (taxe de formation) | 416.00 | 0.00 |
| `4441` | CNSS / AMO (parts salariale et patronale) | 0.00 | 5,755.20 |
| `4452` | Etat - IR retenu a la source | 0.00 | 2,300.66 |
| `4432` | Remunerations dues au personnel | 0.00 | 22,439.74 |
| | **Total** | **30,495.60** | **30,495.60** |

**Écriture de règlement des salaires (journal BQ)**

| Compte | Libellé | Débit | Crédit |
|---|---|---|---|
| `4432` | Règlement des salaires | 22,439.74 | 0,00 |
| `5141` | Banques | 0,00 | 22,439.74 |

Sur 12 mois : charges comptabilisées **365,947.20 DH** ; nets payés **269,276.88 DH** ; dettes sociales et fiscales laissées au passif : `4441` **69,062.40 DH** et `4452` (IR) **27,607.92 DH**.

## 4. Résultat comptable 2025 recalculé, résultat fiscal / IS / CM

| Indicateur | Existant (jeu) | Projeté (option C, paramètres 2026) |
|---|---|---|
| Charges de personnel | 144,000.00 | **365,947.20** |
| Autres charges (inchangées) | 142,400.00 | 142,400.00 |
| Total charges | 286,400.00 | **508,347.20** |
| Produits | 360,000.00 | 360,000.00 |
| **Résultat comptable** | 73,600.00 (benefice) | **-148,347.20** (perte) |

**Résultat fiscal, IS et cotisation minimale (2025)**

- **IS 2025 : calcul refusé** — le taux de l'exercice n'est pas paramétré (loi de finances 2025 requise). Projection indicative avec le taux 2026 (0,20) : résultat fiscal -148,347.20 → IS 0.00 DH.
- **Cotisation minimale 2025** : la société est exonérée (12 mois d'activité depuis le 2025-01-01, fin d'exonération 2028-01-01) ⇒ **0,00 DH** — à confirmer avec les paramètres 2025 (art. 144 / art. 20).
- IS 2025 existant (comptabilisé au jeu) : 18 400,00 DH ; résultat fiscal existant : 92 000,00 DH — **à recalculer intégralement** après régularisation (aucune correction manuelle).

## 5. Impact **compte par compte** sur les à-nouveaux 2026

| Compte | Existant (grand livre 2025) | Projeté (module) | Écart |
|---|---|---|---|
| `6171` | 120,000.00 | 0.00 | **-120,000.00** |
| `6174` | 24,000.00 | 0.00 | **-24,000.00** |
| `61711` | 0.00 | 312,000.00 | **+312,000.00** |
| `61741` | 0.00 | 28,987.20 | **+28,987.20** |
| `61744` | 0.00 | 19,968.00 | **+19,968.00** |
| `61768` | 0.00 | 4,992.00 | **+4,992.00** |
| `4441` | 0.00 | -69,062.40 | **-69,062.40** |
| `4452` | 0.00 | -27,607.92 | **-27,607.92** |
| `5141` | 228,320.00 | 103,043.12 | **-125,276.88** |
| `1199` | 0.00 | 148,347.20 | **+148,347.20** |

Les à-nouveaux 2026 reprennent les **comptes de bilan** (tous sauf les classes 6 et 7) plus le **résultat** : l'écart global sur les à-nouveaux se lit donc sur `5141`, `4441`, `4452` et le compte de résultat. Écriture existante : EC202600001 — 387 520,00 DH / 11 lignes. Comparaison détaillée disponible après régularisation via `closing.regenerer_a_nouveaux`.

**Options soumises à validation (aucune n'est appliquée) :**
| Option | Description | Effet |
|---|---|---|
| **A — Ne pas régulariser 2025** | conserver la paie synthétique du jeu (144 000 DH) | scénario inchangé, résultat 2025 = 73 600 DH ; le module reste la source **à partir de 2026** |
| **B — Salariés de scénario** | créer les salariés **réels du scénario** correspondant au jeu (coût global 14 400 DH/mois) et régénérer 2025 par le module | résultat 2025 ≈ 73 600 DH (à recalculer), paie 2025 issue du module, cohérence totale |
| **C — Retenir les 3 profils de test** | les considérer comme salariés permanents 2025 | charges +221 947,20 DH → résultat 2025 **−148 347,20 DH**, IS 2025 recalculé, à-nouveaux 2026 modifiés |

**Recommandation** : option **B** (ou A si le scénario 2025 doit rester figé) — l'option C ne doit pas être retenue sans décision explicite du donneur d'ordre.
