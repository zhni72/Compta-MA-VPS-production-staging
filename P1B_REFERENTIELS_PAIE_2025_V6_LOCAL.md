# P1B V6 — RÉFÉRENTIELS PAIE 2025 — VALIDATION À PARTIR DES DOCUMENTS LOCAUX

**Projet** : Compta MA — `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Dossier documentaire (lecture seule)** : `C:\Users\Belyazid\Desktop\compt\Documentation`
**Date** : 06/10/2026 — **Mode** : read-only absolu (aucune modification du moteur, de la DB, des paramètres)
**Référence** : validation V6 par corpus local uniquement (Internet interdit) — complète `P1B_REFERENTIELS_PAIE_2025_V5.md`

---

## 0. Garde-fou (avéré)

| Élément | État |
|---|---|
| Projet `compta_ma` | OK |
| `compta_ma.db` (avant/après) | OK — preuve §8 |
| `app/` | OK |
| `.venv\Scripts\python.exe` (3.13.9, pypdf) | OK |
| `Documentation\` (15 PDF) | OK — accessible |

---

## 1. Liste exacte des documents utilisés (12 PDF consultés sur 14)

| # | Document | Rôle | Pages citées |
|---|---|---|---|
| 1 | `02_Fiscalite\cgi-2025-fr.pdf` — CGI édition applicable 2025 | IR art. 59/73/74 ; CM art. 144 ; IS grille transitoire art. 247-XXXVII ; exo art. 57-20° | p. 95-96, 117, 123, 263-265, 470-472 |
| 2 | `02_Fiscalite\BO_7362_fr.pdf` — LF 2025 (loi n° 60-24), BO 7362 du 19-12-2024 | Art. 8 : barème IR 2025, charges de famille 500 DH | p. 2983 (PDF p. 33/116) |
| 3 | `02_Fiscalite\Note-Circulaire-n°-736…LF-2025-1.pdf` — Note DGI 736 | Barème 2025 + **sommes à déduire** ; charges de famille 360→500 ; date d'effet 01/01/2025 | p. 13-15 |
| 4 | `02_Fiscalite\cgi-2026-maroc.pdf` — CGI 2026 | **Comparaison 2025→2026 uniquement** (barème art. 73-I 2026 = 37 %) | art. 73-I |
| 5 | `03_CNSS\dahir_1-72-184.pdf` — Dahir 1-72-184 (régime sécurité sociale) | Assiette (art. 19) ; répartition 2/3-1/3, prestations familiales employeur seul (art. 20) | p. 10-11 (PDF p. 5-6/16) |
| 6 | `03_CNSS\fiche_synthetique_cnss.pdf` — fiche institutionnelle CNSS | Taux : PF 6,40 % ; CT 1,57 % ; LT 11,89 % ; plafond 6 000 DH/mois | p. 2 |
| 7 | `03_CNSS\BO_7443_Ar.pdf` — BO 7443 du 29-09-2025 | **Arrêté n° 1314-25 du 19-05-2025** : exclusions d'assiette CNSS + plafonds | p. 7324-7326 (PDF p. 5-7/66) |
| 8 | `03_CNSS\BO_7464_Ar.pdf` — BO 7464 du 11-12-2025 | **Erratum** à l'arrêté 1314-25 | p. 9245-9246 (PDF p. 11-12/53) |
| 9 | `04_AMO\2.05.734.pdf` — décret n° 2-05-734 (extrait 1 page, arabe) | Taux AMO historiques — extraction illisible : non exploitable | p. 1 |
| 10 | `04_AMO\loi-65-00.pdf` — loi 65-00 (AMO) | Base : cotisation fixée par décret | passim |
| 11 | `04_AMO\ma-bulletin-officiel-dated-2014-12-04-no-6314.pdf` — BO 6314 du 04-12-2014 | **Décret n° 2-14-707 du 10-11-2014** modifiant le décret 2-05-734 : taux AMO secteur privé (4,52 % + 1,85 %), effet 01/01/2016 | p. 4770-4771 (PDF p. 19-20/48) |
| 12 | `05_TFP\decret_ndeg_2-73-633.pdf` — décret n° 2-73-633 (22-05-1974, BO 3213) | TFP : taux 1,6 % (art. 3 mod. 2-86-820) ; assiette (art. 4) ; employeur seul (art. 5) | p. 72-73 |

Extraits mais **non requis** : `01_Comptabilite\cgnc.pdf` (normes comptables), `06_Travail\code du travail….pdf`. `99_Documentation_pedagogique` **écarté** (non réglementaire, conformément à la consigne).

---

## 2. Paramètres réglementaires 2025 CONFIRMÉS (valeur + référence précise)

### 2.1 IR 2025
- **Barème annuel (CGI 2025 art. 73-I p. 117 ; art. 8 LF 2025 = BO 7362 p. 2983 ; Note 736 p. 13)** — applicable aux revenus **acquis à compter du 01/01/2025** (Note 736 p. 14) :
  - 0 – 40 000 DH : **exonéré** ; 40 001 – 60 000 : **10 %** ; 60 001 – 80 000 : **20 %** ; 80 001 – 100 000 : **30 %** ; 100 001 – 180 000 : **34 %** ; **au-delà de 180 000 : 37 %**.
- **Sommes à déduire annuelles (Note 736 p. 13)** : 0 / **4 000** / **10 000** / **18 000** / **22 000** / **27 400**.
- **Tranche haute = 37 %** (et non 38 %) : la Note 736 p. 13 montre que **38 % était le taux 2024** (« le taux marginal… a été réduit de 38 % à 37 % ») ; le CGI 2026 (art. 73-I) affiche encore **37 % pour le surplus** → question « 37 % ou 38 % » tranchée par le corpus : **37 % pour 2025**.
- **Réduction pour charge de famille (CGI 2025 art. 74-I p. 123 ; BO 7362 p. 2983 ; Note 736 p. 15)** : **500 DH par personne à charge**, plafond annuel **3 000 DH** (soit **6 personnes** max), relevée de 360 → 500 par la LF 2025 ; conditions : enfant ≤ 27 ans, revenu annuel ≤ tranche exonérée.
- **Frais professionnels (CGI 2025 art. 59-I-A p. 95-96)** : **35 %** du revenu brut annuel imposable si **≤ 78 000 DH** ; **25 %** si **> 78 000 DH**, déduction plafonnée à **35 000 DH**. Seuil 78 000 inchangé par la LF 2025. (Plafond « 30 000 » non visible : §4.1.)

### 2.2 CNSS 2025
- **Assiette** : ensemble des rémunérations (salaires, indemnités, primes, gratifications, avantages en nature, pourboires) — dahir 1-72-184 **art. 19** (p. 10-11).
- **Répartition** : **2/3 employeur – 1/3 salarié**, allocations familiales **exclusivement à la charge de l'employeur** — dahir 1-72-184 **art. 20** (p. 10-11).
- **Taux par branche (fiche CNSS p. 2)** : allocations familiales **6,40 %** du salaire réel (employeur seul) ; prestations court terme **1,57 %** ; prestations long terme **11,89 %** (du salaire **plafonné à 6 000 DH/mois**).
- **Taux dérivés (1/3 – 2/3)** : **salarié = 4,48 %** (0,52 + 3,96) ; **employeur = 8,98 %** (1,05 + 7,93). Plafond **6 000 DH/mois** uniquement sur prestations court/long terme.
- **Changement d'assiette 2025** : **arrêté n° 1314-25 du 19-05-2025** (BO 7443 du 29-09-2025, p. 7324-7326 ; erratum BO 7464 du 11-12-2025, p. 9245-9246) — éléments **exclus** de l'assiette CNSS avec plafonds : indemnité de déplacement (jusqu'à **100 % du salaire de base, max 5 000 DH/mois**) ; mutation (**10 DH/km** au Maroc) ; représentation (**10 % du salaire de base**) ; prime de séjour salariés étrangers (valeur billet, 1 voyage/4 ans) ; **indemnité de licenciement (jusqu'à 1 000 000 DH)** ; indemnité de formation-insertion, frais de téléphone (erratum), etc. Aucun changement de **taux** CNSS en 2025 dans le corpus.
- Le décret d'habilitation 2-25-266 du 24-04-2025 (cité dans le préambule) n'est **pas** dans le corpus.

### 2.3 AMO 2025
- **Texte le plus récent du corpus** : **décret n° 2-14-707 du 10-11-2014** (BO 6314 du 04-12-2014, p. 4770-4771), modifiant le décret 2-05-734, applicable à compter du **01/01/2016** :
  - salariés du secteur privé : **4,52 % de l'ensemble des rémunérations** (à la charge du salarié), **majoré de 1,85 %** (part patronale) → **total 6,37 %** ;
  - marins-pêcheurs à la part : 1,36 % / 1,70 % du produit brut de vente ; titulaires de pensions : 4,52 % ; assurance volontaire : 4,52 %.
- **Assiette** : ensemble des rémunérations, **sans plafond** (dahir 1-72-184 art. 19 ; décret 2-14-707).
- Le fragment `2.05.734.pdf` (décret original 2005) est un extrait arabe 1 page à l'extraction illisible (chiffres « 1,2 % / 1,5 % » non exploitables) → écarté.
- **Aucun texte du corpus ne mentionne les taux « 2,26 % / 4,11 % »** (cf. §3 — À ARBITRER).

### 2.4 TFP 2025
- **Taux** : **1,6 %** du montant des rémunérations — décret n° 2-73-633 du 22-05-1974, **art. 3** (modifié par décret n° 2-86-820 du 31-12-1986), p. 72.
- **Assiette** : ensemble de la **rémunération brute mensuelle** (y compris indemnités, primes, gratifications, avantages en nature, pourboires) — art. 4, p. 72.
- **Redevable** : **exclusivement l'employeur** — art. 5, p. 72.
- Aucun changement 2025 dans le corpus.

### 2.5 Fiscalité entreprise (couverte par les documents)
- **IS 2025 — grille transitoire (CGI 2025, art. 247-XXXVII-A, p. 470-472 ; LF 2023 loi 50-22 + LF 2025 loi 60-24)** :
  - BNF **≤ 300 000 DH** : **17,50 %** (exercice ouvert au 01/01/2025) ;
  - BNF 300 001 → < 100 M DH : **20 %** ;
  - BNF **≥ 100 M DH** : **31,25 %** (35 % seulement en 2026) ;
  - établissements de crédit / assurances : **39,25 %** (40 % en 2026) ;
  - ZAI / Casablanca Finance City : **18,75 %** (20 % en 2026).
- **Cotisation minimale (CGI 2025, art. 144-I, p. 263-265)** : taux **0,25 %** ; plancher **3 000 DH** (IS) ; **exonération des 36 premiers mois** suivant le début d'exploitation (art. 144-I-C-1°) ; base = **produits hors TVA** (art. 144-I-B, p. 263).
- **Exonération scénario (nouveaux recrutements)** : exonération IR **36 mois** à compter du premier recrutement (CGI 2025, art. 57-20° + dispositions transitoires).

---

## 3. Contradictions éventuelles

| Sujet | Source A (corpus) | Source B | Classement |
|---|---|---|---|
| Taux marginal IR 2025 | 38 % = barème **avant** LF 2025 ; **37 % après** (Note 736 p. 13, CGI 2025 art. 73-I) | CGI 2026 : 37 % (identique) | **Aucune contradiction — 37 % confirmé** |
| Réduction charges de famille | 500 DH × 6 (CGI 2025 art. 74, BO 7362, Note 736 p. 15) | — | **Aucune contradiction** |
| Taux AMO secteur privé | Décret 2-14-707 (BO 6314) : **4,52 % + 1,85 % = 6,37 %** | Moteur : **2,26 % + 4,11 % = 6,37 %** — aucun texte du corpus ne porte ces taux | **À ARBITRER** (totaux égaux, répartition différente) |
| Taux CNSS | Fiche CNSS (rang 6) : 6,40 / 1,57 / 11,89 + dahir 1-72-184 (2/3-1/3) | Décrets de taux et arrêtés de plafond absents du corpus | **Documenté (rang 6)** |
| Plafond CNSS 6 000 DH/mois | Fiche CNSS p. 2 ; dahir art. 19 (plafond fixé par décret) | Arrêté fixateur absent du corpus | **Documenté (rang 6)** |

---

## 4. Paramètres non trouvés / non prouvés

1. **Plafond « 30 000 DH » des frais professionnels (cas 35 %)** — NON PROUVÉ PAR LE CORPUS LOCAL (le texte CGI 2025 art. 59-I-A ne mentionne que le plafond 35 000 pour le cas 25 %). Sans impact arithmétique : 35 % × 78 000 = 27 300 < 30 000.
2. **Participation complémentaire AMO employeur** — NON PROUVÉ PAR LE CORPUS LOCAL (aucune mention ; seule la majoration 1,85 % du décret 2-14-707 est documentée).
3. **Montants mensuels de l'allocation familiale CNSS servie** (prestation, ex. DH/enfant/mois) — NON PROUVÉ PAR LE CORPUS LOCAL (non requis par le moteur : seule la cotisation 6,40 % est calculée).
4. **Décrets de taux CNSS (dont 2-91-718) et arrêtés de plafond 6 000 DH** — absents du corpus (taux prouvés par la fiche de synthèse, rang 6 de la hiérarchie).
5. **Décret d'habilitation 2-25-266 (24-04-2025)** — cité dans le préambule de l'arrêté 1314-25, texte absent du corpus.

---

## 5. Comparaison avec le moteur Compta MA (`app/core/rates_ma.py` — une seule inspection)

Moteur examiné : `BAREMES_PAIE[2025]` (ir_brackets = `IR_BRACKETS_2025`, frais_pro = `None`, deduction_famille = 500, max 6, cnss = `None`) ; `CNSS_2026` (jeu 2026) ; `IS_RATES_BY_YEAR[2025]` ; `COTISATION_MINIMALE_BY_YEAR[2025]` ; `compute_professional_expenses`, `compute_ir_annual/monthly`, `compute_cnss`, `compute_is`, `compute_cotisation_minimale`.

| Paramètre | Valeur officielle 2025 | Source + page | Valeur moteur | Écart | Statut |
|---|---|---|---|---|---|
| IR — barème (tranches, taux) | 0 % ≤ 40 000 ; 10 % ; 20 % ; 30 % ; 34 % ; **37 % > 180 000** | CGI 2025 art. 73-I p. 117 ; BO 7362 p. 2983 ; Note 736 p. 13 | `IR_BRACKETS_2025` : 6 tranches identiques (0/10/20/30/34/37) | Aucun | **CONFORME** |
| IR — sommes à déduire | 0 / 4 000 / 10 000 / 18 000 / 22 000 / 27 400 | Note 736 p. 13 | identiques | Aucun | **CONFORME** |
| IR — tranche exonérée / seuil annuel | 40 000 DH | Note 736 p. 13 | borne 40 000 | Aucun | **CONFORME** |
| IR — charge de famille | 500 DH/pers., plafond 3 000 (6 pers.) | CGI 2025 art. 74 p. 123 ; BO 7362 p. 2983 ; Note 736 p. 15 | 500 DH, max 6 | Aucun | **CONFORME** |
| Frais professionnels | 35 % (brut annuel ≤ 78 000) ; 25 % (> 78 000, plaf. 35 000) | CGI 2025 art. 59-I-A p. 95-96 | `BAREMES_PAIE[2025]["frais_professionnels"] = None` → `BaremeIndisponible` | Pas de calcul 2025 | **ABSENT DU MOTEUR** (Note : la config 2026 du moteur 35/25/78 000/35 000 est conforme) |
| Frais pro — plafond 30 000 (cas 35 %) | non visible dans le CGI 2025 | CGI 2025 art. 59-I-A | cap_below 30 000 (config 2026) | non prouvé (sans impact : 35 %×78 000 = 27 300) | **NON PROUVÉ PAR LE CORPUS LOCAL** |
| CNSS — taux salarié | 4,48 % (= 1/3 × 13,46 % ; 0,52 + 3,96) | fiche CNSS p. 2 ; dahir 1-72-184 art. 20 p. 10 | `BAREMES_PAIE[2025]["cnss"] = None` → refus paie 2025 | Pas de calcul 2025 | **ABSENT DU MOTEUR** (CNSS_2026 = 4,48 % ✓) |
| CNSS — taux employeur | 8,98 % (= 2/3 × 13,46 % ; 1,05 + 7,93) | idem | None (2025) | idem | **ABSENT DU MOTEUR** (CNSS_2026 = 8,98 % ✓) |
| CNSS — plafond | 6 000 DH/mois (prestations CT/LT seulement) | fiche CNSS p. 2 ; dahir art. 19 p. 10 | None (2025) | idem | **ABSENT DU MOTEUR** (CNSS_2026 ceiling = 6 000 ✓) |
| CNSS — prestations familiales | 6,40 % du salaire réel, employeur seul | fiche CNSS p. 2 ; dahir art. 20 p. 10 | None (2025) | idem | **ABSENT DU MOTEUR** (CNSS_2026 = 6,40 % ✓) |
| CNSS — assiette + arrêté 1314-25 | assiette = ensemble des rémunérations **sous exclusions 1314-25** (plafonds : déplacement 100 % base max 5 000 DH/mois ; mutation 10 DH/km ; représentation 10 % base ; licenciement ≤ 1 000 000 DH…) | dahir art. 19 p. 10 ; BO 7443 p. 7324-7326 ; BO 7464 p. 9245-9246 | base = brut imposable, aucune exclusion modélisée | mécanique des exclusions absente | **ÉCART** |
| CNSS — date d'effet 2025 | aucun changement de taux en 2025 ; arrêté 1314-25 publié le 29/09/2025 (effet = publication) | BO 7443 p. 7326 (art. 2) | n/a | assiette 2025 ≠ base moteur | **ÉCART** |
| AMO — taux salarié | 4,52 % des rémunérations (depuis 01/01/2016) | BO 6314 p. 4770-4771 (décret 2-14-707) | None (2025) ; CNSS_2026 = 2,26 % | répartition divergente (total égal 6,37 %) | **À ARBITRER** |
| AMO — taux employeur (majoration) | 1,85 % | idem | None (2025) ; CNSS_2026 = 4,11 % | idem | **À ARBITRER** |
| AMO — participation complémentaire employeur | aucune au-delà de la majoration 1,85 % dans le corpus | idem | n/a | non documenté | **NON PROUVÉ PAR LE CORPUS LOCAL** (absence constatée) |
| AMO — assiette / plafond | ensemble des rémunérations, sans plafond | dahir art. 19 ; décret 2-14-707 | AMO calculée sur le brut sans plafond (structure 2026) | Aucun (structure) | **CONFORME** (structure ; 2025 absent) |
| TFP — taux | 1,6 % | décret 2-73-633 art. 3 p. 72 | None (2025) | Pas de calcul 2025 | **ABSENT DU MOTEUR** (CNSS_2026 = 1,60 % ✓) |
| TFP — redevable | exclusivement l'employeur | art. 5 p. 72 | employeur (2026) | Aucun | **CONFORME** |
| TFP — assiette | rémunération brute mensuelle (primes, indemnités, avantages…) | art. 4 p. 72 | brut (2026) | Aucun | **CONFORME** |
| IS — BNF ≤ 300 000 (2025) | 17,50 % | CGI 2025 art. 247-XXXVII-A p. 470 | 17,5 % (`small_profit`, seuil 300 000) | Aucun | **CONFORME** |
| IS — droit commun 300 001 → < 100 M | 20 % | idem p. 471 | 20 % | Aucun | **CONFORME** |
| IS — BNF ≥ 100 M (2025) | **31,25 %** | idem p. 471 | 35 % (taux 2026 !) | **+3,75 pts** ; frontière : CGI « ≥ 100 M », moteur « > 100 M » | **ÉCART** |
| IS — établissements de crédit / assurances | **39,25 %** | idem p. 471-472 | 40 % | **+0,75 pt** | **ÉCART** |
| IS — CFC / ZAI | **18,75 %** | idem p. 472 | 20 % | **+1,25 pt** | **ÉCART** |
| Cotisation minimale — taux / plancher | 0,25 % ; plancher 3 000 DH | CGI 2025 art. 144-I-D p. 264-265 | 0,25 % ; min 3 000 | Aucun | **CONFORME** |
| Cotisation minimale — exonération | 36 premiers mois d'exploitation (sociétés) | CGI 2025 art. 144-I-C-1° p. 264 | exemption_months = 36 | Aucun | **CONFORME** |
| Cotisation minimale — base | produits **hors TVA** (CA + produits financiers + subventions/dons) | CGI 2025 art. 144-I-B p. 263 | paramétré « CA TTC » (`ca_ttc`) | base TTC vs HT | **ÉCART** (à confirmer côté appelant) |
| Exonération nouveaux recrutements (art. 57-20°) | 36 premiers mois à compter du premier recrutement | CGI 2025 art. 57-20° (disp. transitoires) | gérée (DTS « 9421 », profil exonéré) | Aucun | **CONFORME** |

**Synthèse des statuts (27 lignes)** : CONFORME = 11 · ÉCART = 6 · ABSENT DU MOTEUR = 6 · À ARBITRER = 2 · NON PROUVÉ PAR LE CORPUS LOCAL = 2.

---

## 6. Écarts moteur (récapitulatif)

1. **Paie 2025 bloquée** : `BAREMES_PAIE[2025]["frais_professionnels"] = None` et `["cnss"] = None` → tout calcul de bulletin 2025 lève `BaremeIndisponible`. Le référentiel 2025 étant désormais documenté (frais pro = art. 59 CGI, CNSS = 4,48/8,98/6,40 % + plafond 6 000), la correction du moteur devra **alimenter `BAREMES_PAIE[2025]`** (les valeurs CNSS 2025 = valeurs 2026 déjà en place : aucune inversion de taux, plafond 6 000 identique).
2. **Assiette CNSS 2025** : l'arrêté 1314-25 (BO 7443 du 29/09/2025 + erratum BO 7464) introduit des **exclusions d'assiette plafonnées** que le moteur ne modélise pas (base = brut imposable). À intégrer dans la mécanique `base_cnss` (ou documenter une assiette simplifiée pour le périmètre du scénario).
3. **AMO — répartition** : moteur 2,26 %/4,11 % vs décret 2-14-707 (BO 6314) 4,52 %/1,85 % ; total 6,37 % identique. À arbitrer avant correction (impact direct net à payer / coût employeur).
4. **IS 2025 — taux majorés/sectoriels erronés** : grandes entreprises 35 % au lieu de **31,25 %** ; banques/assurances 40 % au lieu de **39,25 %** ; CFC/ZAI 20 % au lieu de **18,75 %** (le moteur applique la grille 2026 à l'exercice 2025). Seuil grandes entreprises : « ≥ 100 M » (CGI) vs « > 100 M » (moteur).
5. **CM — base** : le moteur calcule sur un « CA TTC » ; le CGI 2025 assied la CM sur les **produits hors TVA** (art. 144-I-B). À vérifier côté appelant avant correction.
6. **Non prouvés (sans blocage calcul)** : plafond FP 30 000 (cas 35 %, sans impact arithmétique) ; participation complémentaire AMO (aucune mention).

---

## 7. Impact potentiel sur la simulation V4

- La simulation P1B V4 (14 409,71 DH/mois, indicatif) a été calculée avec le **jeu 2026** parce que le référentiel 2025 était « à fournir ». Désormais :
  - **Frais professionnels 2025 (art. 59) et CNSS/AMO/TFP 2025** sont **identiques aux valeurs 2026** déjà utilisées (35/25 % – 78 000 ; 4,48/8,98/6,40/1,60 % ; plafond 6 000) → **l'IR 2025 et le net à payer 2025 seraient proches** du résultat V4 (seule différence structurelle : déduction familiale 500 vs 600 → IR 2025 légèrement supérieur à l'IR du jeu 2026 pour les salariés avec personnes à charge).
  - **AMO** : si l'arbitrage retient le corpus (4,52 % salarié + 1,85 % employeur), le **net à payer** diminuerait d'environ **2,26 points de brut** et le **coût employeur** d'environ **2,26 points** par rapport au jeu 2026 (total 6,37 % inchangé).
  - **Assiette CNSS** : l'application des exclusions 1314-25 (à compter du 29/09/2025) réduirait les cotisations sur les indemnités concernées (déplacement ≤ 5 000 DH/mois ; représentation ≤ 10 % du salaire de base…).
  - **IS 2025** : scénario BNF ≤ 300 000 DH → 17,5 % inchangé ; aucun impact IS si le scénario V4 reste dans cette tranche. Impact seulement si BNF > 100 M (31,25 % vs 35 %) ou banques/CFC.
  - **CM 2025** : 0,25 % / 3 000 / exonération 36 mois inchangés ; base HT à vérifier.
- **Conclusion V4** : le résultat V4 reste **indicatif** ; une simulation 2025 propre devra être rejouée avec le référentiel ci-dessus **après** correction du moteur (hors périmètre de cette tâche).

---

## 8. Preuve DB (avant / après — identiques)

| Mesure | Avant | Après |
|---|---|---|
| SHA-256 `compta_ma.db` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` |
| Taille | 1 163 264 o | 1 163 264 o |
| Date de modification | 2026-09-24 02:55:05 | 2026-09-24 02:55:05 |

Aucune modification du moteur, de la DB, des paramètres ni des PDF sources. Le dossier `Documentation` n'a reçu aucune écriture.

---

## 9. Verdict

> **RÉFÉRENTIEL 2025 SUFFISAMMENT DOCUMENTÉ POUR PRÉPARER LA CORRECTION DU MOTEUR**

Réserves avant la correction elle-même (sans bloquer sa préparation) :
1. **AMO à arbitrer** (répartition 4,52 %/1,85 % du décret 2-14-707 du corpus vs 2,26 %/4,11 % du moteur ; total 6,37 % identique) — aucun texte du corpus ne porte 2,26/4,11 ;
2. **CNSS documentée au rang 6** (fiche de synthèse + dahir 1-72-184) : les décrets de taux (2-91-718) et l'arrêté de plafond 6 000 DH ne sont pas dans le corpus — à confirmer par l'expert avant gel définitif ;
3. **Assiette CNSS 2025** : exclusions de l'arrêté 1314-25 à intégrer (détail côté simulation, pas côté taux).

Ce verdict **n'autorise pas** Stage 3 ni aucune réouverture/recalcul 2025.