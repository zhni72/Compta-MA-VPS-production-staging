# P1B v3 — simulation 2025 en **lecture seule** (referentiels 2025)

**Societe** : SOCIETE RECETTE MAROC SARL AU  ·  **Exercice** : 2025  ·  **Ecritures de l'exercice** : 195
**Base inchangee pendant l'execution** : True (SHA-256 52fc68c77aed0369…)

## 1. Referentiels 2025 utilises (aucun taux saisi en dur)

| Element | Valeur 2025 | Source |
|---|---|---|
| IS 2025 — grille transitoire (convergence LF 2023-2025) | 17,5 % si benefice net fiscal <= 300 000 DH ; 20 % au-dela (< 100 M DH) ; 35 % (> 100 M DH) ; 40 % etablissements de credit / assurances ; 20 % CFC | grille IS 2025 fournie au projet (convergence LF) — a confirmer par l'expert-comptable (CGI, tableau IS) (documente (a confirmer)) |
| IR 2025 — bareme mensuel | bareme progressif 6 tranches (0 % jusqu'a 40 000 DH, 10/20/30/34/37 %) — deduction familiale 500 DH par personne (6 max) | bareme IR 2025 (CGI art. 73, version 2025) fourni au projet — `BAREMES_PAIE[2025]` (documente (a confirmer)) |
| Frais professionnels 2025 | **A FOURNIR — aucun taux applique par defaut** | CGI art. 59 (version 2025) : non communique (a_fournir) |
| CNSS / AMO 2025 — taux et plafond | **A FOURNIR — aucune hypothese** (aucune cotisation calculee pour 2025) | CNSS / AMO : textes applicables en 2025 (a fournir par le client) (a_fournir) |
| Prestations familiales / TFP 2025 (part patronale) | **A FOURNIR — aucune hypothese** | CNSS / TFP : textes applicables en 2025 (a fournir par le client) (a_fournir) |
| Cotisation minimale 2025 — taux, plancher, exoneration | 0,25 % du CA TTC ; plancher 3 000 DH ; exoneration 36 mois | CGI art. 144 / art. 20 (version 2025) fourni au projet — a confirmer (documente (a confirmer)) |

## 2. Parametres 2025 **non figes** (aucun taux devine)

- frais professionnels (CGI art. 59, version de l'exercice)
- CNSS / AMO (taux et plafonds de l'exercice)

> Consequence : le **cout employeur 2025** et les ecritures de paie 2025 ne peuvent pas etre recalcules de facon fiable. La paie 2025 est **refusee** par l'application (`BaremeIndisponible`) plutot que calculee avec les taux 2026.

## 3. Chiffres 2025 (comptabilite, source unique)

| Indicateur | Montant |
|---|---|
| Resultat net 2025 | 73 600,00 DH |
| Chiffre d'affaires (71x) | 360 000,00 DH |
| TVA collectee (4455) | 72 000,00 DH |

## 4. IS / cotisation minimale 2025 (simulation)

| Indicateur | Valeur |
|---|---|
| Regle appliquee | benefice net fiscal <= 300000 DH : taux transitoire 2025 |
| Taux retenu | 0.175 |
| IS theorique | 12 880,00 DH |
| Cotisation minimale (base 432 000,00 DH) | 3 000,00 DH |
| **IS du 2025 (max des deux)** | **12 880,00 DH** |
| IS / CM comptabilise 2025 | 36 800,00 DH |
| **Ecart (simulation - comptabilise)** | **-23 920,00 DH** |

## 5. IR 2025 (bareme 2025, deduction familiale 500 DH)


---

> **SUPERSEDEE** : ce document utilisait le resultat net comptable comme resultat fiscal (IS 12 880 DH). La version corrigee (reintegrations, exoneration de la cotisation minimale, resultat net corrige) est **P1B_SIMULATION_2025_V3_CORRIGEE.md**.

