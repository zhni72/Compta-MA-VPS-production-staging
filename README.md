# Compta MA — comptabilité marocaine en Python (type Sage)

Application de **comptabilité et facturation CGNC** pour le Maroc, écrite en Python
(FastAPI + SQLAlchemy 2), conçue **mono-utilisateur** pour démarrer et **prête à passer
en multi-utilisateurs** sur un serveur distant sans réécriture métier.

- Cahier des charges complet : [`CAHIER_DES_CHARGES.md`](CAHIER_DES_CHARGES.md)
- Conformité visée : **CGNC / PCGE**, **CGI 2026** (TVA 20 % / 10 %, IS, cotisation
  minimale), **CNSS / AMO 2026**, mentions légales de facture (ICE), facturation
  électronique (art. 145 CGI).

> ⚠️ Les taux et obligations implémentés correspondent à l'exercice **2026**
> (Loi de Finances 50-25). Toute mise en production doit être validée par un
> **expert-comptable agréé** au Maroc.

---

## 1. Démarrage rapide (phase 1 — SQLite, mono-utilisateur)

```powershell
cd compta_ma
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 1) Schema de base (migrations Alembic) + amorcage des referentiels
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.db.seed

# 2) Lancer l'API
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- Documentation interactive : <http://127.0.0.1:8000/docs>
- Compte créé par défaut : `admin@compta.ma` / `Admin@2026` (**à changer
  immédiatement**, voir `--email` / `--password`).

### Commandes utiles

| Objectif | Commande |
|---|---|
| Créer les tables sans Alembic (démo rapide) | `python -m app.db.seed --create-tables` |
| Importer un plan comptable complet | `python -m app.db.seed --plan mon_plan.csv` |
| Régénérer le plan depuis le PDF officiel | `python tools/plan_pdf_to_csv.py "Plan_Comptable_Marocain.pdf"` |
| Lancer les tests | `python -m pytest` |
| Appliquer les migrations | `python -m alembic upgrade head` |

### Interface graphique (français, type Sage Comptabilité)

L'application n'est **pas** une simple API : elle est livrée avec une interface
graphique complète, en français, dans le style des logiciels de gestion marocains
(Sage, Ciel) — bandeau, navigation latérale, fil d'Ariane, tableaux denses,
montants au format marocain (`1 234 567,50 DH`) et dates `18/09/2026`.

Ouvrez <http://127.0.0.1:8000/> puis connectez-vous (`admin@compta.ma` / `Admin@2026`).

| Groupe | Écrans |
|---|---|
| Tableau de bord | Résultat, charges, TVA de la période, trésorerie, créances clients, dettes fournisseurs, prochaine échéance TVA, dernières factures |
| Commerce | Clients & fournisseurs (+ fiche avec grand livre et documents), factures de vente, factures d'achat, avoirs, règlements |
| Comptabilité | Saisie des écritures (avec contrôle d'équilibre en direct), journal comptable, plan comptable PCGE (890 comptes), **immobilisations** (fiches, plans d'amortissement linéaire/dégressif, dotations, cessions, mises au rebut, régularisation TVA art. 106 — jalon J2) |
| États comptables | Balance générale (récapitulatif par classe), grand livre, compte de produits et charges, bilan avec contrôle d'équilibre — **export PDF des états de synthèse CGNC** (bilan brut / amortissements / net, CPC, **ESG**, **ETIC**) et **bordereau de dépôt au greffe** (jalon J1) |
| Fiscalité | Déclaration de TVA (collectée / déductible / net à payer ou crédit, échéance du 20, ventilation par taux, barème 2026), **relevé des déductions en XML pour la DGI** (EDI) et **bordereau PDF du relevé** (récapitulatif exact du fichier déposé : lignes, totaux, exclusions, anomalies) |
| Paramètres | Fiche société (ICE, IF, RC, patente, CNSS, régime TVA), exercices (ouvrir / clôturer / verrouiller), utilisateurs & rôles avec matrice des droits |

Actions typiques : création de tiers avec **sous-compte PCGE automatique** (34210001),
facture avec lignes multiples et calcul TVA en direct (20 % / 10 %), validation en un
clic (numéro + écriture comptable générée), règlement partiel ou total, annulation avec
contre-écriture, impression de facture aux **mentions légales marocaines** (ICE, IF, RC,
patente, CNSS, ventilation de TVA) prête pour le format A4 / PDF.

> L'API REST reste disponible sur <http://127.0.0.1:8000/docs> pour les intégrations
> (elle n'est plus l'interface principale : l'écran d'accueil est le tableau de bord).

---

## 2. Plan comptable (CGNC / PCGE)

`app/data/plan_comptable_cgnc.csv` contient **890 comptes** (classes 0 à 9, comptes
principaux à 4 chiffres et divisionnaires à 5-6 chiffres) **extraits du plan
comptable marocain officiel** fourni par l'utilisateur
(`Plan_Comptable_Marocain.pdf`).

Le convertisseur `tools/plan_pdf_to_csv.py` :

- lit la hiérarchie **rubrique (2 chiffres) / poste (3 chiffres) / compte (4+)** ;
- **ne retient un compte que si son poste parent existe**, ce qui élimine les faux
  positifs (numéros de page, dates) ;
- marque comme **collectifs** les comptes de regroupement `3421`, `4411`, `3455`
  (la saisie se fait sur leurs divisionnaires, ex. `34210001`).

Comptes clés utilisés par l'application (vérifiés dans ce plan) :

| Usage | Compte |
|---|---|
| Clients | `3421` (+ sous-comptes `34210001`…) |
| Fournisseurs | `4411` (+ sous-comptes `44110001`…) |
| Personnel (avances) | `3431` |
| TVA récupérable (immobilisations / charges) | `3455` / `34552` |
| TVA facturée / TVA due | `4455` / `4456` |
| Banque / Caisse | `5141` / `5161` |
| Achats de marchandises / Ventes de marchandises au Maroc | `6111` / `7111` |
| Charges constatées d'avance | `3491` |

Les sous-comptes de tiers sont **créés automatiquement** lors de la création d'un
tiers (`services/parties.py`), sans casser la codification.

---

## 3. Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Les tests couvrent : barèmes 2026 (IR, CNSS/AMO, IS, cotisation minimale), équilibre
des écritures, immuabilité d'une écriture validée, contre-écriture, numérotation
continue sans trou, TVA multi-taux, déclaration TVA, ventilation ventes/achats,
règlements, CPC, bilan équilibré, contrôle des identifiants (ICE 15 chiffres, IF
**7 ou 8 chiffres, tel quel**), export EDI (ordre des balises du XSD, `<tx>` en
pourcentage, limite de lignes paramétrable, période rattachée au règlement, prorata
art. 106, ventilation CGNC `34551`/`34552`), outils d'import (mapping PCGE
`6141` → `61473`, exclusion des lignes à TVA nulle, plan comptable 890 comptes),
API (authentification, RBAC, flux facture → états), interface web, immobilisations
(amortissements, cessions), audit (chaînage SHA-256, verrouillages, à-nouveaux, banque),
**stocks** (CMUP, FIFO sur trois lots, inventaire, dépréciations, variation) et **dépôt
greffe** (checklist par forme juridique, 7 états du portail, alerte 3 jours, archive ZIP,
certificat), **paie & DTS « 9421 »** (bulletins, barèmes historisés, écritures, DTS XML/EFI),
**résultat fiscal / IS / cotisation minimale** (réintégrations, report déficitaire, acomptes,
contrôles d'exercice clos) et **assembleur de liasse** (contrat des XSD officiels, référentiel
de codification, alimentation balance/immobilisations/stocks/paie, EFI assisté, **fichier XML
EDI validé par le schéma**, API `/liasse`, écran `/liasse`, registre `tax_declarations` avec
accusé de réception), **cessation / cession d'activité** (événements, TVA des régimes **3** et
**4**, régularisation des déductions, relevé EDI, registre) et **facture électronique**
(mentions obligatoires, fichier interne, canal DGI paramétrable, accusés). Base **SQLite en
mémoire**, isolée par test.

---

## 3 bis. Export EDI du relevé des déductions (TVA)

Écrans `/tva/edi` (préparation, contrôles, anomalies) et `/tva/edi/xml`
(téléchargement), également disponibles via l'API (`/api/v1/vat/edi/check`,
`/api/v1/vat/edi/rd`).

Le fichier généré est conforme au **schéma XSD officiel de la DGI** (modèle EDI
« ADC082F-15I », article 112 du CGI — fichier de référence `TVA-EDI.xlsm`) :

- ordre des balises imposé par le schéma : `identifiantFiscal`, `annee`, `periode`,
  `regime`, `releveDeductions` → `rd` (`ord`, `num`, `des`, `mht`, `tva`, `ttc`,
  `refF` → `if`, `nom`, `ice`, `tx`, `mp` → `id`, `dpai`, `dfac`) ;
- **`<tx>` en pourcentage** (`<tx>20</tx>`) : unité confirmée par un dépôt accepté
  par la DGI (l'option `tx_unit=ratio` produit `0.20`, disponible par prudence) ;
- **`<prorata>` non déclarée dans le XSD** → balise **omise par défaut**
  (`prorata=1` pour l'ajouter : elle est alors écrite **en pourcentage**, comme
  l'exemple officiel DGI `<prorata>70</prorata>`) ;
- **IF du déclarant et des fournisseurs sur 7 ou 8 chiffres, utilisé tel quel**
  (`1084612`, `1086826` : **aucun zéro n'est ajouté ni retiré**) ;
- contrôle bloquant si le relevé dépasse la **limite de lignes** (paramétrable via
  `settings.max_rd_lines`, défaut prudent **127** car `<ord>` est un `xs:byte` dans le XSD),
  si le fichier est vide, si l'ICE (15) ou l'IF d'un tiers est invalide ou si le
  fichier dépasse 1 Mo ; mentions CGI rappelées : dépôt XML (jamais ZIP), période
  du 1er au 10 du mois suivant le trimestre, déclaration en brouillon au préalable ;
- **période rattachée à la date de paiement** par défaut : le modèle DGI intitule la
  colonne du régime « REGIME(Encais-1) », la déduction s'exerce donc au règlement.
  L'écran et l'API permettent de basculer sur la **date de facture** ; une facture
  réglée en plusieurs fois n'est déduite que de la **fraction réglée** (l'incrément
  de TVA de la période), ce qui interdit tout double emploi entre périodes ;
- **prorata de déduction** (CGI art. 106) : champ « Prorata de déduction (%) » sur
  l'écran (ou `prorata=0.90` sur l'API) ; la TVA déclarée est réduite d'autant
  (100 % par défaut). La balise `<prorata>` n'est écrite que si elle est demandée ;
- **TVA déductible ventilée selon le CGNC** : `34551` « TVA récupérable sur
  immobilisations » pour une dépense portée par un compte de classe 2, `34552`
  « TVA récupérable sur charges » sinon.

**Injection d'un tableau d'achat fournisseurs** (fichier `|` : date, n° fournisseur,
IF/ICE, montants, mode et date de règlement, comptes) :

```powershell
# simulation (aucune écriture) puis écriture réelle (sauvegarde automatique de la base)
.\.venv\Scripts\python.exe tools\import_achats_fournisseurs.py
.\.venv\Scripts\python.exe tools\import_achats_fournisseurs.py --appliquer `
    --if-societe 01234567 --ice-societe 001234567000099
```

L'outil applique les corrections de plan comptable (`6141` « Études, recherches et
documentation » → `61473` « Frais et commissions sur services bancaires »), écarte
les lignes à **TVA nulle** (aucune déduction possible et hors relevé), crée les
tiers manquants avec IF (7 ou 8 chiffres, tel quel) et ICE (15) contrôlés, ouvre les exercices
absents, valide les factures puis enregistre les règlements — c'est le règlement
qui déclenche la déduction — et journalise chaque ligne dans
`%TEMP%\compta_ma_import\journal_import_achats.csv`. Le tableau de référence du
dossier est `tools/data/achats_fournisseurs_2025_2026.txt`.

**Normalisation des fiches existantes** (si des IF ont été saisis sur 7 chiffres) :

```powershell
.\.venv\Scripts\python.exe tools\normalize_fiscal_ids.py              # vérification seule (simulation)
.\.venv\Scripts\python.exe tools\normalize_fiscal_ids.py --retirer-zero-initial --appliquer
```

---

## 4. Passage en multi-utilisateurs (phase 2)

Aucune réécriture métier : **une seule variable d'environnement change**.

```powershell
# .env
DATABASE_URL=postgresql+psycopg://compta:motdepasse@localhost:5432/compta_ma
SECRET_KEY=<48 caracteres aleatoires>
$env:DATABASE_URL="postgresql+psycopg://..."
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Ce qui est déjà en place pour le multi-utilisateur :

1. **Multi-tenant dès le jour 1** : toutes les tables métier portent `company_id`
   et `fiscal_year_id`.
2. **Authentification** JWT (Argon2id) et **RBAC** : `ADMIN`, `EXPERT_COMPTABLE`,
   `COMPTABLE`, `CAISSIER`, `COMMERCIAL`, `LECTEUR`.
3. **Piste d'audit** (`audit_log`) sur validation d'écriture, facture, annulation,
   règlement.
4. **Verrouillage optimiste** (`row_version` sur écritures et factures) et
   numérotation protégée par `SELECT … FOR UPDATE` (actif sur PostgreSQL).
5. **Exercices** `open` → `closed` → `locked` : saisie refusée hors exercice ouvert.

---

## 5. Déploiement sur serveur distant (phase 3)

```bash
cp .env.example .env      # renseigner DATABASE_URL et SECRET_KEY
docker compose up -d --build
docker compose exec app python -m alembic upgrade head
```

- `docker compose` fournit **PostgreSQL 16** + l'application ; placer un reverse
  proxy **Nginx/Caddy avec HTTPS** devant le port 8000.
- Sauvegardes : `pg_dump` quotidien + copie hors site ; **tester la restauration**.
- Supervision : `/health` (sondes) et la documentation `/docs`.

### Connecteur de facturation électronique (art. 145 CGI, loi 43-20)

Le décret d'application et la spécification technique de la plateforme DGI
(modèle *clearance*) **ne sont pas publiés** à ce jour : la conformité est isolée
pour être branchée sans refonte. Prévoir le format **UBL 2.1 / XML**, la signature
électronique (lois 43-20 et 53-05) et le PDF signé. **Ne pas confondre** avec
SIMPL-TVA (portail de télédéclaration).

---

## 6. Arborescence

```
compta_ma/
├── CAHIER_DES_CHARGES.md      # cahier des charges v1.0 (cadrage, conformité, phases, jalons)
├── CAHIER_DES_CHARGES_GLOBAL.md # ★ CDC GLOBAL v2.0 : vision, architecture, modules P1/P2/P3,
│                              #   cohérence inter-modules, référentiels, écarts d'audit, roadmap
├── README.md
├── requirements.txt / .env.example / .gitignore
├── Dockerfile / docker-compose.yml
├── alembic.ini / alembic/     # migrations (SQLite -> PostgreSQL sans changement de code)
├── pytest.ini
├── referentiels/               # REFERENTIELS OFFICIELS : XSD de la liasse et annexes TVA
│   ├── liasse/                 #   (normal, comptable simplifié, assurances, établissements
│   │                           #   de crédit) + codification_liasse.csv + LISEZ-MOI.md
│   └── tva/                    #   annexe 1 « correspondance balise RD V4.0 » (régimes 3 et 4)
│                               #   + exemple officiel du relevé des déductions
├── tools/                     # plan_pdf_to_csv, normalize_fiscal_ids,
│                              # charger_plan_comptable, import_achats_fournisseurs,
│                              # liasse_codification (contrat XSD, gabarit, vérification),
│                              # poc_pdf (POC moteur PDF — décision D1 : ReportLab)
│                              # (+ tools/data : tableau d'achat fournisseurs de reference)
├── app/
│   ├── main.py                # application FastAPI
│   ├── core/                  # config, securite (Argon2/JWT), audit, numerotation,
│   │                          # baremes marocains 2026 (rates_ma.py)
│   ├── db/                    # Base, session, seed (plan comptable, TVA, societe, admin)
│   ├── models/                # 43 tables SQLAlchemy 2.0 (multi-tenant company_id)
│   ├── schemas/               # validation des entrees/sorties Pydantic
│   ├── services/              # METIER : comptabilite, facturation, tiers, TVA, etats,
│   │                          # etats_synthese (ESG/ETIC), assets (immobilisations), PDF
│   │                          # (pdf.py + pdf_documents.py), stocks, greffe, payroll,
│   │                          # fiscal_liasse (resultat fiscal, IS/CM, controles J7),
│   │                          # liasse_edi (assembleur de liasse, EFI assiste J7),
│   │                          # activity_events (cessation/cession, TVA 3 et 4 — J8),
│   │                          # e_invoice (facture electronique, canal DGI — J8)
│   ├── api/                   # deps (JWT, RBAC), erreurs, routeurs REST
│   ├── web/                   # INTERFACE GRAPHIQUE : gabarits Jinja2, CSS, routes HTML
│   └── data/plan_comptable_cgnc.csv
└── tests/                     # 300 tests (services, API, interface, EDI, PDF, immobilisations, audit, stocks, greffe, paie, IS/liasse, cessation/cession, e-facturation)
```

---

## 7. API (extrait)

> **Préfixe `/api` (régularisation P0 de l'audit J9)** : toutes les routes de ce
> tableau sont montées sous **`/api`** (`POST /api/auth/token`, `GET /api/invoices`…) ;
> la documentation interactive reste sur <http://127.0.0.1:8000/docs>. Cette isolation
> est **structurelle** : une route API ne peut plus jamais intercepter un écran
> (`/audit`, `/stocks`…), quel que soit l'ordre de montage (voir § 18).

| Méthode et route (préfixe `/api`) | Rôle |
|---|---|
| `POST /auth/token`, `GET /auth/me` | Connexion (JWT), profil |
| `POST /auth/users` | Créer un utilisateur (ADMIN) |
| `GET/POST /companies`, `/companies/{id}/fiscal-years` | Dossiers et exercices |
| `GET /accounts`, `POST /accounts` | Plan comptable CGNC |
| `GET/POST /parties`, `GET /parties/balance` | Tiers + balance auxiliaire |
| `POST /invoices` (`auto_validate`), `/invoices/{id}/validate` | Facture : brouillon → validée (n° + écriture) |
| `/invoices/{id}/payments`, `/invoices/{id}/cancel` | Règlements, annulation (contre-écriture) |
| `GET/POST /entries`, `/entries/{id}/validate`, `/entries/{id}/reverse` | Écritures, extourne |
| `GET /vat/return`, `/vat/rates`, `/vat/regime` | Déclaration TVA, barème, régime |
| `GET /vat/summary-by-rate?type=vente\|achat` | Ventilation par taux (collectée ou déductible) |
| `GET /vat/edi/check`, `GET /vat/edi/rd` | Contrôles et **fichier XML du relevé des déductions** (DGI) |
| `GET /reports/balance`, `/grand-livre`, `/journal`, `/cpc`, `/bilan` | États comptables |
| `GET /reports/esg`, `/reports/etic` | Soldes de gestion (ESG) et notes annexes (ETIC) |
| `GET /reports/{bilan\|cpc\|esg\|etic}/pdf` | **États de synthèse au format PDF** (montants identiques à l'écran) |
| `GET /reports/bordereau-greffe/pdf` | **Bordereau + checklist du dépôt au greffe** (PDF) |
| `GET /invoices/{id}/pdf?duplicata=` | **Facture PDF** (mentions CGI art. 145, original ou duplicata) |
| `GET /vat/edi/bordereau` | **Bordereau PDF du relevé des déductions** (récapitulatif du XML déposé) |
| `GET/POST /assets` | **Immobilisations** : lister / créer une fiche (compte 2xxx, durée, mode, TVA 34551) |
| `GET /assets/{code}`, `/assets/comptes/{compte}` | Fiche + plan d'amortissement ; comptes dérivés du PCGE (28x / 619x) |
| `POST /assets/{code}/dotation`, `POST /assets/dotations` | Dotation d'un exercice (6193x / 283x) ; traitement en masse des biens en service |
| `POST /assets/{code}/cession`, `POST /assets/{code}/rebut` | Cession (7513 / 6513 / 3481 + TVA) et mise au rebut (VNA en charge) |
| `GET /assets/etat`, `/assets/cessions`, `/assets/amortissements`, `/assets/controles` | États du module : brut/amortissements/net par poste, cessions, amortissements déductibles, contrôles de cohérence |
| `GET /audit`, `GET /audit/export` | **Journal d'audit** filtrable (action, entité, utilisateur, dates) et **export CSV** (masquage loi 09-08) |
| `GET /audit/chainage`, `POST /audit/chainage/sceller`, `GET /audit/ecritures/{id}/piste` | Contrôle de la piste fiable (SHA-256 chaîné), scellement des écritures, piste d'une écriture |
| `GET/POST /audit/verrouillages`, `DELETE /audit/verrouillages/{id}` | **Verrouillage** de mois ou d'exercice, déverrouillage motivé |
| `POST /audit/cloture/{annee}`, `/audit/cloture/{annee}/reouvrir`, `GET /audit/cloture/{annee}` | **Clôture** avec génération des **à-nouveaux**, réouverture, état des à-nouveaux |
| `GET/POST /audit/releves`, `GET /audit/releves/{id}`, `POST /audit/releves/{id}/rapprocher-auto` | **Rapprochement bancaire** : import du relevé, état de rapprochement, appariement automatique |
| `POST/DELETE /audit/releves/lignes/{id}/rapprocher`, `GET /audit/alertes` | Appariement/ajustement manuel, alertes d'écarts anciens (> 3 mois) |
| `GET/POST /stocks`, `GET /stocks/{reference}` | **Stocks** : lister / créer une fiche article (compte 3xxx, seuil, CMUP ou FIFO) ; fiche + mouvements et file FIFO |
| `POST /stocks/{reference}/mouvements` | Entrée (coût de revient obligatoire) ou sortie valorisée CMUP / FIFO + écriture **3111 / 6114** |
| `POST /stocks/{reference}/provisions` | **Dépréciation** de stock (prudence) : dotation **61961 / 391x** ou reprise |
| `POST /stocks/inventaire`, `GET /stocks/inventaire` | **Inventaire physique** (écarts valorisés, visa obligatoire au-delà de 5 %) ; feuille de comptage |
| `GET /stocks/etat`, `/stocks/variation`, `/stocks/provisions`, `/stocks/controles` | État de stock valorisé et réconcilié, variation de stocks, dépréciations, contrôles de cohérence |
| `POST /stocks/journal`, `POST /stocks/mouvements/comptabiliser` | Constatation du **stock final** (régime intermittent) ; comptabilisation en masse des mouvements |
| `GET /greffe/pieces`, `GET/POST /greffe/depots` | **Greffe** : catalogue des pièces par forme juridique ; lister / créer le dossier de dépôt d'un exercice (date limite = clôture + 6 mois) |
| `GET /greffe/depots/{id}` et `/checklist`, `/controles` | Fiche du dossier, **checklist** (complétude) et **contrôles bloquants** avant soumission |
| `GET/POST /greffe/depots/{id}/pieces`, `POST .../pieces/generer`, `DELETE .../pieces/{code}` | Téléverser une pièce **PDF ≤ 10 Mo**, générer les pièces Compta MA (états + bordereau + attestation), retirer une pièce |
| `POST /greffe/depots/{id}/etat` | Cycle de vie des **7 états** du portail (motif obligatoire pour rejet, annulation, amender, dépôt final) |
| `POST /greffe/depots/{id}/paiements` | Paiement des **taxes** (CMI) — l'alerte **3 jours** s'éteint au paiement |
| `POST /greffe/depots/{id}/certificat`, `POST .../amende` | Archiver le **certificat de dépôt** (SHA-256) ; provisionner l'**amende hors délai** (6195 / 1515) |
| `GET /greffe/depots/{id}/dossier`, `/bordereau`, `/attestation-paiement`, `/certificat` | **Archive ZIP** (pièces + bordereau + manifeste des empreintes) et téléchargements PDF |
| `GET /greffe/etat`, `GET /greffe/alertes` | Suivi des dépôts par exercice (compteurs par état) et **alertes de délais** (3 jours, AG 6 mois, rejet, amende) |
| `GET/POST /payroll/employees`, `GET /payroll/employees/{référence}` | **Paie** : lister / créer une fiche salarié (CIN, CNSS, situation de famille, enfants, exonération 57-20°) ; fiche + contrats |
| `POST /payroll/employees/{référence}/contrats` | Élément contractuel de rémunération (salaire de base, primes, avantages, taux, **date d'effet**) |
| `POST /payroll/runs`, `GET /payroll/runs/{période}` | Préparer (calculer) la paie d'une période ; cycle + bulletins + contrôles |
| `POST /payroll/runs/{période}/valider`, `/payer` | **Écriture de paie** (débit 617x / crédit 444x, 4452, 4432) puis **règlement** (5141 / 5161) |
| `GET /payroll/controles`, `/journal`, `/livre`, `/cotisations`, `/recapitulatif` | Contrôles de la paie, journal de paie, **livre de paie annuel**, cotisations et IR par mois, récapitulatif annuel |
| `GET /payroll/bulletin/{id}/pdf` | **Bulletin de paie** (PDF, gabarit P1.1) |
| `GET /payroll/dts/{année}`, `/xml`, `/efi`, `/fiche-pdf`, `/validation-xsd` | **DTS « 9421 »** : modèle déclaratif, **fichier XML EDI**, **état de saisie EFI**, fiche récapitulative PDF, validation XSD (si schéma fourni) |
| `POST /payroll/dts/{année}/declaration`, `POST /payroll/dts/declarations/{id}/depot`, `GET /payroll/dts/declarations` | Enregistrer la DTS (fichier + **SHA-256**), tracer le dépôt et l'**accusé de réception**, consulter le registre |
| `GET /liasse/{année}`, `GET /liasse/declarations` | **IS & liasse** : dossier de l'exercice (résultat fiscal, IS / cotisation minimale, liasse, contrôles, EFI, registre) ; registre des liasses |
| `GET /liasse/{année}/efi`, `/efi.csv` | **EFI assisté par tableau** (`codeEdi`, libellé, valeur, lignes à compléter) en JSON ou CSV |
| `GET /liasse/{année}/xml`, `/validation-xsd` | **Fichier XML EDI** (refusé si bloquant ou si le schéma le rejette) et **validation XSD réelle** (conforme / refusé / validation impossible) |
| `POST /liasse/{année}/enregistrer`, `POST /liasse/{année}/depot` | Enregistrer la liasse (déclaration brouillon + fichier et **SHA-256**) puis tracer le **dépôt et l'accusé de réception** (soumise / acceptée / rejetée) |

En-tête `X-Company-Id` pour choisir le dossier (facultatif en phase 1 : la première
société active est utilisée).

---

## 8. Règles comptables appliquées

1. **Équilibre obligatoire** : débit = crédit, contrôlé avant validation.
2. **Immuabilité** : une écriture ou une facture validée ne se modifie pas ; la
   correction passe par une **contre-écriture** (extourne) ou un **avoir**.
3. **Numérotation continue, sans trou** : le numéro est attribué à la validation et
   un document annulé **conserve** son numéro.
4. **ICE obligatoire** sur les factures de vente entre professionnels (les
   particuliers en sont dispensés) : la validation est refusée sinon.
5. **Taux en base, historisés** : aucun taux fiscal codé en dur dans la logique
   métier (barème TVA 2026 : 20 % et 10 % uniquement).

---

## 9. Export PDF (jalon J1 — livré)

Moteur **ReportLab** (décision D1 ; WeasyPrint écarté : GTK absent sous Windows). Les
documents sont construits à partir des **mêmes services que l'écran**, donc avec des
**montants identiques au centime** :

| Document | Contenu |
|---|---|
| Bilan | Présentation CGNC **brut / amortissements et provisions / net**, équilibre et réconciliation avec l'écran contrôlés dans le document |
| CPC | Charges (classe 6), produits (classe 7), résultat (bénéfice / perte) |
| **ESG** | Marge brute, valeur ajoutée, EBE, résultats d'exploitation / courant / net — **cohérence ESG ↔ CPC contrôlée** |
| **ETIC** | 9 notes annexes calculées + **informations non disponibles listées** avec leur origine (paie, immobilisations, stocks) |
| Facture | Mentions légales (CGI art. 145), ventilation par taux, original / **duplicata** |
| Bordereaux | **Relevé TVA EDI** (lignes, totaux, exclusions, anomalies, nom du fichier) et **dépôt au greffe** (checklist, portail, délais) |
| Bulletin de paie | Interface documentée et testée, prête pour le module Paie (P1.4) |

Contraintes respectées : **PDF ≤ 10 Mo** (limite du portail greffe) contrôlé à chaque
génération ; mention **« PROVISOIRE »** (corps du document + filigrane) tant que
l'exercice n'est pas clôturé ; libellés normalisés pour les polices PDF.

---

## 10. Immobilisations & amortissements (jalon J2 — livré)

Gestion du cycle de vie complet de l'actif immobilisé (CGNC titre II chapitre I, CGI
art. 10 et 106) : **acquisition → mise en service → dotations → cession / mise au rebut**.

| Fonction | Contenu |
|---|---|
| Fiche d'immobilisation | Compte **2xxx**, fournisseur et facture d'origine, dates d'acquisition et de mise en service, valeur d'origine et résiduelle, durée, mode, coefficient, TVA ; numéro automatique `IM202600001` |
| Comptes dérivés du PCGE | Règle structurelle : `amortissement = « 28 » + poste`, `dotation = « 619 » + poste` (2332 → **2833 / 61933**, 2220 → 2822 / 61922) ; immobilisations financières (24x) et en cours (239x) identifiées comme non amortissables |
| Amortissement **linéaire** et **dégressif** | Annuité constante ou taux = (1 / durée) × coefficient appliqué à la VNC avec **bascule en linéaire** ; coefficients **paramétrables** (1,5 / 2,0 / 2,5) |
| **Prorata temporis** (CGI art. 10) | Mois entiers à partir de la mise en service, ou annuité pleine (option comptable) ; dernière annuité plafonnée à la valeur résiduelle |
| Dotations | Écriture **6193x / 283x** validée et numérotée, ligne de plan, événement tracé ; refus des doublons ; traitement **en masse** par exercice |
| Cessions / rebuts | **7513/7512** (produit), **6513/6512** (VNA), reprise des **28x**, **3481** ou encaissement — le compte 2xxx et son 283x sont **soldés à zéro** |
| **Régularisation TVA art. 106** | Fractions égales sur 5 ans (meubles) / 10 ans (immeubles), paramétrable, avec écriture et avertissement (durée à confirmer) |
| **TVA 34551 / 34552** | La TVA d'immobilisation va au **34551** ; un contrôle détecte toute TVA d'immobilisation logée au 34552 |
| États | **Brut / amortissements / net par poste**, réconcilié avec le grand livre (écarts affichés), amortissements fiscalement déductibles, tableau des cessions — écrans + PDF |
| Contrôles de cohérence | Bien sans durée ni mise en service, sortie sans motif, cession sans prix, dotation de l'exercice de cession manquante, écart fiches ↔ comptabilité |

Vérifications automatiques : `Σ amortissements cumulés + VNC = valeur d'origine` à chaque
exercice (au centime) et **soldes à zéro** du compte d'immobilisation et de son
amortissement après cession (contrôlés par les tests).

> ⚠️ **Point à confirmer** : les coefficients de l'amortissement dégressif (CGI art. 10) et
> la durée de régularisation de la TVA (CGI art. 106) sont **paramétrables** et affichés
> avec un avertissement tant que l'expert-comptable ne les a pas validés.

---

## 11. Audit & traçabilité (jalon J3 — livré)

Les comptes doivent être **défendables devant un contrôle** (DGI, expert-comptable,
commissaire aux comptes, greffe) : piste d'audit fiable, périodes verrouillables,
rapprochement bancaire outillé et journal d'audit exploitable (CGNC « organisation de la
comptabilité », CGI conservation 10 ans, **loi 09-08** pour les données personnelles).

| Brique | Contenu |
|---|---|
| **Piste d'audit fiable** | Empreinte **SHA-256** de chaque écriture validée + **chaînage** (`entry_hash` / `previous_hash`) : toute modification faite hors application **casse le chaînage** et est détectée ; les dossiers repris sont **scellés** en une action |
| **Navigation** | Écriture → **pièce d'origine** (facture, règlement, fiche d'immobilisation, à-nouveaux) et pièce → écritures produites |
| **Verrouillage de période** | Verrou de **mois** ou d'**exercice** : refus dur de la saisie, de la modification et de la suppression d'un brouillon ; **déverrouillage** réservé à l'ADMIN / l'EXPERT_COMPTABLE **avec motif** ; **tentatives refusées journalisées** |
| **Journal d'audit** | Filtres (action, entité, utilisateur, dates, recherche), export **CSV** (BOM UTF-8, séparateur `;`) avec **masquage des données personnelles** (loi 09-08) |
| **Rapprochement bancaire** | Import du relevé **CSV normalisé**, appariement **automatique** (montant exact, date proche) puis **manuel**, **ajustements** motivés, **état de rapprochement** (`solde comptable + écarts = solde bancaire`), **alerte** sur les écarts de plus de 3 mois |
| **Clôture & à-nouveaux** | La clôture contrôle l'**équilibre du bilan**, fige l'exercice et génère l'**écriture d'à-nouveaux** de l'exercice suivant (report des classes 1 à 5 dans le même sens + contrepartie du résultat au 1191/1199) : le bilan et le CPC des exercices suivants sont **complets** (correction de l'écart 9) |

Écrans : **Journal d'audit** (`/audit`, filtres + export + contrôle du chaînage + alertes) et
**Rapprochement bancaire** (`/rapprochement`) ; boutons « Clôturer + à-nouveaux » et
« Verrouiller » sur la page des exercices.

---

## 12. Stocks & inventaire permanent (jalon J4 — livré)

Suivi des articles en **quantité** et en **valeur**, avec la **méthode de valorisation
choisie** (CMUP ou FIFO), l'**inventaire physique**, les **dépréciations** et la
**variation de stocks** réglementaire (CGNC titre II chapitre II — actif circulant ;
CGNC titre V chapitre I — inventaire permanent).

| Brique | Contenu |
|---|---|
| **Fiche article** | Référence, désignation, unité, famille, **compte de stock 3xxx** (contrôlé dans le plan), comptes d'achat / de vente, **seuil d'alerte**, **mode de valorisation** (CMUP ou FIFO — le **LIFO est proscrit**) |
| **Comptes dérivés (CGNC)** | Variation : `311x → 6114`, `312x → 6124`, `313x → 7131`, `315x → 7132` ; provision : `311x → 3911`, `312x → 3912`, `313x → 3913`, `315x → 3915` ; dotation **61961** |
| **Entrées / sorties** | Entrée valorisée au **coût de revient** (frais accessoires inclus) : recalcule le **CMUP** ; sortie valorisée au **CMUP** ou selon la **file FIFO** ; motifs : achat, vente, retour, production, transfert, consommation, **perte/casse** |
| **Écritures** | **Inventaire permanent** : entrée `3111 / 6114`, sortie `6114 / 3111` — le coût des marchandises vendues = achats `6111` − variation `6114` ; **régime intermittent** : `constater_stock_final()` aligne les comptes de stock sur l'inventaire à la clôture |
| **Inventaire physique** | Saisie des quantités réelles, **écart théorique / physique valorisé** au CMUP, écriture de variation ; **visa motivé obligatoire** au-delà de **5 %** de la valeur du stock |
| **Dépréciations** | Provision si **valeur d'inventaire < valeur comptable** (prudence) : dotation **61961 / 391x**, **reprise** l'exercice suivant (seule la variation est comptabilisée) |
| **États** | **État de stock valorisé** (quantité, CMUP, valeur, réconciliation au grand livre), **feuille d'inventaire**, **variation de stocks** (initial / entrées / sorties / final), **état des dépréciations**, **liste des articles sous seuil** |
| **Contrôles** | Quantité négative, **cache de fiche divergent**, mouvement non comptabilisé, article sous seuil, **écart fiches ↔ comptabilité** |

Écran : **Stocks & inventaire** (`/stocks`) — création d'articles, entrées/sorties
valorisées, seuils d'alerte, contrôles de cohérence et constatation du stock final.
API : `/stocks`, `/stocks/{référence}`, `/stocks/{référence}/mouvements`,
`/stocks/{référence}/provisions`, `/stocks/etat`, `/stocks/inventaire`,
`/stocks/variation`, `/stocks/provisions`, `/stocks/controles`, `/stocks/journal`,
`/stocks/mouvements/comptabiliser`.

**Recette vérifiée** : CMUP recalculé après chaque entrée ; **FIFO sur 3 lots** (10 × 100,
10 × 200, 10 × 300 → sortie de 15 = **2 000 DH**) ; **Σ (qté × coût) = valeur du compte de
stock au centime** ; écriture de variation ramenant la balance à l'état de l'inventaire
physique ; provision / reprise ; seuil d'alerte ; **refus des mouvements rétroactifs** en
période verrouillée.

---

## 13. Dépôt au greffe du tribunal (jalon J5 — livré)

Dépôt annuel des **états de synthèse** au greffe du tribunal via le portail
`https://depotbilan.justice.gov.ma` : **checklist des pièces** par forme
juridique, **suivi des 7 états** du portail, **alertes de délais** (paiement sous
3 jours, AG hors délai), **archive ZIP** du dossier et **archivage du
certificat** de dépôt.

**Base légale et source opérationnelle** : **loi 5-96** (art. 10 — AG dans les
**six mois** de la clôture ; art. 93 — publicité par dépôt de pièces au greffe du
tribunal du siège social), **loi 17-95** (art. 14) pour les SA, et le **guide
officiel « Dépôt électronique des états de synthèse »** (Ministère de la Justice,
**novembre 2025**).

| Brique | Contenu |
|---|---|
| **Dossier de dépôt** | Un dossier **par exercice** : forme juridique, date d'AG, **date limite de dépôt** (clôture + 6 mois), dates de soumission / approbation / limite de paiement / dépôt, taxes, amende, référence et empreinte du certificat |
| **Checklist des pièces** | États de synthèse (bilan + CPC + ESG + ETIC, **fusionnés en un PDF**), rapport de gestion, PV de l'AG, état complémentaire (bordereau), justificatif de paiement ; **rapport du CAC** obligatoire pour la SCA (« si CAC nommé » pour SA/SARL) ; **tableau de financement** selon seuils |
| **Suivi des 7 états** | **Nouveau → En cours → Approuvé → Déposé**, plus **Annulé**, **Rejeté** et **Amender** (dépôt hors délai) : transitions contrôlées, **motif obligatoire** (rejet, annulation, amende, dépôt final) et **journal des états** par dossier |
| **Alerte « 3 jours »** | Après approbation, la limite de paiement est à **+3 jours** : alerte orange puis **rouge (rejet automatique)** au-delà ; elle **disparaît au paiement**, et le dépôt final est **refusé** tant que les taxes ne sont pas intégralement réglées |
| **Alerte amende** | AG au-delà de 6 mois (ou absente) : avertissement puis blocage à la soumission ; état **« Amender »** → alerte rouge et **provision de l'amende** (dotation **6195** / provision **1515**) sur saisie du montant notifié |
| **Contrainte PDF ≤ 10 Mo** | Refus de tout fichier non PDF et de toute pièce > **10 Mo** (limite du portail), **empreinte SHA-256** et taille archivées par pièce, intégrité revérifiée avant chaque dépôt |
| **Assembleur ZIP** | `00_bordereau_recapitulatif.pdf` + pièces `NN_piece_libelle.pdf` + `manifeste.json` (empreintes, tailles, délais, taxes) : **refusé** si un contrôle bloquant subsiste, **altération détectée** par empreinte |
| **Certificat de dépôt** | Archivage du certificat signé (PDF, **SHA-256**), référence, date : la preuve légale est téléchargeable depuis l'exercice |

Écran : **Dépôt greffe** (`/greffe`) — dossier de l'exercice, checklist,
contrôles bloquants, alertes, téléversement des pièces, suivi des états, paiement
des taxes, certificat, téléchargements (ZIP, bordereau, attestation). API :
`/greffe/pieces`, `/greffe/depots`, `/greffe/depots/{id}` (+ `/checklist`,
`/controles`, `/pieces`, `/etat`, `/paiements`, `/certificat`, `/amende`,
`/dossier`, `/bordereau`, `/attestation-paiement`), `/greffe/etat`,
`/greffe/alertes`.

> **À compléter avant exploitation** : renseigner la **forme juridique**, le
> **RC**, l'**IF** et l'**ICE** de la société (écran Société) — le portail exige
> le n° de registre de commerce et l'application bloque la soumission sans ces
> identifiants. Les pièces PDF sont archivées sous `media/greffe` : **inclure ce
> répertoire dans la sauvegarde**.

---

## 14. Paie & DTS « 9421 » (jalon J6 — livré)

Bulletins de paie, **écritures de paie** et **déclaration des traitements et
salaires (DTS « 9421 »)** déposable sur les téléservices SIMPL de la DGI, avec
les **barèmes marocains historisés**.

| Brique | Contenu |
|---|---|
| **Fiches salariés** | Matricule, nom, **CIN**, **n° CNSS**, situation de famille, **enfants** (IR), dates d'entrée/sortie, contrat (CDI/CDD/ANAPEC…), RIB, **exonération art. 57-20°** (nouveaux recrutements) — données personnelles (loi 09-08) |
| **Contrats** | Salaire de base, primes (transport, logement, autres), indemnité de représentation, avantages en nature, taux de retraite/mutuelle/assurance groupe, **date d'effet** (historisation) |
| **Calcul du bulletin** | Brut imposable → **CNSS 4,48 % plafonnée à 6 000 DH** + **AMO 2,26 %** → frais professionnels (35 %/25 % plafonnés) → net imposable → **IR par le barème de l'exercice** (annualisation + déduction charges de famille) → avances/oppositions → **net à payer** ; charges patronales (**CNSS 8,98 %, AMO 4,11 %, prestations familiales 6,40 %, formation 1,60 %**) et **coût employeur** |
| **Barèmes historisés** | `app/core/rates_ma.py` : registre par exercice (`BAREMES_PAIE`) — **un exercice non paramétré est refusé** (aucun taux deviné) |
| **Écritures** | Débit `61711`/`61712`/`61713`, `61741` (CNSS + AMO patronales), `61744`, `61768` ; Crédit `4441` (CNSS/AMO salariales **et** patronales), `4443`/`4445`/`4448`, `4452` (**IR retenu**), `4434` (oppositions), `3431` (avances), **`4432` (net à payer)** ; règlement `4432 → 5141` / `5161` |
| **DTS « 9421 »** | Modèle déclaratif (déclarant, personnel permanent, **salariés exonérés art. 57-20°**, cotisations, totaux), **fichier XML EDI**, **état de saisie EFI** (saisie assistée), fiche récapitulative **PDF**, registre `tax_declarations` (fichier + **SHA-256** + accusé de réception) |
| **États** | **Journal de paie** (période), **livre de paie annuel** (cumuls mensuels par salarié), **état des cotisations et de l'IR par mois**, **récapitulatif annuel**, **bulletin de paie PDF** |
| **Contrôles** | Net négatif, **opposition > net saisissable**, **Σ bulletins ≠ écriture**, **n° CNSS manquant** (bloquant pour la DTS), CIN manquante, **période verrouillée** (P1.6), **réconciliation DTS ↔ comptes `617x`** |

Écran : **Paie & DTS** (`/paie`) — salariés, cycle de paie (préparer → valider →
payer), bulletins, livre, cotisations, DTS et téléchargements XML/PDF. API :
`/payroll/employees` (+ `/contrats`), `/payroll/runs/{periode}` (+ `/valider`,
`/payer`), `/payroll/controles`, `/payroll/journal`, `/payroll/livre`,
`/payroll/cotisations`, `/payroll/recapitulatif`, `/payroll/bulletin/{id}/pdf`,
`/payroll/dts/{annee}` (+ `/xml`, `/efi`, `/fiche-pdf`, `/validation-xsd`,
`/declaration`), `/payroll/dts/declarations`.

> **À confirmer (voir CDC § 9.13 et § 9.13.1)** : le fichier **DTS XML suit désormais le modèle
> officiel EDI V5.1** (racine `TraitementEtSalaire`, schéma `traitementSalaire.xsd`, **sans
> namespace**, **3 listes PP / PO / STG**, totaux normalisés) — le **XSD officiel n'étant pas
> fourni** par la DGI, la validation reste inactive (`valider_xsd` renvoie `valide=None`, jamais
> « conforme ») et le **mode EFI assisté** (3 onglets) sert de repli ; renseigner `DTS_XSD_PATH`
> active la validation. Le **net à payer est crédité au `4432`** (« rémunérations dues au
> personnel ») : le compte **`3431`** est un compte d'**actif** (« avances et acomptes au
> personnel ») et sert à régulariser les avances.

---

## 15. IS & liasse fiscale (jalon J7 — étape 1 livrée)

Détermination du **résultat fiscal** et de l'**impôt sur les sociétés** à partir de la
balance, préalable à la **liasse fiscale EDI** (étapes 2 et 3).

| Brique | Contenu |
|---|---|
| **Résultat fiscal** | `app/services/fiscal_liasse.py` : le résultat comptable (CPC) est retraité **hors comptes `67x`** — l'**IS n'est pas déductible** (CGI art. 11) — puis augmenté des **réintégrations** et diminué des **déductions** et du **report déficitaire** (art. 114, **plafonné au bénéfice** de l'exercice) |
| **Réintégrations / déductions** | **catalogue paramétrable** (code, libellé, **référence CGI**, comptes) ; les charges non déductibles par nature (`6583` amendes et pénalités, provisions `6195`/`6196`/`6197`, `1515`/`1555`…) sont **détectées** dans la balance et **proposées** — la **saisie du comptable prévaut** et l'origine est tracée (« saisie » / « détection automatique ») |
| **IS vs cotisation minimale** | `compute_is` (**taux historisé** de l'exercice) contre `compute_cotisation_minimale` (**0,25 % du CA TTC**, plancher **3 000 DH**, exonération **36 mois** ; CA TTC = CA `71x` + TVA collectée `4455`) → **impôt dû = le plus élevé des deux** (CGI art. 144), **CM due même en cas de déficit** |
| **Acomptes et solde** | acomptes = solde du compte **`3453`** « acomptes sur impôts sur les résultats » + crédits d'impôt saisis → `solde_a_payer` ou `excedent_a_reporter`, `taux_effectif` |
| **Contrôles** | **bloquants** : **exercice non clos** (P1.6), balance déséquilibrée, exercice sans écriture ; **avertissements** : réintégrations détectées non retenues (art. 11), **cotisation minimale supérieure à l'IS** (art. 144), **déficit reportable** (art. 114) ; le contrôle `fiscal.recap` récapitule la **concordance comptable ↔ fiscale** |
| **Σ liasses = balance** | `reconciliation_balance()` : équilibre de la **partie double** (Σ soldes = 0), totaux **par classe**, produits / charges / résultat et indicateur **`pret_pour_liasse`** — base de la réconciliation **tableau par tableau** de l'étape 2 |
| **Entrée unique** | `dossier_is()` = calcul + balance + contrôles (routes API et écran **IS & liasse** livrés à l'étape 3 avec le XML) |
| **Assembleur (étape 2)** | `app/services/liasse_edi.py` : contrat **lu dans les XSD officiels** (racine `Liasse`, `modele/id` = **7** pour le comptable simplifié, **24 tableaux**, **1 328 `codeEdi`**), **référentiel de codification** `referentiels/liasse/codification_liasse.csv` — un code ou un tableau **hors schéma** est **refusé** (jamais deviné) |
| **Alimentation** | rubriques `solde:<compte>`, `racine:<2-3 chiffres>`, `classe:<1-7>` (**balance définitive**), résultat fiscal / IS / CM, **immobilisations (J2)**, **stocks (J3)**, **personnel / DTS (J6)** ; une source absente est **signalée** et la cellule reste « à compléter » |
| **Modèle de données** | `liasse_tables` / `liasse_cells` (`code_edi`, `rubrique`, `valeur`, `valeur_numerique`, `numero_ligne`, `extra_field`, `source`) — migration additive `a7f3c51d8b42` ; contrôle « **Σ liasses = balance** » cellule par cellule |
| **EFI assisté** | `etat_de_saisie_efi_liasse()` : une feuille **par tableau** (`codeEdi`, libellé, valeur, état `valeur` / `a_completer`) + export **CSV** pour la saisie sur SIMPL |
| **Registre** | Déclaration **`LIASSE`** en **brouillon** (régime = modèle, `nb_lignes`, montant = **impôt dû**), **idempotente**, **figée** dès dépôt, trace d'audit `LIASSE_RECORDED` |
| **Outils** | `tools/liasse_codification.py` : `--contrat`, `--codes`, `--rubriques`, `--gabarit` (trame du référentiel dérivée du schéma), `--verifier` |
| **Fichier XML EDI (étape 3)** | `build_liasse_xml()` : `Liasse` → `modele/id` (**fixé par le XSD**) → `resultatFiscal` → `groupeValeursTableau` → `ValeursTableau` → `tableau/id` → `groupeValeurs` → `ValeurCellule` (`cellule/codeEdi`, `valeur`, `numeroLigne`) → `extraFieldvaleurs` ; tableaux vides **omis** (le schéma exige une cellule par tableau) |
| **Validation XSD réelle** | `valider_xsd()` (lxml) : **conforme** / **refusé** (écarts ligne par ligne) / **validation impossible** (schéma absent) — jamais « présumé conforme » ; `produire_liasse_xml()` **refuse** la production si un contrôle bloquant subsiste ou si le schéma rejette le fichier |
| **API & écran** | API `/liasse/{annee}` (+ `/efi`, `/efi.csv`, `/validation-xsd`, `/xml`, `/enregistrer`, `/depot`, `/declarations`) ; écran **`/liasse`** (IS/CM, contrôles, cellules, EFI assisté, formulaires de dépôt, registre) et exports `/etats/liasse.xml`, `/etats/liasse-efi.csv` |
| **Accusé de réception** | Déclaration **brouillon → soumise → acceptée** (ou **rejetée** avec motif) : nom, taille et **empreinte SHA-256** du fichier déposé, dates de dépôt/accusé, déclaration **figée** ensuite, traces d'audit `LIASSE_RECORDED` / `LIASSE_SUBMITTED` |

> **À confirmer (voir CDC § 9.14, § 9.15 et § 8.2 — ambiguïtés A13, A20, A21, A22)** : la table
> **rubrique ↔ `codeEdi`** est un **référentiel éditable** validé par l'expert-comptable —
> **l'annexe DGI « Codification des cellules » n'est pas fournie** et les XSD ne portent
> **aucun libellé** (le `réferentiel des codifications.xlsx` livré est un référentiel **CbCR**) ;
> la liste des **charges non déductibles**, la **base exacte de la cotisation minimale** (CA TTC
> reconstitué, produits financiers et accessoires) et la **durée du report déficitaire**
> (CGI art. 114) restent à valider — l'application n'applique **aucune durée en dur**, ne
> **devine aucun code** et affiche les avertissements correspondants.

---

## 16. Cessation / cession d'activité & e-facturation (jalon J8 — livré)

### 16.1 Cessation / cession d'activité (P2.2)

Événements de vie de l'entreprise et **déclaration de TVA de sortie** (régimes **3**
et **4** de l'annexe 1 « correspondance balise RD V4.0 »).

| Brique | Contenu |
|---|---|
| **Événements** | `app/services/activity_events.py` + table **`activity_events`** : **cessation temporaire** (régime **3**), **cession** et **cessation** (régime **4**) — date d'effet, **motif**, repreneur (cession), lien vers la déclaration du registre |
| **Base légale (CGI 2026)** | **art. 114** : déclaration TVA de cession/cessation **dans les 30 jours** + **régularisation des déductions** (renvoi aux art. 101 à 105) ; **art. 150-I** : déclaration de changement **sous 45 jours** ; **art. 150 bis** : **cessation temporaire** dans le **mois suivant la clôture**, pour **2 exercices** renouvelable **1**, **motifs obligatoires** |
| **TVA de sortie** | période du **1ᵉʳ janvier** (ou du **lendemain du dernier événement**) à la **date d'effet** : collectée / déductible / nette, **total à payer** (TVA + régularisations), crédit reportable |
| **Régularisations** | **immobilisations en service** (calcul du module P1.2, prorata des années restantes — **art. 102 et 104-II-1°**) ; **stocks** : valeur affichée, **montant de TVA saisi** (aucun taux deviné) |
| **Contrôles** | **bloquants** : motif manquant (cessation temporaire), **échéance des 30 jours dépassée** ; **avertissements** : repreneur non identifié, régularisation des stocks à examiner, déclaration non enregistrée, **écritures après la date d'effet** |
| **EDI & registre** | **relevé des déductions** au **régime 3/4** (`<periode>1</periode>`) + déclaration inscrite dans **`tax_declarations`** (`regime` = 3 ou 4, montant = total à payer), **figée** après dépôt, avec **accusé de réception** |
| **Référentiel** | `referentiels/tva/` : annexe 1 « correspondance balise RD V4.0 » et exemple officiel du relevé |

### 16.2 E-facturation (P2.3)

| Brique | Contenu |
|---|---|
| **Mentions obligatoires** | catalogue de **17 mentions** contrôlées avec **niveau** (bloquant / avertissement) et **référence vérifiable** : numéro séquentiel, date, échéance, identités et identifiants (**IF**, **ICE**, RC, adresse), désignation, quantités et prix HT, taux de TVA, **cohérence des montants**, mode de paiement (CGI **art. 146**, loi 15-95, obligation d'ICE) |
| **Document** | table **`e_invoice_documents`** : statut, format, canal, **XML**, **empreinte SHA-256**, identifiant DGI, accusé, dates d'envoi et d'accusé |
| **Cycle de vie** | `generer_document()` (refus si une mention bloquante manque), `envoyer()` (**canal** API / manuel / EFI, **simulation par défaut**), `enregistrer_accuse()` (**accepté** ou **rejeté motivé**) ; document **figé** une fois terminal ; traces d'audit `E_INVOICE_GENERATED` / `_SENT` / `_ACKNOWLEDGED` |
| **Contrôles de dossier** | canal non configuré, **spécification DGI absente**, mentions manquantes, factures sans document, transmissions et accusés en attente, documents rejetés |

> **À confirmer (voir CDC § 9.17, § 9.18 et § 8.2 — ambiguïtés A23 et A24)** :
> le **cahier des charges e-facturation de la DGI n'est pas fourni** : le fichier produit
> est un **format interne** (`interne-v1`) marqué `<conformite>non validée…</conformite>`
> et **ne doit pas** être déposé tel quel ; le **canal DGI** reste **paramétrable**
> (`E_INVOICE_ENDPOINT`, `E_INVOICE_API_KEY`) et fonctionne en **simulation**
> (`E_INVOICE_DRY_RUN=true`) tant que la spécification n'est pas publiée — le **repli EFI**
> (dépôt manuel) est opérationnel. Par ailleurs, les **citations d'articles du CGI** du
> CDC ont été corrigées pour les nouvelles fonctions (l'**art. 145** traite de la **tenue
> de la comptabilité**, les mentions de facture relèvent de l'**art. 146** et la
> régularisation TVA des immobilisations des **art. 102 et 104-II-1°** — la correction des
> libellés déjà livrés au module P1.2 est **tracée comme action D16**).

---

## 18. Régularisation P0 — audit J9 (**PASS**)

Traçabilité complète : audit → `AUDIT_ANOMALIES_J9.md` (+ preuves brutes
`AUDIT_ANOMALIES_J9.txt`, outil `tools/j9_audit_anomalies.py`) ; correctifs →
preuve avant/après mesurée `PREUVE_P0.md` (`tools/p0_preuve_avant_apres.py`).

| Item | Correctif (cause racine) | Preuve |
|---|---|---|
| **P0.1** Collisions de routes | L'API REST est montée **exclusivement sous `/api`** (`app/main.py`) et l'interface est déclarée hors documentation (`include_in_schema=False`) : plus aucune interception possible d'une session Web par une route `Bearer` | `/audit`, `/audit/export`, `/stocks` : **401 → 200** avec session ; sans session → **303** vers `/connexion` ; `/api/audit` 401 sans jeton, 200 avec. Défaut latent découvert : `/stocks` renvoyait **500** (`VALUATION_METHOD_LABELS` absent du service) — corrigé |
| **P0.2** Relevé EDI TVA | `collect_rd_lines` calcule **la base HT et la TVA sur la même fraction** (cumuls plafonnés au TTC, donc exacts sur la vie de la facture) ; nouveaux **contrôles bloquants** `HT + TVA = TTC` et `TVA = base × taux × prorata` appliqués à l'écran **et dans `build_rd_xml`** (fichier refusé sinon) | FA26-12 (9 000 / 1 800 / 10 800, réglée 4 320) : ligne EDI **9 000 / 720 / 9 720 → 3 600 / 720 / 4 320** ; scan **48 périodes : 45 → 0** ligne incohérente |
| **P0.3** ETIC | `etats_synthese.detail()` / `total()` comparent désormais le **préfixe** du compte (`startswith`) et non les 2 premiers caractères : les racines **617** (personnel, note 9) et **619** (dotations, note 4) alimentent l'ETIC | Note 9 : **0 → 203 295,60 DH** sur 6 comptes (`6171, 61711, 6174, 61741, 61744, 61768`) ; note 4 porte `2834` **et** `6193` |
| **P0.4** Documents de facture | Nouveau service `invoicing.controles_coherence_facture()` : **refus** des lignes à 0 à la **validation**, **refus d'émission** (`DocumentIncoherentError`) d'un PDF dont les lignes / la ventilation TVA ne réconcilient pas les totaux ; l'écran de détail et l'aperçu affichent « Document incohérent » | 74 factures balayées : **0 incohérence** produite ; ligne à 0 ou facture sans ligne → **validation refusée** et **document refusé** (message explicite au lieu d'un fichier faux) |

**Tests de non-régression ajoutés** (24) : `tests/test_routing_isolation.py` (5),
`tests/test_ecrans_smoke.py` (8 : balayage de tous les écrans + écrans métier),
`tests/test_etic_notes.py` (3), `tests/test_facture_document.py` (6),
`tests/test_edi_tva.py` (+2). Suite complète : **324/324 tests verts**.

**Données** : aucun correctif ne modifie les données métier ; la base de recette
n'a pas été touchée par la régularisation (horodatage inchangé, `P0` en lecture
seule). La double paie de recette (A2) et les arbitrages restent traités en **P1**.

---

## 19. Régularisation **P1** — paie, **source unique** (**PASS**)

**Cible fonctionnelle** : le **module Paie est l'unique source** des écritures de paie
(anomalie **A2** de l'audit J9 : les écritures synthétiques `PAIE26-01` … `PAIE26-12` du jeu de
données **doublaient** la paie du module).

**Méthode autorisée : réinitialisation contrôlée du jeu de recette** (aucune suppression
silencieuse) :

1. **sauvegarde** `compta_ma.db.bak-p1-20260923-150952` (1 064 Ko) vérifiée par l'outil ;
2. **inventaire exact** avant modification : `P1_INVENTAIRE_PAIE_AVANT.txt` ;
3. **retrait tracé** de 13 écritures 2026 (12 seed `PAIE26-xx` + l'écriture du module), du cycle
   de paie 2026-01 et de la DTS de recette — chaque retrait est inscrit dans la **piste d'audit**
   (`PAYROLL_RESET_*`) avec l'instantané complet de l'écriture ; la piste est **rescellée**
   (171 écritures, **0 rupture**) ;
4. **régénération par le module** : 12 cycles 2026 (préparer → valider → payer) = **36 bulletins**,
   **24 écritures** (12 charges + 12 paiements), DTS 2026 régénérée (IR 27 607,92 DH, 3 salariés,
   empreinte SHA-256) ;
5. **recalcul intégral** sans correction manuelle :
   Paie → Journal → Balance → CPC → ESG → Bilan → ETIC → résultat fiscal → IS.

**Contrôle bloquant ajouté (cause racine)** : `payroll.ecritures_paie_hors_module()` — toute charge
de personnel d'une **autre origine** sur la période **empêche** la comptabilisation de la paie du
module (`PayrollError` motivée). C'est ce contrôle qui rend la double alimentation **impossible à
l'avenir**.

| Point | Avant | Après |
|---|---|---|
| Écritures de paie 2026 / cycles / bulletins | 13 / 1 / 3 | **24 / 12 / 36** |
| `6171` + `6174` (seed) | 172 800,00 | **0,00** |
| `61711` (appointements) | 26 000,00 | **312 000,00** |
| `61741` / `61744` / `61768` | 4 495,60 | **53 947,20** |
| `4432` (nets à payer) | -22 439,74 | **0,00** (tous payés) |
| `4441` / `4452` (CNSS / IR à verser) | -8 055,86 | **-96 670,32** |
| Résultat comptable | 49 344,40 (bénéfice) | **-113 307,20** (perte) |
| Résultat fiscal / IS | 69 304,40 / 13 860,88 | **-93 347,20 / 0,00** |
| Bilan équilibré · CPC = ESG = Bilan | oui / oui | **oui / oui** |
| Tests | 324/324 | **326/326** |

Détail chiffré et analyse : **`P1_AVANT_APRES.md`** (outil `tools/p1_rapport_avant_apres.py`, qui
recalcule la **même chaîne** sur la sauvegarde *avant* et sur la base courante *après*).
Outils : `tools/p1_inventaire_paie.py`, `tools/p1_reinitialiser_paie.py` (simulation par défaut).

**Arbitrage à confirmer (scénario, aucune correction manuelle appliquée)** : la masse salariale
**réelle** (26 000 DH de brut/mois) dépasse le chiffre d'affaires du scénario de recette
(432 000 DH/an) : l'exercice 2026 devient déficitaire. La trésorerie bancaire reste **débiteure**
(223 003,12 DH) : aucun reclassement en trésorerie-passif n'est requis (le contrôle et le
reclassement CGNC `5541`/`5548` sont livrés — § 20). L'IS est nul (perte) et la **cotisation
minimale** aussi (exonération des **36 premiers mois** calculée sur les dates réelles de la
société, art. 20 CGI). Le scénario devra être adapté (CA ou effectif) si un bénéfice est attendu —
**sans jamais corriger un montant à la main**.

---

## 20. Régularisation **P1 — suite** — PASS (réouverture encadrée, trésorerie, garde-fou paie, exonération CM, taux IS de l'exercice)

Dossier complet : **`REGULARISATION_P1_SUITE.md`** ; suite de tests : **`PREUVE_P1SUITE_TESTS.log`**
(**348/348 verts**, code de sortie 0) ; simulation 2025 (lecture seule) : **`P1B_SIMULATION_2025.md`**.

| Chantier | Livrable | Effet |
|---|---|---|
| **Réouverture d'exercice sécurisée** (A10) | `closing.reouvrir_exercice(motif=…, regenerer_a_nouveaux=…)`, `closing.verrouiller_exercice(motif=…)`, `closing.regenerer_a_nouveaux(...)` (+ comparaison par compte), `closing.apercu_reouverture(...)` ; route web **passant par les services** (formulaire avec motif obligatoire et case « régénérer les à-nouveaux ») | plus aucun changement de statut direct : motif ≥ 10 caractères, verrous de période et N+1 verrouillé contrôlés, à-nouveaux régénérés et **comparés**, tout est tracé (`FISCAL_YEAR_REOPENED`, `FISCAL_YEAR_LOCKED`, `OPENING_REGENERATED`) |
| **Soldes créditeurs de trésorerie** | `app/services/tresorerie.py` : `controler_tresorerie()`, `reclasser_solde_crediteur()`, `reclasser_soldes_crediteurs()` | reclassement CGNC automatique en **trésorerie-passif** (`5141/5143/5146 → 5541`, `5148 → 5548`) par écriture OD tracée et **idempotente** ; les **caisses créditrices** (impossibles) restent des anomalies à corriger. Contrôle exécuté sur la base : 2025 et 2026 **conformes** (solde bancaire débiteur de 223 003,12 DH) |
| **Garde-fou Paie affiné** | `payroll.controle_doublon_paie()` | bloque les **doublons réels** (numérotation `PAIE…` ou comptes de dette de paie `4432/443x/444x/4452`) et **autorise les OD légitimes en 617x** avec avertissement |
| **Exonération de cotisation minimale** | colonnes `date_constitution` / `date_debut_exploitation` (migration `p1c1a2b3d4e5`), `fiscal_liasse.date_debut_activite()`, `mois_activite_effectif()`, `exoneration_cotisation_minimale()` | durée d'activité **calculée** (plus de `12` par défaut) : base de recette début 2025-01-01 ⇒ exonération jusqu'au 2028-01-01 (2025 : 12 mois, 2026 : 24 mois) |
| **Taux d'IS de l'exercice** | `IS_RATES_BY_YEAR` + `is_rates(annee)` + `compute_is(..., annee=)` ; `calculer_is()` restitue `taux_is_exercice`, `mois_activite` et la source de l'exonération | un exercice non paramétré est **refusé** (aucun taux deviné) : le recalcul de 2025 exigera le barème de la loi de finances 2025 |

**Séquence 2025 — en attente de votre validation** : `P1B_SIMULATION_2025.md` liste les
**trois paramétrages à fournir** (barème de paie 2025, taux d'IS 2025, paramètres de cotisation
minimale 2025) et projette l'impact (charges de personnel 144 000 → 365 947,20 DH ; résultat
73 600 → −148 347,20 DH ; à-nouveaux 2026 ajustés de +221 947,20 DH). **Les écritures 2025 sont
intactes** : la séquence (réouverture → régularisation → reclôture → régénération des à-nouveaux →
recalcul 2026 → comparaison) ne sera lancée qu'après votre accord.

---

## 21. Régularisation **P1 Greffe** (contenu des pièces) et **P2** (navigation) — PASS

**P1 Greffe — anomalie bloquante corrigée.** Deux pièces du dossier de recette
(`rapport_gestion_j9.pdf`, `pv_ag_j9.pdf`) étaient **acceptées** alors qu'elles ne contenaient
**rien** : 193 octets, page vide, contenu identique (même SHA-256). L'ancien contrôle ne vérifiait que
le type MIME et la taille (< 10 Mo). Désormais, le **contenu** est contrôlé et bloquant :

- PDF illisible (corrompu, chiffré), fichier vide, non-PDF → refus ;
- **page blanche** (toutes les pages < 30 caractères) → refus ;
- **contenu insuffisant** (< 120 caractères de texte) → refus ;
- **pièces substantielles** (PV d'AG, rapport de gestion) : < 400 caractères ou **mentions métier
  obligatoires absentes** → refus ;
- **même contenu pour deux pièces** (SHA-256) → refus + contrôle bloquant `greffe.pieces_dupliquees` ;
- une pièce **déjà archivée mais invalide** n'est plus comptée comme fournie (`statut = invalide`,
  contrôles bloquants `greffe.piece_contenu_invalide`) — le dossier de recette est donc signalé ;
- l'état **« Approuvé » exige une date d'assemblée générale** (loi 5-96, art. 10).

Le **rapport de gestion** et le **PV d'AG** sont maintenant **rédigés par l'application** à partir des
comptes de l'exercice (chiffres clés, situation financière, affectation du résultat, perspectives ;
date d'AG, associé unique ou assemblée des associés, résolutions d'approbation et d'affectation),
avec **SHA-256 recalculé après génération**. **Aucun dépôt ni certificat de greffe n'est simulé.**
Vérification : `python tools/p1_greffe_controle_contenu.py [--ecrire --date-ag AAAA-MM-JJ]`.

**P2 — Menu réorganisé (12 sections) et 11 écrans lecture seule.** Le menu reprend l'arborescence
validée (Tableau de bord, Comptabilité avec **Journal comptable visible**, États de synthèse
(Bilan/CPC/**ESG**/**ETIC**), Immobilisations, Stocks & provisions, Paie, Fiscalité,
Juridique/Greffe, Clôture & cessation, E-facturation, Audit & traçabilité, Paramètres) en
**conservant toutes les URL existantes**. Écrans ajoutés (`app/web/ecrans_lecture.py`, `GET` seule) :
`/etats/esg`, `/etats/etic`, `/stocks/mouvements`, `/stocks/inventaire`, `/stocks/provisions`,
`/parametres/a-nouveaux`, `/parametres/journaux`, `/parametres/referentiels`, `/audit/integrite`,
`/e-facturation`, `/activite` — tous alimentés par les services existants, **sans aucune mutation
comptable**, **sans changement de permission**. Tests : `tests/test_menu_p2.py` (smoke de chaque
entrée de menu, présence des sections, absence d'écriture, permissions par rôle) et
`tests/test_greffe_contenu.py` (reproduction exacte des PDF de 193 octets).

**Contre-visite de recette (23/09/2026) — deux écrans P2 corrigés.** Sur la base de recette (et non
sur une base de test vide), `/etats/etic` renvoyait **HTTP 500 `TypeError: 'decimal.Decimal' object is
not iterable`** (le total d'une note ETIC est un scalaire *Decimal*, or le gabarit itere `tableau.total`
comme une **ligne de cellules** : le défaut n'apparaissait que si le total était **non nul**) et
`/activite` renvoyait **HTTP 500 `AttributeError: 'AuditLog' object has no attribute 'get'`**
(`journal_audit` renvoie des lignes **ORM**, lues à tort comme des dictionnaires : le défaut
n'apparaissait qu'avec un journal **non vide**). Corrections sans `try/except` : `_ligne_total()` /
`_cellule()` produisent une ligne de cellules alignée et formatée pour l'ETIC ; `/activite` lit les
attributs `AuditLog` et libelle l'utilisateur via `audit_trail.utilisateurs_journal` (comme l'écran
`/audit`). Tests de non-régression **sur contenu métier** : `tests/test_p2_ecrans_recette.py`.
Recette rejouée : `tools/p2_recette_menus.py` (base de recette **copiée**, LECTEUR créé dans la copie)
balaie **les 60 entrées du menu réel** avec **ADMIN** puis **LECTEUR** (0 échec), vérifie le contenu
ETIC/activité et la redirection **303 → /connexion** des 11 écrans P2 sans session, et compare
l'empreinte SHA-256 de la base réelle avant/après (**inchangée**).

**Dossier Greffe 2025 finalisé (23/09/2026, étape 1 uniquement).** Les deux pièces vides de
**193 octets** (`rapport_gestion_j9.pdf`, `pv_ag_j9.pdf`, même SHA-256) ont été remplacées par les
documents rédigés par l'application : **`Rapport_gestion_2025.pdf`** (5 112 o —
`fe0c66cdb6b87f8b…`) et **`PV_AG_2025.pdf`** (4 831 o — `fb5c19d691f21b83…`, date d'AG **08/01/2026**
fournie comme date de recette). Contrôles rejoués : **27 PASS / 0 NOK** (mentions métier, lisibilité
2 pages chacune, SHA-256 distincts, empreinte base = disque, complétude **5/5**, aucun contrôle
bloquant) avec cohérence **résultat 2025 = 73 600,00 / total du bilan 387 520,00 / CA 360 000,00 /
affectation « report à nouveau »** entre comptabilité, rapport de gestion, PV d'AG et états de
synthèse (5 pages : bilan, CPC, ESG, ETIC). **Aucun dépôt réel, aucun paiement, aucun certificat**
(statut `approuve` inchangé, `date_depot` vide) et **aucune écriture comptable** touchée (195 avant et
après). Outils : `tools/p1_greffe_finaliser_2025.py` (préparation / exécution / `--extraits`) et
`tools/p1_greffe_verif_2025.py` (vérification indépendante base + disque) ; livrable
**`PREUVE_GREFFE_2025_FINAL.md`**.


---

## 7. Étape 2 — P1B v3 : référentiels 2025 en **lecture seule**

Les référentiels 2025 sont désormais **saisis avec leur source** dans `app/core/rates_ma.py`
(aucun taux saisi en dur ailleurs, aucun exercice neuf deviné) :

| Référentiel 2025 | Valeur | Source / statut |
|---|---|---|
| IS (grille transitoire) | **17,5 %** si bénéfice net fiscal ≤ 300 000 DH ; 20 % au-delà (< 100 M) ; 35 % (> 100 M) ; 40 % banques/assurances ; 20 % CFC | fournie au projet — *documenté (à confirmer)* |
| IR (barème) | 6 tranches : 0 % jusqu'à 40 000 DH, puis 10/20/30/34/37 % | CGI art. 73, version 2025 — *documenté (à confirmer)* |
| Déduction familiale | **500 DH** par personne, 6 au maximum (600 DH en 2026) | idem |
| Cotisation minimale | 0,25 % du CA TTC, plancher 3 000 DH, exonération 36 mois | CGI art. 144 / art. 20 — *documenté (à confirmer)* |
| **Frais professionnels 2025** | **à fournir** — aucun taux appliqué (CGI art. 59 v. 2025 non communiqué) | *a_fournir* |
| **CNSS / AMO 2025** | **à fournir** — aucune cotisation calculée | *a_fournir* |
| **Prestations familiales / TFP 2025** | **à fournir** | *a_fournir* |

Le module est maintenant **sensible à l'exercice** : `compute_ir_annual`, `compute_ir_monthly`,
`compute_professional_expenses`, `frais_professionnels_mensuels` et `compute_cnss` prennent
l'exercice en paramètre et **refusent** (`BaremeIndisponible`) un exercice non documenté au lieu
d'appliquer les taux 2026 (l'exercice 2026 reste identique : 32 tests dédiés passent).

### Simulation v3 CORRIGÉE (lecture seule) — `tools/p1b_simulation_2025_v3.py`

Le calcul IS suit désormais la **démarche fiscale** (moteur `fiscal_liasse.calculer_is`, CGI art. 11
et 144) et non le résultat net comptable :

| Étape | Montant |
|---|---|
| Résultat net comptabilisé (après IS) | 73 600,00 DH |
| + Réintégration de l'IS comptabilisé (**non déductible**) | 18 400,00 DH |
| = **Résultat comptable avant IS / base fiscale** | **92 000,00 DH** |
| Déductions fiscales | 0,00 DH |
| **Résultat fiscal 2025** | **92 000,00 DH** |
| Taux IS 2025 (grille transitoire, BNF ≤ 300 000 DH) | **17,50 %** |
| **IS 2025 calculé** | **16 100,00 DH** |
| IS comptabilisé (6701) | 18 400,00 DH |
| **Écart** | **2 300,00 DH** |

**Cotisation minimale** : taux 0,25 % / plancher 3 000 DH affichés séparément → **CM théorique
3 000,00 DH**, mais **non exigible** : début d'exploitation **01/01/2025** (fiche société), exonération
des **36 premiers mois** (jusqu'au 01/01/2028) → **aucune dette fiscale de 3 000 DH**. Le taux IS 2025
sélectionne automatiquement le taux transitoire (`compute_is` : `small_profit` si BNF ≤ 300 000 DH) ;
2026 reste inchangé (20 %, 92 000 → 18 400).

**Impôt finalement dû 2025 = 16 100,00 DH** ; **résultat net corrigé = 75 900,00 DH** ; **impact
à-nouveaux 2026** : report à nouveau **+2 300,00 DH**, dette d'IS **−2 300,00 DH**, **total du bilan
inchangé (375 520,00 DH)**.

**IR/paie 2025 : blocage maintenu** — frais professionnels et CNSS/AMO 2025 non documentés, aucune
paie 2025 n'est calculée (`BaremeIndisponible`), IR non chiffré.

**Preuve de non-écriture** : SHA-256 de la base identique avant/après, **195 écritures** avant et
après. Livrables : **`P1B_SIMULATION_2025_V3_CORRIGEE.md`** (référence) et
`P1B_SIMULATION_2025_V3.md` (première version, marquée *superseded*). **P1B étape 3 non lancée** :
elle attend la validation humaine de cette simulation corrigée.

---

## 17. Suite (phases 2 et 3)

- Immobilisations (dépréciations réversibles 6194x / 293x), paie (IR/CNSS/TFP, bulletins), stocks (CUMP/FIFO).
- **Liasse fiscale EDI** (P7 restant) : validation du **référentiel de codification** par l'expert-comptable (annexe DGI « Codification des cellules », ambiguïté A22), dépôt réel sur SIMPL et suivi des **accusés de réception**.
- **Cessation / cession d'activité (P2.2)** : API et écran de suivi des événements (chronologie, échéances, régularisations) et **correction des citations « art. 106 »** existantes (action **D16**).
- **CSS**, acomptes trimestriels, états fiscaux (ESG) et **cotisation minimale** dans le dossier de dépôt.
- Interface web (Jinja2 + HTMX) : saisie guidée, dossier de dépôt au greffe en une action.
- **E-facturation (P2.3)** : branchement du **schéma DGI** dès publication (`valider_conformite(schema=…)` et `E_INVOICE_ENDPOINT` réel sans simulation), API/écran de suivi (statuts, accusés, rejets), avoirs et autofacturation (A24).

---

*Le plan comptable embarqué provient du plan comptable marocain officiel fourni par
l'utilisateur ; il reste à faire valider/compléter par l'expert-comptable du dossier.*