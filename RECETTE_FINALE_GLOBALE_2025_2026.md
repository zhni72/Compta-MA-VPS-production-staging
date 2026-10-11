# RECETTE FINALE GLOBALE 2025–2026 — LECTURE SEULE

**Projet** : `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Société** : SOCIETE RECETTE MAROC SARL AU (company_id = 1) · régime TVA : mensuel
**Périmètre** : exercices 2025 (clos) et 2026 (ouvert)
**Interpréteur** : `.venv\Scripts\python.exe`
**Nature** : recette transversale **READ-ONLY** — aucune écriture DB, aucune réouverture,
aucune reclôture, aucune régénération (paie / à-nouveaux / Greffe), aucune correction de code,
aucune migration, aucun package, aucun Web, aucun SQL UPDATE/DELETE/INSERT, aucune restauration.
**Méthode de lecture** : connexion SQLite en mode **lecture seule** (`uri mode=ro`) ;
toute écriture éventuelle aurait levé une erreur au lieu de modifier la base.
Les montants proviennent des services métier de l'application (journal, balance, grand livre,
CPC, ESG, Bilan, ETIC, fiscalité, TVA, paie, Greffe, piste d'audit) — même source que l'écran.

---

## 1. Garde-fou / hash DB

| Contrôle | Constat | Statut |
|---|---|---|
| cwd exact = projet `compta_ma` | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` | PASS |
| `.venv\Scripts\python.exe` existe | oui | PASS |
| `compta_ma.db` existe | oui — 1 228 800 octets | PASS |
| Exercice 2025 | `closed` | PASS |
| Exercice 2026 | `open` | PASS |

| Preuve DB | Valeur |
|---|---|
| SHA-256 **début** de recette | `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101` |
| SHA-256 **fin** de recette | `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101` |
| SHA-256 attendu (Stage 3 final) | `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101` |
| Hash identique début = fin = attendu | **OUI** |
| Backup de référence (comparaison paie) | `compta_ma.db.bak-p1b-stage3-20261009-140154` (lu, non restauré) |

Garde-fou : **PASS**.

---

## 2. Comptabilité 2025

| État | Contrôle | Constat | Statut |
|---|---|---|---|
| Journal | Débit = Crédit | 102 écritures · D = C = **1 716 137,43** DH | PASS |
| Grand livre | Cohérence avec la balance | compte 5141 = **239 339,48** DH (grand livre = balance) | PASS |
| Balance | Débit = Crédit · équilibre | 24 comptes · D = C = **1 716 137,43** DH | PASS |
| CPC | Résultat | charges 307 956,13 − produits 360 000,00 = **52 043,87** DH (bénéfice) | PASS |
| ESG | Cohérence avec le CPC | RN = **52 043,87** DH · `coherent_avec_cpc = true` | PASS |
| Bilan | Actif = Passif | actif 398 539,48 = passif 346 495,61 + résultat 52 043,87 = **398 539,48** DH | PASS |
| Bilan CGNC | brut / amort. / net | brut 398 539,48 − amort. 12 000,00 = net **386 539,48** = passif + résultat | PASS |
| ETIC | Note 9 (charges de personnel) | **172 916,52** DH | PASS |

**ESG 2025** : marge brute 284 000,00 · valeur ajoutée 248 000,00 · EBE 75 083,48 ·
résultat d'exploitation 63 083,48 · résultat courant 63 083,48 · résultat net 52 043,87.

**Contrôles d'intégrité 2025** :

| Contrôle | Constat | Statut |
|---|---|---|
| Écritures déséquilibrées | 0 | PASS |
| Écritures 2025 non scellées | 0 (102/102 validation, 0 brouillon) | PASS |
| Résultat **avant IS** (référence) | **63 083,48** DH | PASS |
| Résultat **net** (référence) | **52 043,87** DH | PASS |

**Soldes clés 2025** : 5141 = 239 339,48 · 4441 = −39 741,24 · 4452 = −194,76 ·
4453 = −11 039,61 · 4455 = −72 000,00 · 34552 = 36 000,00 · 3421 = 43 200,00 ·
4411 = −11 520,00 · 1111 = −200 000,00.

Comptabilité 2025 : **PASS**.

---

## 3. Paie 2025

| Contrôle | Constat | Statut |
|---|---|---|
| Cycles de paie 2025 | **12** (statut `paye`) | PASS |
| Bulletins 2025 | **24** (2 salariés × 12 mois) | PASS |
| Salariés du scénario | **SAL-2025-A** (id 4), **SAL-2025-B** (id 5) | PASS |
| EMP001 / EMP002 / EMP003 non transformés | présents au référentiel (1/2/3), **0 bulletin 2025** | PASS |
| Écritures synthétiques `PAIE25-01..12` restantes | **0** | PASS |
| Coût employeur annuel | **172 916,52** DH | PASS |
| Double paie | 0 doublon réel sur les 12 périodes (`controle_doublon_paie`) | PASS |
| Écritures paie & paiements équilibrées | 24 écritures du module, **0 déséquilibrée** | PASS |

**Cumuls 2025** : brut 142 800,00 · cotisations salariales 9 624,72 · IR retenu **194,76** ·
net payé 132 980,52 · **coût employeur 172 916,52** DH.

**Composition des écritures du module 2025** (12 cycles) :
12 écritures **OD** (paie) + 12 écritures **BQ** (paiement), source `payroll`,
référence `PAIE 2025-MM` — toutes équilibrées.

Paie 2025 : **PASS**.

---

## 4. Fiscalité / TVA 2025

### 4.1 Impôt sur les sociétés

| Élément | Constat | Statut |
|---|---|---|
| Résultat avant impôt | **63 083,48** DH | PASS |
| Réintégrations / déductions | 0,00 / 0,00 DH | PASS |
| **Résultat fiscal** | **63 083,48** DH | PASS |
| **IS théorique / impôt dû** | **11 039,61** DH | PASS |
| Cotisation minimale (CM) | **0,00** DH (`cotisation_minimale_due = 0`) | PASS |
| Solde d'IS à payer | 11 039,61 DH (acomptes/crédits 0,00) | PASS |
| Dette IS — compte 4453 | **−11 039,61** DH (créditeur) | PASS |
| Contrôles fiscaux bloquants | 0 (2 contrôles d'information : solde à payer, récap) | PASS |

**Absence de double comptabilisation de l'IS** — mouvements du compte 4453 en 2025 :

| Écriture | Date | Réf | Débit | Crédit |
|---|---|---|---|---|
| EC202500089 | 2025-12-31 | IS-2025 | 0,00 | 18 400,00 |
| EC202500114 | 2025-12-31 | IS-2025-REG | 7 360,39 | 0,00 |

Solde net 4453 = 18 400,00 − 7 360,39 = **11 039,61** créditeur, en face d'une **charge unique**
au compte 6701 de solde **11 039,61** DH. Cohérence fiscalité ⇄ CPC ⇄ écritures : **PASS**.

### 4.2 TVA 2025 (état disponible dans l'application)

Régime de la société : **mensuel** → 12 périodes mensuelles cohérentes (échéance le 20 du mois suivant).

| Contrôle | Constat | Statut |
|---|---|---|
| Périodes cohérentes | 12 mois, bornes exactes (01→fin de mois), échéances J+20 | PASS |
| TVA collectée annuelle | **72 000,00** DH (= Σ des 12 périodes : 6 000,00/mois) | PASS |
| TVA déductible annuelle | **36 000,00** DH (= Σ des 12 périodes) | PASS |
| Assiettes / soldes comptables | solde **4455 = −72 000,00** (= collectée) ; solde **34552 = 36 000,00** (= déductible) | PASS |
| Doublon manifeste de période | **aucun** | PASS |
| Janvier 2025 | collectée 6 000,00 − déductible 14 000,00 → crédit de TVA reporté **8 000,00** DH | PASS |

Aucun recalcul ni correction de déclaration n'a été effectué (conformément au périmètre).
Point documentaire (voir §11, mineure M1) : le registre `tax_declarations` ne contient qu'une
ligne de type TVA (période « 2026 », statut `brouillon`, mode `simulation`) — **aucune
déclaration TVA 2025 n'y est enregistrée**, alors que le calcul TVA 2025 reste disponible et
cohérent.

Fiscalité / TVA 2025 : **PASS**.

---

## 5. À-nouveaux 2026

| Contrôle | Constat | Statut |
|---|---|---|
| Écriture d'ouverture 2026 | **EC202600120** du **2026-01-01**, source `opening`, 13 lignes, **scellée** | PASS |
| Écriture équilibrée | D = C = **398 539,48** DH | PASS |
| Delta global | **0,00** DH | PASS |
| Deuxième à-nouveau parasite | **aucun** — 1 seule écriture `opening` en 2026 | PASS |
| Cohérence 31/12/2025 → 01/01/2026 | classes 1 à 5 reprises à l'identique + contrepartie résultat 1191 | PASS |

**Comptes cibles vérifiés** :

| Compte | Attendu | Constaté | Statut |
|---|---|---|---|
| 5141 | 239 339,48 DH (débiteur) | 239 339,48 | PASS |
| 4441 | 39 741,24 DH (créditeur) | −39 741,24 | PASS |
| 4452 | 194,76 DH (créditeur) | −194,76 | PASS |
| 4453 | 11 039,61 DH (créditeur) | −11 039,61 | PASS |
| 1191 | 52 043,87 DH (créditeur) | −52 043,87 | PASS |

Détail complet des 13 lignes : 1111 −200 000,00 · 2340 60 000,00 · 2834 −12 000,00 ·
3111 20 000,00 · 3421 43 200,00 · 34552 36 000,00 · 4411 −11 520,00 · 4441 −39 741,24 ·
4452 −194,76 · 4453 −11 039,61 · 4455 −72 000,00 · 5141 239 339,48 · 1191 −52 043,87.

**Cohérence de bascule** : la comparaison des soldes d'arrêté au 31/12/2025 et des lignes
d'ouverture au 01/01/2026 ne fait apparaître qu'un seul écart, sur le compte **1191**
(fin 2025 = 0 → ouverture 2026 = −52 043,87) ; c'est le **mécanisme attendu** de report du
résultat net de l'exercice clos dans les capitaux propres de l'exercice suivant (contrepartie
qui équilibre l'écriture) — **non une anomalie** (voir §11, mineure M2).

À-nouveaux 2026 : **PASS**.

---

## 6. Comptabilité 2026

| État | Contrôle | Constat | Statut |
|---|---|---|---|
| Journal | Débit = Crédit | 106 écritures · D = C = **2 605 123,56** DH | PASS |
| Grand livre | Cohérence avec la balance | compte 5141 = **234 022,60** DH | PASS |
| Balance | Débit = Crédit · équilibre | 25 comptes · D = C = **2 605 123,56** DH | PASS |
| CPC | Résultat (valeur réelle) | charges 545 307,20 − produits 432 000,00 = **−113 307,20** DH | PASS |
| ESG | Cohérence avec le CPC | RN = **−113 307,20** DH · `coherent_avec_cpc = true` | PASS |
| Bilan | Actif = Passif | actif 407 822,60 = passif 521 129,80 + résultat (−113 307,20) = **407 822,60** DH | PASS |
| Bilan CGNC | brut / amort. / net | brut 407 822,60 − amort. 27 000,00 = net **380 822,60** = passif + résultat | PASS |
| ETIC | Note 9 (charges de personnel) | 365 947,20 DH | PASS |

**ESG 2026** : marge brute 329 000,00 · valeur ajoutée 287 600,00 · EBE −78 347,20 ·
résultat d'exploitation −93 347,20 · résultat courant −93 347,20 · résultat net −113 307,20.

Conformément au périmètre, **aucun montant de résultat 2026 n'était imposé** : la valeur réelle
relevée est **−113 307,20 DH (perte)**, et seule sa **cohérence** interne (CPC = ESG = Bilan)
a été contrôlée — elle est vérifiée.

**Contrôles d'intégrité 2026** : 106/106 écritures validées · 0 brouillon · 0 déséquilibrée ·
0 non scellée. Aucune anomalie née de la régénération des à-nouveaux.

Comptabilité 2026 : **PASS**.

---

## 7. Paie 2026 (non modifiée par Stage 3)

| Contrôle | Constat | Statut |
|---|---|---|
| Cycles 2026 | **12** (statut `paye`) | PASS |
| Bulletins 2026 | **36** (3 salariés × 12 mois) | PASS |
| Salariés 2026 | EMP001 / EMP002 / EMP003 (inchangés) | PASS |
| Comparaison avec backup pré-Stage 3 | 36 vs 36 bulletins, **signatures identiques** (salarié × période × brut / IR / net / coût employeur) | PASS |
| Duplication / suppression / régénération involontaire | **aucune** (0 doublon, 24 écritures module équilibrées) | PASS |

**Cumuls 2026** : brut 312 000,00 · cotisations 15 115,20 · IR 27 607,92 · net 269 276,88 ·
coût employeur 365 947,20 DH. Composition : 12 écritures **OD** + 12 écritures **BQ** (source
`payroll`), toutes équilibrées.

Comparaison réalisée en **lecture seule** sur `compta_ma.db.bak-p1b-stage3-20261009-140154`
(aucune restauration) : **contenu 2026 strictement identique**.

Paie 2026 : **PASS**.

---

## 8. Greffe 2025

| Élément | Constat | Statut |
|---|---|---|
| Dossier de dépôt | #1 · SARL · statut **`approuve`** | PASS |
| Date AG d'approbation | **2026-01-08** (limite portail 2026-06-30, loi 5-96 art. 10) | PASS |
| Dépôt réel / certificat | `date_depot = null`, `certificat_path = null` (aucun dépôt réel) | PASS |
| Complétude | **5/5** pièces obligatoires fournies | PASS |
| Contrôles bloquants Greffe | **0** (0 contrôle émis) | PASS |
| Taxes | montant 1 000,00 DH · payé 1 000,00 · solde **0,00** | PASS |

**Les 5 pièces finales** (toutes présentes, non vides, empreintes distinctes) :

| Pièce | Fichier | Taille | SHA-256 |
|---|---|---|---|
| etats_synthese | Etats_synthese_2025.pdf | 15 347 o | `70eb474ffddb78f9b2293f4ffeb585597928933497275c5204984f27c68c1b2d` |
| rapport_gestion | Rapport_gestion_2025.pdf | 5 328 o | `735a7efa9f6fa1ef1c13cb605ae1bdd8123af178504c3f1b55c194e85b993b8b` |
| pv_ag | PV_AG_2025.pdf | 4 930 o | `ae2f19374ceb15004c39772dfc8b6bd85b6ed55eb50928cf2ea6bbc1de3f2cec` |
| etat_complementaire | Bordereau_depot_greffe_2025.pdf | 4 791 o | `6c73fd3c3c0b8dfc2d6e8b6a45a4f17717e68af19872bb5cab0c1416ac186a2f` |
| justificatif_paiement | Attestation_paiement_taxes_2025.pdf | 2 312 o | `5cf536b481b2bf4d4c4df966a5a07ba612ce4895377dd694f22f90fe4556f2ff` |

Les tailles lues sur le disque sont identiques aux tailles en base (cohérence base ⇄ archive).
Aucun document n'a été régénéré.

**Contrôle Greffe final = 14/14 PASS** :

- [PASS] 5 pièces présentes
- [PASS] aucune pièce vide (taille > 1000)
- [PASS] empreintes toutes distinctes
- [PASS] contenu métier des états de synthèse
- [PASS] états de synthèse cohérents (CPC = Bilan)
- [PASS] rapport : résultat net corrigé (**52 043,87 DH**)
- [PASS] rapport : total bilan net (**386 539,48 DH**)
- [PASS] PV : résultat net corrigé (52 043,87 DH)
- [PASS] PV : total bilan net (386 539,48 DH)
- [PASS] checklist complète (5/5)
- [PASS] aucun contrôle bloquant Greffe
- [PASS] date AG dans le délai (6 mois)
- [PASS] aucun dépôt réel (statut inchangé)
- [PASS] aucun certificat de dépôt

Greffe 2025 : **PASS**.

---

## 9. Audit & traçabilité

| Contrôle | Constat | Statut |
|---|---|---|
| Chaîne d'audit intègre | `integre = true` | PASS |
| Écritures scellées | **208 / 208** | PASS |
| Ruptures de chaîne | **0** | PASS |
| Écritures non scellées | **0** | PASS |
| Rescellage Stage 3 tracé | `P1B_STAGE3_RESCELLAGE` = 1 (opération exceptionnelle identifiable) | PASS |

**Traces Stage 3 présentes** (journal d'audit, company 1 — total 593 entrées) :

| Action | Occurrences |
|---|---|
| FISCAL_YEAR_REOPENED (réouverture) | 1 |
| PAYROLL_RESET_SUPPRESSION (retrait PAIE25) | 25 |
| PAYROLL_PREPARED / PAYROLL_VALIDATED / PAYROLL_PAID | 25 / 25 / 24 |
| FISCAL_YEAR_CLOSED (dont reclôture) | 2 |
| P1B_STAGE3_CLOTURE | 1 |
| OPENING_REGENERATED (régénération à-nouveaux) | 1 |
| OPENING_ENTRY_GENERATED | 2 |
| GREFFE_PIECES_GENERATED | 16 |
| P1B_STAGE3_RESCELLAGE | 1 |

La séquence complète **réouverture → retrait PAIE25 → paie 2025 → régularisation IS →
reclôture → à-nouveaux 2026 → rescellage contrôlé** est intégralement tracée.

Audit : **PASS**.

---

## 10. Tests

| Étape | Résultat |
|---|---|
| Tests ciblés (comptabilité / paie / fiscalité / clôture / Greffe / audit) — 14 fichiers | **156 passed** (1 warning `StarletteDeprecationWarning`) |
| Suite complète (une seule exécution) | **456 passed**, 0 échec (1 warning) — baseline **456** maintenue |
| Hash DB avant / après tests | identique (voir §10 ci-dessous et §1) |

La suite complète s'exécute sur base SQLite **en mémoire** (fixtures `tests/conftest.py`) :
elle ne touche pas `compta_ma.db`. Preuve : SHA-256 identique avant et après l'exécution.

Tests : **PASS**.

---

## 11. Anomalies classées

### Bloquantes
- **Aucune.**

### Importantes
- **Aucune.**

### Mineures / points documentaires (sans impact sur la cohérence comptable)
- **M1 — Registre des déclarations TVA : pas de ligne 2025.** Le registre unique
  `tax_declarations` ne contient qu'une seule déclaration de type TVA (période « 2026 »,
  statut `brouillon`, mode `simulation`). Aucune déclaration TVA 2025 n'y est enregistrée.
  Le calcul TVA 2025 reste néanmoins **disponible et cohérent** (12 périodes, assiettes
  cohérentes, soldes 4455/34552 correspondants, aucun doublon). Point purement **documentaire**.
  *Aucune correction effectuée (hors périmètre READ-ONLY).*
- **M2 — Écart de bascule 1191 (attendu).** La comparaison 31/12/2025 → 01/01/2026 présente un
  unique écart sur le compte 1191 (0 → −52 043,87 DH). Il correspond au **mécanisme normal**
  de report du résultat net de l'exercice clos (contrepartie d'équilibrage de l'à-nouveau),
  **non une anomalie** ; il est signalé par transparence.

Aucune anomalie n'affecte l'équilibre, la cohérence CPC/ESG/Bilan, la fiscalité, la paie,
le Greffe ou la piste d'audit.

---

## 12. Verdict final

Preuve DB (rappel) :

- SHA-256 début de recette : `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101`
- SHA-256 fin de recette   : `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101`
- Hash attendu             : `4e2c9ec37d8c8956d0d52199ca008bee16b6a97ecf2115597364a3b7600b9101`
- **Base inchangée pendant toute la recette.**

> ## **RECETTE FINALE 2025–2026 PASS — BASE COMPTABLE VALIDÉE**

*Recette transversale en lecture seule ; aucune écriture DB, aucune réouverture, aucune
reclôture, aucune régénération (paie / à-nouveaux / Greffe), aucune correction de code,
aucune migration, aucun package, aucun Web, aucun SQL d'écriture, aucune restauration de
backup. STOP.*