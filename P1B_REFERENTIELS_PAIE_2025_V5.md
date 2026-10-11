# P1B V5 — Validation documentaire des référentiels paie 2025 — Compta MA

**Projet** : `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Phase** : P1B V5 — LECTURE SEULE. Aucune modification base / code / paramètres / paie. Stage 3 non lancé.
**Interpréteur** : `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma\.venv\Scripts\python.exe` (exclusif).
**Rapport** : rédaction unique en fin de phase. Aucun recalcul global de la paie ; IS/CM non refaits (paramètres déjà utilisés en P1B V4, vérifiés ponctuellement).

---

## 0. Preuve READ-ONLY — compta_ma.db

| Grandeur | Avant | Après |
|---|---|---|
| SHA-256 | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` (identique) |
| Taille | 1 163 264 octets | 1 163 264 octets (identique) |
| Dernière modification | 2026-09-24 02:55:05 | 2026-09-24 02:55:05 (identique) |

Inventaire de contrôle (SQLite **read-only** `mode=ro`, interpréteur du `.venv`) : `employees` = 3 (profils test EMP001-003) · `pay_contracts` = 6 · `payroll_runs` = 12 (2026-01 → 2026-12, tous « payé ») · `payslips` = 36 (2026) · `payslip_lines` = 144 (2026) → **0 cycle / 0 bulletin 2025** ; cohérent avec P1B V4.

---

## 1. Tableau complet des paramètres 2025

Statuts (Section 4 du mandat) : **CONFIRMÉ** = preuve officielle accessible et lue ; **À CONFIRMER** = valeur documentée mais non vérifiable en ligne par cet audit ; **ABSENT** = paramètre manquant dans le moteur pour 2025 ; **NON APPLICABLE** = non utilisé par le moteur.

| # | Paramètre | Valeur 2025 (référence) | Base / unité | Plafond éventuel | Date d'effet | Source | Statut |
|---|---|---|---|---|---|---|---|
| 1 | Barème IR (retenue à la source) | 0 % jusqu'à 40 000 ; 10 % (40k–60k, SAD 4 000) ; 20 % (60k–80k, SAD 10 000) ; 30 % (80k–100k, SAD 18 000) ; 34 % (100k–180k, SAD 22 000) ; tranche supérieure : **37 % (SAD 27 400) dans le moteur vs 38 % (SAD 29 200) tel que publié usuellement — non arbitré** | Revenu net imposable annuel (MAD) | Tranche haute ouverte | 01/01/2025 (barème non modifié par la LF 2025) | CGI art. 73-I ; DGI (guide IR) — **portail DGI inaccessible (HTTP 405)** | **À CONFIRMER** |
| 2 | Déduction pour charges de famille | 500 DH / personne à charge, 6 max (3 000 DH/an) | Réduction de l'IR annuel dû | 6 personnes | 01/01/2025 (LF 2025 : 360 → 500 DH) | CGI art. 74 modifié par LF n° 60-24 pour 2025 (documenté dans le projet) — source officielle en ligne inaccessible | **À CONFIRMER** |
| 3 | Frais professionnels | 35 % plafonné 30 000 DH/an si brut ≤ 78 000 DH ; 25 % plafonné 35 000 DH/an au-delà | Brut imposable annuel | 30 000 / 35 000 DH/an | 01/01/2025 (non modifié par la LF 2025) | CGI art. 59 (édition 2025) — source officielle inaccessible | **ABSENT** (moteur : `None` pour 2025 → paie refusée) |
| 4 | CNSS salarié (prestations sociales) | 4,48 % | Salaire brut plafonné | Plafond CNSS | 2025 (structure stable depuis 01/01/2023) | Régime général CNSS — texte consolidé CNSS (taux non extractibles : page dynamique) | **ABSENT** (moteur : `None`) |
| 5 | CNSS employeur (prestations sociales) | 8,98 % | Salaire brut plafonné | Plafond CNSS | idem | idem | **ABSENT** (moteur : `None`) |
| 6 | Plafond CNSS | 6 000 DH/mois (72 000 DH/an) | Salaire brut mensuel | 6 000 DH/mois | Inchangé depuis 01/07/2011 (décret 2-10-517) | CNSS / textes CNSS — à confirmer | **ABSENT** (moteur : plafond 2025 non rattaché ; présent seulement via `CNSS_2026`) |
| 7 | AMO salarié | 2,26 % | Salaire brut (sans plafond) | Sans plafond | 2025 (depuis 01/01/2023) | Loi 65-00 / loi 62-22 — détail non extractible | **ABSENT** (moteur : `None`) |
| 8 | AMO employeur | 4,11 % | Salaire brut (sans plafond) | Sans plafond | idem | idem | **ABSENT** (moteur : `None`) |
| 9 | Prestations familiales (employeur) | 6,40 % | Salaire brut | Sans plafond | 2025 | Régime prestations familiales CNSS | **ABSENT** (moteur : `None`) |
| 10 | TFP (employeur) | 1,60 % | Salaire brut | Sans plafond | 2025 | Taxe de formation professionnelle | **ABSENT** (moteur : `None`) |
| 11 | IS 2025 (utilisé en V4) | Grille transitoire : 17,5 % si BNF ≤ 300 000 ; 20 % (< 100 M) ; 35 % (> 100 M) ; 40 % banques/assurances/BAM/CDG ; 20 % CFC/ZAI | Bénéfice net fiscal | Seuil taux réduit : 300 000 DH | Exercice 2025 | LF convergence 2023–2025, CGI art. 19-IX — documenté (à confirmer) en V4 | **À CONFIRMER** |
| 12 | Cotisation minimale (utilisée en V4) | 0,25 % du CA TTC ; plancher 3 000 DH ; exonération 36 premiers mois | CA TTC | Plancher 3 000 DH/an | Exercice 2025 | CGI art. 144 / art. 20 — documenté (à confirmer) en V4 | **À CONFIRMER** |
| 13 | SMIG / SMAG | Non utilisé par le moteur | — | — | — | — | **NON APPLICABLE** |
| 14 | Retraite complémentaire / mutuelle / assurance groupe | Taux contractuels par salarié (pas un paramètre réglementaire 2025) | Selon contrat | Selon contrat | Selon contrat | Contrats de travail | **NON APPLICABLE** |
| 15 | Assiette de cotisations sociales (éléments exonérés et leurs plafonds) | Clarifiée par l'arrêté n° 1314-25, applicable au 01/10/2025 (communiqué CNSS consulté) | Salaires bruts versés | Selon arrêté | 01/10/2025 | cnss.ma (communiqué du 16/10/2025) | **ABSENT** (moteur : assiette = brut intégral, aucune exclusion modélisée) |
| 16 | Allocations familiales versées (prestation) | 300 DH × 3 premiers enfants + 100 DH × 3 suivants (prestation, pas une cotisation du moteur) | Prestation CNSS | 6 enfants | 2025 | cnss.ma — FAQ officielle consultée | **NON APPLICABLE** |

**Synthèse §1** : CONFIRMÉ = **0** · À CONFIRMER = **4** · ABSENT (moteur) = **9** · NON APPLICABLE = **3**.

---

## 2. Sources officielles utilisées

| Source | URL | Résultat obtenu |
|---|---|---|
| CNSS — taux et plafonds des cotisations | https://www.cnss.ma/fr/taux-et-plafonds-des-cotisations | Page accessible (HTTP 200) mais tableau des taux rendu dynamiquement (JS) → taux **non extractibles** par cet audit |
| CNSS — espace employeur | https://www.cnss.ma/fr/employeur | Communiqué officiel « assiette de cotisations sociales à compter du 1er octobre 2025 » (arrêté n° 1314-25) → **fait établi** (paramètre n° 15) |
| CNSS — réglementation | https://www.cnss.ma/fr/reglementation | Référence à « Recueil des textes juridiques consolidés relatifs au régime de sécurité sociale (07/01/2026) », loi 65-00, loi 27-22 → existence des textes confirmée, détail non extractible |
| CNSS — FAQ | https://www.cnss.ma/fr/faq | Allocations familiales versées : 300 DH (3 premiers enfants) + 100 DH (3 suivants) → **fait établi** (paramètre n° 16) |
| CNSS — publications | https://www.cnss.ma/fr/publications | Rapport annuel 2025 et rapports statistiques AMO/CNSS 2025 référencés (PDF officiels existants) |
| Ministère de l'Économie et des Finances | https://www.finances.gov.ma (/fr) | Magazine officiel « Al Maliya — Spécial Loi de Finances 2025 » (n° 23, 30/04/2025) référencé ; publications LF 2025 présentes sur le site |
| Portail légal du Ministère de la Justice | https://adala.justice.gov.ma | Portail officiel des textes légaux accessible ; aucun texte CGI/LF 2025 ouvert faute de chemin stable |

Aucun taux/plafond/barème chiffré n'a donc pu être **lu en détail** dans une page officielle au cours de cet audit (dynamisation JS + blocages techniques § 3) — conséquence directe sur le statut (§ 5/6).

## 3. Sources officielles inaccessibles

| Source | URL tentée | Erreur |
|---|---|---|
| DGI — Impôt sur le revenu | https://www.tax.gov.ma/wps/portal/DGI/Impots/IR | **HTTP 405** |
| DGI — portail | https://www.tax.gov.ma/wps/portal/DGI/home | **HTTP 405** → SOURCE OFFICIELLE INACCESSIBLE |
| SGG — Bulletin Officiel / textes légaux | http://www.sgg.gov.ma | Placeholder « IIS Windows Server » (701 octets) → SOURCE OFFICIELLE INACCESSIBLE |
| finances.gov.ma — note de présentation LF 2025 (chemin deviné) | https://www.finances.gov.ma/Publication/dep/2024/Note-de-presentation-du-projet-de-loi-de-finances-2025.pdf | **HTTP 404** |
| Maroc.ma — dossier LF 2025 | https://www.maroc.ma/fr/dossiers/loi-de-finances-2025 | **HTTP 404** |
| Moteurs de recherche (Bing, DuckDuckGo) | — | Résultats hors sujet / CAPTCHA — aucune localisation de document officiel supplémentaire |

## 4. Comparaison avec le moteur (une seule inspection)

| Paramètre | Référence 2025 | Valeur moteur actuelle (`app/core/rates_ma.py`) | Écart |
|---|---|---|---|
| Barème IR | 6 tranches (0/10/20/30/34/38 % — à confirmer) | `IR_BRACKETS_2025` : 6 tranches (0/10/20/30/34/**37 %**, SAD 27 400) | Divergence tranche haute : 37 % vs 38 % (à arbitrer) |
| Déduction charges de famille | 500 DH × 6 max (à confirmer) | `IR_FAMILY_DEDUCTION_BY_YEAR[2025] = 500` ; max 6 | Aucun si 500 confirmé |
| Frais professionnels | art. 59 : 35 % plaf. 30 000 (brut ≤ 78 000), 25 % plaf. 35 000 (à confirmer) | `BAREMES_PAIE[2025]["frais_professionnels"] = None` → `BaremeIndisponible` | **ABSENT** — calcul refusé |
| CNSS salarié / employeur | 4,48 % / 8,98 % (à confirmer) | `BAREMES_PAIE[2025]["cnss"] = None` → refus | **ABSENT** |
| Plafond CNSS | 6 000 DH/mois (à confirmer) | 2025 : non rattaché (seul `CNSS_2026["ceiling_social"] = 6000`) | **ABSENT** pour 2025 |
| AMO salarié / employeur | 2,26 % / 4,11 % (à confirmer) | idem (`None` 2025) | **ABSENT** |
| Prestations familiales / TFP | 6,40 % / 1,60 % (à confirmer) | idem (`None` 2025) | **ABSENT** |
| Assiette de cotisations (arrêté 1314-25) | exclusions à compter du 01/10/2025 | Assiette = brut intégral (aucune exclusion) | Non modélisée |
| IS 2025 | grille transitoire (à confirmer) | `IS_RATES_BY_YEAR[2025]` complet (17,5 % ≤ 300 000 ; 20/35/40/CFC 20 %) | Aucun (déjà utilisé en V4) |
| CM 2025 | 0,25 % · plancher 3 000 · exo 36 mois (à confirmer) | `COTISATION_MINIMALE_BY_YEAR[2025]` complet | Aucun (déjà utilisé en V4) |

Vérifications moteur effectuées (read-only, `.venv`) : `parametres_paie_manquants(2025)` = [« frais professionnels (CGI art. 59, version de l'exercice) », « CNSS / AMO (taux et plafonds de l'exercice) »] ; `referentiel_complet(2025)` = False ; `compute_cnss(…, 2025)` et `compute_professional_expenses(…, 2025)` lèvent `BaremeIndisponible` (tests `tests/test_rates_ma_2025.py`).

---

## 5. Paramètres CONFIRMÉS

**Aucun (0).** Aucune valeur n'a pu être corroborée par une source officielle lue en détail dans cette phase (barrières techniques décrites § 2/3). C'est la conséquence directe de la règle de preuve (Section 5 du mandat), pas une remise en cause des valeurs elles-mêmes.

## 6. Paramètres À CONFIRMER (4)

1. **Barème IR 2025** — dont tranche haute : 37 % (SAD 27 400) dans le moteur vs 38 % (SAD 29 200) tel que publié usuellement → arbitrage expert requis.
2. **Déduction pour charges de famille 2025** — 500 DH × 6 max ; mesure LF 2025 documentée dans le projet (LF n° 60-24), source officielle en ligne inaccessible.
3. **IS 2025** — grille transitoire (17,5 % ≤ 300 000 ; 20/35/40/CFC 20 %) ; statut inchangé depuis P1B V4.
4. **Cotisation minimale 2025** — 0,25 % · plancher 3 000 · exonération 36 mois ; statut inchangé depuis P1B V4.

En complément, **les valeurs de référence des 9 paramètres ABSENT (§ 7)** — taux CNSS/AMO/prestations familiales/TFP, plafond CNSS 6 000, frais professionnels — **restent aussi à confirmer documentairement** (aucune lecture officielle chiffrée possible).

## 7. Paramètres ABSENTS dans le moteur (9)

1. Frais professionnels 2025 (`BAREMES_PAIE[2025]["frais_professionnels"] = None`)
2. CNSS salarié 2025 (`cnss = None`)
3. CNSS employeur 2025 (`cnss = None`)
4. Plafond CNSS 2025 (non rattaché à l'exercice 2025)
5. AMO salarié 2025 (`cnss = None`)
6. AMO employeur 2025 (`cnss = None`)
7. Prestations familiales employeur 2025 (`cnss = None`)
8. TFP 2025 (`cnss = None`)
9. Assiette de cotisations (exclusions de l'arrêté n° 1314-25, effet 01/10/2025 — non modélisées)

→ Conséquence actuelle : **la paie 2025 est refusée** par le moteur (`BaremeIndisponible`) ; aucun taux 2026 n'est appliqué par défaut (règle permanente : aucun taux deviné).

## 8. Impact potentiel sur la simulation V4 (aucun recalcul ; chiffres V4 repris)

- V4 : 12 écritures synthétiques 2025 de 12 000 DH/mois (6171/6174/5141) ; résultat comptable avant IS 92 000 DH ; net comptable 73 600 DH ; aucun cycle ni bulletin réel 2025.
- Si le référentiel 2025 était complété et la paie réellement recalculée, les ordres de grandeur simulés en V4 (à re-valider humainement) : 5141 ≈ −11 019,48 ; 4441 ≈ +39 741,24 ; 4452 ≈ +194,76 ; reprise IS 4453 ≈ −7 360,39 ; résultat 1191 ≈ −21 556,13 (≈ 52 043,87 DH).
- Aujourd'hui, faute de référentiel complet, **aucune paie 2025 ne peut être produite** : l'impact réel demeure non chiffrable par le moteur.

## 9. Liste des écarts moteur / référence

1. **Tranche haute du barème IR** : moteur 37 % (SAD 27 400) vs 38 % (SAD 29 200) tel que publié usuellement — présent dans `IR_BRACKETS_2025` **et** `IR_BRACKETS_2026` (impact 2026 également) — non arbitré (source officielle inaccessible).
2. **Seuil des frais professionnels** : constante moteur 78 000 DH vs commentaire interne (`SOURCES_REFERENTIELS`) et rapport antérieur « 55 000 DH » → **contradiction interne au projet**, à arbitrer.
3. **Absence des 7 paramètres sociaux 2025** (CNSS salarié/employeur, plafond, AMO salarié/employeur, prestations familiales, TFP) → aucun coût employeur 2025 calculable.
4. **Absence des frais professionnels 2025** → aucun net imposable 2025 calculable.
5. **Assiette de cotisation** : moteur = brut intégral ; arrêté n° 1314-25 (01/10/2025) prévoit des éléments exonérés plafonnés → à examiner avant tout calcul 2025.
6. **Cohérence IR 2025/2026** : barèmes identiques dans le moteur — cohérent avec l'absence de modification du barème par les LF 2025/2026, à confirmer.

## 10. Verdict final

**RÉFÉRENTIEL 2025 INSUFFISAMMENT VALIDÉ.**

Justification courte : (a) **0 paramètre CONFIRMÉ** — les sources officielles prioritaires étaient inaccessibles ou non extractibles par cet audit (DGI HTTP 405, SGG indisponible, tableau CNSS rendu en JS, moteurs de recherche bloqués) ; (b) **9 paramètres restent ABSENT du moteur**, ce qui maintient le refus de toute paie 2025 (`BaremeIndisponible`) ; (c) **2 écarts à arbitrer** (tranche haute IR 37 % vs 38 % ; seuil frais professionnels 78 000 vs 55 000). Conformément à la règle de preuve, aucune valeur n'a été classée CONFIRMÉE sur la seule base de documents internes au projet. Le constat de P1B V4 (**NON PRÊT POUR STAGE 3**) est donc confirmé, avec cette fois une traçabilité complète des sources tentées.

---

*Rapport rédigé en lecture seule. Aucune écriture base, aucun code modifié, aucun paramètre touché, aucun salarié/bulletin/cycle créé, aucune écriture supprimée, aucun état recalculé, aucune réouverture 2025, aucun à-nouveaux 2026 modifié, aucun Greffe touché, aucun package installé, aucune migration, aucun PostgreSQL, aucun Stage 3.*



