# P1B v3 CORRIGEE — IS 2025 par la demarche fiscale (lecture seule)

**Societe** : SOCIETE RECETTE MAROC SARL AU  ·  **Exercice** : 2025  ·  **Ecritures** : 195
**Base inchangee pendant l'execution** : True (SHA-256 52fc68c77aed0369…) — aucune ecriture modifiee.

## 1. Resultat comptable -> resultat fiscal -> IS 2025

| Etape | Montant |
|---|---|
| Resultat net **comptabilise** (apres IS) | 73 600,00 DH |
| + Reintegration de l'IS comptabilise (**non deductible**, CGI art. 11) | 18 400,00 DH |
| = **Resultat comptable avant IS** | **92 000,00 DH** |
| + Autres reintegrations (catalogue CGI art. 11) | 0,00 DH |
| - Deductions fiscales | 0,00 DH (aucune identifiee) |
| **Resultat fiscal (BNF) 2025** | **92 000,00 DH** |
| Taux IS applicable (exercice 2025) | **17,50 %** (BNF <= 300 000 DH : grille transitoire 2025) |
| **IS 2025 calcule** | **16 100,00 DH** |
| IS comptabilise (compte 6701) | 18 400,00 DH |
| **Ecart (IS comptabilise - IS calcule)** | **2 300,00 DH** |

## 2. Cotisation minimale 2025 et exoneration

| Element | Valeur |
|---|---|
| Taux theorique | 0,25 % du CA TTC |
| Plancher theorique | 3 000,00 DH |
| Base (CA TTC : CA HT + TVA collectee) | 432 000,00 DH |
| **CM theorique** (avant exoneration) | 3 000,00 DH |
| Debut d'exploitation retenu | 2025-01-01 (fiche societe) |
| Duree d'exoneration legale | 36 mois |
| Fin d'exoneration | 2028-01-01 |
| Mois d'activite de l'exercice | 12 |
| **Cotisation minimale exigible 2025** | **NON (0,00 DH)** |
| Justification | societe en activite depuis le 2025-01-01 : les 36 premiers mois couvrent l'exercice 2025 (jusqu'au 2028-01-01) — cotisation minimale **non exigible** ; les 3 000 DH de plancher ne constituent **pas** une dette fiscale. |

## 3. Impot finalement du et resultat net corrige

| Element | Montant |
|---|---|
| IS calcule | 16 100,00 DH |
| Cotisation minimale exigible | 0,00 DH |
| **Impot finalement du 2025** | **16 100,00 DH** |
| Acomptes verses (3453) | 0,00 DH |
| Credits d'impot | 0,00 DH |
| Solde a payer | 16 100,00 DH |
| **Resultat net corrige 2025** (resultat avant IS - IS du) | **75 900,00 DH** |
| Resultat net comptabilise | 73 600,00 DH |

## 4. Impact projete sur les a-nouveaux 2026 (simulation)

| Poste | Situation actuelle | Apres correction | Ecart |
|---|---|---|---|
| Report a nouveau (resultat 2025) | 73 600,00 DH | 75 900,00 DH | +2 300,00 DH |
| Dette d'IS (6701 / 4453) | 18 400,00 DH | 16 100,00 DH | -2 300,00 DH |
| Total du bilan net 2025 | 375 520,00 DH | 375 520,00 DH | 0,00 DH (equilibre conserve) |

> Correction **strictement interne** : baisse de la charge d'IS (2 300,00 DH) et de la dette d'impot du meme montant ; le total du bilan reste inchange. **Aucune ecriture n'a ete passee** (simulation).

## 5. Paie / IR 2025 — blocage maintenu

- frais professionnels (CGI art. 59, version de l'exercice)
- CNSS / AMO (taux et plafonds de l'exercice)

> Les parametres sociaux et de frais professionnels 2025 n'etant pas documentes, **aucune paie 2025 n'est calculee** (le moteur refuse : `BaremeIndisponible`) et l'IR 2025 reste **non chiffre** — aucun taux devine.
- IR 2025 : aucune donnee de paie 2025

## 6. References et statut

| Element | Valeur | Source |
|---|---|---|
| IS 2025 — grille transitoire (convergence LF 2023-2025) | 17,5 % si benefice net fiscal <= 300 000 DH ; 20 % au-dela (< 100 M DH) ; 35 % (> 100 M DH) ; 40 % etablissements de credit / assurances ; 20 % CFC | grille IS 2025 fournie au projet (convergence LF) — a confirmer par l'expert-comptable (CGI, tableau IS) (documente (a confirmer)) |
| IR 2025 — bareme mensuel | bareme progressif 6 tranches (0 % jusqu'a 40 000 DH, 10/20/30/34/37 %) — deduction familiale 500 DH par personne (6 max) | bareme IR 2025 (CGI art. 73, version 2025) fourni au projet — `BAREMES_PAIE[2025]` (documente (a confirmer)) |
| Frais professionnels 2025 | **A FOURNIR — aucun taux applique par defaut** | CGI art. 59 (version 2025) : non communique (a_fournir) |
| CNSS / AMO 2025 — taux et plafond | **A FOURNIR — aucune hypothese** (aucune cotisation calculee pour 2025) | CNSS / AMO : textes applicables en 2025 (a fournir par le client) (a_fournir) |
| Prestations familiales / TFP 2025 (part patronale) | **A FOURNIR — aucune hypothese** | CNSS / TFP : textes applicables en 2025 (a fournir par le client) (a_fournir) |
| Cotisation minimale 2025 — taux, plancher, exoneration | 0,25 % du CA TTC ; plancher 3 000 DH ; exoneration 36 mois | CGI art. 144 / art. 20 (version 2025) fourni au projet — a confirmer (documente (a confirmer)) |

## 7. Conclusion

- **IS 2025** : base fiscale 92 000,00 DH x 0.175 = **16 100,00 DH** ; cotisation minimale **non exigible (exoneration des 36 premiers mois)** ; impot du **16 100,00 DH** ; ecart de **2 300,00 DH** avec l'IS comptabilise.
- **Resultat net corrige 2025** : **75 900,00 DH** (avant toute regularisation de paie).
- **Simulation uniquement** : exercice 2025 inchange (SHA-256 de la base identique, 195 ecritures avant et apres).
- **P1B etape 3 non lancee** : elle suppose la validation humaine de la presente simulation corrigee (et, pour l'IR, la documentation des parametres de paie 2025).

