# P1 Greffe (contenu des pièces) et P2 (navigation / écrans lecture seule)

**Date** : 23/09/2026 · **Suite de tests** : **410/410** (`python -m pytest -q`)
**Périmètre** : correctif **P1 Greffe** (anomalie bloquante du constat de recette), puis **P2**
(réorganisation du menu + écrans lecture seule), puis **contre-visite de recette P2** (deux écrans en
HTTP 500 sur la base réelle — corrigés, cf. § 4). **Aucune écriture 2025 modifiée** (le dossier de
recette et ses écritures restent en l'état : la réouverture de 2025 attend un GO explicite).

> **Statut** — **P1 Greffe : PASS**. **P2 : corrigé et rejoué sur la base de recette, en attente de
> votre contre-visite en navigateur** (P2 n'est pas redéclaré PASS avant votre confirmation).

---

## 1. P1 Greffe — anomalie bloquante corrigée

### Constat (reproduit à l'octet)
Deux pièces du dossier de recette (`rapport_gestion_j9.pdf`, `pv_ag_j9.pdf`) étaient **acceptées**
avec : **193 octets**, **page vide**, **contenu identique** (même SHA-256 `794abaa4f6f0…`) :

```
%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj
trailer<</Root 1 0 R>>
%%EOF
```

L'ancien contrôle ne vérifiait que **le type MIME et la taille < 10 Mo** : un PDF vide passait.

### Correctif (contrôles bloquants de contenu)
| # | Contrôle | Règle | Emplacement |
|---|---|---|---|
| 1 | PDF illisible (corrompu, chiffré, sans `startxref`) | refus, non archivé | `greffe.analyser_piece_pdf` / `verifier_contenu_piece` |
| 2 | Fichier vide / non-PDF (conservé) | refus | `greffe.verifier_piece_pdf` |
| 3 | Aucune page ou **toutes les pages blanches** (< 30 car./page) | refus « page(s) blanche(s) » | idem |
| 4 | Texte extrait < **120 caractères** | refus « contenu insuffisant » | idem |
| 5 | Pièces **substantielles** (PV d'AG, rapport de gestion) : < **400 caractères** ou **mentions métier** absentes | refus « contenu metier obligatoire absent » | idem |
| 6 | **Même contenu pour deux pièces différentes** (SHA-256) | refus « Contenu identique » | `greffe.ajouter_piece` |
| 7 | Pièce archivée mais **invalide** : `fournie` **recalculé depuis le contenu** | statut `invalide` + contrôles bloquants `greffe.piece_contenu_invalide`, `greffe.pieces_dupliquees` | `greffe.checklist`, `greffe.controles_depot` |
| 8 | **Date d'assemblée générale obligatoire** avant l'état « Approuvé » | transition refusée sans date d'AG (loi 5-96, art. 10) | `greffe.changer_etat` |

L'analyse de contenu utilise **`pypdf`** (déjà présent, 6.19.0) : pages, texte extrait, normalisation
sans accents pour la comparaison des mentions métier.

### Régularisation documentaire : pièces **réelles** produites par l'application
- **Rapport de gestion** (`pdf_rapport_gestion`) : situation de la société, activité et chiffres clés
  (CA, achats, marge, valeur ajoutée, EBE, charges de personnel, résultats), situation financière
  (actif / passif, contrôle d'équilibre), **affectation proposée du résultat** (report à nouveau —
  aucune distribution décidée par défaut), perspectives, rappel des obligations légales.
  Sur le jeu de recette : **5 112 octets — 2 675 caractères utiles, 2 pages**.
- **PV d'AG** (`pdf_pv_ag`) : **date d'assemblée**, qualité des participants (**associé unique** si la
  société est une SARL AU — cas de la société de recette — sinon assemblée des associés), ordre du
  jour, **1re résolution** (approbation des comptes : total du bilan, résultat net, CA),
  **2e résolution** (affectation du résultat), **3e résolution** (pouvoirs pour les formalités),
  mentions et signatures, contrôle du **délai légal de 6 mois**.
  Sur le jeu de recette : **4 835 octets — 2 707 caractères utiles, 2 pages**.
- `greffe.generer_pieces(..., date_ag=…)` génère désormais **4 pièces** (états de synthèse, bordereau,
  rapport de gestion, PV d'AG) ; le **SHA-256 est recalculé après génération** et journalisé
  (`GREFFE_PIECES_GENERATED` avec date d'AG, tailles et empreintes).
- **Aucune simulation** : l'application ne fait jamais passer le dossier à « Déposé » toute seule et
  ne fabrique **aucun certificat de greffe** (le certificat reste un fichier fourni par le greffe,
  archivé avec son empreinte) — vérifié par test.

### Interface
- `/greffe` : champ **Date AG** ajouté au formulaire « Générer les pièces » ; la checklist affiche
  l'**analyse de contenu** (pages, caractères, pages blanches, mentions) et le motif exact de refus ;
  les pièces invalides apparaissent « **refusée (contenu)** ».

### Outil de vérification
`tools/p1_greffe_controle_contenu.py` (lecture seule par défaut) : checklist analysée, contrôles
(bloquants), complétude, puis **simulation** du rapport de gestion et du PV d'AG réels. L'écriture
(`--ecrire`) exige `--date-ag AAAA-MM-JJ` : **aucune date d'assemblée n'est inventée**. Exécution sur
le dossier de recette (lecture seule) :

```
[OK ] etats_synthese        5 page(s), 6875 caractere(s), 0 page(s) blanche(s)
[NOK] rapport_gestion       193 octets  PDF illisible (PdfReadError: startxref not found)
[NOK] pv_ag                 193 octets  PDF illisible (PdfReadError: startxref not found)
Controles : 5 (bloquants : 4)  dont piece_contenu_invalide (x2) et pieces_dupliquees
Completude : 3/5 — manquantes : Rapport de gestion ; Proces-verbal de l'assemblee generale
RAPPORT DE GESTION genere : 5112 octets — 2 page(s), 2675 caractere(s)
PV D'AG : non produit (aucune date d'assemblee enregistree — aucune date n'est inventee)
```

### Tests dédiés (`tests/test_greffe_contenu.py`, 12 tests)
- **193 octets exacts** refusés pour `pv_ag` et `rapport_gestion` (rien n'est archivé, ni disque) ;
- fichier vide, non-PDF, **page blanche**, **contenu insuffisant**, **mentions métier absentes** ;
- **doublon de contenu** (même SHA-256) refusé et contrôle bloquant `greffe.pieces_dupliquees` ;
- pièce vide **déjà archivée** (état de recette reconstitué) : `fournie = False`, statut `invalide`,
  soumission bloquée ;
- génération réelle : rapport/PV > 1 000 octets, mentions et **montants de l'exercice** présents,
  **date d'AG** reportée, **SHA-256 recalculé** distinct, checklist `fournie` ;
- PV refusé **sans date d'AG** (aucune pièce générée) ; « Approuvé » refusé sans date d'AG ;
- **ni dépôt ni certificat simulés**.

Tests adaptés (ils téléversaient des PDF vides) : `tests/test_greffe.py`, `tests/test_api.py`,
`tests/test_web.py` utilisent désormais de **vrais** documents produits par le module.

---

## 2. P2 — Navigation et écrans lecture seule (GO « sans mutation comptable »)

### Menu réorganisé (`app/web/templates/base.html`) — **URL existantes conservées**
Tableau de bord · Commerce · **Comptabilité** (Saisie des écritures, **Journal comptable** — désormais
visible, Grand livre, Balance générale, Plan comptable) · **États de synthèse** (Bilan, CPC, ESG,
ETIC) · **Immobilisations** (Fiches, Linéaires, Dégressifs, Cessions/sorties) · **Stocks &
provisions** (Articles, Mouvements, Inventaire, Valorisation, Provisions/dépréciations) · **Paie**
(Salariés, Bulletins, Cycles, Écritures de paie, DTS/État 9421) · **Fiscalité** (TVA, Relevé des
déductions/EDI, IS, Liasse fiscale) · **Juridique / Greffe** (Dossier de dépôt, PV d'AG, Rapport de
gestion, Paiement, Certificat/récépissé) · **Clôture & cessation** (Exercices, Clôture, À-nouveaux,
Réouverture contrôlée, Verrouillage, Cessation) · **E-facturation** (Factures, Avoirs, Statuts de
transmission, Rejets/réémission) · **Audit & traçabilité** (Journal d'audit, Événements système,
Exports, Contrôles d'intégrité) · **Paramètres** (Société, Journaux, Utilisateurs & rôles,
Référentiels fiscaux, Référentiels EDI).

### 11 écrans lecture seule ajoutés (`app/web/ecrans_lecture.py`, gabarit `ecran_lecture.html`)
| Écran | URL | Source (services existants) |
|---|---|---|
| ESG | `/etats/esg` | `etats_synthese.etat_soldes_gestion` (soldes + familles, cohérence CPC) |
| ETIC | `/etats/etic` | `etats_synthese.notes_etic` + informations **non disponibles** explicitées |
| Mouvements | `/stocks/mouvements` | `stocks.list_items` + `stock_movements` (500 derniers) |
| Inventaire | `/stocks/inventaire` | `stocks.inventaire_valorise` |
| Provisions | `/stocks/provisions` | `stocks.etat_provisions` (base, valeur d'inventaire, dotation, motif) |
| À-nouveaux | `/parametres/a-nouveaux` | `closing.controle_a_nouveaux` (exercice et précédent) |
| Journaux | `/parametres/journaux` | `Journal` + volumétrie des écritures |
| Référentiels fiscaux | `/parametres/referentiels` | `IS_RATES_BY_YEAR`, `COTISATION_MINIMALE_BY_YEAR`, `SOURCES_REFERENTIELS` |
| Contrôles d'intégrité | `/audit/integrite` | `audit_trail.verifier_chainage`, équilibre du bilan, écritures déséquilibrées |
| E-facturation | `/e-facturation` | `e_invoice.situation` / `list_documents` (statuts, rejets, accusés) |
| Activité | `/activite` | `audit_trail.journal_audit` + documents e-facturation |

Routes **GET uniquement**, enregistrées avec `include_in_schema=False` comme les autres écrans :
**aucune permission modifiée**, **aucun service métier touché**, **aucune écriture comptable créée**.

### Tests (`tests/test_menu_p2.py`, 44 tests)
- **smoke test de chaque entrée de menu** (41 entrées réparties dans les 12 sections) : 200 ou 303,
  jamais 4xx/5xx ;
- présence des 12 sections et de **tous les liens** du menu dans la page ;
- les 11 écrans lecture seule répondent 200 **et n'ajoutent aucune écriture** (comptage avant/après) ;
- **permissions par rôle** : un `LECTEUR` accède aux écrans (comme avant) mais la **clôture** lui est
  refusée et **l'exercice reste ouvert** (aucun effet de bord).

---

## 3. Reste à faire (dans l'ordre validé)

1. **Greffe — écriture réelle sur le dossier de recette** : fournir la **date de l'assemblée générale**
   (≤ 30/06/2026), puis
   `python tools/p1_greffe_controle_contenu.py --ecrire --date-ag AAAA-MM-JJ`
   → le rapport de gestion et le PV d'AG réels remplacent les deux pièces de 193 octets.
2. **P2 — éléments restants du plan** : filtres d'affichage (immobilisations par mode, journal par
   code — URLs déjà en place dans le menu), reclassement 2340 → 2332/2355, TVA sur immobilisations,
   colonne Pièce au grand livre, formulaire « nouvel exercice », `payments.entry_id`, liasse/DTS.
3. **P1B v3 (2025)** : référentiel 2025 **IR** (seuil exonéré 40 000 DH ; 10/20/30/34/37 % ;
   réduction familiale 500 DH/personne/an, 6 maximum) et **IS** (grille transitoire, 17,5 % pour le
   cas de droit commun ≤ 300 000 DH) à saisir **avec source** ; **CNSS / AMO / prestations familiales
   / TFP 2025 : non figées** (aucune source officielle fournie → aucun taux inventé) ; l'écran
   `/parametres/referentiels` valorise les paramètres et leurs sources.
4. **Aucune écriture 2025** touchée avant le GO final (réouverture encadrée + regeneration paie).

---

## 4. Contre-visite de recette P2 — deux écrans en HTTP 500 (**corrigés**)

### Reproduction sur la base de recette (session ADMIN réelle)

Commande (lecture seule) : `python tools/p2_repro_500.py /etats/etic /activite`.
**Tracebacks complets** obtenus :

```
[ADMIN admin@compta.ma] GET /etats/etic
  File "app/web/ecrans_lecture.py", line 195, in page_etic
  File "app/web/ecrans_lecture.py", line 78, in _page            (render)
  File "jinja2/environment.py", line 942, in handle_exception
  File "jinja2/runtime.py", line 432, in _to_iterator
  TypeError: 'decimal.Decimal' object is not iterable

[ADMIN admin@compta.ma] GET /activite
  File "app/web/ecrans_lecture.py", line 819, in page_activite
  AttributeError: 'AuditLog' object has no attribute 'get'
```

### Cause racine 1 — `/etats/etic` : total scalaire vs ligne de cellules
`etats_synthese.notes_etic` renvoie pour chaque note un **`total` scalaire** (un `Decimal`) ; le
gabarit `ecran_lecture.html` itere `tableau.total` comme une **ligne de cellules**
(`{% for cellule in tableau.total %}`). Le total n'était donc itéré que s'il était **non nul**
(`{% if tableau.total %}`) : avec les capitaux propres de la recette (note 10), l'itération d'un
`Decimal` a produit l'erreur 500.

**Correction (contrat explicite, pas de masquage)** :
- `_ligne_total(colonnes, montant)` convertit le total en **ligne de cellules** alignée :
  `["Total", "500 000,00"]` (2 colonnes) ou `["", "Total", "1 234,50"]` (3 colonnes), `None` si
  aucun total ;
- `_cellule(valeur)` formate les montants (`Decimal`/`int`/`float`) et laisse les textes tels quels :
  les lignes des notes ETIC s'affichent désormais au format français (« 1 234,56 »).

### Cause racine 2 — `/activite` : lignes ORM lues comme des dictionnaires
`audit_trail.journal_audit` retourne des **lignes ORM `AuditLog`** — l'écran `/audit` (référence) les
lit **par attributs** — alors que `/activite` les lisait comme des dictionnaires
(`entre.get("created_at")`), d'où l'`AttributeError` **dès que le journal contenait au moins un
événement** (482 entrées dans la base de recette).

**Correction** : lecture par attributs (`entre.created_at`, `entre.action`, `entre.entity`,
`entre.entity_id`) et **libellé utilisateur** via `piste.utilisateurs_journal` (nom complet, à défaut
courriel), exactement comme l'écran `/audit` — la colonne affiche « Administrateur » et non
l'identifiant technique. **Aucun `try/except`** n'a été ajouté : l'erreur est supprimée à la source.

### Pourquoi les tests ne l'avaient pas vu — et la parade
Les deux défauts exigeaient des **données** : `tests/test_menu_p2.py` appelait `/etats/etic` et
`/activite` **sans écriture validée ni événement d'audit** (total nul → branche non exécutée ;
journal vide → boucle vide) : le code fautif n'était jamais atteint.

Parade : `tests/test_p2_ecrans_recette.py` (**6 tests**) poste des écritures **réelles** (capital 11x
= 500 000 ; charges de personnel 617x = 17 700) pour **forcer les chemins fautifs**, puis vérifie le
**contenu métier** attendu (et non le seul code HTTP) :
- note 10 : « Total | 500 000,00 » ; note 9 : comptes 6171/6174 et « 17 700,00 » ;
- `/activite` : action `ENTRY_VALIDATED`, entité `Entry <id>`, libellé de l'utilisateur, tableau
  e-facturation ;
- contrat de rendu : `_ligne_total` renvoie une liste de cellules (jamais un scalaire).

### Validation (base de recette)
`python tools/p2_recette_menus.py` — la base de recette est **copiée** (le LECTEUR de recette est créé
dans la copie) ; l'empreinte SHA-256 de la base réelle est comparée avant/après :

| Contrôle | Résultat |
|---|---|
| ADMIN — 60 entrées de menu balayées | **0 échec** (aucun 4xx/5xx) |
| LECTEUR — 60 entrées de menu | **0 échec** |
| `/etats/etic` contenu | **Note 1 —**, **Note 10**, **Total**, **Capitaux propres**, **15 montants formatés** |
| `/activite` contenu | actions `DTS_RECORDED`, `ENTRY_VALIDATED`, `PAYROLL_PAID`, `PAYROLL_VALIDATED` ; entités `Entry 207`, `Entry 208`, `PayrollRun 12`, `TaxDeclaration 3` ; utilisateur **Administrateur** |
| Sans session — 11 écrans P2 | **303 → /connexion?next=…** pour chacun |
| Base de recette | **inchangée** (SHA-256 `8bdbac236e61c3b6…` identique avant/après) |

`python tools/p2_repro_500.py /etats/etic /activite` (base réelle, ADMIN) : **HTTP 200** (21 008 et
37 598 octets), **303** sans session.

**Serveur en cours (navigateur réel).** Requêtes `GET` avec cookie de session ADMIN sur le serveur
`uvicorn --reload` déjà lancé (port 8000, rechargé avec le correctif) :

```
LIVE /etats/etic -> HTTP 200 (21 006 octets)   Note 1 / Note 10 / Total / Capitaux propres : OK
LIVE /activite   -> HTTP 200 (37 596 octets)   ENTRY_VALIDATED / DTS_RECORDED / PayrollRun 12 /
                                               « Administrateur » : OK
sans session     -> HTTP 303 -> /connexion?next=/etats/etic (resp. /activite)
```

**Suite de tests : `python -m pytest -q` → code de sortie `0` — 410/410** (dont les 6 nouveaux tests
de `tests/test_p2_ecrans_recette.py`).

### Statut
**P2 n'est pas redéclaré PASS** : les deux routes sont stables sur la base de recette en test HTTP
avec session réelle, la contre-visite **en navigateur** reste à confirmer par vos soins. La
réouverture 2025 et toute écriture comptable restent **non exécutées**.

---

## 5. Finalisation du dossier Greffe 2025 (**exécutée**, étape 1 uniquement)

### Date d'assemblée générale
**08/01/2026**, fournie explicitement par le demandeur comme **date de recette (fictive)** : le
livrable et le dossier la portent comme telle. Aucune date n'a été devinée par l'application
(`greffe.generer_pieces` refuse de produire le PV sans date ; l'état « Approuvé » l'exige).

### Avant / après (dossier #1, exercice 2025, statut `approuve`)

| Pièce | Avant | Après |
|---|---|---|
| `rapport_gestion` | `rapport_gestion_j9.pdf` — **193 o** — `794abaa4f6f06fc5…` — PDF illisible | `Rapport_gestion_2025.pdf` — **5 112 o** — `fe0c66cdb6b87f8b…` — 2 pages, 2 675 car. |
| `pv_ag` | `pv_ag_j9.pdf` — **193 o** — `794abaa4f6f06fc5…` (même contenu) | `PV_AG_2025.pdf` — **4 831 o** — `fb5c19d691f21b83…` — 2 pages, 2 707 car. |
| Autres pièces | états de synthèse, bordereau, justificatif de paiement | **inchangées** (empreintes identiques) |

Les deux anciens fichiers de 193 octets sont **supprimés du disque** (`media/greffe/1/1/`), les
nouveaux portent des **SHA-256 distincts** et sont stockés avec leur empreinte en base.

### Contrôles rejoués : **27 PASS / 0 NOK**
- **Pièces (19)** : lisibilité, mentions métier obligatoires (contrôles bloquants de l'application),
  documents distincts, empreinte base = disque (5 pièces), plus aucune pièce < 400 octets, empreintes
  toutes distinctes, exercice 2025 présent dans les deux documents, **date d'AG reportée dans le PV
  (08/01/2026)**, **résultat 2025 identique (rapport = PV = comptabilité : 73 600,00)**, **total du
  bilan 387 520,00**, **chiffre d'affaires 360 000,00**, **affectation du résultat identique dans le
  rapport et le PV** (« report à nouveau », aucune distribution), **états de synthèse 2025** (5 pages :
  bilan, CPC, ESG, ETIC).
- **Dossier (8)** : checklist « fournie » pour les deux pièces, **complétude 5/5**, **aucun contrôle
  bloquant** (les 4 blocages `greffe.checklist_incomplete`, `greffe.piece_contenu_invalide` x2 et
  `greffe.pieces_dupliquees` ont disparu), exercice/date d'AG/délai de six mois cohérents,
  **chronologie clôture (31/12/2025) ≤ AG (08/01/2026) ≤ soumission (10/01/2026)**, et **aucun dépôt
  réel** (statut `approuve` inchangé, `date_depot` vide, aucun certificat, aucun paiement ajouté,
  aucun événement créé).

### Périmètre respecté
- **Aucune écriture comptable** créée ou modifiée : **195 écritures** avant et après.
- **Aucun dépôt réel**, **aucun paiement réel**, **aucun certificat/récépissé** simulé ou fabriqué
  (le certificat officiel reste à téléverser après le dépôt sur le portail).
- **P2/menu non touchés** ; aucune arborescence modifiée.

### Outils et livrables
- `tools/p1_greffe_finaliser_2025.py` : préparation (lecture seule) puis exécution
  `--date-ag AAAA-MM-JJ [--recette] [--hors-delai] [--toutes]` ; produit le livrable.
- `tools/p1_greffe_verif_2025.py` : vérification **indépendante** (base + disque).
- **`PREUVE_GREFFE_2025_FINAL.md`** : états avant/après, SHA-256, date d'AG, contrôles PASS/NOK,
  cohérences, extraits lisibles des deux documents (annexe A), vérification indépendante (annexe B).
- Correctif d'affichage : le compteur « mention(s) métier » de l'analyse générique
  (`greffe.analyser_piece_pdf`) affichait 0 pour toutes les pièces ; il compte désormais les mentions
  du référentiel complet (`MOTS_CLES_TOUS`), la liste propre à chaque pièce restant **bloquante**.




---

## 6. Correctifs de generation du dossier 2025 (recette du 24/09/2026)

Le dossier reste en statut **recette/provisoire** (execution technique validee, aucune valeur definitive tant que la regularisation comptable 2025 — P1B etape 3 — n'est pas faite).

1. **Total du bilan** : le rapport de gestion et le PV d'AG portaient le **total actif brut** de l'ecran (387 520,00 DH). Ils portent desormais le **total du bilan net equilibre** des etats de synthese (375 520,00 DH = brut 387 520,00 - amortissements et provisions 12 000,00) ; le brut n'apparait plus que « pour memoire » (`Pour memoire : total actif brut` et « ramene au net » dans la 1re resolution). Un controle bloquant l'interdit desormais comme total approuve.
2. **Identite harmonisee** (fiche societe) : `forme_juridique()`, `siege_social()`, `associe_unique()`, `qualite_assemblee()` alimentent le rapport de gestion, le PV d'AG, le bordereau / etat complementaire et le bordereau greffe — forme, siege et qualite **identiques** partout (« SARL AU » deduit de la raison sociale car la fiche est incomplete, siege « Casablanca (adresse a completer dans la fiche societe) »). La fiche societe ne portant ni forme ni adresse, **rien n'a ete invente** : les manques sont explicites.
3. **Bordereau / etat complementaire** : regenere **avec la date d'AG** (08/01/2026) et l'identite completee ; une seule version active par piece (contrainte d'unicite + remplacement du fichier precedent), aucun fichier orphelin — verifie par `tools/p1_greffe_finaliser_2025.py`.
4. **Archive finale** : une piece **presente mais invalide** (PDF de 193 octets, document anterieur a la date d'AG) fait desormais **refuser l'archive** (`assembler_dossier`) au lieu d'y entrer.
5. **Regeneration complete** (etats de synthese, rapport de gestion, PV d'AG, bordereau, attestation) : **37 PASS / 0 NOK**, aucune ecriture comptable touchee (195 avant/apres), aucun depot/paiement/certificat. Livrable : `PREUVE_GREFFE_2025_FINAL.md` (etape 1 conservee dans `PREUVE_GREFFE_2025_ETAPE1.md`).

### Apres la regularisation comptable 2025 (P1B etape 3) : hors perimetre, a declencher sur GO
Regenerer **etats de synthese 2025, rapport de gestion, PV d'AG et bordereau**, recalculer les SHA-256 et rejouer les controles de coherence :
``````
python tools/p1_greffe_finaliser_2025.py --date-ag 2026-01-08 --recette --toutes
``````

---

## 8. Correction P1B v3 — IS 2025 par la demarche fiscale (24/09/2026)

La premiere version comparait le **resultat net comptable** (73 600 DH) — deja net d'IS — a la grille IS : le calcul etait doublement faux (base non fiscale et taux standard 20 %). Correction :

| Etape | Montant |
|---|---|
| Resultat net comptabilise (apres IS) | 73 600,00 DH |
| + Reintegration de l'IS comptabilise (**non deductible**, CGI art. 11) | 18 400,00 DH |
| = **Resultat comptable avant IS (base fiscale provisoire)** | **92 000,00 DH** |
| Reintegrations complementaires / deductions | 0,00 / 0,00 DH |
| **Resultat fiscal 2025** | **92 000,00 DH** |
| **Taux IS 2025** (transitoire, BNF <= 300 000 DH) | **17,50 %** |
| **IS 2025 calcule** | **16 100,00 DH** |
| IS comptabilise (6701) | 18 400,00 DH |
| **Ecart** | **2 300,00 DH** |

**Cotisation minimale** : taux 0,25 % du CA TTC et plancher 3 000 DH affiches separement -> CM theorique 3 000,00 DH (base 432 000,00 DH), mais **NON exigible** : debut d'exploitation **01/01/2025** (fiche societe) -> exoneration des **36 premiers mois** (jusqu'au 01/01/2028) ; les 3 000 DH ne constituent **pas** une dette fiscale.

- **Impot finalement du 2025 = 16 100,00 DH** ; **resultat net corrige = 75 900,00 DH** ; **impact a-nouveaux 2026** : report a nouveau **+2 300,00 DH**, dette d'IS **-2 300,00 DH**, total du bilan **inchange** (375 520,00 DH).
- Moteur : `fiscal_liasse.calculer_is` (resultat avant impot + reintegrations/deductions, CGI art. 11 et 144) et `exoneration_cotisation_minimale` (dates reelles). `rates_ma.compute_is` selectionne desormais le **taux transitoire** de l'exercice (`small_profit`, 17,5 % en 2025) quand le BNF ne depasse pas le seuil annuel ; **2026 inchange** (20 %).
- **Paie/IR 2025 : blocage maintenu** (frais professionnels et CNSS/AMO 2025 non documentes) ; aucun taux devine.
- Livrable : **`P1B_SIMULATION_2025_V3_CORRIGEE.md`** (ancienne version marquee *superseded*) — **aucune ecriture modifiee** (SHA-256 de la base identique, 195 ecritures) ; **P1B etape 3 non lancee** (validation humaine requise).
