# P1B STAGE 3 — REGULARISATION CONTROLEE PAIE 2025 — RAPPORT FINAL

**Projet** : `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`  ·  **Exercice cible** : 2025  ·  **Societe** : SOCIETE RECETTE MAROC SARL AU
**Scenario valide** : SAL-2025-A = 6 000 DH brut/mois · SAL-2025-B = 5 900 DH brut/mois · 12 mois.
**Interpreteur** : `.venv\Scripts\python.exe` (garde-fou OK). Aucune migration, aucun package, aucun Web, aucun SQL de contournement.

## 1. Backup initial

| Grandeur | Valeur |
|---|---|
| Fichier de sauvegarde | `compta_ma.db.bak-p1b-stage3-20261009-140154` |
| SHA-256 original | `52fc68c77aed0369be424d628a39d07db953f61b1ca3cf7b18689fcbcfb58743` |
| SHA-256 backup | `52fc68c77aed0369be424d628a39d07db953f61b1ca3cf7b18689fcbcfb58743` |
| Taille | 1163264 octets |
| mtime original | 2026-10-09T13:32:16.500916 |
| Original = backup | **True** |

## 2. Reouverture 2025 (service metier)

- Statut avant : `closed` → apres : **`open`**
- Motif : **Régularisation contrôlée paie 2025 — P1B Stage 3**
- Verrous de periode : aucun
- Impact N+1 : 106 ecriture(s) dans 2026 ; a-nouveaux N+1 conserves : EC202600001
- Trace d'audit : `FISCAL_YEAR_REOPENED`

## 3. Ecritures synthetiques retirees

- Cibles exclusives : PAIE25-01 … PAIE25-12 ; **12 ecritures retirees** (attendu 12, 0 restante).
- Tracabilite : `PAYROLL_RESET_SUPPRESSION` (instantane complet compte/debit/credit par ecriture).
- Piste d'audit rescellee : 176 sur 183 ; ruptures=0 ; integre=True
- Journal apres retrait : ['3996984.08', '3996984.08', True] (D = C)

| Ecriture | Date | Piece | Comptes |
|---|---|---|---|
| EC202500008 | 2025-01-28 | PAIE25-01 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500015 | 2025-02-28 | PAIE25-02 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500022 | 2025-03-28 | PAIE25-03 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500029 | 2025-04-28 | PAIE25-04 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500036 | 2025-05-28 | PAIE25-05 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500043 | 2025-06-28 | PAIE25-06 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500050 | 2025-07-28 | PAIE25-07 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500057 | 2025-08-28 | PAIE25-08 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500064 | 2025-09-28 | PAIE25-09 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500071 | 2025-10-28 | PAIE25-10 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500078 | 2025-11-28 | PAIE25-11 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |
| EC202500085 | 2025-12-28 | PAIE25-12 | 6171 D10000.00/C0.00, 6174 D2000.00/C0.00, 5141 D0.00/C12000.00 |

## 4. Salaries crees

| Matricule | Base mensuelle | Situation | Charges |
|---|---|---|---|
| SAL-2025-A | 6000.00 DH | celibataire | 0 |
| SAL-2025-B | 5900.00 DH | marie | 1 |

EMP001/EMP002/EMP003 non convertis, non reutilises (aucune paie 2025 pour ces salaries).

## 5. Cycles / bulletins generes (module)

- Cycles 2025 : **12** · bulletins : **24** (2 salaries × 12 mois).
- Cout employeur annuel : **172916.52 DH** ; net paye : 132980.52 DH ; IR retenu : 194.76 DH.

| Periode | Bulletins | Brut | IR | Net | Cout employeur | Ecriture / Paiement |
|---|---|---|---|---|---|---|
| 2025-01 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500090 / EC202500091 |
| 2025-02 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500092 / EC202500093 |
| 2025-03 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500094 / EC202500095 |
| 2025-04 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500096 / EC202500097 |
| 2025-05 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500098 / EC202500099 |
| 2025-06 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500100 / EC202500101 |
| 2025-07 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500102 / EC202500103 |
| 2025-08 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500104 / EC202500105 |
| 2025-09 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500106 / EC202500107 |
| 2025-10 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500108 / EC202500109 |
| 2025-11 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500110 / EC202500111 |
| 2025-12 | 2 | 11900.00 | 16.23 | 11081.71 | 14409.71 | EC202500112 / EC202500113 |

## 6. Ecritures paie / paiement 2025 (module)

- Ecritures du module 2025 : **24** (12 OD de paie + 12 BQ de paiement) ; PAIE25-* synthetiques restantes : **0**.
- Ecriture de paie mensuelle (journal OD, deduite des bulletins) : 61711 salaire de base D 11 900,00 ; 61741 cotisations patronales CNSS/AMO D 1 557,71 ; 61744 prestations familiales D 761,60 ; 61768 TFP D 190,40 / 4432 net a payer C 11 081,71 ; 4441 CNSS-AMO C 3 311,77 ; 4452 IR C 16,23 (total D = C = 14 409,71).
- Ecriture de paiement mensuelle (journal BQ) : 4432 D 11 081,71 / 5141 C 11 081,71.
- Soldes 2025 (D-C) : 4432=0.00 · 4441=-39741.24 · 4452=-194.76 · 5141=239339.48 · 6701=11039.61 · 4453=-11039.61 · 3453=0.00

## 7. Resultat comptable 2025 (apres regularisation)

| Indicateur | Montant |
|---|---|
| Total produits (classe 7) | 360000.00 DH |
| Total charges (classe 6) | 307956.13 DH |
| Charges de personnel (ETIC note 9) | 172916.52 DH |
| **Resultat comptable (CPC = ESG = Bilan)** | **52043.87 DH** |
| Resultat avant impot (fiscal) | 63083.48 DH |
| Resultat fiscal | 63083.48 DH |

## 8. IS / CM 2025

| Indicateur | Valeur |
|---|---|
| IS theorique (17,5 % × 63 083,48) | **11039.61 DH** |
| Cotisation minimale | **0.00 DH** (exoneration : True) |
| Impot du (max IS / CM) | 11039.61 DH |
| IS comptabilise initialement (6701) | 18400.00 DH |
| Ecart repris (4453 D / 6701 C) | **7360.39 DH** (EC202500114) |
| IS comptabilise apres regularisation | **11039.61 DH** |
| Dette IS (4453) apres regularisation | 11039.61 DH |

## 9. Resultat net 2025

**Resultat net = 63 083,48 − 11 039,61 = 52043.87 DH** (vs 73 600,00 avant regularisation).

## 10. Cloture 2025 (service metier)

- Statut : **`closed`**
- Motif : **Clôture après régularisation paie 2025 — P1B Stage 3**
- Resultat net fige : 52043.87 DH ; total actif : 398539.48 DH
- Traces : `FISCAL_YEAR_CLOSED` + `P1B_STAGE3_CLOTURE`

## 11. A-nouveaux 2026 avant / apres (service metier)

- Avant : EC202600001 (11 lignes, total 387520.00 DH)
- Apres : EC202600120 (13 lignes, total 398539.48 DH)
- **Delta global = 0.00 DH** (equilibre)
- Piste rescellee apres regeneration : 131 ecriture(s) ; integre=True ; ruptures=0

| Compte | AN avant | AN corrige | Delta |
|---|---|---|---|
| 1191 | -73600.00 | -52043.87 | 21556.13 |
| 4441 | 0.00 | -39741.24 | -39741.24 |
| 4452 | 0.00 | -194.76 | -194.76 |
| 4453 | -18400.00 | -11039.61 | 7360.39 |
| 5141 | 228320.00 | 239339.48 | 11019.48 |

**References V8** : 5141 ≈ 239 339,48 ; 4441 ≈ 39 741,24 C ; 4452 ≈ 194,76 C ; 4453 ≈ 11 039,61 C ; 1191 ≈ 52 043,87 C — conformes.

## 12. Recalcul 2026

- Cycles 2026 : **12** (inchange) · bulletins : **36** (inchange) · ecritures module 2026 : 24.
- Journal 2026 : D 2605123.56 = C 2605123.56 (True)
- CPC 2026 : produits 432000.00 - charges 545307.20 = resultat -113307.20
- Bilan 2026 : actif 407822.60 = passif 407822.60 (True)
- ESG 2026 net -113307.20 ; ETIC note 9 365947.20
- Fiscal 2026 : avant impot -93347.20 ; resultat fiscal -93347.20 ; IS 0.00 ; CM 0.00
- **Paie operationnelle 2026 inchangee** ; seules les consequences d'ouverture 2025→2026 changent (bilan / a-nouveaux).

## 13. Greffe 2025 regenere

- Dossier #1 · statut `approuve` · date AG 2026-01-08 · completude 5/5
- Resultat net attendu : 52 043,87 ; total bilan net attendu : 386 539,48
- Controles Greffe : 0 (0 bloquant) ; aucun depot reel, aucun certificat.

| Piece | Fichier | Taille | SHA-256 (nouveau) |
|---|---|---|---|
| etat_complementaire | Bordereau_depot_greffe_2025.pdf | 4791 o | `6c73fd3c3c0b8dfc2d6e8b6a45a4f177…` |
| etats_synthese | Etats_synthese_2025.pdf | 15347 o | `70eb474ffddb78f9b2293f4ffeb58559…` |
| justificatif_paiement | Attestation_paiement_taxes_2025.pdf | 2312 o | `5cf536b481b2bf4d4c4df966a5a07ba6…` |
| pv_ag | PV_AG_2025.pdf | 4930 o | `ae2f19374ceb15004c39772dfc8b6bd8…` |
| rapport_gestion | Rapport_gestion_2025.pdf | 5328 o | `735a7efa9f6fa1ef1c13cb605ae1bdd8…` |

- [PASS] 5 pieces presentes
- [PASS] aucune piece vide (taille > 1000)
- [PASS] empreintes toutes distinctes
- [PASS] contenu metier etats de synthese
- [PASS] etats de synthese coherents (CPC=Bilan)
- [PASS] rapport : resultat net corrige
- [PASS] rapport : total bilan net
- [PASS] PV : resultat net corrige
- [PASS] PV : total bilan net
- [PASS] checklist complete (5/5)
- [PASS] aucun controle bloquant Greffe
- [PASS] date AG dans le delai (6 mois)
- [PASS] aucun depot reel (statut inchange)
- [PASS] aucun certificat de depot

## 14. Audit trail

- Piste : 208 ecriture(s), 208 scellee(s), 0 rupture(s), integre=True
  - `FISCAL_YEAR_REOPENED` : 1
  - `PAYROLL_RESET_SUPPRESSION` : 25
  - `PAYROLL_EMPLOYEE_CREATED` : 5
  - `PAYROLL_CONTRACT_ADDED` : 14
  - `PAYROLL_PREPARED` : 25
  - `PAYROLL_VALIDATED` : 25
  - `PAYROLL_PAID` : 24
  - `FISCAL_YEAR_CLOSED` : 2
  - `P1B_STAGE3_CLOTURE` : 1
  - `OPENING_REGENERATED` : 1
  - `OPENING_ENTRY_GENERATED` : 2
  - `GREFFE_PIECES_GENERATED` : 16

## 15. Tests

- Tests cibles Paie / Fiscalite / Cloture / Greffe / Audit : **PASS**
- Suite complete : **456 tests PASS** (0 echec) — baseline 456 maintenue (`PREUVE_P1B_STAGE3_TESTS.log`).

## 16. Backup final

| Grandeur | Valeur |
|---|---|
| Fichier de sauvegarde | `compta_ma.db.bak-p1b-stage3-final-20261009-144431` |
| SHA-256 DB finale | `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101` |
| SHA-256 backup final | `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101` |
| Taille | 1228800 octets |
| mtime | 2026-10-09T14:28:16.319416 |
| Identiques | **True** |

## 17. Anomalies eventuelles

- Aucune anomalie bloquante.
- Point d'attention : la regeneration des a-nouveaux supprime l'ancienne ecriture d'ouverture (situee au milieu de la chaine) ; la piste d'audit a ete **rescellee** par le mecanisme prevu (reprise de dossier, trace `P1B_STAGE3_RESCELLAGE`).
- Ecart cout employeur vs cible historique 14 400 DH/mois : +9,71 DH (taux reglementaires, aucun montant force).

## 18. Verdict final

> ## **P1B STAGE 3 PASS — 2025 REGULARISE / 2026 RESYNCHRONISE**

*Generation unique, session unique ; aucun depot reel, aucun certificat fictif, aucune migration, aucun package, aucun Web.*
