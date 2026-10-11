# Audit des anomalies signalées (J9) — constats, causes racines, correctifs proposés

**Date** : 23/09/2026 · **Base auditée** : `compta_ma.db` (184 écritures, 74 factures, 142 règlements, 895 comptes)
**Méthode** : outil de diagnostic **en lecture seule** `tools/j9_audit_anomalies.py` → preuves brutes dans
`AUDIT_ANOMALIES_J9.txt` (requêtes SQL, appels de services, requêtes HTTP réelles avec session, scan des 48 périodes TVA).
**Aucun module applicatif n'a été modifié** (consigne respectée) : seuls 2 fichiers ont été **créés**
(`tools/j9_audit_anomalies.py`, le présent rapport). La suite de tests a été relancée après l'audit :
**300/300 tests verts**.
**Aucune donnée n'a été écrite** : l'horodatage de `compta_ma.db` est resté celui d'avant l'audit
(23/09/2026 04:07), alors que l'audit a été exécuté à 14:01.

## 0. Synthèse

| # | Anomalie signalée | Verdict | Cause racine | Gravité |
|---|---|---|---|---|
| A1 | Journal d'audit / Stocks / provisions inaccessibles, « authentification requise » | **CONFIRMÉE** | 3 routes API masquent les écrans web (`/audit`, `/audit/export`, `/stocks`) ; aucun écran « provisions » n'existe | **Bloquante** |
| A2 | Double alimentation de la paie 2026 | **CONFIRMÉE** | Aucun contrôle de recouvrement entre la paie comptabilisée (jeu) et la paie du module | **Majeure** |
| A3 | TVA incohérente dans le XML (FA26-08, FA26-09, taux 20 %) | **CONFIRMÉE** | `mht` reste au montant **facture** alors que `tva` est proratisée au **règlement** → `ttc = mht + tva` incohérent | **Bloquante (dépôt DGI)** |
| A4 | FA26-12 : ligne HT/TVA/TTC à 0 vs totaux 9 000/1 800/10 800 | **PARTIELLE** | L'incohérence réelle de FA26-12 est le **relevé XML** (9 000 / **720** / 9 720) ; un « 0 » de ligne est **non reproduit** dans la base, mais **possible** (lignes à 0 acceptées) | **Majeure** |
| A5 | Dossier greffe incomplet (PV AG / rapport quasi vides, date AG absente) | **CONFIRMÉE** | Pièces non contrôlées au-delà de « PDF ≤ 10 Mo » ; date d'AG non obligatoire à l'approbation | **Majeure** |
| A6 | Immobilisations mal classées (2340 « Matériel de transport ») | **CONFIRMÉE** | Le jeu comptabilise au **2340** et l'import reprend ce compte en dur (`tools/j9_importer_jeu.py:638`) | Moyenne |
| A7 | ETIC : charges de personnel = 0 alors que le CPC porte des 617 | **CONFIRMÉE** | Bug : `note(9, …, ("617",))` compare une racine de **3** chiffres à `account_number[:2]` → jamais de correspondance | **Majeure (liasse)** |
| A8 | IS calculé sur un résultat faussé par la paie | **CONFIRMÉE** (conséquence de A2) | L'IS part du résultat comptable, qui contient la double paie → écart **6 099,12 DH** | **Majeure** |
| A9 | « Ouverture d'exercice » propose 2026 alors qu'il existe | **CONFIRMÉE** | Le formulaire pré-remplit `annee_courante` (année civile) au lieu du premier exercice libre | Mineure |
| A10 | Réouverture de 2025 alors que 2026 contient des écritures | **CONFIRMÉE** | `changer_statut_exercice` écrit le statut **sans aucun contrôle** | **Majeure** |

## 1. A1 — Écrans inaccessibles : **trois collisions de routes**

**Constat** : `GET /audit`, `GET /audit/export` et `GET /stocks` renvoient **HTTP 401 `{"detail":"Authentification requise"}`**
même avec une session administrateur valide (balayage des 40 écrans GET : 6 anomalies, dont 3 dues aux collisions).

```
141 route(s) API + 96 route(s) d'interface ; 3 collision(s) : l'API etant montee en premier, elle masque l'ecran.
  GET /audit         gagnant : api.audit:get_journal_audit    masque : interface:page_audit
  GET /audit/export  gagnant : api.audit:export_audit_csv     masque : interface:exporter_journal
  GET /stocks        gagnant : api.stocks:list_stock_items    masque : interface:page_stocks
```

**Cause racine** : `app/main.py` monte **tous les routeurs API avant** l'interface (l. 116-132 puis l. 135).
FastAPI sert la **première** route correspondante : l'API (`app/api/routers/audit.py:51`, `stocks.py:46`, jeton
`Bearer` obligatoire) intercepte ces trois chemins → l'écran web n'est **jamais atteint**. Ce n'est **pas** un
problème de session (durée de vie 480 min, cookie bien posé) : les 34 autres écrans renvoient 200.

**Anomalies liées détectées dans le même balayage** :
- **`/provisions` et `/etats/provisions` : HTTP 404** — aucun écran de provisions (dépréciation stocks `39x`,
  provisions pour risques `15x`, dépréciation créances `49x`). Seule l'API expose `GET /stocks/provisions`
  (et `GET /audit/verrouillages`) : c'est le « provision inaccessible » signalé. La table `stock_provisions` et
  le service `app/services/stocks.py` existent pourtant.
- **`Journal comptable` (`/etats/journal`) : 200 mais absent du menu** (`base.html` ne contient aucun lien) :
  la page n'est atteignable que par URL.
- **Le grand livre n'affiche pas la colonne « Pièce / Référence »** (`etats_grand_livre.html:59` : Date, Numéro,
  Libellé) alors que le journal l'a (`etats_journal.html:61`) : la trace vers FA26-12 n'est pas lisible au GL
  (les règlements ont aussi `entry_id = NULL`).

**Correctif proposé (non appliqué)** : préfixer l'API (`/api/...`) **ou** monter l'interface **avant** l'API dans
`app/main.py` ; ajouter au menu « Journal comptable » et « Provisions » ; créer l'écran de provisions (le service
`stocks.provisions` et la table existent déjà) ; ajouter la colonne « Pièce » au grand livre.

## 2. A2 — Double alimentation de la paie 2026

| Origine | Écritures | Comptes | Montant 2026 |
|---|---|---|---|
| Jeu de données (saisie manuelle) | `PAIE26-01` … `PAIE26-12` (journal BQ, `source=import_jeu_j9`) | `6171` + `6174` | **172 800,00** (12 × 14 400,00) |
| Module Paie (recette 01/2026) | écriture n° 183 (`source=payroll`, 3 bulletins) | `61711` `61741` `61744` `61768` / `4432` `4441` | **30 495,60** |

Totaux 2026 : 6171 = 144 000,00 · 61711 = 26 000,00 · 6174 = 28 800,00 · 61741/61744/61768 = 4 495,60 →
les comptes **6171** (père) et **61711** (enfant) coexistent : tout état qui agrège `617x` **cumule les deux**.

**Cause racine** : aucun **contrôle de recouvrement** entre la paie comptabilisée et celle du module.
`app/services/payroll.py` (comptes l. 101-121) comptabilise sans vérifier qu'une charge de personnel existe déjà
sur la période. La recette J9 a volontairement ajouté la paie de test (30 495,60 DH) pour exercer le module :
elle est identifiée et **réversible** (`source=payroll`, période 2026-01, n° 183).

**Impact** : résultat 2026 sous-évalué de 30 495,60 DH (49 344,40 au lieu de 79 840,00 attendu par le jeu) ;
IS affecté (A8) ; DTS 2026 créée avec un IR de 2 300,66 DH et `fiscal_year_id = NULL`.

**Correctif proposé** : alerte bloquante « charge de personnel déjà comptabilisée sur la période » avant
comptabilisation d'un cycle de paie ; état de rapprochement *paie comptabilisée ↔ paie du module* ; purge de
l'écriture de recette (procédure de l'étape 6 déjà écrite).

## 3. A3 — Relevé des déductions TVA : `mht` facture vs `tva` proratisée

**Constat (mode par défaut « date de paiement »)** — exemple réel, août 2026 :

```
  ord=1   FA26-07      mht   9,000.00 tva    630.00 ttc   9,630.00 tx 20 %   (attendu 1 800,00)
  ord=2   FA26-08      mht   9,000.00 tva  1,080.00 ttc  10,080.00 tx 20 %   (attendu 1 800,00)  <<< ECART
  ord=3   LOY26-08     mht   2,200.00 tva    440.00 ttc   2,640.00 tx 20 %
```
L'écran (`/tva/edi`) et le **fichier XML** affichent donc : `<mht>9000.00</mht><tva>1080.00</tva><ttc>10080.00</ttc><tx>20</tx>`
→ **`ttc ≠ ttc de la facture (10 800)`**, `tva ≠ mht × 20 %` : le contrôle de cohérence de la DGI peut rejeter le fichier.

**Scan exhaustif (48 périodes, 2025-2026)** : base *date de facture* → **0 ligne incohérente** ;
base *date de paiement* (**le défaut**) → **45 lignes incohérentes** sur les 48 périodes.

**Cause racine** : `app/services/edi_tva.py`
- l. 386-390 : `mht = facture.total_ht` (montant **facture** complet) et `tva_facture = facture.total_vat` ;
- l. 409-444 : en base « paiement », seule la **TVA** est recalculée au prorata du règlement
  (`tva = tva_facture × réglé_apres / du_ttc − tva_facture × réglé_avant / du_ttc`) — **`mht` n'est pas proratisé** ;
- l. 462-463 : `ttc = money(mht + tva)` → fabrique le TTC incohérent.

**Impact** : risque de **rejet du dépôt EDI** par la DGI, TVA déductible déclarée sur une base fausse (les
prorata sont justes en montant, mais illisibles/incohérents dans la ligne).
**Correctif proposé** : proratiser **la base et la TVA** (et recalculer le TTC = base proratisée + TVA), ou
émettre une ligne **par tranche de règlement** avec `mht` fractionné ; ajouter un contrôle interne bloquant
`mht × tx / 100 == tva` et `ttc == mht + tva` avant écriture du fichier.

## 4. A4 — FA26-12 : ligne à 0 ?

**Ce qui est vérifié conforme dans la base** (facture n° 72, achat du 08/12/2026) :

| Écran / document | Ligne | Totaux | Verdict |
|---|---|---|---|
| `invoice_lines` (base) | HT 9 000,00 · TVA 1 800,00 · TTC 10 800,00 | 9 000 / 1 800 / 10 800 | conforme |
| Écran détail `/factures/72` | ligne 9 000,00 / 20 % / 10 800,00 | 9 000 / 1 800 / 10 800 | conforme |
| Aperçu impression | idem | idem | conforme |
| **PDF de la facture** | `9 000,00 \| 20 % \| 10 800,00` | ventilation 20 % : 9 000 / 1 800 | conforme |
| Liste des achats | 9 000,00 / 1 800,00 / 10 800,00 / réglé 4 320,00 / reste 6 480,00 | conforme | conforme |
| Écriture comptable n° 174 | 6111 D 9 000 · 34552 D 1 800 · 4411 C 10 800 | équilibrée | conforme |
| **Relevé EDI 12/2026** | **9 000,00 / 720,00 / 9 720,00** | 9 000 / 1 800 / 10 800 | **incohérent (A3)** |

Balayage global : **0 ligne de facture à montant nul** dans la base ; **0 facture** dont les lignes ne
réconcilient pas l'en-tête.

**Deux mécanismes réels peuvent produire l'écran « ligne à 0 »** (le second est reproductible) :
1. `app/services/edi_tva.py` l. 441-444 : la TVA de la ligne EDI peut devenir très petite (mais pas nulle ici) ;
2. **Validation d'une ligne à 0** : `compute_line` (`invoicing.py:47-63`) accepte `quantity = 0` ou
   `unit_price = 0` ; `validate_invoice` (`invoicing.py:287-290`) ne refuse que « facture sans ligne » et
   « montant total nul » ; le formulaire web ne filtre que les lignes **sans désignation**
   (`routes.py:546-549`). Une facture **peut donc être validée avec une ligne « désignée » à 0,00** et des
   totaux corrects (9 000 / 1 800 / 10 800) → exactement le symptôme décrit. Aucun contrôle « ligne à montant nul »
   n'existe, ni à la validation, ni dans l'ETIC/la liasse.

**Correctif proposé** : refuser (ou signaler) toute ligne à montant nul à la validation ; contrôle global
`total_ht == Σ line_ht` (déjà vrai en base) **+** `line_ht > 0` ; corriger A3 pour le relevé.
*Si la capture d'écran du « 0 » provient d'un autre écran, elle permettra de confirmer ce point en quelques minutes.*

## 5. A5 — Dossier greffe (dépôt 1 / exercice 2025)

| Élément | Constat | Analyse |
|---|---|---|
| `date_ag` | **`None`** alors que le dossier est **`approuve`** | Le service détecte l'AG absente/dépassée (`greffe.py:934-938`) mais **ne bloque pas** l'approbation ; la date reste vide à l'écran et à l'attestation |
| `pv_ag` | `pv_ag_j9.pdf` — **193 octets** | Pièce quasi vide **acceptée** : `verifier_piece_pdf` (`greffe.py:178-198`) ne contrôle que « non vide, PDF, ≤ 10 Mo » — aucune vérification de contenu (pages, texte) |
| `rapport_gestion` | `rapport_gestion_j9.pdf` — **193 octets**, **même SHA-256** que le PV AG | Les deux pièces sont **identiques** et acceptées sans contrôle de doublon |
| `etats_synthese`, `etat_complementaire`, `justificatif_paiement` | 13 220 / 4 032 / 2 312 octets, `source=genere` | Générés par l'application : corrects |
| Cycle de vie | `nouveau → en_cours → approuve` le même jour, dépôt au 10/01/2026 | Cohérent, mais **`date_depot = None`** (le dépôt final n'a pas été enregistré) alors que le certificat/paiement existent |

**Cause racine** : contrôles de complétude **déclaratifs** (liste `controles_depot`, `greffe.py:860`) et non
bloquants sur les points clés (date d'AG, contenu minimal des pièces) ; les pièces de la recette ont été fournies
comme **fichiers factices de 193 octets** par l'outil de recette (données de test, à purger) — mais l'application
les a acceptées sans broncher, ce qui est le défaut à corriger.
**Correctif proposé** : rendre bloquants (1) la présence de la date d'AG avant approbation, (2) une taille minimale
et un nombre de pages minimal des pièces PDF, (3) le refus de deux pièces au contenu identique (même SHA-256) ;
interdire l'enregistrement du paiement/certificat avant `date_depot`.

## 6. A6 — Immobilisations classées au 2340 « Matériel de transport »

```
  IMM-001  Matériel et outillage                  compte 2340  « Matériel de transport »
  IMM-002  Matériel informatique complémentaire   compte 2340  « Matériel de transport »
```
Le plan comptable **contient les bons comptes** : `2332` « Matériel et outillage », `23324` « Outillage »,
`2355` « Matériel informatique » (+ `2833`/`28332`/`28355` pour les amortissements).

**Cause racine** : le **jeu de données** comptabilise les acquisitions au 2340 (`EC202500002`, `EC202600090`)
et l'outil d'import crée les fiches sur ce compte **en dur** : `tools/j9_importer_jeu.py:614-644`
(`account_number="2340"`, `tva_compte="34551"`). Ce n'est donc pas un bug du module Immobilisations (qui prend le
compte de la fiche), mais une **erreur de codification du jeu reprise telle quelle par l'import**.
**Correctif proposé** : reclasser (dossier de test) outillage → `2332`/`23324` et informatique → `2355`, avec
contre-passation et plan d'amortissement recalculé ; à défaut, documenter l'écart. À signaler au fournisseur du
jeu de données (arbitrage A6 « codification des immobilisations »).

## 7. A7 — ETIC : charges de personnel à zéro (bug de code)

Le CPC 2026 porte bien : `6171` = 144 000,00 · `61711` = 26 000,00 · `6174` = 28 800,00 ·
`61741/61744/61768` = 4 495,60. Or la note 9 de l'ETIC (« Charges de personnel de l'exercice ») est **vide**.

**Cause racine** : `app/services/etats_synthese.py`
- l. 432-437 : `detail(*racines)` sélectionne `l["account_number"][:2] in racines` → comparaison sur **2 caractères** ;
- l. 502 : la note est appelée avec la racine **`"617"`** (3 caractères) → `"61" == "617"` est **toujours faux**.
- Le **même bug** affecte la note 4 (l. 487-493) qui attend `"619"` (dotations d'exploitation) : les dotations
  `6193` (15 000,00) **n'apparaissent jamais** dans l'ETIC.
Les autres notes (`"21"`, `"22"`, `"23"`, `"28"`, `"44"`…) utilisent des racines à 2 caractères et fonctionnent.

**Impact** : ETIC (annexe obligatoire de la liasse) **fausse** ; risque de rejet/redressement si déposée telle quelle.
**Correctif proposé** : faire porter la comparaison sur `account_number.startswith(racine)` (les racines 3/5
caractères fonctionnent alors aussi) et ajouter un test de non-régression (note 9 = 203 295,60 DH en 2026,
note 4 = 15 000,00 DH).

## 8. A8 — IS calculé sur le résultat faussé

```
  2025 : résultat comptable 73 600,00 · avant impôt 92 000,00 · IS calculé 18 400,00   (conforme au jeu)
  2026 : résultat comptable 49 344,40 · avant impôt 69 304,40 · IS calculé 13 860,88   (au lieu de 19 960,00)
```
**Cause** : `fiscal_liasse.resultat_avant_impot` (l. 126-155) part du **résultat comptable** (CPC), qui intègre la
double paie de A2 (30 495,60 DH de charges en trop) → base fiscale minorée de 30 495,60 DH → IS minoré de
**6 099,12 DH** par rapport à l'IS de 19 960,00 DH déjà comptabilisé au grand livre (compte 6701).
**Correctif** : sans objet propre — le correctif de A2 (purge de l'écriture de paie de recette + contrôle de
recouvrement) rétablit la base ; ajouter à l'écran IS/liasse un **contrôle de cohérence** entre l'IS calculé et
l'IS comptabilisé (écart = alerte bloquante).

## 9. A9 — « Ouvrir un nouvel exercice » propose 2026 (déjà existant)

**Constat** : l'exercice 2026 existe (statut `open`, 95 écritures) ; le champ du formulaire est pré-rempli avec
**2026**. Si l'utilisateur valide, `get_or_create_fiscal_year` renvoie l'exercice existant et le message affiché est
« Exercice 2026 ouvert. » → l'utilisateur croit avoir créé un exercice (aucun doublon n'est créé, mais **aucun
avertissement** non plus).

**Cause racine** : `app/web/routes.py:1598` (`annee_courante=date.today().year`) + gabarit
`parametres_exercices.html:86` (`value="{{ annee_courante }}"`). Le formulaire ne propose pas le **premier exercice
libre** et ne signale pas qu'une année existe déjà.
**Correctif proposé** : pré-remplir `max(exercices) + 1` (avec `annee_courante` en repli) ; si l'année existe,
répondre « l'exercice X existe déjà (statut, N écritures) » au lieu de « ouvert ».

## 10. A10 — Réouverture d'un exercice sans contrôle

**Constat** : `POST /parametres/exercices/2025/open` **réouvre 2025** alors que 2026 contient 95 écritures et que
des à-nouveaux ont été générés — aucune vérification, aucun passage par le service de clôture, aucun motif exigé.

**Cause racine** : `app/web/routes.py:1620-1649` : `exercice.status = statut` est écrit **directement**
(`closed_at` remis à `None`), sans appel à `app/services/closing.py` ni à `period_locks`, alors que la clôture
(l. 2577) passe bien par le service. Les règles annoncées à l'écran (« toute réouverture est tracée ») ne sont
donc pas appliquées par ce chemin.
**Impacts** : incohérence des à-nouveaux, écritures possibles dans un exercice déjà reporté, piste d'audit
incomplète (aucune trace de l'événement de réouverture).
**Correctif proposé** : passer par un service unique `closing.reouvrir_exercice(year)` qui vérifie : (1) aucun
verrou de période, (2) **aucune écriture dans les exercices postérieurs**, (3) à-nouveaux non générés **ou** demande
de confirmation explicite avec **suppression/reversal tracé** des à-nouveaux, (4) motif obligatoire et écriture
dans la piste d'audit ; bloquer sinon.

## 11. Anomalies supplémentaires détectées (non signalées)

| # | Anomalie | Preuve / cause |
|---|---|---|
| S1 | **`/provisions` inexistant** (écran) alors que la table `stock_provisions` et l'API `/stocks/provisions` existent | 404 sur les 2 chemins testés ; aucune entrée au menu |
| S2 | **Journal comptable absent du menu** | `base.html` : seuls Balance / Grand livre / CPC / Bilan figurent |
| S3 | **Grand livre sans colonne « Pièce/Référence »** | `etats_grand_livre.html:59` ; les écritures du jeu portent pourtant `reference = FA26-12` |
| S4 | **Règlements sans écriture comptable** (`payments.entry_id = NULL` pour les 142 règlements) | le règlement est bien décaissé au journal mais sans lien vers sa ligne d'écriture → traçabilité du lettrage incomplète |
| S5 | **TVA sur immobilisations logée au 34552** (charges) au lieu de `34551` | écritures du jeu ; la fiche immo porte pourtant `tva_compte = 34551` → écart de ventilation dans la déclaration |
| S6 | **Déclarations fiscales de recette atypiques** : `tax_declarations` TVA période « 2026 » avec `regime = 4` (cession-cessation) et DTS `fiscal_year_id = NULL` | enregistrements créés par la recette (P2.2/P2.3) : aucune règle de format de période/regime n'est imposée à l'enregistrement |
| S7 | **L'écran de déclaration de TVA ne justifie pas les montants** : aucune liste de factures/détail ligne à ligne (0 occurrence de FA26-12 sur `/tva?year=2026&month=12`) | la déclaration est calculée par agrégats (`vat_summary_by_rate`) sans table de détail auditable |
| S8 | **Écran `/etats/liasse.xml` → 303** (redirection) car l'exercice/l'annexe A22 n'est pas validé | comportement voulu, mais le message gagnerait à être explicite sur la cause |

## 12. Ce qui a été vérifié **conforme** (pour mémoire)

- Équilibre partie double 2025/2026, bilan actif = passif, CPC, balance, grand livre, journal.
- Cohérence factures ↔ écritures ↔ règlements (`0` facture dont les lignes ne réconcilient pas l'en-tête ;
  `0` ligne à montant nul ; créances 25 920 / dettes 6 480 / stocks 25 000 / immobilisations 90 000 réconciliés).
- PDF facture (mentions CGI art. 145, ventilation par taux, duplicata), PDF états, bordereaux.
- E-invoice : XML cohérent (`montantHT 30 000 / montantTva 6 000 / montantTtc 36 000`) pour les 8 factures générées.
- Chaîne d'audit scellée 184/184 sans rupture ; écriture dans un exercice clos refusée.
- 40 écrans GET balayés : **34 en 200**, 3 en 401 (anomalie A1), 3 redirections 303 normales
  (`/connexion`, `/deconnexion`, `/etats/liasse.xml`), `/provisions` en 404 (écran inexistant).

## 13. Plan de correctifs proposé (à valider — **rien n'a été modifié**)

| Priorité | Correctif | Fichiers concernés |
|---|---|---|
| **P0** | Monter l'interface **avant** l'API (ou préfixer l'API) → rétablit `/audit`, `/stocks`, export CSV | `app/main.py` |
| **P0** | Proratiser `mht` **et** `tva` du relevé EDI (+ contrôle `mht×tx/100 == tva`, `ttc = mht+tva`) | `app/services/edi_tva.py` |
| **P0** | Corriger `detail()` (comparaison par `startswith`) → ETIC notes 4 et 9 | `app/services/etats_synthese.py` |
| **P1** | Contrôle de recouvrement paie ↔ comptabilité + purge de l'écriture de paie de recette | `app/services/payroll.py`, données |
| **P1** | Réouverture d'exercice via service + contrôles (verrous, écritures postérieures, à-nouveaux, motif, audit) | `app/web/routes.py`, `app/services/closing.py` |
| **P1** | Contrôles greffe bloquants (date d'AG, pièces non vides/dupliquées, dépôt avant paiement) | `app/services/greffe.py` |
| **P2** | Refus des lignes de facture à montant nul ; écran « Provisions » ; lignes de menu ; colonne « Pièce » au GL | `invoicing.py`, `web/`, `templates/` |
| **P2** | Formulaire d'exercice : proposer le premier exercice libre + message si l'année existe | `web/routes.py`, `parametres_exercices.html` |
| **P2** | Reclassement 2340 → 2332/2355 (dossier de test) et arbitrages A6/A24/A25 déjà ouverts | données / arbitrages |

**Preuves brutes reproductibles** : `.\.venv\Scripts\python.exe tools\j9_audit_anomalies.py`
(régénère `AUDIT_ANOMALIES_J9.txt`, aucune écriture en base).




