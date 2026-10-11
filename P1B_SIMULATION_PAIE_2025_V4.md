# P1B v4 — Simulation paie 2025 — LECTURE SEULE — Compta MA

**Projet** : `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Interpréteur** : `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma\.venv\Scripts\python.exe` (Python 3.13.9) — exclusif.
**Rapport** : rédaction unique. Aucune écriture base, aucun salarié créé, aucun code modifié, aucun package changé.

## Preuve READ-ONLY — compta_ma.db
| Grandeur | Avant | Après |
|---|---|---|
| SHA-256 | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` | identique |
| Taille | 1 163 264 octets | identique |
| Dernière modification | 2026-09-24 02:55:05 | identique |

---

## 1. Inventaire paie 2025 (lecture seule)

### 1.1 Les 12 écritures synthétiques (journal BQ, 28 du mois, source `import_jeu_j9`, toutes `validated`)
| Numéro | Réf | Date | Lignes |
|---|---|---|---|
| EC202500008 | PAIE25-01 | 2025-01-28 | 6171 D 10 000,00 — 6174 D 2 000,00 — 5141 C 12 000,00 |
| EC202500015 | PAIE25-02 | 2025-02-28 | idem |
| EC202500022 | PAIE25-03 | 2025-03-28 | idem |
| EC202500029 | PAIE25-04 | 2025-04-28 | idem |
| EC202500036 | PAIE25-05 | 2025-05-28 | idem |
| EC202500043 | PAIE25-06 | 2025-06-28 | idem |
| EC202500050 | PAIE25-07 | 2025-07-28 | idem |
| EC202500057 | PAIE25-08 | 2025-08-28 | idem |
| EC202500064 | PAIE25-09 | 2025-09-28 | idem |
| EC202500071 | PAIE25-10 | 2025-10-28 | idem |
| EC202500078 | PAIE25-11 | 2025-11-28 | idem |
| EC202500085 | PAIE25-12 | 2025-12-28 | idem |

- **Montants** : 12 000,00 DH/mois de charges (10 000 + 2 000) et 12 000,00 DH/mois décaissés (5141). **Annuel : 144 000,00 DH** de charges et de décaissement.
- **Comptes utilisés** : `6171` Rémunérations du personnel ; `6174` Charges sociales ; `5141` Banques.
- **Structure** : aucune retenue IR, aucune cotisation CNSS/AMO détaillée — écritures globalisées (charges et paiement net par banque).

### 1.2 Salariés / bulletins / cycles 2025
- `employees` : **3 fiches de TEST uniquement** — EMP001 (3 000 DH), EMP002 (7 000 DH), EMP003 (16 000 DH), entrées 2025-01-01, CDI (> point 2).
- `pay_contracts` : 6 contrats (un par profil et par année 2025/2026).
- `payroll_runs` : **12 cycles 2026 uniquement** (2026-01 → 2026-12, tous « payé ») ; **aucun cycle 2025**.
- `payslips` : 36 (tous 2026) ; `payslip_lines` : 144 (tous 2026) ; `period_locks` : vide.

### 1.3 Résultat 2025 (état actuel, base de référence)
- Produits classe 7 : 360 000,00 DH.
- Charges classe 6 : 286 400,00 DH — dont `6701` IS comptabilisé 18 400,00 DH (EC202500089 : 6701 D / 4453 C).
- **Résultat comptable avant IS : 92 000,00 DH ; net comptable : 73 600,00 DH** (conforme au contexte validé).
- Exercices : 2025 `closed`, 2026 `open`. À-nouveaux 2026 : EC202600001 (AN2025).
- Société : SOCIETE RECETTE MAROC SARL AU — ICE 001234567000099 — constitution et exploitation **2025-01-01**.

### 1.4 Sources / référentiels du moteur
`app/core/rates_ma.py` (BAREMES_PAIE, IS_RATES_BY_YEAR, COTISATION_MINIMALE_BY_YEAR, SOURCES_REFERENTIELS), `app/data/plan_comptable_cgnc.csv`, table `vat_rates`.

## 2. Profils de test — exclus
EMP001/EMP002/EMP003 sont des profils de recette IR (« seuil exonéré », « tranche 30 % », « tranche 37 % »). Ils ne sont **pas** transformés en salariés réels. Le scénario (§ 4) est **explicitement construit pour la recette 2025** (matricules scénario `SAL-2025-A/B`).

## 3. Paramètres paie 2025 — statut de preuve
| Paramètre | Valeur 2025 | Source dans l'application | Statut |
|---|---|---|---|
| Barème IR (6 tranches 0 → 37 %) | tranches 2025 identiques 2026 | `IR_BRACKETS_2025` (`rates_ma.py`) | **À CONFIRMER** |
| Déduction charges de famille | 500 DH/personne (max 6) | `IR_FAMILY_DEDUCTION_BY_YEAR[2025]` | **À CONFIRMER** |
| Frais professionnels (CGI art. 59) | **non fourni** | `BAREMES_PAIE[2025]["frais_professionnels"] = None` | **ABSENT** |
| CNSS salariale 4,48 % / patronale 8,98 % | **non fourni 2025** (jeu 2026 documenté) | `BAREMES_PAIE[2025]["cnss"] = None` | **ABSENT** |
| AMO salariale 2,26 % / patronale 4,11 % | idem | idem | **ABSENT** |
| Prestations familiales patronales 6,40 % | idem | `SOURCES_REFERENTIELS[2025]` = a_fournir | **ABSENT** |
| TFP patronale 1,60 % | idem | idem | **ABSENT** |
| Plafond CNSS / mois | 6 000 (jeu 2026 documenté) | `CNSS_2026` | **ABSENT** (2025) |
| IS 2025 | 17,5 % si BNF ≤ 300 000 ; 20 % au-delà (< 100 M) | `IS_RATES_BY_YEAR[2025]` | **À CONFIRMER** |
| CM 2025 | 0,25 % CA ; plancher 3 000 ; exonération 36 mois | `COTISATION_MINIMALE_BY_YEAR[2025]` + dates réelles | **À CONFIRMER** — exonération 2025 démontrée (12 mois d'activité) |
| Retraite / mutuelle / assurance-groupe | non retenues (taux 0, facultatif) | contrats scénario | CONFIRMÉ (facultatif) |

**Conséquence réglementaire de Compta MA** : CNSS/AMO et frais professionnels 2025 étant ABSENTs, le moteur **refuse** tout calcul réel 2025 (`BaremeIndisponible`). La simulation ci-dessous utilise le **jeu de paramètres 2026 — le seul jeu complet documenté** — explicitement étiqueté « À CONFIRMER pour 2025 ». Aucune valeur n'est inventée.

## 4. Scénario salarié proposé (en mémoire, recette 2025)
| Matricule | Fonction | Brut mensuel | Situation familiale | Enfants |
|---|---|---|---|---|
| SAL-2025-A | Directeur (gérant) | 6 000,00 DH | célibataire | 0 |
| SAL-2025-B | Employé administratif | 5 900,00 DH | marié | 1 |

Choix : bruts ≤ plafond CNSS 6 000 → cotisations sociales sur la totalité (coût stable), effectif cohérent avec une petite SARL au premier exercice.

## 5. Calcul mensuel (formules du moteur — `compute_cnss`, `frais_professionnels_mensuels`, `compute_ir_monthly`, `annee=2026`)
| Rubrique | SAL-2025-A | SAL-2025-B | Entreprise |
|---|---|---|---|
| Salaire brut | 6 000,00 | 5 900,00 | 11 900,00 |
| CNSS salariale 4,48 % (plaf. 6 000) | 268,80 | 264,32 | 533,12 |
| AMO salariale 2,26 % | 135,60 | 133,34 | 268,94 |
| **Cotisations salariales** | **404,40** | **397,66** | **802,06** |
| Frais professionnels | 2 100,00 | 2 065,00 | 4 165,00 |
| **Base imposable (net imposable)** | **3 495,60** | **3 437,34** | **6 932,94** |
| IR mensuel | 16,23 | 0,00 | 16,23 |
| **Net à payer** | **5 579,37** | **5 502,34** | **11 081,71** |
| CNSS patronale 8,98 % (plaf. 6 000) | 538,80 | 529,82 | 1 068,62 |
| AMO patronale 4,11 % | 246,60 | 242,49 | 489,09 |
| Prestations familiales 6,40 % | 384,00 | 377,60 | 761,60 |
| TFP 1,60 % | 96,00 | 94,40 | 190,40 |
| **Charges patronales** | **1 265,40** | **1 244,31** | **2 509,71** |
| **Coût employeur mensuel** | **7 265,40** | **7 144,31** | **14 409,71** |

## 6. Calcul annuel et écart vs cible historique
| Grandeur | Annuel |
|---|---|
| Salaire brut | 142 800,00 DH |
| Cotisations salariales (CNSS+AMO) | 9 624,72 DH |
| IR retenu à la source | 194,76 DH |
| **Net payé aux salariés** | **132 980,52 DH** |
| Charges patronales | 30 116,52 DH |
| **Coût employeur annuel** | **172 916,52 DH** |

**Écart :**
- Mensuel : cible 14 400,00 − calculé 14 409,71 = **+9,71 DH (+0,07 %)**.
- Annuel : cible 172 800,00 − calculé 172 916,52 = **+116,52 DH (+0,07 %)**.
- Le montant n'est **pas forcé** : il découle des taux réglementaires documentés (jeu 2026, À CONFIRMER 2025).
- Rappel : la paie synthétique actuelle pèse **12 000,00 DH/mois (144 000,00/an)** sans détail social/fiscal ; la substitution crée le vrai coût employeur et les dettes CNSS/IR.

## 7. Écritures comptables simulées (mapping réel du module — vérifié sur les cycles 2026)
**Écriture mensuelle de paie** (validation, journal OD) :
| Compte | Libellé | Débit | Crédit |
|---|---|---|---|
| 61711 | Appointements et salaires (brut) | 11 900,00 | |
| 61741 | Cotisations de sécurité sociale (CNSS pat. + AMO pat.) | 1 557,71 | |
| 61744 | Prestations familiales | 761,60 | |
| 61768 | Autres charges sociales (TFP) | 190,40 | |
| 4432 | Rémunérations dues au personnel (net) | | 11 081,71 |
| 4441 | CNSS / AMO (salarial + patronal) | | 3 311,77 |
| 4452 | État — IR retenu à la source | | 16,23 |
| **Total** | | **14 409,71** | **14 409,71** |

**Écriture mensuelle de paiement** (journal BQ) : 4432 D 11 081,71 / 5141 C 11 081,71.

**Annuelles (× 12)** : 61711 142 800,00 ; 61741 18 692,52 ; 61744 9 139,20 ; 61768 2 284,80 ; 4432 132 980,52 (solde 0 après paiement) ; 4441 39 741,24 ; 4452 194,76 ; 5141 décaissement net 132 980,52.

## 8. Résultat comptable simulé
- Charges paie : 144 000,00 (synthétique) → **172 916,52** (scénario) = **+28 916,52**.
- **Résultat comptable avant IS : 92 000,00 − 28 916,52 = 63 083,48 DH**.
- Reprise d'IS 2025 (voir § 9) : −7 360,39 → **résultat net corrigé ≈ 52 043,87 DH** (vs 73 600,00 actuel).
- Impact Journal : 24 écritures (12 paie + 12 paiements) remplaçant les 12 écritures synthétiques ; impact Balance : mouvements accrus sur 61711/61741/61744/61768 (charges) et 5141/4441/4452/4432 ; impact CPC/ESG/ETIC : ligne « charges de personnel » portée à 172 916,52 ; impact Bilan : dettes sociales/IR en 44x et trésorerie réduite de 11 019,48.

## 9. Résultat fiscal / IS / CM simulés
- **Base fiscale = résultat comptable avant IS (retraitement obligatoire — jamais le net avec IS booké)** = **63 083,48 DH**.
- **IS 2025 = 17,5 % × 63 083,48 = 11 039,61 DH** (BNF ≤ 300 000 — `small_profit` ; `compute_is(annee=2025)` confirmé : 16 100,00 sur 92 000,00).
- **CM 2025 = 0,00 DH** (exonération 36 premiers mois d'activité — 12 mois en 2025, dates réelles 2025-01-01 ; `compute_cotisation_minimale`).
- **IS dû = max(IS, CM) = 11 039,61 DH** ; excédent booké = 18 400,00 − 11 039,61 = **7 360,39 DH** (à régulariser en stage 3 : reprise 6701/4453).
- Note : la réintégration de l'IS comptabilisé (18 400) est prise en compte par la base « avant IS » ; aucune réintégration supplémentaire dans ce périmètre.

## 10. Impact prévisionnel sur les à-nouveaux 2026 (simulé — aucune régénération)
Écriture actuelle : EC202600001 (AN2025). Variation simulée en cas de substitution :
| Compte | Actuel (AN2025) | Simulé | Δ |
|---|---|---|---|
| 5141 | 228 320,00 | 217 300,52 | **−11 019,48** |
| 4432 | 0,00 | 0,00 | 0,00 |
| 4441 | 0,00 | 39 741,24 | **+39 741,24** |
| 4452 | 0,00 | 194,76 | **+194,76** |
| 4453 | 18 400,00 | 11 039,61 | **−7 360,39** |
| 1191 | 73 600,00 | 52 043,87 | **−21 556,13** |

**Total des Δ = 0,00 DH** (équilibré). Comptes inchangés : 1111, 2340, 2834, 3111, 3421, 34552, 4411, 4455. (Dettes 4441/4452 non réglées à fin 2025 ; hypothèse : CNSS/IR payés en 2026.)

## 11. Impact Greffe
- Dossier Greffe 2025 existant : **statut « approuvé »** (SARL).
- La régularisation simulée modifie : **Bilan 2025** (dettes 44x, trésorerie), **CPC** (charges de personnel), **résultat net** (73 600,00 → 52 043,87), donc **rapport de gestion** et **PV AG** (résultat à affecter).
- Le dossier reste **provisoire** tant que 2025 n'est pas régularisé ; toute correction doit être validée humainement avant mise à jour du dépôt.

## 12. Paramètres restant à confirmer
1. **Frais professionnels 2025** (CGI art. 59) — ABSENT — indispensable.
2. **CNSS / AMO 2025** (taux salarialux/patronaux, plafond 6 000) — ABSENT — indispensable.
3. **Prestations familiales 6,40 % et TFP 1,60 % pour 2025** — ABSENT — indispensable au coût employeur.
4. Barème IR 2025 + déduction familiale 500 DH — À CONFIRMER (documenté dans le code).
5. IS 2025 — taux transitoire 17,5 % (BNF ≤ 300 000) — À CONFIRMER.
6. CM 2025 — taux 0,25 %, plancher 3 000, exonération 36 mois — À CONFIRMER (exonération 2025 démontrée par les dates réelles).
7. **Scénario salarié** : identités réelles (CIN, n° CNSS, situation familiale, contrats) — à valider par le donneur d'ordre.

## 13. Verdict
**NON PRÊT POUR STAGE 3.**

**Justification** :
- Paramètres 2025 indispensables **ABSENT** (frais professionnels, CNSS/AMO, prestations familiales/TFP) → le moteur refuse de calculer la paie 2025 (`BaremeIndisponible`) ; le résultat 14 409,71 DH/mois est indicatif (jeu 2026, À CONFIRMER 2025).
- Aucun salarié réel 2025 : les profils EMP001-003 sont des profils de test, exclus ; le scénario SAL-2025-A/B doit être validé (identités réelles).
- Dossier Greffe 2025 « approuvé » → toute écriture de régularisation (réouverture, remplacement des 12 écritures synthétiques, paie module, IS, à-nouveaux) exige validation humaine préalable et motif tracé.
- La reprise d'IS (7 360,39 DH) et la variation de résultat (73 600,00 → 52 043,87) doivent être entérinées par l'expert-comptable avant toute modification.

---

*Rapport généré en lecture seule — aucune écriture DB, aucun réglage, aucune migration. Après rédaction, la preuve READ-ONLY de `compta_ma.db` reste identique à la valeur « Avant » ci-dessus.*


