# P1B V7A — ARBITRAGE FINAL AMO + CM 2025 (READ-ONLY)

**Projet** : Compta MA — `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Dossier documentaire (lecture seule)** : `C:\Users\Belyazid\Desktop\compt\Documentation`
**Python** : `.venv\Scripts\python.exe` du projet (3.13.9) — seul ven utilisé
**Date** : 06/10/2026 — **Mode** : read-only absolu (aucune modification du moteur, de la DB, des paramètres, des référentiels)
**Référence** : complète P1B V6 (`P1B_REFERENTIELS_PAIE_2025_V6_LOCAL.md`) ; ne réaudite ni IR, ni frais professionnels, ni CNSS/PF/TFP, ni IS général, ni paie complète (hors périmètre V7A).

---

## 0. Garde-fou obligatoire (avéré)

| Élément | État |
|---|---|
| cwd exact = `compta_ma` | OK |
| `compta_ma.db` existe | OK |
| `app/` existe | OK |
| `.venv\Scripts\python.exe` existe | OK |
| Utilisation exclusive du venv Compta MA | OK |

---

## 1. Arbitrage AMO 2025

### 1.1 Divergence V6 à clarifier

| Source | Part salariale | Part patronale | Total |
|---|---|---|---|
| Texte réglementaire du corpus (décret 2-14-707, BO 6314) | 4,52 % | 1,85 % | 6,37 % |
| Moteur actuel (jeu `CNSS_2026` : 2,26 % / 4,11 %) | 2,26 % | 4,11 % | 6,37 % |

**Ne pas conclure sur le seul total** : il faut déterminer qui supporte quelle quote-part en 2025 et sur quelle base (fait ci-après).

### 1.2 Textes lus (3 sources AMO uniquement, pages nécessaires)

| # | Document | Pages lues | Rôle |
|---|---|---|---|
| 1 | `04_AMO\loi-65-00.pdf` (loi 65-00, 2002) | art. 45-48 (p. 21-22), art. 106-108 (p. 41), art. 101 (p. 40) | Base légale : taux fixé par décret (art. 48) ; assiette secteur privé = ensemble des rémunérations (art. 106-2°) ; employeur débiteur du versement (art. 108) |
| 2 | `04_AMO\2.05.734.pdf` (décret 2-05-734 du 18/07/2005, 1 page, arabe) | p. 1 | Extraction partiellement exploitable : article 1er, cotisation à la charge de l'« أجير » (salarié) sur le salaire mensuel brut total (« مجموع الأجر الشهري الإجمالي ») |
| 3 | `04_AMO\ma-bulletin-officiel-dated-2014-12-04-no-6314.pdf` (BO 6314 du 04/12/2014) | p. 4770-4771 (PDF p. 19) | Décret n° 2-14-707 du 10/11/2014 **modifiant** le décret 2-05-734 : taux AMO secteur privé + date d'effet (PDF p. 18-19) |

### 1.3 Tableau d'arbitrage AMO 2025

| Composante | Taux | Salarié | Employeur | Assiette | Source + page | Statut |
|---|---|---|---|---|---|---|
| Taux de cotisation AMO — salariés du secteur privé | **4,52 %** | **OUI** (« à la charge du salarié », lisible à l'OCR) | — | L'ensemble des rémunérations | Décret 2-14-707 art. 1er, BO 6314 p. 4770 (PDF p. 19) | **CONFIRMÉ** |
| Majoration — part patronale | **1,85 %** | — | **OUI** (déduit : structure « majoré » + total 6,37 % ; libellé OCR « à la charge de l'employeur » non restitué) | L'ensemble de la rémunération brute | Décret 2-14-707 art. 1er, BO 6314 p. 4770 (PDF p. 19) | **CONFIRMÉ** (attribution par déduction ; OCR dégradée — point déclaré) |
| Total théorique | **6,37 %** | 4,52 % | 1,85 % | Rémunération brute | Décret 2-14-707 art. 1er | **CONFIRMÉ** |
| Assiette | — | — | — | Salariés secteur privé : « l'ensemble des rémunérations visées à l'article 19 du dahir portant loi n° 1-72-184 » (rémunération brute, sans plafond) | Loi 65-00 art. 106-2° (p. 41) ; décret 2-14-707 art. 1er (BO 6314 p. 4770) | **CONFIRMÉ** |
| Plafond | — | — | — | **Aucun** (silence des textes : « l'ensemble des rémunérations » sans plafond) | Loi 65-00 art. 106-2° ; décret 2-14-707 art. 1er | **CONFIRMÉ** (absence de plafond) |
| Bénéficiaire / redevable | — | Cotisation fixée par décret ; employeur **débiteur** du versement de la totalité auprès de l'organisme gestionnaire | — | Loi 65-00 art. 48, 107, 108 (p. 22, 41) | **CONFIRMÉ** |
| Date d'effet du texte applicable | 01/01/2016 (« entrera en vigueur à compter du 1er janvier 2016 ») | — | — | Décret 2-14-707 art. 2, BO 6314 p. 4771 (PDF p. 19) | **CONFIRMÉ** |
| Jeu 2,26 % / 4,11 % employé par le moteur | 2,26 % salarié / 4,11 % employeur | — | — | **Aucun texte du corpus ne porte ce jeu pour le secteur privé** | Corpus AMO complet (3 sources) | **NON PROUVÉ** (par le corpus) |

### 1.4 Conclusion AMO

> **AMO ARBITRÉ (corpus) — année 2025 : 4,52 % à la charge du salarié + 1,85 % (majoration) à la charge de l'employeur, total 6,37 %, assiette = rémunération brute (ensemble des rémunérations), sans plafond, date d'effet du texte : 01/01/2016.**

- Le seul jeu de taux « secteur privé » du corpus est celui du décret 2-14-707 (4,52 / 1,85), en vigueur depuis le 01/01/2016 et non modifié par un texte du corpus ;
- Le jeu 2,26 / 4,11 du moteur correspond à la grille « secteur public » (décret 2-05-734, 2005) reprise par la grille CNSS unifiée post-généralisation (à compter du 01/12/2022) ; **aucun de ces éléments n'est dans le corpus** ;
- **Point déclaré NON PROUVÉ par le corpus** (sans boucle) : l'existence d'un texte postérieur au 2-14-707 modifiant la répartition pour 2025 (généralisation AMO, grille CNSS unifiée). Le corpus ne peut ni la confirmer ni l'infirmer → **à confirmer par l'expert-comptable avant gel** ; non bloquant pour V7B, la correction devant **paramétrer explicitement** la répartition 2025.

### 1.5 Comparaison AMO avec le moteur actuel

| Élément | Moteur actuel | Référence 2025 (corpus) | Conformité |
|---|---|---|---|
| Part salariale | 2,26 % — `CNSS_2026["employee_amo"]` (`app/core/rates_ma.py:202`) appliqué dans `app/services/payroll.py:429` | 4,52 % (décret 2-14-707 art. 1er) | **ÉCART** |
| Part patronale | 4,11 % — `CNSS_2026["employer_amo"]` (`rates_ma.py:203` ; `payroll.py:511,517`) | 1,85 % (majoration, même article) | **ÉCART** |
| Total | 6,37 % | 6,37 % | Conforme (mais insuffisant : la répartition diffère) |
| Assiette | Salaire brut, **sans plafond** (`rates_ma.py:486,488` : `employee_amo = brut × 2,26 %`, `employer_amo = brut × 4,11 %`) | Ensemble des rémunérations, sans plafond | **CONFORME** |
| Plancher | Aucun | Aucun | **CONFORME** |

## 2. Arbitrage cotisation minimale (CM) 2025

### 2.1 Tableau d'arbitrage CM

| Élément | Référence 2025 | Implémentation actuelle | Conforme / Écart | Justification |
|---|---|---|---|---|
| Taux | **0,25 %** — CGI 2025 art. 144-I-D (p. 264) ; 0,15 % réservé pétrole/gaz/huile/sucre/farine/eau/électricité/médicaments (hors scénario) | `COTISATION_MINIMALE_2025["rate"] = 0,0025` (`rates_ma.py:254`) | **CONFORME** | Valeur identique |
| Minimum | **3 000 DH** pour l'IS ; 1 500 DH pour l'IR — CGI 2025 art. 144-I-D (p. 265) | `COTISATION_MINIMALE_2025["minimum"] = 3000` (`rates_ma.py:255`) ; `max(cm, 3000)` (`rates_ma.py:584-585`) | **CONFORME** | Valeur identique |
| Assiette — nature | Montant **« hors taxe sur la valeur ajoutée »** des produits — CGI 2025 art. 144-I-B (p. 263) | `chiffre_affaires()` calcule un **CA TTC** = CA HT (comptes 71x) **+ TVA collectée (4455)** (`fiscal_liasse.py:194-217`) ; `calculer_is` appelle `compute_cotisation_minimale(chiffre_affaires_ttc, …)` (`fiscal_liasse.py:435-437`) | **ÉCART DÉMONTRÉ** | Le moteur **inclut la TVA** dans l'assiette ; la loi l'**exclut explicitement** |
| Assiette — contenu | CA + autres produits d'exploitation (art. 9-I-A-1°, 5°) + produits financiers (art. 9-I-B-1°-3°) + subventions et dons (art. 9-I-A-4°, art. 9-I-C-2°, 4°) — art. 144-I-B | Uniquement les comptes de racine `71` + TVA `4455` (`fiscal_liasse.py:54-55, 206-209`) | **ÉCART** | Produits financiers (76x), subventions/dons (74x/77x), autres produits d'exploitation (75x) **non remontés** dans la base |
| Exonération | **36 premiers mois** suivant le début d'exploitation, **cessant à l'expiration des 60 premiers mois suivant la constitution** (sociétés non concessionnaires) — CGI 2025 art. 144-I-C-1° (p. 264) | `exemption_months = 36` sur les mois d'activité depuis la date de début d'activité (`rates_ma.py:256, 582-583` ; `fiscal_liasse.py:312-373`) | **ÉCART (partiel)** | 36 mois bien implémentés ; **butée 60 mois depuis la constitution absente** |
| Référence d'exercice | CGI édition 2025 applicable à l'exercice 2025 | `COTISATION_MINIMALE_BY_YEAR[2025]` paramétré (`rates_ma.py:258-261`) | **CONFORME** | Historisation par exercice respectée |
| LF 2025 (loi n° 60-24, BO 7362) / Note 736 | **Aucune modification de l'art. 144** (CM IS) par la LF 2025 | — | **CONFORME** | BO 7362 : aucun hit « cotisation minimale » / « 0,25 » ; p. 43 = délai d'exonération TVA 36 mois sociétés foncières/OPCI (hors CM). Note 736 p. 37 = exemple CM 3 % Profit foncier (personnes physiques) ; p. 54 = exonération CM liée à l'exonération IS « FIFA » — hors scénario |

### 2.2 Référence fiscale 2025 (passages nécessaires)

| Référence | Passage | Page |
|---|---|---|
| CGI 2025, art. 144-I-B | « La base de calcul de la cotisation minimale est constituée par le montant, **hors taxe sur la valeur ajoutée**, des produits suivants : … » (CA, autres produits d'exploitation, produits financiers, subventions et dons) | p. 263 |
| CGI 2025, art. 144-I-C-1° | Exonération 36 premiers mois du début d'exploitation ; **cesse à l'expiration des 60 premiers mois suivant la date de constitution** | p. 264 |
| CGI 2025, art. 144-I-D | Taux **0,25 %** (0,15 % produits énergétiques/de base) ; minimum **3 000 DH** (IS) / 1 500 DH (IR) | p. 264-265 |
| CGI 2025, art. 9-I | Composition des produits imposables (A-1°/4°/5°, B-1°/2°/3°, C-2°/4°) | p. 29 |
| LF 2025 (BO 7362) + Note 736 | Aucune évolution de la CM IS 2025 (vérifié ciblé) | passim |

### 2.3 Inspection de l'implémentation CM actuelle (une seule passe)

1. `app/core/rates_ma.py:557-585` — `compute_cotisation_minimale(ca_ttc, months_of_activity=12, *, annee)` : `cm = ca_ttc × rate (0,25 %)` ; `max(cm, minimum 3000)` ; `0` si `months_of_activity <= 36`. La variable d'entrée est **réellement interprétée comme une base TTC** (nom, docstring « 0,25 % du CA TTC », et appelant).
2. `app/services/fiscal_liasse.py:194-217` — `chiffre_affaires()` : `ca_ht` = somme des soldes créditeurs inversés des comptes `71x` ; `tva_collectee` = solde du compte `4455` ; retourne `chiffre_affaires_ttc = ca_ht + tva`.
3. `app/services/fiscal_liasse.py:430-437` — `calculer_is()` : `cotisation_minimale = compute_cotisation_minimale(affaires["chiffre_affaires_ttc"], months_of_activity=mois, annee=annee)`.

**Verdict de l'inspection** :
- le moteur calcule sur **CA TTC** (HT + TVA), pas sur le montant **hors TVA** exigé par l'art. 144-I-B ;
- l'intitulé « CA TTC » n'est **pas seulement un mauvais libellé** : le **calcul est réellement faux** par rapport à la règle 2025 (base surévaluée de la TVA incluse et incomplète en contenu) ;
- le plancher 3 000 DH, le taux 0,25 % et l'exonération 36 mois sont conformes ; la butée 60 mois (constitution) fait défaut.

## 3. Écarts réellement démontrés

| Réf | Écart | Preuve |
|---|---|---|
| AMO-1 | Répartition AMO secteur privé : moteur 2,26 % / 4,11 % au lieu de **4,52 % salarié / 1,85 % employeur** (total 6,37 % inchangé) | Décret 2-14-707 art. 1er, BO 6314 p. 4770 (PDF p. 19) ; moteur `rates_ma.py:202-203` |
| AMO-2 | Le jeu 2,26 / 4,11 n'est porté par **aucun texte du corpus** | Corpus AMO complet (3 sources) — déclaré **NON PROUVÉ** |
| CM-1 | Base de la CM : **TTC** (CA HT + TVA 4455) au lieu du montant **hors TVA** | CGI 2025 art. 144-I-B (p. 263) vs `fiscal_liasse.py:194-217, 435-437` |
| CM-2 | Contenu d'assiette incomplet : produits financiers (76x), subventions/dons (74x/77x), autres produits d'exploitation (75x) absents | art. 144-I-B + art. 9-I vs `fiscal_liasse.py:54-55, 206-209` |
| CM-3 | Exonération : butée « 60 premiers mois suivant la constitution » non implémentée | art. 144-I-C-1° (p. 264) vs `rates_ma.py:256, 582-583` |
| CM-4 | Documentation du moteur « 0,25 % du CA TTC » (docstrings et journal des taux) erronée au regard de la règle 2025 | `rates_ma.py:293, 383, 563` ; `fiscal_liasse.py:55, 195-199` |

**Points déclarés non résolus par le corpus local (sans boucle)** :
- existence d'un texte postérieur au décret 2-14-707 (généralisation AMO à compter du 01/12/2022, grille CNSS unifiée) modifiant la répartition AMO pour 2025 — **absent du corpus** ;
- libellé exact « à la charge de l'employeur » de la majoration 1,85 % — non restitué par l'OCR du BO 6314 (attribution déduite de la structure « majoré » et du total 6,37 %).

---

## 4. Conclusion

> **AMO ARBITRÉ** — 2025 : 4,52 % salarié + 1,85 % employeur (total 6,37 %), assiette = rémunération brute sans plafond, effet 01/01/2016 (décret 2-14-707, BO 6314 p. 4770-4771). Réserve hors corpus : généralisation AMO 2022 (à confirmer par l'expert ; non bloquante pour V7B).
>
> **CM ARBITRÉ** — 2025 : taux 0,25 %, plancher 3 000 DH, base **hors TVA** (CA + autres produits d'exploitation + produits financiers + subventions/dons), exonération 36 mois limitée à 60 mois depuis constitution (CGI 2025 art. 144 p. 263-265). LF 2025 sans impact.

> ## VERDICT GLOBAL : **PRÊT POUR P1B V7B — CORRECTION DU MOTEUR**

---

## 5. Preuve DB (avant / après — identiques)

| Mesure | Avant | Après |
|---|---|---|
| SHA-256 `compta_ma.db` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` |
| Taille | 1 163 264 o | 1 163 264 o |
| Date de modification | 2026-09-24 02:55:05 | 2026-09-24 02:55:05 |

Aucune modification du moteur, de la DB, des paramètres AMO/CM, des référentiels, des migrations ni de `Documentation`. Une seule passe documentaire (AMO : 3 sources ; CM : 3 sources) ; une seule inspection du code CM ; aucun Web Fetch ; aucun Stage 3.

## 6. Sources consultées

| Volet | Documents |
|---|---|
| **AMO (3/3)** | `04_AMO\loi-65-00.pdf` ; `04_AMO\2.05.734.pdf` ; `04_AMO\ma-bulletin-officiel-dated-2014-12-04-no-6314.pdf` |
| **CM (3/3)** | `02_Fiscalite\cgi-2025-fr.pdf` ; `02_Fiscalite\BO_7362_fr.pdf` ; `02_Fiscalite\Note-Circulaire-n°-736…LF-2025.pdf` |
| Comparaison seule | `02_Fiscalite\cgi-2026-maroc.pdf` (écarté : faux positif de mots-clés, aucun impact AMO/CM) |



