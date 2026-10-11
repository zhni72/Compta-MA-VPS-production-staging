# CAHIER DES CHARGES GLOBAL — Compta MA

> **Nom de projet :** Compta MA (comptabilité marocaine CGNC / DGI, type Sage)
> **Version du document :** 2.11 — **CDC GLOBAL de référence** (régularisation P0 de l'audit J9 : § Partie 8 A25-A28, Partie 10 § 10.6)
> **Date :** 23 septembre 2026
> **Périmètre :** comptabilité générale + facturation + fiscalité déclarative (TVA, IS, paie, greffe)
> **Statut :** document de référence pour toutes les sessions de développement à venir
> **Document v1 conservé :** `CAHIER_DES_CHARGES.md` (cadrage initial, phases 1→3, § 0 normatif).
> Le présent document **l'englobe** et fait foi pour l'architecture, les modules et la feuille de route.

---

## 0. Règle permanente et mode d'emploi de ce document

> **Règle permanente n° 1 —** L'application est réalisée **conformément aux normes
> comptables marocaines (CGNC / PCGE)** et aux **normes de la DGI**. Toute évolution est
> vérifiée contre ces référentiels : **la conformité fiscale et comptable prime sur toute
> considération ergonomique, technique ou de délai**.

> **Règle permanente n° 2 —** Aucune donnée fiscale n'est « devinée » : lorsqu'un
> référentiel est ambigu (unité, longueur, format), le doute est **tracé dans le
> document** (§ 8), un **défaut prudent** est choisi, et l'arbitrage est soumis à
> l'expert-comptable ou à la DGI.

> **Règle permanente n° 3 —** Tout module produit des **écritures équilibrées**,
> des **contrôles bloquants** avant dépôt et un **journal d'audit** exploitable.

**Ce document est structuré pour être lu à trois niveaux :**

| Lecteur | Parties à lire |
|---|---|
| Décideur / expert-comptable | Parties 1, 3 (synthèses), 7, 9 |
| Développeur | Parties 2, 3, 4, 5, 6, 8, 10 |
| Contrôleur / auditeur | Parties 6, 7, 8, 10 |

**Référentiels locaux dépouillés (audit du 22/09/2026)** — tous dans
`C:\Users\Belyazid\Desktop\image\compta_maroc\deepsesk\` :

| Chemin | Contenu | Usage |
|---|---|---|
| `Documentation\reference-comptable\cgnc.pdf` | CGNC (norme générale + plan comptable) | règles d'évaluation immobilisations/stocks, états de synthèse |
| `Documentation\Reference-fiscle\cgi-2026-maroc.pdf` | **CGI édition 2026** | taux, seuils, délais, sanctions |
| `Documentation\reference-juridique\` | loi 17-95 (SA), loi 5-96 (SNC/SCS/SCA/SARL), charte PME (loi 53-00), hébergement touristique | formes sociales, délais d'AG, publicité |
| `Documentation\RÉFÉRENTIEL TECHNIQUE DGI\TVA\` | CC EDI Simpl-TVA RD v2.0, **Annexe 1 balises RD V4.0**, exemple XML v2.0 | module TVA EDI (livré) |
| `Documentation\RÉFÉRENTIEL TECHNIQUE DGI\ir\` | Guide **DRG professionnel 2020**, guide **DTS « 9421 »**, **4 XSD de liasse fiscale** | modules IS/liasse et Paie |
| `Documentation\RÉFÉRENTIEL TECHNIQUE DGI\simple-is\` | CC EDI **Simpl-IS v1.0** (`9370`), v2.0.3, XSD **CbCR OCDE**, référentiel des codifications | modules IS/liasse et CbCR |
| `Documentation\RÉFÉRENTIEL TECHNIQUE DGI\Taxe Professionnelle\` | CC EDI TH/TSC v1 (03/06/2025), XSD + wrapper + référentiel | module P3 TP |
| `deepsesk\TVA-EDI.xlsm` | modèle officiel DGI **ADC082F-15I** + **XSD embarqué** | contrôle du relevé TVA |
| `deepsesk\GuideUtilisation.pdf` | **« Dépôt électronique des états de synthèse »** — Ministère de la Justice, nov. 2025 | **module greffe (P1)** |

---

## SOMMAIRE

- **Partie 1** — Vision et périmètre
- **Partie 2** — Architecture globale
- **Partie 3** — Modules P1 (Export PDF · Immobilisations · Stocks · Paie/DTS · Dépôt tribunal · Audit & traçabilité)
- **Partie 4** — Modules P2 (IS/liasse EDI · Cessation-cession · E-facturation)
- **Partie 5** — Modules P3 (à tracer)
- **Partie 6** — Mécanisme de cohérence globale
- **Partie 7** — Normes et référentiels applicables
- **Partie 8** — Écarts d'audit à corriger
- **Partie 9** — Priorisation, feuille de route et charge
- **Partie 10** — Tests et validation
- **Annexes** — A. Commandes du projet · B. Glossaire

---

## Carte d'ensemble (vue « une page »)

```
                        ┌───────────────────────────────────────────────┐
                        │            compta_ma  (FastAPI)               │
                        │   API REST /docs  +  Interface web Jinja2     │
                        └───────────────────────┬───────────────────────┘
                                                │
   ┌──────────────────────── SOCLE COMPTABLE DÉJÀ LIVRÉ ─────────────────────────┐
   │ Plan comptable CGNC (890 comptes) · Écritures partie double · Tiers ICE/IF   │
   │ Factures achat/vente · Règlements · TVA (déclaration + EDI RD) · États       │
   │ (balance, grand livre, CPC, bilan) · Exercices · Audit log · RBAC            │
   └───────┬───────────────┬───────────────┬───────────────┬──────────────────────┘
           │               │               │               │
     ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
     │  P1.1 PDF │   │ P1.2 Immo │   │ P1.3 Stock│   │ P1.4 Paie │
     │ états+pièces│  │ 2xxx+amort│   │ 3xxx+CMUP │   │ DTS 9421  │
     └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
           │               │               │               │
     ┌─────▼───────────────▼───────────────▼───────────────▼──────────────────────┐
     │ P1.6 Piste d'audit · verrouillage de période · rapprochement bancaire       │
     └─────┬──────────────────────────────────────────────────────────────────────┘
           │
   ┌───────▼───────────────┬──────────────────────┬──────────────────────────────┐
   │ P1.5 Dépôt greffe     │ P2.1 IS & liasse EDI │ P2.2 Cessation/cession TVA   │
   │ depotbilan.justice…   │ Simpl-IS (tables)    │ régimes 3 et 4 (V4.0)        │
   └───────────────────────┴──────────────────────┴──────────────────────────────┘
                     (P3 : CbCR · EDI TH/TSC · consolidation · analytique · devises)
```

---

## Partie 1 — Vision et périmètre

### 1.1 Présentation du produit

**Compta MA** est une application de **comptabilité générale et de fiscalité déclarative
marocaine**, multi-sociétés, destinée aux PME et aux professionnels de la comptabilité.
Elle couvre la chaîne complète :

> **pièce justificative → écriture équilibrée → états financiers → déclaration fiscale →
> dépôt légal (DGI / greffe du tribunal) → archivage probant**

Sa valeur ajoutée n'est pas « saisir des écritures », mais **produire des livrables
acceptés par l'administration marocaine** : relevé des déductions TVA (EDI), liasse
fiscale (EDI), déclaration des traitements et salaires (DTS « 9421 »), dépôt des états de
synthèse au greffe — avec les contrôles bloquants et la piste d'audit correspondants.

### 1.2 Utilisateurs cibles

| Profil | Besoin dominant | Modules décisifs |
|---|---|---|
| **PME (comptabilité interne)** | produire factures, états, déclarations, déposer au greffe | TVA EDI (livré), PDF, Immo, Stock, Paie, Greffe |
| **Cabinet comptable / fiduciaire** | tenir **plusieurs dossiers**, produire pour ses clients, déposer en leur nom | multi-sociétés, rôles, **profil « Professionnel » du greffe**, IS/liasse, outils d'import |
| **Expert-comptable / commissaire aux comptes** | révision, piste d'audit, verrouillage, contrôle interne | Audit & traçabilité, rapprochements, journal d'audit, états comparatifs |
| **Chef d'entreprise / dirigeant** | pilotage, échéances, sanctions évitées | tableaux de bord, alertes d'échéances (greffe 3 jours, TVA 20, IS 3 mois) |

Rôles techniques (RBAC existant `roles`) : `ADMIN`, `EXPERT_COMPTABLE`, `COMPTABLE` (+ à
ajouter : `RH_PAIE`, `DEPOSANT_GREFFE`, `AUDITEUR_LECTEUR`).

### 1.3 Périmètre fonctionnel global

| Code | Module | Statut | Priorité |
|---|---|---|---|
| **N0** | Socle : plan comptable, écritures, tiers, facturation, règlements, exercices, RBAC, audit log | ✅ **livré** | — |
| **N1** | TVA : taux historisés, déclaration (collectée/déductible/crédit), ventilation par taux | ✅ **livré** | — |
| **N2** | **Relevé des déductions TVA — export EDI DGI** (Annexe balises RD, modèle ADC082F-15I) | ✅ **livré et déposé (T2 2026)** | — |
| **N3** | États : balance, grand livre, journal, CPC, bilan | ✅ **livré** (écran) | — |
| **P1.1** | **Export PDF** : états de synthèse, notes, factures, bordereaux | ✅ **livré (J1)** | **P1** |
| **P1.2** | **Immobilisations & amortissements** (2xxx) | ✅ **livré (J2)** | **P1** |
| **P1.3** | **Stocks & inventaire permanent** (3xxx) | ✅ **livré (J4)** | **P1** |
| **P1.4** | **Paie & DTS « 9421 »** (IR 2026, CNSS/AMO) | ✅ **livré (J6)** | **P1** |
| **P1.5** | **Dépôt tribunal (greffe)** des états de synthèse | ✅ **livré (J5)** | **P1** |
| **P1.6** | **Audit & traçabilité renforcée** (piste fiable, verrouillage, rapprochements) | ✅ **livré (J3)** | **P1** |
| **P2.1** | **IS & liasse fiscale EDI** (Simpl-IS : tables + codeEdi) | ✅ **livré (J7)** | **P2** |
| **P2.2** | **Cessation / cession d'activité** (régimes TVA 3 et 4) | ✅ **livré (J8)** | **P2** |
| **P2.3** | **E-facturation** (mentions, fichier, canal DGI, accusés) | ⚠️ **livré (J8) — sous réserve de la spécification DGI** (A24) | **P2** |
| **P3.1** | CbCR — déclaration pays par pays (CBC OCDE) | ❌ tracé | **P3** |
| **P3.2** | EDI TH/TSC (taxe professionnelle, articles en masse) | ❌ tracé | **P3** |
| **P3.3** | Consolidation des comptes (CGNC Titre V) | ❌ tracé | **P3** |
| **P3.4** | Comptabilité analytique | ❌ tracé | **P3** |
| **P3.5** | Gestion des devises / écarts de conversion (CGNC Titre II ch. IV) | ❌ tracé | **P3** |

### 1.4 Principes directeurs (non négociables)

1. **Conformité d'abord** — CGNC/PCGE et CGI priment sur l'ergonomie et la performance ;
   tout format de sortie est vérifié contre son **XSD ou sa table de balises officielle**.
2. **Traçabilité intégrale** — chaque donnée est rattachée à sa **source** (facture,
   règlement, paie, inventaire, dépôt greffe) : `source`/`source_id` généralisés, journal
   d'audit append-only, conservation **10 ans** (CGI ; loi 09-08).
3. **Modularité** — un module = un paquet `app/services/<module>` + son routeur + ses
   gabarits + ses tests ; **aucun module n'écrit directement** dans les tables d'un autre :
   il passe par le service (règle n° 3, § 6).
4. **Écritures équilibrées ou rien** — toute génération comptable (facture, paie,
   dotation, inventaire, régularisation) produit une écriture **équilibrée**, validée, non
   modifiable, extournée si nécessaire.
5. **Contrôles bloquants avant dépôt** — pas de fichier EDI, pas de dépôt greffe, pas de
   clôture sans passage des contrôles bloquants du module.
6. **Mono-utilisateur → multi-serveur sans réécriture métier** — un seul paramètre change
   (`DATABASE_URL`) ; le code ne dépend jamais du SGBD.
7. **Idempotence des outils d'import** — rejouer un import ne crée jamais de doublon
   (clé métier : société + tiers + référence).
8. **Sûreté des données de production** — toute écriture en masse est précédée d'une
   **sauvegarde horodatée** et journalisée.

### 1.5 Indicateurs de réussite (à mesurer en recette)

| Indicateur | Cible |
|---|---|
| Taux d'acceptation des fichiers déposés (TVA RD, DTS, liasse) | **100 %** au 1ᵉʳ dépôt |
| Écart balance après production d'un module | **0,00 DH** |
| Couverture de tests du dépôt (services + EDI + outils) | **≥ 80 %**, *85 tests* aujourd'hui comme plancher |
| Délais légaux respectés (TVA le 20, IS 3 mois, greffe) | **alertes 15/7/3 jours** avant échéance |
| Aucune écriture hors période verrouillée | **blocage dur** |

---

## Partie 2 — Architecture globale

### 2.1 Architecture technique

| Couche | Technologie | Statut | Remarque |
|---|---|---|---|
| Langage | Python **3.13** (venv projet `.venv`) | ✅ | |
| Web / API | **FastAPI** + Uvicorn, docs auto `/docs` | ✅ | API et interface partagent les mêmes services |
| ORM / DB | **SQLAlchemy 2.0**, SQLite (phase 1) → **PostgreSQL** (psycopg 3) | ✅ | aucun code métier dépendant du SGBD |
| Migrations | **Alembic** | ✅ | toute nouvelle table = une migration |
| Interface | **Jinja2** + CSS (`app/web/`), français, type Sage | ✅ | mêmes gabarits réutilisés pour le PDF |
| Validation | **pydantic** / pydantic-settings | ✅ | |
| Sécurité | **PyJWT** + **argon2**, RBAC | ✅ | loi 09-08 (données personnelles) |
| Tests | **pytest** + httpx (TestClient) | ✅ | **77 tests** (plancher à ne jamais franchir) |
| Conteneur | Docker / docker-compose | ✅ | phases 2/3 |
| **Contrôle XSD** | `xml.etree` (existant) + **`lxml`** (à ajouter) | ⚠️ à ajouter | **seul `lxml` valide un XSD** → conformité TVA RD, liasse, DTS |
| **Rendu PDF** | **ReportLab** ✅ *(retenu au POC du jalon J0 ; WeasyPrint écarté)* | ✅ `app/services/pdf.py` | WeasyPrint exige le **runtime GTK** (`libgobject-2.0-0`) absent sous Windows → échec d'import |
| Alertes / échéances | tâche planifiée locale ou APScheduler | ❌ à ajouter | TVA (le 20), IS (3 mois), greffe (3 jours) |

> **Décision d'architecture PDF — TRANCHÉE (jalon J0, 22/09/2026) : ReportLab.**
> Un **service unique** `app/services/pdf.py` expose
> `rendre_pdf(document: Document, taille_max=10 Mo) -> bytes`, `moteur_disponible()`
> et `controle_taille_pdf()` ; les modules ne connaissent que ce service.
> · **ReportLab ✅ retenu** : pur Python, **aucune dépendance système**. POC mesuré :
>   120 lignes → **0,50 s / 11,5 Ko** ; 250 lignes → 1,4 s / 23 Ko ; **1 000 lignes
>   → 2,2 s / 86 Ko** ⇒ un état de ~5 000 lignes reste sous le critère de 10 s.
> · **WeasyPrint ❌ écarté** : `OSError: cannot load library 'libgobject-2.0-0'`
>   (runtime **GTK/Pango** requis) → impossible d'empaqueter l'application
>   proprement sous Windows. Il aurait permis de réutiliser les gabarits Jinja2.
> · Contrainte normative respectée : **PDF ≤ 10 Mo** par fichier (portail greffe),
>   contrôlée par `controle_taille_pdf()` — vérifié par test automatisé.
> · Reproductibilité : `python tools\poc_pdf.py --lignes 1000`.

### 2.2 Découpage en modules (arborescence cible)

```
app/
├── core/            config, sécurité, audit, numérotation, barèmes marocains (rates_ma)
├── db/              base, session, seed (plan comptable, TVA, société, admin)
├── models/          tables SQLAlchemy par domaine :
│                    company, party, invoice, entry, tax  (livrés)
│                    + asset, stock, payroll, greffe, banking  (nouveaux)
├── schemas/         Pydantic (entrées/sorties API)
├── services/        ── CŒUR MÉTIER : un fichier par domaine ──
│   ├── accounting.py      écritures, validation, extourne          (livré)
│   ├── invoicing.py       factures, lignes, règlements             (livré)
│   ├── parties.py         tiers + sous-comptes                     (livré)
│   ├── vat.py             TVA : déclaration, ventilation           (livré)
│   ├── edi_tva.py         relevé des déductions EDI DGI            (livré)
│   ├── reporting.py       balance, grand livre, CPC, bilan         (livré)
│   ├── identifiers.py     IF/ICE : normalisation, contrôle         (livré)
│   ├── accounts.py        plan comptable, comptes à la volée       (livré)
│   ├── pdf.py             moteur PDF ReportLab (Document, contrôle 10 Mo)   (livré — D1)
│   ├── etats_synthese.py  bilan brut/amortissements/net, ESG, ETIC (CGNC)   (livré — J1)
│   ├── pdf_documents.py   documents PDF : états, pièces, bordereaux         (livré — J1)
│   ├── assets.py          ★ immobilisations, amortissements, cessions       P1.2
│   ├── stocks.py          ★ articles, mouvements, CMUP/FIFO, inventaire     P1.3
│   ├── payroll.py         ★ paie, bulletins, cotisations, comptabilisation  P1.4
│   ├── edi_dts.py         ★ déclaration DTS « 9421 » (XML EDI)              P1.4
│   ├── greffe.py          ★ dossier de dépôt + suivi des états + alertes    P1.5
│   ├── audit_trail.py     ★ piste fiable, verrouillage, rapprochements      P1.6
│   ├── fiscal_liasse.py   ★ liasse IS/IR (tables + codeEdi)                 P2.1
│   ├── activity_events.py ★ cessation temporaire / cession TVA (3 et 4)     P2.2
│   └── e_invoice.py       ★ facture électronique (art. 145 / loi 43-20)     P2.3
├── api/routers/     REST par domaine (+ un routeur par nouveau module)
├── web/             routes HTML + gabarits Jinja2 (+ nouveaux écrans)
└── data/            plan_comptable_cgnc.csv (890 comptes) + XSD/référentiels DGI

tests/               un fichier par module + intégration + conformité XSD
tools/               imports et maintenance (plan comptable, achats, normalisation IF)
```

**Règle des 4 artefacts obligatoires** — un module P1/P2 n'est « livré » que lorsqu'il
fournit : ① le **service métier** (règles + écritures), ② le **routeur API** + schémas
Pydantic, ③ les **écrans web** en français, ④ les **tests** (unitaires, intégration, et
**validation du format de sortie** quand il alimente un dépôt officiel).

**Conventions de code (rappel, déjà appliquées dans le socle)** : français pour les
libellés et messages utilisateur ; anglais pour le code ; `from __future__ import
annotations` ; typage systématique ; erreurs métier via `AccountingError` /
`ComplianceError` ; chaque service expose des fonctions pures testables ; aucun accès SQL
hors service.

### 2.3 Modèle de données global

**Tables existantes (18)** — socle multi-tenant : `companies`, `fiscal_years`, `users`,
`roles`, `user_roles`, `user_companies`, `journals`, `accounts`, `third_parties`,
`invoices`, `invoice_lines`, `payments`, `entries`, `entry_lines`, `vat_rates`,
`numbering_sequences`, `audit_log`, `alembic_version`.

**Modèle relationnel cible (les ★ sont les tables nouvelles)**

```
companies ─┬─ fiscal_years ── period_locks ★            (P1.6 verrouillage mensuel/exercice)
           ├─ third_parties ─┬─ invoices ── invoice_lines
           │                 ├─ payments
           │                 ├─ assets ★ ── asset_depreciation_lines ★ ── asset_events ★
           │                 └─ employees ★ ── pay_contracts ★ ── payslips ★ ── payslip_lines ★
           ├─ accounts ──── entries ── entry_lines ──── (source, source_id) → tout module
           ├─ stock_items ★ ── stock_movements ★ ── stock_counts ★ ── stock_count_lines ★
           │                 └─ stock_provisions ★
           ├─ tax_declarations ★    (TVA, IS/IR, DTS : période, état, fichier, accusé)
           │      ├─ liasse_tables ★ ── liasse_cells ★          (P2.1)
           │      └─ activity_events ★                          (P2.2)
           ├─ greffe_deposits ★ ─┬─ greffe_documents ★
           │                     ├─ greffe_payments ★
           │                     └─ greffe_events ★
           ├─ bank_statements ★ ── bank_statement_lines ★ ── bank_reconciliations ★
           └─ e_invoice_documents ★                             (P2.3)
```

| Table ★ | Module | Colonnes clés | Rôle / relations |
|---|---|---|---|
| `assets` | P1.2 ✅ | `company_id`, `third_party_id` (fournisseur), `invoice_id`, `num_compte` (2xxx), `libelle`, `date_acquisition`, `date_mise_service`, `valeur_origine`, `duree_annees`, `mode` (linéaire/dégressif), `coefficient`, `tva_compte` (34551), `statut` (en service / cédé / rebuté) | fiche d'immobilisation ; source de tout amortissement |
| `asset_depreciation_lines` | P1.2 ✅ | `asset_id`, `exercice`, `base`, `annuite`, `cumul`, `vnc`, `entry_id` | plan d'amortissement **et** écriture de dotation |
| `asset_events` | P1.2 ✅ | `asset_id`, `type` (dotation / cession / rebut / **régularisation art. 106**), `date`, `montant`, `entry_id`, `motif` | journal des mouvements |
| `stock_items` | P1.3 | `company_id`, `reference`, `designation`, `unite`, `compte_stock` (3xxx), `compte_achat`, `compte_vente`, `seuil_alerte`, `mode_valorisation` (CMUP/FIFO), `stock_courant`, `cmup_courant` | fiche article |
| `stock_movements` | P1.3 | `item_id`, `date`, `type` (entrée / sortie / **inventaire**), `quantite`, `cout_unitaire`, `valeur`, `invoice_id`, `entry_id` | historisation **inventaire permanent** |
| `stock_counts` / `stock_count_lines` | P1.3 | `date`, `statut` ; `item_id`, `qte_theorique`, `qte_physique`, `ecart`, `valeur_ecart` | inventaire physique et variation de stock |
| `stock_provisions` | P1.3 | `item_id`, `exercice`, `montant`, `entry_id` | dépréciation des stocks (3911 / 6196) |
| `employees` | P1.4 | `company_id`, `matricule`, `nom`, `cin`, `cnss`, `situation_familiale`, `enfants`, `date_entree`, `type_contrat` | salarié (données personnelles → loi 09-08) |
| `pay_contracts` | P1.4 | `employee_id`, `salaire_base`, `primes`, `avantages`, `date_effet`, `mode_paiement` | élément contractuel |
| `payslips` / `payslip_lines` | P1.4 | `employee_id`, `periode` (AAAA-MM), `brut`, `ir`, `cnss`, `amo`, `net`, `entry_id` ; `libelle`, `base`, `taux`, `gain`, `retenue` | bulletins + écriture de paie |
| `tax_declarations` | P1.4 · P1.5 · P2.1 · P2.2 | `company_id`, `type` (TVA/IS/IR/DTS), `periode`, `regime`, `statut` (brouillon/soumise/acceptée/rejetée), `fichier`, `hash`, `accuse_le` | **registre unique des déclarations** (traçabilité et relances) |
| `activity_events` | P2.2 | `company_id`, `type` (cessation_temporaire / cession / cessation), `date_effet`, `regime_tva` (3 ou 4), `periode`, `declaration_id` | événements de vie de l'entreprise |
| `greffe_deposits` | P1.5 | `company_id`, `fiscal_year_id`, `forme_juridique`, `statut` (les 7 états du portail), `date_ag`, `date_limite_depot`, `date_soumission`, `date_approbation`, `date_limite_paiement`, `date_depot`, `montant_taxes`, `reference_certificat`, `certificat_path` | suivi du dépôt au greffe |
| `greffe_documents` | P1.5 | `deposit_id`, `type_piece`, `nom_fichier`, `taille_octets`, `hash_sha256` | pièces PDF ≤ 10 Mo, contrôlées |
| `greffe_payments` | P1.5 | `deposit_id`, `montant`, `date`, `moyen` (CMI), `reference` | taxes du dépôt |
| `greffe_events` | P1.5 | `deposit_id`, `etat_avant`, `etat_apres`, `date`, `motif` (motif de rejet du greffe) | journal des transitions |
| `period_locks` | P1.6 | `company_id`, `fiscal_year_id`, `periode` (mois ou `None` = exercice), `verrouille_le`, `par_user_id` | verrouillage dur des écritures |
| `bank_statements` / `bank_statement_lines` | P1.6 | `company_id`, `compte` (5141…), `date_debut`, `date_fin`, `solde_final` ; `date`, `libelle`, `montant`, `sens` | relevés bancaires importés |
| `bank_reconciliations` | P1.6 | `statement_line_id`, `entry_line_id`, `type` (rapproché / ajustement), `entry_id` | rapprochement bancaire |
| `liasse_tables` / `liasse_cells` | P2.1 | `declaration_id`, `tableau_id` ; `code_edi`, `valeur`, `numero_ligne` | liasse **au format DGI** (tables + `codeEdi`) |
| `e_invoice_documents` | P2.3 | `invoice_id`, `statut`, `xml`, `identifiant_dgi`, `accuse`, `envoye_le` | facture électronique (art. 145 / loi 43-20) |

**Règles de schéma** : toute table métier porte `company_id` (multi-société), `created_at`
et, quand elle produit une écriture, `entry_id` ; toute ligne d'écriture porte
`source` + `source_id` (piste d'audit fiable). Aucune table nouvelle ne duplique un solde :
les soldes sont **calculés** depuis `entry_lines` (une seule vérité comptable).

### 2.4 Mécanisme de cohérence entre modules — le cycle de production

Tout s'articule autour d'un **cycle annuel unique** que chaque module vient alimenter ou
consommer, sans jamais court-circuiter la comptabilité :

```
                    ┌──────────────────── EXERCICE N ─────────────────────┐
  Factures ──┐      │                                                      │
  Règlements ├─────►│ ÉCRITURES ÉQUILIBRÉES (entries / entry_lines)        │
  Paie ──────┤      │   ↑ source + source_id  (piste d'audit fiable)       │
  Immo ──────┤      │   ↑ verrouillage par period_locks (P1.6)             │
  Stocks ────┘      └───────────┬──────────────────────────────────────────┘
                                │
      MENSUEL ──────────────────┼──► TVA (le 20) · DTS 9421 · rapprochement bancaire · verrouillage du mois
   TRIMESTRIEL ─────────────────┼──► relevé des déductions TVA → XML EDI DGI  ✅ déployé
                                │
       ANNUEL (ordre imposé) ───┴──► 1. inventaire des stocks (P1.3)
                                     2. dotations aux amortissements (P1.2)
                                     3. régularisations TVA art. 106 (P1.2)
                                     4. états de synthèse → PDF (P1.1)
                                     5. AG dans les 6 mois de la clôture (P1.5)
                                     6. liasse fiscale IS → EDI Simpl-IS (P2.1)
                                     7. dépôt des états de synthèse au greffe (P1.5)
                                     8. certificat de dépôt archivé (P1.5 / P1.6)
```

**Matrice « qui consomme quoi / qui produit quoi » (dépendances réelles) :**

| Module | Consomme | Produit | Dépendances bloquantes |
|---|---|---|---|
| **P1.1 PDF** | `reporting` (bilan, CPC, ESG, notes), factures, paie, greffe | PDF ≤ 10 Mo | aucun (transverse) |
| **P1.2 Immo** | factures d'achat classe 2, plan comptable (23xx/283x), `fiscal_years` | écritures 2xxx + **34551** + dotations 6193/283x ; plan d'amortissement ; régularisations art. 106 | **P1.1** (notes annexes) |
| **P1.3 Stocks** | factures achat/vente, articles, inventaires physiques | écritures 3xxx, **variation de stocks**, provisions 391x/6196 | P1.1 |
| **P1.4 Paie** | salariés, contrats, barèmes IR/CNSS (`rates_ma`) | bulletins, écritures 617x/444x/445x/3431, **DTS « 9421 » XML** | P1.1 (bulletins), `tax_declarations` |
| **P1.5 Greffe** | états de synthèse (P1.1), forme juridique, date d'AG | dossier de pièces + suivi des 7 états + certificat | **P1.1 obligatoire** |
| **P1.6 Audit** | toutes les écritures, relevés bancaires, `audit_log` | verrouillages, rapprochements, piste d'audit, alertes | transverse (bloque tout le monde) |
| **P2.1 IS/liasse** | balance définitive (après immo + stocks + paie), immo, provisions | `liasse_tables`/`liasse_cells` → XML EDI Simpl-IS | P1.2, P1.3, P1.4, P1.6 (exercice clos) |
| **P2.2 Cessation/cession** | événements de vie, TVA de la période | déclarations TVA régimes **3** et **4** | N2 (EDI TVA), P2.1 |
| **P2.3 E-facturation** | factures de vente | XML facture électronique + accusé DGI | N1 (TVA), P1.1 (PDF) |

**Règles de non-régression (résumé — détail en Partie 6)** :
① aucune écriture validée n'est modifiée (extourne uniquement) ; ② une période verrouillée
refuse toute écriture (y compris import d'outil) ; ③ un module déclaratif ne modifie jamais
les écritures ; ④ tout nouveau module passe les **contrôles transverses** (équilibre, TVA,
IF/ICE, complétude) avant validation ; ⑤ la suite de tests existante (**77**) reste verte,
et chaque module ajoute ses propres tests.

### 2.5 Schéma visuel — architecture applicative

```
       UTILISATEURS                    APPLICATIONS                      DONNÉES
 ┌──────────────────┐        ┌──────────────────────────────┐   ┌────────────────────┐
 │ PME · Cabinet    │◄──────►│  Interface web (Jinja2, FR)  │   │  SQLite (phase 1)  │
 │ Expert-comptable │        │  /connexion /factures /tva…  │   │  PostgreSQL (ph.2) │
 │ Dirigeant        │        │  API REST /docs (FastAPI)    │◄─►│  Alembic migrations│
 └──────────────────┘        └───────────────┬──────────────┘   └─────────┬──────────┘
                                             │                            │
                              ┌──────────────▼──────────────┐   ┌─────────▼──────────┐
                              │        SERVICES MÉTIER      │   │  ÉCRITURES         │
                              │ accounting · invoicing ·    │◄─►│  entries/entry_    │
                              │ vat · edi_tva · reporting · │   │  lines (équilibre) │
                              │ pdf · assets · stocks ·     │   └─────────┬──────────┘
                              │ payroll · greffe · audit…   │             │
                              └───┬─────────┬─────────┬─────┘             │
                                  │         │         │                   │
        ┌─────────────────────────▼──┐ ┌────▼──────┐ ┌▼──────────────────┴──────────┐
        │ DÉPÔTS OFFICIELS (fichiers)│ │ ARCHIVES  │ │ DOCUMENTS (PDF)               │
        │ · TVA RD XML → Simpl-TVA   │ │ 10 ans    │ │ · états de synthèse           │
        │ · DTS XML → SIMPL « 9421 » │ │ certificat│ │ · factures, bulletins         │
        │ · Liasse XML → Simpl-IS    │ │  dépôt    │ │ · bordereaux de dépôt         │
        │ · PDF → depotbilan.justice │ │ greffe    │ │                               │
        └────────────────────────────┘ └───────────┘ └───────────────────────────────┘
```

---

## Partie 3 — Modules P1 (priorité haute)

### 3.1 P1.1 — Export PDF (états, pièces, bordereaux)

**Objectif** — produire tous les documents **papier/PDF** de la chaîne comptable et
**débloquer le dépôt au greffe** (le portail n'accepte que des PDF ≤ 10 Mo).

**Périmètre fonctionnel**

| Sortie | Contenu | Source |
|---|---|---|
| **États de synthèse** | ① **Bilan** (actif/passif, brut/amortissements/net), ② **CPC** (compte de produits et charges), ③ **ESG — État des Soldes de Gestion** (marge brute, VA, EBE, résultat d'exploitation, résultat courant, résultat net), ④ **ETIC — État des Informations Complémentaires** (notes annexes), ⑤ **Tableau de Financement** (si seuils atteints) | `reporting` |
| **États de contrôle** | balance générale (6/7 colonnes), grand livre par compte, journaux, balance âgée clients/fournisseurs | `reporting` |
| **Pièces** | facture de vente (mentions CGI art. 145), avoir, facture d'achat, bulletin de paie, bon de réception, ordre de virement | `invoicing`, `payroll` |
| **Bordereaux** | bordereau de dépôt greffe (liste des pièces + checklist), bordereau TVA/DTS/liasse (récapitulatif du fichier transmis) | `greffe`, `edi_tva`, `edi_dts`, `fiscal_liasse` |

**Règles normatives**
- **CGNC**, plan comptable général des entreprises, **Titre I : états de synthèse** — modèle
  national normalisé (bilan / CPC / ESG / ETIC) : les libellés et la présentation doivent
  **suivre le modèle officiel**, pas une mise en page libre.
- **CGNC — caractéristiques des états de synthèse** : régularité, sincérité, image fidèle,
  continuité d'exploitation, permanence des méthodes, coût historique, spécialisation des
  exercices, prudence, clarté, importance significative.
- **CGI art. 145** : mentions obligatoires de la facture, dont **ICE**, numérotation
  continue — déjà contrôlé dans l'application.
- **Guide greffe (Ministère de la Justice, nov. 2025)** : **PDF ≤ 10 Mo par fichier**.

**Contrôles bloquants**
1. Génération refusée si le **bilan n'est pas équilibré** (`total actif = total passif`) ;
2. refus si un compte collectif est mouvementé directement (règle existante) ;
3. **taille ≤ 10 Mo** par document destiné au greffe (message explicite + proposition de
   compression) ;
4. avertissement si l'exercice n'est pas clôturé (mention « provisoire » apposée) ;
5. filigrane « BROUILLON » tant que la déclaration/exercice n'est pas validé (évite un
   dépôt légal d'un document non définitif).

**Critères d'acceptation**
- les montants du PDF sont **identiques au centime** à ceux de l'écran (`reporting`) ;
- l'ESG est calculé automatiquement depuis la balance (soldes de gestion 6xx/7xx, comptes
  611x à 619x, 711x à 719x) et **reconcilié** avec le CPC et le résultat net ;
- un PDF de bilan d'un dossier de 5 000 lignes d'écriture génère en **< 10 s** et pèse
  < 2 Mo ;
- tests : comparaison des montants PDF/écran, contrôle de taille, présence des mentions
  légales.

**Dépendances** : `reporting` (livré) ; **aucune** (module transverse, à faire en premier
car il conditionne P1.5 et la facturation client).

**Charge estimée** : **5 j** (dont ½ j de POC moteur).

### 3.2 P1.2 — Immobilisations & amortissements

**Objectif** — gérer le cycle de vie des immobilisations (acquisition → mise en service →
amortissement → cession/rebut) avec **comptes CGNC exacts**, **TVA d'immobilisation au
34551** et **régularisations TVA art. 106**.

**Périmètre fonctionnel**

| Écran / action | Contenu |
|---|---|
| Fiche immobilisation | libellé, `num_compte` (2xxx), fournisseur + facture d'origine, date d'acquisition, **date de mise en service**, valeur d'origine HT, **durée** (années), **mode** (linéaire / dégressif), coefficient, valeur résiduelle, photo/pièce jointe |
| Plan d'amortissement | généré à la mise en service : base, annuité, cumul, **VNC** par exercice (tableau projeté + réalisé) |
| Dotation annuelle | calcul + écriture **6193x / 283x** (dépréciations : **6194x**), générée par exercice |
| Cession / rebut / mise au rebut | sortie d'actif : **7513** (produit de cession), **3481** (créance), **6513** (VNA), reprise des amortissements (**283x**) |
| **Régularisation TVA art. 106** | sur immobilisations : fraction annuelle (5 ans, 10 ans pour les immeubles ⚠️ à confirmer) → écriture de régularisation |
| États | tableau des immobilisations (brut / amortissements / net par poste), tableau des cessions, état des amortissements fiscalement déductibles |

**Comptes PCGE utilisés (vérifiés dans `plan_comptable_cgnc.csv`, 890 comptes)**

| Opération | Débit | Crédit |
|---|---|---|
| Acquisition d'immobilisation | `2xxx` (ex. **2332** matériel et outillage, **2340** matériel de transport, **2351** mobilier, **2355**/`235x` matériel informatique) + **34551** (TVA récupérable sur immobilisations) | `4411…` fournisseur (ou `5141` si paiement immédiat) |
| Dotation aux amortissements | **6193x** (61933 installations/matériel, 61934 matériel de transport, 61935 mobilier/matériel de bureau, 61931 terrains, 61932 constructions) | **283x** (2833, 2834, 2835, 2831, 2832) |
| Dépréciation (idem, réversible) | **6194x** (61943 corporelles, 61942 incorporelles) | `293x`/`284x` (provisions pour dépréciation) |
| Cession (produit) | `3421`/`5141`/`5161` ou **3481** (créance sur cession) | **7513** (produits des cessions d'immobilisations corporelles) |
| Cession (sortie d'actif) | **6513** (VNA des immobilisations corporelles cédées) | `2xxx` valeur d'origine + reprise dans **283x** (amortissements cumulés) |
| Mise au rebut | **6513** | `2xxx` + `283x` |

**Règles normatives**
- **CGNC — plan comptable, Titre II, Chapitre I : Actif immobilisé** — trois catégories
  (immobilisations en non-valeurs, corporelles et incorporelles, financières) ;
  **amortissement** = constatation **systématique** et **irréversible** de la dépréciation
  liée au temps et à l'usage ; **dépréciation** = constat **réversible** ; la **VNC**
  (valeur nette d'amortissement) = valeur d'entrée − amortissements cumulés.
- **CGNC — méthodes d'évaluation** : base = **coût d'acquisition** (dépenses directement
  attribuables), durée d'utilité par catégorie, amortissement **linéaire** par défaut ;
  un bien peut être amorti **par composants**.
- **CGI art. 10** : amortissements fiscalement déductibles, **prorata temporis** (décompte
  à partir de la mise en service), durée d'utilisation, et **amortissement dégressif**
  réservé à certains biens d'équipement — le **coefficient multiplicateur doit être
  paramétré** (voir § 8, ambiguïté n° 4).
- **CGI art. 106** : **régularisation de la TVA** ayant grevé une immobilisation lorsque la
  déduction totale n'est pas acquise (prorata / sortie du droit à déduction) : régularisation
  par **fractions égales** étalées dans le temps (immobilisations meubles / immeubles).
- **TVA** : la TVA sur immobilisation va au **34551** (« État - TVA récupérable sur
  immobilisations ») et **jamais** au 34552 — règle **déjà implémentée** dans
  `invoicing.tva_deductible_account()`.

**Contrôles bloquants**
1. durée > 0 et **valeur résiduelle < valeur d'origine** ;
2. mise en service **postérieure à l'acquisition** ;
3. **impossible de modifier une dotation rattachée à une période verrouillée** (P1.6) ;
4. une cession exige un **prix** (ou un justificatif de mise au rebut) et **génère une
   écriture complète** (produit + sortie d'actif + TVA de cession le cas échéant) ;
5. un bien **déjà cédé** ne peut plus être amorti ;
6. amortissement du **dernier exercice plafonné** pour ramener la VNC à la valeur
   résiduelle (jamais d'amortissement négatif).

**Critères d'acceptation**
- Σ amortissements cumulés + VNC = valeur d'origine, à chaque exercice, **au centime** ;
- la dotation d'un bien **mis en service en cours d'exercice** applique un **prorata
  temporis** (règle fiscale), paramétrable (comptable : annuité pleine ou prorata) ;
- après cession, le compte 2xxx et son 283x sont **soldés à zéro** ;
- tests : calcul linéaire/dégressif, prorata temporis, sortie d'actif équilibrée,
  régularisation art. 106, verrouillage de période.

**Dépendances** : `invoicing` (factures classe 2 → 34551, livré), **P1.1** (notes annexes),
**P1.6** (verrouillage). **Alimente** : bilan (brut/amort./net), CPC (dotations),
**P2.1 liasse** (tableaux d'immobilisations et d'amortissements), ETIC.

**Charge estimée** : **8 j**.

### 3.3 P1.3 — Stocks & inventaire permanent

**Objectif** — suivre les articles en quantité et en valeur, produire la **variation de
stocks** réglementaire et les provisions, avec la **méthode de valorisation choisie**
(CMUP ou FIFO).

**Périmètre fonctionnel**

| Écran / action | Contenu |
|---|---|
| Fiche article | référence, désignation, unité, famille, `compte_stock` (3xxx), compte d'achat, compte de vente, **seuil d'alerte**, **mode de valorisation** (CMUP / FIFO), TVA d'achat/vente |
| Entrées | facture d'achat stockée, retour client, entrée pour production, **transfert** ; coût unitaire = prix HT **+ frais accessoires** |
| Sorties | vente, consommation interne, **perte/casse**, retour fournisseur ; valorisation au **CMUP** ou **FIFO** en vigueur |
| Inventaire physique | saisie des quantités réelles, **écarts** (théorique/physique), valorisation de l'écart, écriture |
| Variation de stocks | constat à la clôture (mode intermittent) ou suivi permanent (mode permanent) |
| Dépréciation | provision si **valeur d'inventaire < valeur comptable** (prudence) → **391x / 6196** |
| États | état de stock valorisé, mouvements par article, rotation, **liste des articles sous seuil** |

**Deux régimes de tenue (paramètre par société)**

| Régime | Fonctionnement | Comptes |
|---|---|---|
| **Intermittent** (défaut) | achats en charges ; à la clôture, constatation du **stock final** et de la **variation** | achats `6111`/`6112`/`6121`/`6122`/`6123` · stock final **3111**/3112/3118 · variation **6114** (marchandises) / **6124** (matières et fournitures, 61241-61243) |
| **Inventaire permanent** (CGNC Titre V) | les comptes de stock sont **mouvementés en permanence** ; pas de variation constatée en fin d'exercice | **3111**, 3112, 3116, 3118 ; sorties valorisées au coût |

**Comptes PCGE utilisés (vérifiés dans le plan de référence)**

| Poste | Comptes |
|---|---|
| Stocks | **3111** marchandises (groupe A), **3112** (groupe B), **3116** en cours de route, **3118** autres, 312x/313x/314x (matières, produits en cours, produits finis) |
| Provisions | **3911** marchandises, **3912** matières et fournitures, **3913** produits en cours, **3914** produits intermédiaires, **3915** produits finis |
| Achats / variation | **6111**/**6112** achats de marchandises, **6114** variation de stocks de marchandises, **6119** RRR obtenus, **6121**/**6122**/**6123** achats de matières et fournitures, **6124** variation des stocks de matières et fournitures |
| Ventes | **7111** ventes de marchandises (+ 7113 export, 7119 RRR accordés), **7121**/**7124** ventes de biens/services |
| Dépréciation (charge) | **6196** (D.E.P. pour dépréciation des stocks — à confirmer sur le sous-compte 6196x du plan) |

**Règles normatives**
- **CGNC — Titre II, Chapitre II : Actif circulant → Stocks** : évaluation au **coût de
  revient** (coût d'acquisition + frais accessoires d'achat + coûts de production) ;
  méthodes de valorisation admises : **coût moyen pondéré (CMUP)** et **FIFO
  (« premier entré, premier sorti »)** ; la méthode du **LIFO est proscrite** ; application
  avec **permanence des méthodes** (changement = information en ETIC).
- **CGNC — Titre V, Chapitre I** : « **Tenue des comptes d'inventaire permanent en
  comptabilité générale** » → le suivi permanent est explicitement prévu par le référentiel.
- **CGNC — méthodes d'évaluation / prudence** : les stocks sont **dépréciés** lorsque la
  valeur d'inventaire (prix du marché, état, obsolescence) devient inférieure à la valeur
  comptable.
- **Inventaire physique** : au moins **une fois par exercice** (obligation légale de
  dresser l'inventaire) — l'écart d'inventaire est **valorisé et justifié**.

**Contrôles bloquants**
1. **quantité négative interdite** (sauf mode « stock négatif autorisé » explicitement
   activé, avec alerte) ;
2. **sortie non valorisée** refusée (aucun mouvement à 0 DH sans justification) ;
3. changement de méthode de valorisation **en cours d'exercice refusé** (permanence des
   méthodes) ;
4. écart d'inventaire au-delà d'un seuil (ex. > 5 % de la valeur du stock) → **visa
   obligatoire** (utilisateur habilité) et motif ;
5. **période verrouillée** → aucun mouvement rétroactif.

**Critères d'acceptation**
- Σ (quantités × coût unitaire) = valeur du compte de stock **au centime**, dans les deux
  régimes ;
- CMUP recalculé après chaque entrée : `CMUP = ( valeur stock + valeur entrée ) / ( qté + qté )` ;
- FIFO : la consommation suit strictement la file (test avec 3 lots à coûts différents) ;
- l'écriture de variation ramène la balance à l'état de l'inventaire physique ;
- tests : CMUP, FIFO, écart d'inventaire, provision, seuil d'alerte, verrouillage.

**Dépendances** : `invoicing` (achats/ventes), **P1.1** (états), **P1.6** (verrouillage).
**Alimente** : bilan (poste stocks, net de provisions), CPC (achats, variation, dotations),
**P2.1 liasse** (tableaux de stocks et provisions).

**Charge estimée** : **8 j**.

### 3.4 P1.4 — Paie & DTS « 9421 »

**Objectif** — produire les **bulletins de paie**, les **écritures de paie** et la
**déclaration des traitements et salaires (DTS)** déposable sur les téléservices SIMPL,
avec les barèmes marocains historisés.

**Périmètre fonctionnel**

| Écran / action | Contenu |
|---|---|
| Fichier salariés | matricule, état civil, **CIN**, **n° CNSS**, situation de famille, **nombre d'enfants** (IR), date d'entrée/sortie, type de contrat, coordonnées bancaires |
| Contrat / rémunération | salaire de base, primes, indemnités, avantages (logement, transport), mode de paiement, date d'effet |
| Cycle de paie mensuel | saisie des variables (heures, primes, absences, avances, oppositions) → **calcul** → **validation** (écriture) → **paiement** (par banque ou caisse) |
| Calcul | **IR** (barème progressif, réduction pour charges de famille), **CNSS** (parts salariale et patronale, plafond), **AMO**, mutuelle, retraite complémentaire (CIMR), assurances groupe |
| Bulletin de paie | mise en page légale (mentions obligatoires), **PDF** (P1.1) |
| Comptabilisation | écriture globale de paie par période (+ écriture de paiement) |
| **DTS « 9421 »** | génération du **fichier XML EDI** + fiche récapitulative, contrôle avant dépôt, suivi (`tax_declarations`) |
| États | livre de paie annuel, état des cotisations, attestations de salaire, cumuls par salarié |

**Comptes PCGE utilisés (vérifiés dans le plan de référence)**

| Nature | Comptes |
|---|---|
| Rémunérations (charge) | **6171** : `61711` appointements et salaires · `61712` primes et gratifications · `61713` indemnités et avantages divers · `61714` commissions au personnel · `61715` rémunérations des administrateurs, gérants et associés |
| Charges sociales (charge) | **6174** : `61741` cotisations de sécurité sociale (CNSS) · `61742` caisses de retraite · `61743` mutuelles · `61744` prestations familiales · `61745` assurances accidents du travail ; **6176** charges sociales diverses (`61761` assurances groupe, `61763` allocations aux œuvres sociales, `61764` habillement, `61765` préavis et licenciement, `61766` médecine du travail) |
| Dettes sociales | **4432** rémunérations dues au personnel · `4434` oppositions sur salaires · `4437` charges du personnel à payer · **4441** Caisse Nationale de la Sécurité Sociale · `4443` caisses de retraite · `4445` mutuelles · `4447` charges sociales à payer · `4448` autres organismes sociaux |
| Dette fiscale (IR retenu à la source) | **4452** État - Impôts, taxes et assimilés (sous-compte IR sur salaires à créer si absent) |
| Paiement | `5141` banque (virement des salaires) · `5161` caisse |

**Écriture type d'une paie mensuelle**

```
Débit  6171x  rémunérations brutes (salaires, primes, indemnités)
Débit  6174x  charges patronales (CNSS, AMO, retraite, mutuelle, AT)
Crédit 4432   net à payer au personnel
Crédit 4441   part salariale + part patronale CNSS/AMO
Crédit 4443 / 4445  retraite complémentaire / mutuelle
Crédit 4452   IR retenu à la source
Crédit 4434   oppositions sur salaires (le cas échéant)
→ total débit = total crédit (contrôle bloquant)
```

**Règles normatives**
- **CGI / LF 2026 (barème IR)** : barème progressif, **réduction pour charges de famille**,
  règles de la retenue à la source sur traitements et salaires — barèmes **historisés par
  date de validité** dans `app/core/rates_ma.py` (déjà présent pour IR/CNSS/AMO, à étendre).
- **CNSS / AMO 2026** (arrêté **n° 1314.25**, Code du travail) : assiette et **plafonds**,
  parts salariale et patronale, prestations familiales et accidents du travail.
- **DGI — GUIDE DTS** (« déclaration des traitements et salaires », communément appelée
  **« la 9421 »**) : dépôt via les **téléservices SIMPL** ; **deux modes** : **EFI** (saisie
  en ligne) et **EDI** (fichier **XML généré par un logiciel**) ; formulaire structuré en
  onglets (personnel permanent ; **salariés bénéficiant de l'exonération — art. 57-20°** du
  CGI ; documents scannés à **zipper** avant insertion). Référence locale :
  `Documentation\RÉFÉRENTIEL TECHNIQUE DGI\ir\GUIDE+DTS.pdf`.
- **Loi 09-08 (CNDP)** : les données de paie (CIN, CNSS, situation familiale) sont des
  **données personnelles** → accès restreint (rôle `RH_PAIE`), journalisation, conservation
  **10 ans**.

> ⚠️ **Point bloquant identifié (voir § 8, écart n° 6)** : le **XSD du fichier DTS n'est pas
> présent** dans le référentiel dépouillé (seul le guide d'utilisation l'est). Sans schéma,
> la génération EDI ne peut pas être **validée par l'application**. Deux options :
> **(a)** obtenir le XSD/annexe DTS auprès de la DGI (recommandé) ; **(b)** livrer d'abord le
> module en mode **EFI assisté** (production d'un état de saisie), l'EDI XML venant ensuite.

**Contrôles bloquants (paie)**
1. **assiette et plafonds** CNSS/AMO respectés (barème historisé) ;
2. IR calculé par le **barème en vigueur à la date de paie** (jamais codé en dur) ;
3. **net à payer ≥ 0** ; une **opposition** ne peut excéder le net saisissable ;
4. écriture de paie **équilibrée** (débit = crédit) sinon refus ;
5. **période de paie verrouillée** → aucune saisie ni recalcul rétroactif (P1.6) ;
6. la DTS est refusée si **Σ bulletins ≠ total déclaré**, si un salarié a un **n° CNSS
   manquant**, ou si le fichier échoue à la **validation XSD** (lorsque le schéma est
   disponible).
**Critères d'acceptation**
- IR d'un cas de test de référence (barème 2026) = valeur attendue **au dirham** ;
- CNSS plafonnée : test avec un salaire au-dessus du plafond ;
- Σ bulletins = écriture = déclaration DTS (trois sources, un seul total) ;
- bulletin conforme aux **mentions obligatoires** et au **modèle 9421** ;
- tests : calcul IR/CNSS/AMO, plafonds, oppositions, écriture équilibrée, verrouillage.

**Dépendances** : **P1.1** (bulletins PDF), `rates_ma` (barèmes), `tax_declarations`
(registre), **P1.6** (verrouillage). **Alimente** : CPC (charges de personnel), bilan
(dettes sociales/fiscales), **P2.1 liasse** (tableau des frais de personnel).

**Charge estimée** : **15 j** (le module le plus lourd du lot P1).

### 3.5 P1.5 — Dépôt tribunal (greffe) des états de synthèse

**Objectif** — rendre **opérationnelle et traçable** l'obligation légale de dépôt annuel des
états de synthèse au **greffe du tribunal** via le portail du Ministère de la Justice, avec
checklist, contrôles, suivi d'état, alertes de délais et **archivage du certificat**.

**Base légale et source opérationnelle**
- **Loi 5-96** (SNC, SCS, SCA, **SARL** ; dahir n° **1-97-49 du 13 février 1997**) :
  **art. 10** — le rapport de gestion, l'inventaire et **les états de synthèse** sont
  soumis à l'approbation de l'assemblée **dans les six mois** de la clôture (documents
  communiqués 15 jours avant) ; **Titre VII « De la publicité », art. 93** — la publicité
  s'effectue « **par dépôt d'actes ou de pièces au greffe du tribunal du lieu du siège
  social** » et par insertion dans un journal d'annonces légales et au Bulletin officiel.
- **Loi 17-95** (sociétés anonymes ; modifiée notamment par la loi 19-20) : **art. 14** —
  « la publicité par dépôt d'actes ou de pièces est faite **au greffe du tribunal** auprès
  duquel le registre du commerce est tenu » (double exemplaire certifié).
- **Guide officiel « Dépôt électronique des états de synthèse »** (Ministère de la Justice,
  Direction de la Modernisation et des SI, **novembre 2025**) — référence locale :
  `deepsesk\GuideUtilisation.pdf`.

**Processus officiel à implémenter (repris du guide)**

```
1. Inscription électronique sur le portail        → https://depotbilan.justice.gov.ma
2. Dépôt de la demande d'adhésion (imprimée/signée) auprès du tribunal  → validation par le greffe
   (profils : « Professionnel » = cabinet déposant pour ses clients  |  « Entreprise »)
3. Dépôt des états de synthèse : sélection du N° de REGISTRE DE COMMERCE + informations
   de l'exercice + chargement des PIÈCES (type de pièce + fichier)
        ⇒ contrainte technique : FICHIER PDF, taille ≤ 10 Mo
4. Paiement électronique des taxes APRÈS approbation du dossier (paiement en ligne CMI)
        ⇒ délai de 3 JOURS, sinon rejet automatique
5. Certificat de dépôt signé électroniquement  ⇒ à archiver (preuve légale)
```

**Les 7 états d'une demande de dépôt (à suivre dans l'application)**

| État du portail | Signification | Action attendue dans compta_ma |
|---|---|---|
| **Nouveau** | créée, non soumise | reprise ou annulation possible |
| **En cours** | en traitement par le greffe | aucun envoi ; suivi |
| **Annulé** | annulée | clôture de la ligne, motif conservé |
| **Rejeté** | dossier incomplet (motif du greffe) | **alerte forte** : corriger la pièce, re-soumettre |
| **Amender** | **dépôt hors délai** → amende à payer | **alerte rouge** : régulariser + provisionner l'amende |
| **Approuvé** | traité, attend le paiement | **alerte 3 jours** (rejet automatique au-delà) |
| **Déposé** | finalisé, certificat disponible | **archiver le certificat** + verrouiller l'exercice |

**Checklist des pièces du dossier de dépôt (paramétrable ; liste officielle à relever au
portail lors de la 1ʳᵉ adhésion ⚠️)**

| Pièce | SNC | SARL | SA | Produit par compta_ma |
|---|---|---|---|---|
| **États de synthèse** (bilan, CPC, ESG, ETIC) — certifiés conformes | ✔ | ✔ | ✔ | **P1.1 PDF** |
| **Tableau de financement** (selon seuils) | — | selon | selon | P1.1 |
| **Rapport de gestion** | ✔ | ✔ | ✔ | P1.1 (gabarit à saisir/compléter) |
| **Rapport du/des commissaires aux comptes** | — | si nommés | ✔ (si CAC) | pièce externe (dépôt manuel) |
| **Procès-verbal de l'AG d'approbation** + texte des résolutions | ✔ | ✔ | ✔ | gabarit P1.1 (saisie) |
| **État de synthèse / déclaration complémentaire du portail** | ✔ | ✔ | ✔ | généré par `greffe` |
| **Justificatif de paiement des taxes** | ✔ | ✔ | ✔ | `greffe_payments` |

**Périmètre fonctionnel**

| Écran / action | Contenu |
|---|---|
| Dossier de dépôt (par exercice) | forme juridique, date d'AG, exercice, **checklist de pièces**, génération des PDF, contrôle de complétude |
| Contrôles préalables | voir liste ci-dessous ; aucune soumission sans « tout vert » |
| Export du dossier | **archive ZIP** (pièces PDF + bordereau récapitulatif) prête à téléverser sur le portail |
| Suivi du dépôt | ligne par exercice avec **état**, dates (soumission, approbation, limite de paiement, dépôt), **motifs de rejet**, montant des taxes |
| Alertes | AG > 6 mois (risque **Amender**/amende), **3 jours** après approbation, dépôt non finalisé en fin d'exercice suivant |
| Archives | **certificat de dépôt signé** + hash, classé au dossier permanent (conservation 10 ans) |

**Contrôles bloquants**
1. **exercice clos** (statut `fermé`) : on ne dépose pas des comptes provisoires ;
2. **bilan équilibré** et états de synthèse générés sans anomalie ;
3. chaque pièce **PDF ≤ 10 Mo** ; complétude de la **checklist** pour la forme juridique ;
4. **date d'AG ≤ 6 mois** après la clôture (loi 5-96 art. 10) → sinon **avertissement
   bloquant** : le dépôt sera « Amender » (amende) ;
5. **RC / IF / ICE** de la société renseignés et conformes (le portail exige le **n° de
   registre de commerce**) ;
6. interdiction de **re-soumettre** une ligne « Déposé » (unicité par exercice).

**Critères d'acceptation**
- un dossier complet est produit en **une action** (ZIP + bordereau) et chaque pièce passe le
  contrôle de taille ;
- le **cycle de vie des 7 états** est historisé (`greffe_events`) avec motif de rejet ;
- l'alerte « 3 jours » se déclenche à l'approbation et disparaît au paiement ;
- le certificat est archivé avec **empreinte SHA-256** et accessible depuis l'exercice ;
- tests : checklist par forme juridique, contrôle des 10 Mo, calcul de la date limite d'AG,
  transitions d'état, alerte 3 jours.

**Dépendances** : **P1.1 (obligatoire)** ; `parties`/`companies` (RC, IF, ICE) ;
**P1.6** (verrouillage après dépôt). **Charge estimée** : **6 j**.

### 3.6 P1.6 — Audit & traçabilité renforcée

**Objectif** — rendre les comptes **défendables devant un contrôle** (DGI, expert-comptable,
commissaire aux comptes, greffe) grâce à une **piste d'audit fiable**, des périodes
**verrouillables**, un **rapprochement bancaire** outillé et un **journal d'audit**
exploitable.

**Périmètre fonctionnel**

| Brique | Contenu |
|---|---|
| **Piste d'audit fiable** | `source` + `source_id` sur **toute** ligne d'écriture (facture, règlement, paie, dotation, inventaire, régularisation) ; navigation **écriture → pièce d'origine** et inversement ; conservation **10 ans** |
| **Chaînage / immuabilité** | empreinte **SHA-256** par écriture validée + **chaînage** (hash de l'écriture précédente) : toute altération devient détectable ; journal **append-only** |
| **Verrouillage de période** | `period_locks` (mois et/ou exercice) : **refus dur** de toute écriture, y compris les **outils d'import** ; **journalisation des tentatives** ; déverrouillage réservé à `ADMIN`/`EXPERT_COMPTABLE` avec motif |
| **Rapprochement bancaire** | import du **relevé** (CSV normalisé, OFX) → appariement **automatique** (montant, date, libellé) puis **manuel** ; ajustements ; **état de rapprochement** (solde comptable / solde bancaire / écarts justifiés) |
| **Journal d'audit exploitable** | `audit_log` enrichi : utilisateur, IP, action, entité, **avant/après (JSON)**, filtres par date/utilisateur/entité/action, **export CSV** |
| **Tableau de bord de conformité** | contrôles transverses permanents + **échéances** (TVA le 20, DTS, IS 3 mois, AG 6 mois, greffe) avec feux vert/orange/rouge |

**Règles normatives**
- **CGNC — « Organisation de la comptabilité »** : comptabilité tenue avec **pièces
  justificatives**, **sans blanc ni altération**, dans l'ordre chronologique, et
  **permanence des méthodes** ; les livres et pièces doivent pouvoir être présentés à tout
  contrôle.
- **CGI** : conservation des registres et pièces pendant **dix (10) ans** (obligation de
  conservation rattachée aux obligations déclaratives ; ex. art. 116 du CGI consulté).
- **Code de commerce (loi 15-95)** : obligation de tenir une comptabilité et de conserver
  les livres et pièces (⚠️ numéros d'articles à confirmer dans l'édition en vigueur).
- **Loi 09-08 (CNDP)** : la traçabilité des **accès** aux données personnelles (salariés,
  tiers) est une exigence de sécurité.
- **Loi 17-95 / loi 5-96** : le **commissaire aux comptes** doit pouvoir vérifier les
  comptes → le journal d'audit et la piste fiable **facilitent sa mission**.

**Contrôles bloquants / alertes**
1. écriture dans une **période verrouillée** → **refus** (+ journalisation de la tentative) ;
2. **rupture de chaînage** (hash) détectée → alerte critique « dossier altéré
   hors application » ;
3. écriture **déséquilibrée** → refus (déjà en place) ;
4. **compte collectif** mouvementé directement → refus (existant) ;
5. **doublon** de pièce (même tiers + même référence) → alerte ;
6. écart de rapprochement bancaire **ancien (> 3 mois)** → alerte rouge ;
7. toute écriture **sans pièce justificative** → alerte « pièce manquante » (objectif : 0).

**Critères d'acceptation**
- test automatisé : une tentative d'écriture sur période verrouillée **échoue** et laisse une
  trace dans `audit_log` ;
- la modification d'une écriture en base (test d'intrusion) **casse le chaînage** et est
  détectée par le contrôle ;
- l'état de rapprochement s'équilibre : `solde comptable ± écarts = solde bancaire` ;
- le journal d'audit s'exporte en CSV filtrable et reste **immuable** ;
- tests : verrouillage/déverrouillage, hash & chaînage, appariement bancaire (auto/manuel),
  export du journal, alertes d'échéances.

**Dépendances** : transverse — **bloque** tous les autres modules (aucun module ne doit
écrire hors période ouverte). **Alimente** : P1.2/P1.3/P1.4 (dotations, inventaires, paie
saisis dans des périodes ouvertes) et **P2.1** (exercice clos).

**Charge estimée** : **7 j**.

---

## Partie 4 — Modules P2 (priorité moyenne)

### 4.1 P2.1 — IS & liasse fiscale EDI (Simpl-IS)

**Objectif** — produire la **déclaration annuelle du résultat (IS/IR)** et la **liasse
fiscale** au **format EDI de la DGI**, contrôlée et archivable.

**Périmètre fonctionnel**

| Étape | Contenu |
|---|---|
| **Résultat fiscal** | part du résultat net comptable → **réintégrations / déductions** fiscales, **résultat fiscal**, report déficitaire |
| **IS** | calcul du taux applicable (barème LF 2026 dans `rates_ma`), **cotisation minimale** (assiette et taux), **crédit d'impôt / acomptes**, solde |
| **Liasse** | construction de **tables numérotées** et de **cellules codées** (`codeEdi`) : bilan, CPC, ESG, immobilisations, amortissements, stocks, personnel, dettes/créances, provisions… |
| **Modes de dépôt** | **EDI** (fichier XML) ou **EFI** (saisie assistée) selon le guide **DRG/Simpl-IS** |
| **Contrôles** | cohérence liasse ↔ balance ↔ états de synthèse ; validation **XSD** ; complétude des tableaux obligatoires |
| **Suivi** | `tax_declarations` (période, état, fichier, hash, accusé de réception) + archivage |

**Référentiels et format**
- **Cahier des charges EDI Simpl-IS** — version **1.0** (référence locale
  `deepsesk\9370_cahierdescharges.pdf`) et **v2.0.3**
  (`Documentation\RÉFÉRENTIEL TECHNIQUE DGI\simple-is\simpl_is_cahier_des_charges_edi_v2_0_3.pdf`).
- **Schémas XSD de liasse** (`Documentation\RÉFÉRENTIEL TECHNIQUE DGI\ir\`) :
  `liasse_modele_normal.xsd`, `liasse_modele_comptable simplifié.xsd`,
  `liasse_modele_Assurances.xsd`, `liasse_modele_établissements de crédit.xsd`.
  Structure observée : `groupeValeursTableau → ValeursTableau → tableau(id)` puis
  `ValeurCellule → cellule(codeEdi) → valeur` (+ `numeroLigne`, `extraField`).
  **Tableaux listés dans le schéma** : id `1, 2, 5, 6, 7, 10, 11, 12, 23, 24, 26, 27, 28,
  32, 34, 36, 37, 38, 39, 40, 41, 200, 201, 202, 203, 220, 240`.
- **`référentiel des codifications.xlsx`** : table de correspondance **rubrique ↔ `codeEdi`**
  (les codes vont de quelques centaines à ~14 380) → **c'est la pièce maîtresse du module**.
- **IR/DRG** : `Guide de Télédéclaration de la Déclaration de Revenu Global (DRG)
  professionnel) — 2020`, qui décrit la **saisie de la liasse fiscale en EFI et son envoi en
  EDI** (pour les entreprises relevant de l'IR).

> ⚠️ **Point de vigilance majeur** : la liasse n'est pas une « impression » mais un
> **mapping de données** (tableaux + codes) → le module doit embarquer le référentiel de
> codification **versionné**, et un **test de non-régression par tableau** (nombre de
> cellules attendues). Une erreur de code = déclaration erronée : c'est le module le plus
> **risqué** du projet, à faire **après** le socle P1.

**Contrôles bloquants**
1. **exercice clos** et verrouillé (P1.6) ;
2. **concordance** : chaque tableau de la liasse est réconcilié avec la balance et les états
   de synthèse (écart toléré : 0, sauf justification tracée) ;
3. **résultat fiscal** cohérent avec le CPC et les réintégrations saisies ;
4. **cotisation minimale** comparée à l'IS calculé (le dû = le plus élevé) ;
5. **validation XSD** obligatoire avant toute remise de fichier ;
6. refus si un tableau obligatoire est **absent** (détecté par le schéma).

**Critères d'acceptation**
- liasse générée **valide au XSD** (outil `lxml`) sur un dossier de test ;
- réconciliation automatique : Σ liasses = balance sur **tous** les postes suivis ;
- le régénérateur produit un fichier **strictement identique** pour un même dossier
  (déterminisme) ;
- tests : mapping des codes, cohérence, IS/cotisation minimale, validation XSD.

**Dépendances** : **P1.1** (états), **P1.2**, **P1.3**, **P1.4** (données de liasse),
**P1.6** (clôture). **Charge estimée** : **15 j** (dont ~5 j de mapping).

### 4.2 P2.2 — Cessation et cession d'activité (TVA régimes 3 et 4)

**Objectif** — déclarer les événements de **vie de l'entreprise** introduits par la
**V4.0** de la table des balises RD.

**Périmètre fonctionnel**
- **cessation temporaire d'activité** (`<regime>3</regime>`, `<periode>1</periode>`) ;
- **cession ou cessation définitive TVA** (`<regime>4</regime>`, `<periode>1</periode>`) ;
- **déclaration des déductions** correspondante + **dernière déclaration TVA** de la période ;
- **apurement** : régularisations (immobilisations non totalement déduites, stocks à la
  cessation), solde de TVA, archivage ;
- **états de synthèse de cessation** (bilan de clôture) via **P1.1** ;
- suivi dans `tax_declarations` + `activity_events` (type, date d'effet, régime).

**Référentiels**
- **Annexe 1 — table des balises RD, version 4.0** (DGI) : « Modifications apportées au
  tableau pour intégrer la **déclaration de cession ou cessation de la TVA** » : `regime` =
  **1** mensuel, **2** trimestriel, **3** cessation temporaire d'activité, **4** cession ou
  cessation TVA ; `periode` = 1 pour ces deux cas. Référence locale :
  `Documentation\RÉFÉRENTIEL TECHNIQUE DGI\TVA\Annexe1_EDI_Simpl-TVA_Correspondance_Balise_RD_V4.0.pdf`.
- **CGI** : conditions et **délais** de déclaration de cessation/cession ⚠️ *(à confirmer dans
  l'édition 2026 : le délai et les obligations d'apurement doivent être vérifiés avant
  développement — voir § 8, écart n° 1)*.

**Contrôles bloquants** : date d'effet renseignée ; aucune déclaration TVA **postérieure** à
la cessation définitive ; **régularisations calculées** avant clôture ; fichier EDI conforme
(`regime` 3/4 + `periode` 1) et validé.

**Dépendances** : **N2** (moteur EDI TVA livré), **P1.2** (régularisations TVA),
**P1.6** (clôture). **Charge estimée** : **4 j**.

### 4.3 P2.3 — E-facturation (art. 145 CGI / loi 43-20)

**Objectif** — émettre, transmettre et archiver la **facture électronique** conformément au
cadre marocain, en réutilisant le moteur de facturation existant.

**Périmètre fonctionnel**
- génération du **document électronique** de facture (d'avoir également) depuis la facture
  validée, avec **mentions légales** complètes (CGI art. 145) ;
- **cycle de vie** : brouillon → émise → transmise → **acceptée / rejetée** → archivée ;
- **archivage probant** (fichier + hash + accusé) sur **10 ans**, lié à la facture ;
- contrôle **avant émission** : identité du client (ICE), mentions, cohérence TVA ;
- suivi dans `e_invoice_documents` + `tax_declarations` si l'échange est assimilé à une
  déclaration.

**Référentiels**
- **CGI art. 145** (mentions obligatoires, ICE) — déjà contrôlé à la validation des factures.
- **Loi 43-20** relative à la facturation électronique (cadre légal marocain) ; échéancier
  d'assujettissement par catégorie de contribuables.

> ⚠️ **Référentiel incomplet (voir § 8, écart n° 7)** : le **cahier des charges technique
> DGI de la facturation électronique** (format du fichier, signature, protocole de
> transmission, QR code) **n'est pas présent** dans la documentation dépouillée. Le module
> ne peut donc pas être **spécifié au format** avant obtention de ce document.

**Contrôles bloquants** : mentions légales complètes ; **ICE** du client (entre
professionnels) ; unicité de la facture (séquence) ; validation du format ; interdiction de
transmettre une facture annulée/avoir sans référence à l'originale.

**Dépendances** : `invoicing` (livré), **P1.1** (version PDF), **N1** (TVA).
**Charge estimée** : **10 j** (hors attente de spécification DGI).

---

## Partie 5 — Modules P3 (à tracer, hors périmètre immédiat)

| Module | Contenu | Référentiels disponibles localement | Déclencheur |
|---|---|---|---|
| **P3.1 — CbCR (déclaration pays par pays)** | production du fichier **CBC** (XML OCDE) : entité déclarante, groupe, juridictions, agrégats (CA, résultat, impôt, capital, effectifs, actifs), entités constitutives | `CBC_cahier de charges_V1.0.pdf` (« Cahier des charges du mode EDI de la **déclaration pays par pays** »), `CBC_XSD_DGI.xsd`, `isocbctypes_v1.1.xsd`, `oecdcbctypes_v5.0.xsd` (namespaces `urn:oecd:ties:cbc:v2` et `…:cbcstf:v5`), `Exemple_XML_CBC.xml` | client **groupe multinational** concerné (⚠️ seuil et champ d'application à confirmer sur le CGI) |
| **P3.2 — EDI TH/TSC (taxe professionnelle)** | demande de **génération en masse des articles** TH/TSC : projets immobiliers, titres fonciers, permis d'habiter, communes (codes), nature et usage des biens, superficies | `Génération en masse des articles TH TSC EDI CDC.pdf` (**v1 du 03/06/2025**), `Annexe1_DemandeCreationArticleWrapper.xsd`, `Annexe2_…Wrapper.xml` (exemple complet), `Annexe3_Referentiel.pdf` (nomenclatures commune/nature/usage) | client **promoteur immobilier** / BTP |
| **P3.3 — Consolidation** | périmètre de consolidation, méthodes (**intégration globale**, **proportionnelle**, **mise en équivalence**), retraitements et éliminations, comptes consolidés | **CGNC Titre V, chapitre IV « Consolidation »** | groupe détenant des participations |
| **P3.4 — Comptabilité analytique** | axes analytiques (sections, produits, projets), charges par destination, coûts de revient, marge par activité | **CGNC Titre V, chapitre II « Comptabilité analytique »** | besoin de pilotage de coûts |
| **P3.5 — Gestion des devises** | multi-devises (factures, règlements), cours de conversion, **écarts de conversion**, provisions pour pertes de change, réévaluation de clôture | **CGNC Titre II, chapitre IV « Éléments dont la valeur dépend des fluctuations de monnaie étrangère »** | facturation à l'export/import (déjà partiellement tracé pour les ventes `7113`/`7122`) |

**Règle P3** : ces modules **ne sont pas planifiés** ; ils sont tracés ici pour éviter les
décisions d'architecture qui les rendraient impossibles plus tard. Deux exigences de
préparation sont néanmoins retenues : ① prévoir un **champ devise** sur les factures et les
règlements (P3.5) ; ② prévoir des **axes analytiques optionnels** sur les lignes d'écriture
(P3.4) — les deux sont **peu coûteux maintenant**, très coûteux après coup.

---

## Partie 6 — Mécanisme de cohérence globale

### 6.1 La chaîne de valeur des données (principe fondateur)

```
   PIÈCE                     ÉCRITURE                ÉTAT / DÉCLARATION           DÉPÔT / PREUVE
   ─────                     ────────                ──────────────────           ──────────────
facture achat ─────────┐
règlement ─────────────┤
bulletin de paie ──────┼──► entries/entry_lines ──► balance ──► bilan/CPC/ESG ──► PDF états de synthèse
dotation amortissement ┤    (DÉBIT = CRÉDIT)         grand livre     liasse IS        ──► dépôt greffe
inventaire de stocks ──┤    source + source_id      journaux        TVA (RD EDI)     ──► certificat
régularisation TVA ────┘    hash + chaînage                         DTS 9421         ──► archivage 10 ans
```

**Trois propriétés garanties par ce chaînage :**
1. **Remontée** : d'un montant du bilan au document d'origine (`source_id`) ;
2. **Descente** : d'une facture à toutes ses conséquences comptables ;
3. **Détection** : toute écriture ajoutée, modifiée ou supprimée hors du flux normal casse
   le chaînage de hachage (P1.6) et devient visible.

### 6.2 Matrice de dépendances (qui alimente / qui bloque qui)

Légende : `→` alimente · `⇢` dépend (consomme) · `⊘` bloque (contrôle dur)

| | P1.1 PDF | P1.2 Immo | P1.3 Stock | P1.4 Paie | P1.5 Greffe | P1.6 Audit | P2.1 Liasse | N1–N2 TVA |
|---|---|---|---|---|---|---|---|---|
| **P1.1 PDF** | — | ⇢ états | ⇢ états | ⇢ bulletins | → pièces | ⇢ journal | → états | ⇢ relevés |
| **P1.2 Immo** | → notes | — | — | — | → notes | ⊘ verrou | → tableaux immo | → **34551** |
| **P1.3 Stock** | → états | — | — | — | → notes | ⊘ verrou | → tableaux stocks | — |
| **P1.4 Paie** | → bulletins | — | — | — | — | ⊘ verrou | → frais personnel | → IR/CNSS |
| **P1.5 Greffe** | ⇢ **obligatoire** | — | — | — | — | → archivage | — | — |
| **P1.6 Audit** | ⇢ journal | ⊘ période | ⊘ période | ⊘ période | ⊘ certificat | — | ⊘ **exercice clos** | ⊘ période |
| **P2.1 Liasse** | ⇢ états | ⇢ immo | ⇢ stocks | ⇢ paie | — | ⇢ clôture | — | ⇢ TVA |
| **N1–N2 TVA** | → relevés | ⇢ **34551** | — | — | — | ⊘ période | → TVA liasse | — |

**Lecture** : `P1.6 Audit` est le module **le plus contraignant** (il verrouille tout) mais le
**moins dépendant** (il ne consomme que des écritures) → à développer **tôt**. `P2.1 Liasse`
est le **plus dépendant** (immo + stocks + paie) → à développer **en dernier**.

### 6.3 Règles de non-régression (contrat de développement)

| # | Règle | Contrôle automatisé |
|---|---|---|
| **R1** | Une écriture **validée** n'est jamais modifiée : seules l'**extourne** et la contre-passation sont permises | test d'immuabilité (existant) + chaînage (P1.6) |
| **R2** | Toute écriture est **équilibrée** (Σ débit = Σ crédit) | contrôle avant `validate_entry` |
| **R3** | Aucune écriture dans une **période verrouillée** (y compris imports et outils) | test de verrouillage (P1.6) |
| **R4** | Un module **déclaratif** (TVA, liasse, DTS, greffe) ne **modifie jamais** les écritures : il lit et contrôle | tests d'intégration |
| **R5** | Une **source** est toujours renseignée : aucune écriture « orpheline » | contrôle de complétude `source`/`source_id` |
| **R6** | La **TVA d'immobilisation** va au **34551**, celle des charges au **34552** | test dédié (existant) |
| **R7** | Les **IF/ICE** sont contrôlés et normalisés **avant** dépôt, sans sur-contraindre la source officielle | tests identifiants + § 8 |
| **R8** | La suite de tests **ne régresse jamais** | `pytest` (**85** aujourd'hui = plancher) |

### 6.4 Registre des contrôles automatiques

| Contrôle | Périmètre | Moment | Si échec |
|---|---|---|---|
| Équilibre de l'écriture | écriture | validation | **refus** |
| Équilibre général (Σ débit − Σ crédit = 0) | dossier | avant clôture / dépôt | **blocage** |
| Bilan équilibré (actif = passif) | exercice | PDF bilan, liasse, greffe | **blocage** |
| TVA ligne à ligne = base × taux | dossier | avant EDI TVA | **blocage** |
| TVA déclarée = TVA comptabilisée | période | déclaration | alerte |
| IF/ICE présents et conformes | tiers + société | saisie + dépôt | **blocage** |
| ICE manquant sur facture B2B | facture | validation | **refus** (existant) |
| Doublon de pièce (tiers + référence) | dossier | saisie / import | alerte |
| Verrouillage de période | toute écriture | chaque écriture | **refus** |
| Chaînage de hachage | dossier | à la demande / avant dépôt | **alerte critique** |
| Taille PDF ≤ 10 Mo | greffe | génération du dossier | **blocage** |
| Complétude des pièces du greffe | greffe | soumission | **blocage** |
| Date d'AG ≤ 6 mois de la clôture | greffe | création du dépôt | **avertissement bloquant** |
| Paiement des taxes ≤ 3 jours après approbation | greffe | suivi quotidien | **alerte rouge** |
| Validation XSD (TVA RD, DTS, liasse, CBC) | EDI | génération | **blocage** |
| Concordance liasse ↔ balance ↔ états | liasse | génération | **blocage** |
| Cotisation minimale vs IS calculé | IS | déclaration | **blocage** |
| Stock négatif / sortie non valorisée | stocks | mouvement | **refus** |
| VNC + cumul amortissements = valeur d'origine | immobilisations | dotation / clôture | **blocage** |
| Aucun règlement orphelin / facture non soldée | dossier | clôture | alerte (existant) |

### 6.5 Incohérences et alertes à signaler (l'application doit « parler »)

L'application **signale**, elle ne corrige jamais en silence :
① écart **TVA collectée / déductible** produisant un **crédit structurel** (cas rencontré en
production : **aucune vente déclarée pour 902,05 DH de TVA déductible**) ;
② **écart relevé EDI ↔ comptabilité** : le relevé suit la **date de paiement** (régime de
l'encaissement), la comptabilité la **date d'écriture** → écart normal mais **à expliciter**
dans le dossier de travail ;
③ facture **incomplète** (mention légale manquante) ;
④ immobilisation **non mise en service** depuis plus de 6 mois ;
⑤ stock **immobile** ou sous **seuil d'alerte** ;
⑥ salarié **sans n° CNSS** / données de paie incomplètes ;
⑦ dépôt greffe **hors délai** (risque « Amender » + amende) ;
⑧ écriture **sans pièce justificative** ;
⑨ déclaration TVA **postérieure** à une cessation définitive.

### 6.6 Traçabilité entre modules (règle d'implémentation)

| Donnée produite | Source | Trace conservée |
|---|---|---|
| Écriture de facture | `Invoice` | `source = "invoice"`, `source_id = invoice.id` *(existant)* |
| Écriture de règlement | `Payment` | `source = "payment"`, `source_id = payment.id` |
| Écriture de dotation | `Asset` + `AssetDepreciationLine` | `source = "asset_depreciation"`, `source_id = ligne.id` |
| Écriture de variation de stock | `StockMovement` / `StockCount` | `source = "stock_inventory"`, `source_id = …` |
| Écriture de paie | `PayRun` / `Payslip` | `source = "payroll"`, `source_id = période` |
| Écriture de régularisation TVA | `AssetEvent` (art. 106) | `source = "vat_regularisation"`, `source_id = event.id` |
| Fichier déposé (TVA / DTS / liasse / CBC) | `TaxDeclaration` | fichier + **hash SHA-256** + accusé horodaté |
| Dossier de dépôt greffe | `GreffeDeposit` | pièces + hash + **certificat** archivé |

**Conséquence pratique** : deux écrans transverses suffisent à prouver la cohérence —
① **« Piste d'audit »** (recherche par pièce → écritures → états) et
② **« Tableau de bord de conformité »** (tous les contrôles du § 6.4, avec feux vert/orange/rouge).

---

## Partie 7 — Normes et référentiels applicables

### 7.1 Table de correspondance « règle → source → implémentation »

| Domaine | Document et ancrage précis | Ce que l'application en fait | Référence locale |
|---|---|---|---|
| **Comptabilité (référentiel)** | **CGNC** — Code Général de Normalisation Comptable : norme générale (principes, méthodes d'évaluation) + plan comptable général des entreprises (Titres I à V) ⚠️ *numéro du texte de promulgation non lisible dans le PDF fourni (couverture image) : à relever sur le Bulletin Officiel* | logique comptable, états de synthèse, règles d'évaluation immo/stocks | `Documentation\reference-comptable\cgnc.pdf` |
| **Comptabilité (plan de comptes)** | **PCGE** — plan comptable des entreprises ; plan de référence du projet : **890 comptes** | `app/data/plan_comptable_cgnc.csv`, contrôle de codification, sous-comptes de tiers | projet `app/data/` |
| **États de synthèse** | **CGNC Titre I** : bilan · CPC · **ESG (État des Soldes de Gestion)** · **ETIC (État des Informations Complémentaires = notes annexes)** · tableau de financement selon seuils | P1.1 PDF · P2.1 liasse · P1.5 greffe | CGNC |
| **Immobilisations** | **CGNC Titre II ch. I** (actif immobilisé, amortissements, dépréciations) + **CGI art. 10** (amortissements déductibles, prorata temporis, dégressif) | module **P1.2** | CGNC + CGI 2026 |
| **TVA — TVA récupérable** | **CGNC** : `34551` TVA récupérable sur **immobilisations**, `34552` sur **charges** | `invoicing.tva_deductible_account()` *(implémenté)* | plan de comptes |
| **TVA — taux** | **CGI** (art. **99** et suivants ; références **99-A / 99-B** citées par le projet ⚠️ *à re-confirmer sur l'édition 2026*) ; **LF 2026** : **20 %** et **10 %** (7 % et 14 % supprimés au 01/01/2026) | `app/core/rates_ma.py`, table `vat_rates` **historisée** | CGI 2026 |
| **TVA — relevé des déductions (EDI)** | **Annexe 1 « Correspondance des balises RD » v4.0** + modèle **ADC082F-15I** (**art. 112 CGI**) + son **XSD** + **CC EDI Simpl-TVA RD v2.0** + **exemple XML v2.0** | `app/services/edi_tva.py` *(implémenté)* : ordre des balises, `<tx>` en pourcentage, `<mp><id>` 1→7, `<dpai>`/`<dfac>`, `<prorata>` optionnel | `…\TVA\Annexe1_…_RD_V4.0.pdf`, `deepsesk\TVA-EDI.xlsm`, `…\TVA\annexe2_…Exemple_V2.0.xml` |
| **TVA — régularisation / prorata** | **CGI art. 106** : régularisation de la TVA sur immobilisations, changement de prorata, cessation | module **P1.2** ; mécanisme de prorata *implémenté* | CGI 2026 |
| **Factures** | **CGI art. 145** : mentions obligatoires, **ICE**, numérotation continue | `invoicing` + gabarits ; module P2.3 | CGI 2026 |
| **IS / IR** | **CGI** : IS (taux 20/35 %, **cotisation minimale**), IR, acomptes, délais de déclaration | `rates_ma.py`, module **P2.1** | CGI 2026 |
| **Liasse fiscale (EDI)** | **CC EDI Simpl-IS v1.0** (réf. DGI **9370**) et **v2.0.3** ; **XSD de liasse** (normal, comptable simplifié, assurances, établissements de crédit) ; **référentiel des codifications** ; **guide DRG professionnel 2020** (liasse en EFI **et** EDI) | module **P2.1** | `…\simple-is\`, `…\ir\` |
| **Paie / DTS** | **Guide DTS** — « déclaration des traitements et salaires », formulaire **9421** (dépôt **EDI/EFI** via SIMPL) ; **CGI** : barème IR, **art. 57-20°** (exonérations salariés), **art. 116** (retenues à la source) | module **P1.4** | `…\ir\GUIDE+DTS.pdf` |
| **Social** | **CNSS / AMO** : assiettes et plafonds ; **arrêté n° 1314.25** ; **Code du travail** | `rates_ma.py`, module **P1.4** | sources officielles |

| **Sociétés commerciales** | **Loi 17-95** (SA ; **art. 14** : publicité par **dépôt d'actes ou de pièces au greffe du tribunal** ; modifiée notamment par la loi 19-20) ; **Loi 5-96** (SNC, SCS, SCA, **SARL** ; dahir n° **1-97-49 du 13 février 1997**) : **art. 10** (AG d'approbation **≤ 6 mois** de la clôture, documents communiqués 15 jours avant) et **Titre VII « De la publicité », art. 93** (dépôt **au greffe du tribunal** du siège + journal d'annonces légales + Bulletin officiel) | forme juridique, dossier **P1.5 greffe**, délais | `Documentation\reference-juridique\` |
| **Dépôt des états de synthèse** | **Guide « Dépôt électronique des états de synthèse »** — Ministère de la Justice, Direction de la Modernisation et des SI, **novembre 2025** ; portail **https://depotbilan.justice.gov.ma** : profils *Professionnel / Entreprise*, **pièces PDF ≤ 10 Mo**, 7 états du dossier, **paiement ≤ 3 jours** après approbation, **certificat signé électroniquement** | module **P1.5** | `deepsesk\GuideUtilisation.pdf` |
| **Entreprise (statut)** | **Charte PME — loi 53-00** (dahir **n° 1-02-188** du 25/07/2002) ; **loi relative aux établissements touristiques et autres formes d'hébergement** | paramétrage société, obligations sectorielles | `reference-juridique\` |
| **Commerce (tenue des livres)** | **Code de commerce — loi 15-95** ⚠️ *numéros d'articles à confirmer* : obligation de tenir une comptabilité, conservation des livres et pièces | module **P1.6** (conservation, piste d'audit) | sources officielles |
| **Données personnelles** | **Loi 09-08** (dahir n° 1-09-15) — CNDP : protection des données, sécurité, durées de conservation | RBAC, chiffrement, journalisation, conservation **10 ans** | projet (CDC v1 § 0) |
| **Taxe professionnelle (TH/TSC)** | **CC EDI « génération en masse des articles TH TSC »** v1 du **03/06/2025** + XSD/wrapper + **référentiel** des nomenclatures (commune, nature et usage des biens) | module **P3.2** | `…\Taxe Professionnelle\` |
| **CbCR (pays par pays)** | **CC EDI « déclaration pays par pays » v1.0** + XSD **OCDE** (`urn:oecd:ties:cbc:v2`, `…:cbcstf:v5`) + exemple XML | module **P3.1** | `…\simple-is\CBC…` |
| **Facturation électronique** | **Loi 43-20** + **CGI art. 145** ; ⚠️ **CDC technique DGI absent** du référentiel fourni | module **P2.3** (spécification en attente) | — |

### 7.2 Hiérarchie des normes et règle d'arbitrage

En cas de contradiction entre deux sources, l'ordre **décroissant** suivant s'applique :

```
1. Loi / dahir / loi de finances      (CGI, loi 5-96, loi 17-95, loi 15-95, loi 09-08, loi 43-20)
2. Décret d'application
3. Arrêté                             (ex. CNSS n° 1314.25)
4. Cahier des charges officiel        (DGI : CC EDI Simpl-TVA RD v2.0 ; Ministère de la Justice : dépôt des états de synthèse)
5. Annexe / table des balises         (ex. Annexe 1 « balises RD » v4.0)
6. Schéma technique XSD / modèle      (ex. modèle officiel ADC082F-15I)
7. Exemple officiel fourni            (ex. annexe2_EDI_releveDeduction_Exemple_V2.0.xml)
```

**Règle d'arbitrage du projet** : en cas de divergence entre un niveau inférieur et un niveau
supérieur — cas réel rencontré avec `<prorata>` (documentée dans l'**annexe v4.0** et dans
l'**exemple officiel**, **absente du XSD**) — on retient la solution **acceptée par
l'administration au niveau le plus élevé**, on la rend **paramétrable**, et on **trace
l'écart** au § 8. Le format finalement retenu pour le relevé TVA est celui d'un
**fichier réellement déposé et accepté** (`ReleveDeductions_2026_T2.xml`).

---

## Partie 8 — Écarts d'audit à corriger

### 8.1 Les huit écarts identifiés (module · correction · impact · priorité)

> **État au 22/09/2026 — jalons J0, J2 et J3** : les écarts **2, 3 et 5** sont **corrigés et
> testés** (§ 9.7) ; l'écart **8** était déjà corrigé (outillage), documentation à remplacer ;
> l'écart **9** (absence d'écritures d'à-nouveaux) est **corrigé au jalon J3** (§ 9.10) —
> la clôture génère désormais l'écriture d'ouverture de l'exercice suivant. Restent ouverts :
> **1** (traité par P2.2), **4** (confirmation DGI), **6** (XSD DTS à obtenir), **7**
> (CDC e-facturation à obtenir).

| # | Constat (source) | Module concerné | Correction à apporter | Impact si non corrigé | Prio |
|---|---|---|---|---|---|
| **1** | **`<regime>` : la V4.0 ajoute deux régimes** — `3` = cessation **temporaire** d'activité, `4` = **cession / cessation TVA** (avec `<periode>1</periode>`) — Annexe 1 **V4.0** | **P2.2** + N2 (moteur EDI) | ajouter les régimes 3 et 4 au moteur EDI, créer le module d'événements de vie (`activity_events`) et le workflow d'apurement | **impossibilité** de déclarer une cessation / cession → déclaration incomplète, sanctions | **P2** |
| **2** | **`<prorata>` : unité et caractère optionnel** — documentée en annexe V4.0 (« Prorata de déduction — Double ») et portée par l'exemple officiel en **pourcentage entier** (`<prorata>70</prorata>`, `80`), **absente du 3ᵉ `<rd>`**, **non déclarée au XSD** | N2 (EDI TVA) | écrire la balise **en pourcentage** quand elle est demandée (option `inclure_prorata` déjà existante) ; conserver l'**omission par défaut** (cas du fichier T2 **déposé et accepté**) ; documenter l'unité | balise émise avec la **mauvaise unité** (`0.90` au lieu de `90`) → rejet ou déclaration erronée | **P1** |
| **3** | **`<if>` / `<identifiantFiscal>` de type « String »**, **exemples officiels à 7 chiffres** (`1003928`, `3300624`) ; **ICE** de l'exemple à **12 chiffres** (vs 15) | N2 + `identifiers` + P1.4 | rendre la normalisation **non destructive** : ne jamais transformer un IF légitime de **7 chiffres** en 8 ; le complément à 8 ne s'applique qu'aux saisies tronquées ; le contrôle ICE/IF devient **avertissement** hors contexte de dépôt | **IF erroné** transmis à la DGI = déclaration rattachée à un **mauvais contribuable** | **P1** |
| **4** | **`<ord>` : annexe V4.0 = « Entier »** alors que le **XSD du modèle DGI** le déclare `xs:byte` (**≤ 127**) | N2 (EDI TVA) | **confirmer auprès de la DGI** ; en attendant conserver le garde-fou **127** (prudent) mais le rendre **paramétrable** (`MAX_RD_LINES`) et documenter le dépôt par sous-périodes | limitation inutile du dépôt **ou** fichier rejeté | **P2** |
| **5** | **Modes de paiement V4.0** : `1` espèce · `2` chèque · `3` prélèvement · `4` virement · `5` effet · **`6` compensation** · `7` autres | N2 + `PAYMENT_METHOD_CODES` | vérifier que la table applicative couvre **6 = compensation** et aligner libellés/identifiants sur la V4.0 | mode de règlement faux dans le relevé (contrôle DGI) | **P1** |
| **6** | **XSD de la DTS absent** du référentiel (seul le guide d'utilisation est fourni) | **P1.4** (paie) | obtenir le **schéma/annexe DTS** auprès de la DGI ; à défaut, livrer d'abord un **mode EFI assisté** (état de saisie) et différer l'EDI XML | EDI DTS **non validable** → risque de rejet au dépôt | **P1** |
| **7** | **CDC technique de la facturation électronique absent** (loi 43-20 / art. 145 CGI) | **P2.3** | obtenir le CDC DGI (format, signature, transmission) ; en attendant se limiter à la **facture PDF** + archivage | module non spécifiable → développement à l'aveugle | **P2** |
| **8** | **Plan comptable de production incomplet** : **770 comptes** (sans `61473`, `61455`, `6147`) → contrainte FK `invoice_lines.account_number` → **42 rejets** ; et le document « enregistrement et timbre » fourni est en réalité un guide d'**immatriculation de véhicules** | transversal (tous modules) + documentation | **corrigé** : outil `tools/charger_plan_comptable.py` + garde-fou `preparer_comptes()` ; **règle** : toute base charge le plan de référence (**890 comptes**) avant import ; **remplacer** le document « enregistrement et timbre » par la référence des droits d'enregistrement/timbre du CGI | écritures impossibles (FK), plan non conforme au PCGE | **P1** |
| **9** | **Aucune écriture d'à-nouveaux à la clôture d'exercice** (détecté au jalon J2) : les états d'un exercice postérieur au premier (bilan, CPC, balance) ne reprennent pas les **soldes d'ouverture** | transversal (clôture / états) + P1.2 | **corrigé au jalon J3 (§ 9.10)** : la clôture d'exercice génère l'**écriture d'à-nouveaux** de l'exercice suivant (report des classes 1 à 5 dans le même sens + contrepartie du résultat au 1191/1199, journal `AN`, source `opening`) ; le calcul des soldes applique la **règle anti double comptage** (`closing.soldes_a_la_date`) ; rétro-compatible : un dossier sans à-nouveaux reste calculé en cumul depuis l'origine | **bilan et CPC faux dès la 2ᵉ année** (reports omis) — **risque majeur levé** | **P1 ✅** |

### 8.2 Ambiguïtés référentielles à lever (arbitrage expert-comptable / DGI)

| # | Ambiguïté | Conséquence | Recommandation |
|---|---|---|---|
| **A1** | **Numéro du texte de promulgation du CGNC** non lisible dans le PDF fourni (couverture image) | référence juridique incomplète dans le dossier | relever le dahir/BO officiel et compléter le § 7.1 |
| **A2** | **CGI art. 99-A / 99-B** cités par le projet pour les taux de TVA : l'article de référence des taux doit être re-vérifié | citation erronée possible dans les documents remis au client | vérifier sur l'édition 2026 et corriger la table § 7.1 |
| **A3** | **Code de commerce (loi 15-95)** : numéros d'articles sur la **tenue des livres** et la **conservation (10 ans)** | base juridique de la piste d'audit et de l'archivage | confirmer les articles exacts |
| **A4** | **Amortissement dégressif** : coefficient multiplicateur et biens éligibles (**CGI art. 10**) | calcul fiscal faux si le coefficient est erroné | lire l'article sur l'édition 2026 et **paramétrer** (jamais coder en dur) |
| **A5** | **Régularisation TVA (art. 106)** : durée (**5 ans** / **10 ans** pour les immeubles) et base de calcul | régularisation erronée en cas de cessation ou de changement de prorata | confirmer le texte **avant** développement de P1.2 |
| **A6** | **DTS** : **périodicité et échéance** exactes (mensuelle ? le 20 du mois suivant ?) | dépôt hors délai | confirmer sur le CGI / le guide DGI |
| **A7** | **Greffe** : **liste officielle des « types de pièce »** du portail (liste déroulante) et **délai légal de dépôt** (usage : dans le mois suivant l'AG) | dossier incomplet → état **« Rejeté »** | **relever la liste exacte lors de la première adhésion** et la figer dans la checklist paramétrable (**P1.5 — ✅ livré (J5) : checklist paramétrable + test d'épinglage ; confirmation de la liste toujours attendue**) |
| **A8** | **CbCR** : seuil et champ d'application de l'obligation déclarative au Maroc | périmètre du module P3.1 | confirmer sur le CGI (loi de finances d'introduction) |
| **A9** | **Cessation / cession TVA (régimes 3 et 4)** : délais et obligations d'apurement | déclaration tardive, régularisations oubliées | confirmer sur le CGI avant P2.2 |
| **A10** | **ICE** : norme marocaine **15 chiffres** vs **exemple DGI à 12 chiffres** | contrôle trop strict possible en phase transitoire | conserver **15** (norme) mais **avertir** au lieu de bloquer hors contexte de dépôt |
| **A11** | **Greffe — montant de l'amende pour dépôt hors délai** (état « Amender ») : aucun barème dans le guide de novembre 2025 | provision de l'amende impossible à calculer automatiquement (risque de provision erronée) | **ne rien coder en dur** : l'application alerte, **exige la saisie** du montant notifié et comptabilise **6195 / 1515** (✅ en place en J5) ; fixer le barème dès que le texte applicable est identifié |
| **A12** | **Greffe — date limite de dépôt** : la loi 5-96 (art. 10) fixe l'**AG dans les 6 mois**, l'usage admet **un mois après l'AG** pour le dépôt | alerte de retard approximative | l'application retient **clôture + 6 mois** (`date_limite_depot`) et **alerte le dépassement** ; affiner dès que le délai de dépôt est confirmé |
| **A13** | **Liasse fiscale — référentiel `codeEdi`** : `réferentiel des codifications.xlsx` livré avec le projet est le référentiel **CbCR** (pays par pays) et **non** la table rubrique ↔ `codeEdi` de la liasse IS | liasse inexploitable : cellules erronées ou vides | dériver la table des **énumérations des XSD officiels DGI** (`liasse_modele_*.xsd`, option `LIASSE_XSD_DIR`) et la **versionner** — arbitrage retenu pour J7 |
| **A14** | **DTS V5.1 — aucun XSD fourni** (`traitementSalaire.xsd` absent du cahier des charges EDI V5.1) | validation impossible : la structure suit l'**exemple officiel** seulement | **demander le XSD à la DGI** ; en attendant `valider_xsd()` renvoie `valide=None` (jamais « conforme ») et le **mode EFI assisté** reste le repli |
| **A15** | **DTS V5.1 — racine sans namespace** (`xsi:noNamespaceSchemaLocation`) alors que l'EDI-TVA est en `.../ETVA/...` | fichier rejeté par le téléservice | conserver la structure **sans namespace** (conforme à l'exemple V5.1) et **valider par un dépôt test** |
| **A16** | **DTS — catégorie** PP / PO / STG déduite du **type de contrat** (hypothèse retenue en J6) | salarié classé dans la mauvaise liste → DTS rejetée | ajouter une **colonne explicite « catégorie DTS »** sur le salarié (à planifier) |
| **A17** | **DTS — exonération art. 57-20°** : aucune liste correspondante dans le modèle V5.1 | exonération non déclarée au bon endroit | confirmer l'emplacement (liste ou attribut) sur l'**Annexe 1** du référentiel |
| **A18** | **DTS — `nom` / `prenom`** déduits du champ unique `nom` (1ᵉʳ mot = nom) | prénom mal séparé (nom composé) | ajouter une **colonne `prenom` dédiée** |
| **A19** | **DTS — balises de montant par salarié** dérivées du vocabulaire des totaux | balises potentiellement non conformes | vérifier sur l'**Annexe 1** (correspondance balise ↔ déclaration) |
| **A20** | **IS — charges non déductibles** : la détection par comptes (`6583` amendes et pénalités, provisions `6195`/`6196`/`6197`, `1515`/`1555`) ne couvre qu'une **partie** des réintégrations du CGI art. 11 | réintégration incomplète → **IS minoré** | le catalogue est **paramétrable** et la détection n'est qu'une **proposition** (origine tracée) ; l'avertissement `fiscal.reintegrations_a_examiner` reste affiché ; **liste à valider par l'expert-comptable** |
| **A21** | **IS — durée et conditions du report déficitaire** (CGI art. 114) | report calculé sur une durée erronée | l'application **n'applique aucune durée en dur** (`DUREE_REPORT_DEFICITAIRE = None`), **plafonne le report au bénéfice** de l'exercice et affiche l'avertissement `fiscal.deficit_reportable` ; arbitrage expert-comptable |
| **A22** | **Liasse — annexe « Codification des cellules » non fournie** : les XSD ne portent que des **énumérations** (aucun libellé), le CC EDI v2.0.3 y renvoie explicitement, et le `réferentiel des codifications.xlsx` est **CbCR** (A13 confirmée) ; la **sémantique des `extraField`** (code et valeur attendus) est également inconnue | la correspondance `codeEdi` ↔ rubrique comptable ne peut pas être dérivée automatiquement : liasse incomplète ou erronée si des codes étaient devinés | référentiel **`codification_liasse.csv` éditable** (validé par l'expert-comptable, trame générée par `tools/liasse_codification.py --gabarit` à partir du schéma) ; **`extraFieldvaleurs` émis vide** (aucune valeur inventée) ; **EFI assisté** par tableau en attendant ; aucun code inventé (`liasse.code_hors_schema`, `liasse.rubrique_inconnue` bloquants) — **demander l'annexe à la DGI** |
| **A23** | **Citations d'articles du CGI erronées dans le CDC** : les mentions obligatoires de la **facture** ne relèvent **pas** de l'**art. 145** (qui traite de la **tenue de la comptabilité**, y compris « sous format électronique » — vérifié sur l'édition 2026 fournie) et la **régularisation** de la TVA des biens amortissables relève des **art. 102 et 104-II-1°** (renvoi de l'**art. 114** aux art. 101 à 105), **non** de l'**art. 106** (qui liste les **exclusions** du droit à déduction) | base légale inexacte dans les documents remis au client et dans les messages de l'application (`Régularisation TVA (art. 106 CGI)`, `prorata CGI art. 106`) | J8 a corrigé les **nouvelles** références (art. 114, 150, 150 bis, 102, 104-II, 146 ; commentaires « art. 145 » retirés) ; **corriger les libellés existants** (module P1.2, écrans, tests `test_web.py`, `test_assets.py`) au prochain correctif dédié : c'est une chaîne affichée aux utilisateurs |
| **A24** | **E-facturation — cahier des charges DGI absent** : aucun document « loi 43-20 » ni schéma XML dans le référentiel technique reçu ; l'édition 2026 du CGI **ne mentionne ni** « facturation électronique » **ni** « 43-20 » | format de fichier et canal d'échange **inconnus** : impossible de produire un fichier « conforme » | J8 livre le **cycle de vie** (document, statuts, accusés, empreinte), les **mentions contrôlables** et un **format interne** explicitement marqué `non validée` ; le **canal DGI est paramétrable** (`E_INVOICE_ENDPOINT`, simulation par défaut) ; **demander le CDC e-facturation à la DGI** puis brancher le XSD dans `valider_conformite(schema=…)` |

**Traitement de ces ambiguïtés dans le projet** : chacune doit être **tranchée par écrit**
(expert-comptable pour le fiscal/comptable, DGI pour le format des fichiers) et le présent
document mis à jour ; tant qu'une ambiguïté n'est pas levée, le module concerné applique le
**défaut prudent** décrit et affiche l'avertissement correspondant à l'utilisateur.

### 8 bis. Écarts de la recette J9 traités en **P0** (régularisation — corrigés et testés)

| # | Anomalie constatée (recette J9) | Cause racine | Traitement (correctif) | Prévention (test de non-régression) |
|---|---|---|---|---|
| **A25** | **Collisions de routes API / interface** : `/audit`, `/audit/export` et `/stocks` renvoyaient **401 `Authentification requise`** même avec une session Web valide ; **aucun écran « provisions »** (404) ni lien « Journal comptable » au menu | l'API REST était montée **à la racine, avant** l'interface : la route `Bearer` interceptait l'écran (défaut rendu invisible par la recette, qui ne contrôlait pas les codes HTTP) | API montée **exclusivement sous `/api`** (`app/main.py`), interface déclarée `include_in_schema=False` ; défaut latent révélé par le déblocage : `/stocks` renvoyait **500** (`VALUATION_METHOD_LABELS` absent du service) — corrigé | `tests/test_routing_isolation.py` (5 tests : aucun chemin partagé, surface OpenAPI sous `/api`, 200 avec session, 303 sans session, API protégée par jeton) et `tests/test_ecrans_smoke.py` (balayage de **tous** les écrans GET : aucune 5xx) |
| **A26** | **Relevé EDI TVA incohérent** : `<mht>` au montant de la facture alors que `<tva>` était limitée à la fraction réglée (ex. FA26-08 : 9 000 / 1 080 / 10 080 pour un taux de 20 %) | `collect_rd_lines` ne proratisait que la TVA (`edi_tva.py`), le TTC étant reconstruit par `mht + tva` | base HT **et** TVA calculées sur **la même fraction éligible** (cumuls plafonnés au TTC : exactes sur la vie de la facture) ; **contrôles bloquants** `TTC = base + TVA` et `TVA = base × taux × prorata` remontés à l'écran **et refusés par `build_rd_xml`** | `test_edi_tva.py` : facture partiellement réglée (base 49,17 / TVA 9,84 / TTC 59,01), XML produit cohérent, **génération refusée** sur la signature du défaut (mht complet + TVA fractionnée) ; scan des 48 périodes : 45 → **0** incohérence |
| **A27** | **ETIC faux** : note 9 « charges de personnel » **vide** et dotations absentes de la note 4, alors que le CPC portait 6171/61711/6174 et 6193 | `etats_synthese.detail()`/`total()` filtraient sur `account_number[:2]` : une racine de **3 caractères** (« 617 », « 619 ») ne pouvait jamais correspondre | comparaison par **préfixe** (`startswith`) | `tests/test_etic_notes.py` (notes 9, 4 et non-régression des racines à 2 caractères) |
| **A28** | **Document de facture incohérent** : ligne et ventilation de TVA à **0** possibles alors que les totaux étaient corrects ; document **transmis** tel quel (PDF/impression) | aucune vérification lignes ↔ totaux avant émission ; les lignes à montant nul étaient acceptées à la validation | `invoicing.controles_coherence_facture()` : **refus** des lignes à 0 à la validation et **refus d'émission** du document (`DocumentIncoherentError`) ; alerte « Document incohérent » sur le détail et l'aperçu | `tests/test_facture_document.py` (6 tests : cas nominal, ligne à 0 refusée, PDF refusé, facture sans ligne refusée, écrans avertis, téléchargement refusé) |

**Double alimentation de la paie (A2 de l'audit J9)** et **IS minoré (A8)** sont traités en
**P1** (le module Paie doit devenir la source unique des écritures, puis recalcul
Balance → CPC → ESG → Bilan → ETIC → résultat fiscal → IS). **A6** (immobilisations codées
au 2340 par le jeu de données), **A9/A10** (exercices), **provisions**, **`payments.entry_id`**
et **référentiel de comptes** sont traités en **P2**.

### 8 ter. **P1 — double paie : corrigé et testé** (23/09/2026)

| # | Anomalie | Cause racine | Traitement | Prévention |
|---|---|---|---|---|
| **A29** | **Double alimentation de la paie 2026 (A2)** : 12 écritures synthétiques du jeu (`6171`+`6174`, 14 400 DH/mois) **plus** l'écriture du module → charges de personnel **172 800** au lieu de la paie réelle, résultat et IS faussés | aucune vérification, à la comptabilisation de la paie, de l'existence d'une charge de personnel d'une **autre origine** sur la période | **réinitialisation contrôlée du jeu de recette** (méthode autorisée par l'utilisateur) : 13 écritures retirées **avec trace d'audit complète** (`PAYROLL_RESET_SUPPRESSION`), piste **rescellée** (0 rupture), cycle et DTS de recette supprimés ; **12 paies 2026 régénérées par le module** (36 bulletins, 24 écritures) ; chaîne recalculée intégralement | nouveau contrôle **bloquant** `payroll.ecritures_paie_hors_module()` + `tests/test_paie_source_unique.py` (2 tests : refus de valider une paie si une charge hors module existe ; acceptation après régularisation, comptes `61711/4432/444x/4452` vérifiés) |

**Résultat mesuré** (`P1_AVANT_APRES.md`, même chaîne calculée sur la sauvegarde *avant* et la base
*après*) : charges de personnel 203 295,60 → **365 947,20** ; résultat comptable 49 344,40 → **-113 307,20** ; IS 13 860,88 → **0,00** (perte + exonération de cotisation minimale de 36 mois) ;
**Journal équilibré**, **Bilan équilibré**, **CPC = ESG = Bilan** ; `4432` soldé ; `4441`/`4452`
(CNSS/IR à verser) 96 670,32 DH déclarés par la DTS régénérée. **A8** (IS sur résultat faussé) est
donc levée par construction : l'IS est recalculé sur le résultat réel, sans correction manuelle.

### 8 quater. **P1 — suite** : réouverture, trésorerie, garde-fou paie, exonération CM, taux IS (23/09/2026)

| # | Anomalie / exigence | Cause racine | Traitement | Prévention (tests) |
|---|---|---|---|---|
| **A30** | **Réouverture d'exercice non encadrée (A10)** : la route web écrivait le statut **directement** (aucun motif, aucune trace) et le service refusait *toute* réouverture dès que des à-nouveaux existaient, sans chemin de régénération | contrôle de statut absent côté service pour la route ; absence d'un mécanisme de régénération des à-nouveaux | `closing.reouvrir_exercice(motif=…, regenerer_a_nouveaux=…)`, `verrouiller_exercice(motif=…)`, `regenerer_a_nouveaux()` (comparaison par compte), `apercu_reouverture()` ; la route web passe **par les services** et le formulaire impose le motif | `tests/test_reouverture_exercice.py` (7 : motif, verrous, N+1 verrouillé, cycle complet réouverture → correction → reclôture → régénération, refus d'écran) ; `test_audit_trail.py` mis à jour |
| **A31** | **Soldes créditeurs de trésorerie** non contrôlés : un compte bancaire débiteur pouvait rester créditeur (concours bancaire à l'actif) | aucun contrôle ni compte de contrepartie paramétré | `services/tresorerie.py` : contrôle + reclassement OD tracé et idempotent vers `5541`/`5548` ; caisses créditrices = anomalies à corriger | `tests/test_tresorerie.py` (5) |
| **A32** | **Garde-fou Paie trop strict** : toute charge `617x` hors module bloquait la paie, y compris des **OD légitimes** | critère unique « charge 617x » | `controle_doublon_paie()` : bloquant seulement pour les **doublons réels** (numérotation `PAIE…` ou comptes de dette de paie), avertissement pour les OD légitimes | `tests/test_paie_source_unique.py` (4) |
| **A33** | **Exonération de cotisation minimale supposée** : `mois_activite = 12` par défaut, sans lien avec les dates réelles de la société | aucune donnée de constitution / début d'exploitation ; paramètre implicite | colonnes société (migration `p1c1a2b3d4e5`) + `date_debut_activite()`, `mois_activite_effectif()`, `exoneration_cotisation_minimale()` ; source restituée (saisie ou dates réelles) | `tests/test_is_exercice_et_exoneration.py` (7) |
| **A34** | **Taux d'IS non historisé** : `compute_is` appliquait toujours les taux 2026 (le CDC annonçait pourtant un « taux historisé de l'exercice ») | registre unique 2026 | `IS_RATES_BY_YEAR` + `is_rates(annee)` : taux de l'exercice, **refus explicite** d'un exercice non paramétré (aucun taux deviné) | `tests/test_is_exercice_et_exoneration.py` (refus 2025) |

**Simulation 2025 (lecture seule)** : `P1B_SIMULATION_2025.md` — la régularisation de la paie 2025
exige **trois paramétrages officiels** (barème de paie 2025, taux d'IS 2025, paramètres de
cotisation minimale 2025) ; impact projeté : charges 144 000 → 365 947,20 DH, résultat 73 600 →
−148 347,20 DH, à-nouveaux 2026 +221 947,20 DH. **Aucune écriture 2025 modifiée.**


**-113 307,20** ; IS 13 860,88 → **0,00** (perte + exonération de cotisation minimale de 36 mois) ;
**Journal équilibré**, **Bilan équilibré**, **CPC = ESG = Bilan** ; `4432` soldé ; `4441`/`4452`
(CNSS/IR à verser) 96 670,32 DH déclarés par la DTS régénérée. **A8** (IS sur résultat faussé) est
donc levée par construction : l'IS est recalculé sur le résultat réel, sans correction manuelle.

---

## Partie 9 — Priorisation, feuille de route et charge

### 9.1 Principe d'ordonnancement (trois règles)

1. **Débloquer avant de construire** : l'export **PDF** (P1.1) est un prérequis du **greffe**,
   de la facturation client et des états à faire signer → il vient **en premier** après les
   corrections.
2. **Sécuriser avant d'étendre** : la **piste d'audit / verrouillage** (P1.6) doit être en
   place **tôt**, car tous les modules suivants écrivent dans des périodes verrouillables.
3. **Le plus dépendant en dernier** : la **liasse fiscale** (P2.1) agrège immo + stocks +
   paie → elle ferme la marche du lot P2.

### 9.2 Graphe d'exécution

```
  J0  Sprint 0 — corrections d'écarts (TVA RD : prorata, IF, modes)      2 j   ◄── PRIORITÉ ABSOLUE
        │
  J1  P1.1 Export PDF (états de synthèse, factures, bordereaux)          5 j
        │
        ├──────────────► J2  P1.6 Audit & traçabilité (verrouillage, piste, rapprochement)  7 j
        │                     │
        │                     ├────► J3  P1.2 Immobilisations & amortissements             8 j ─┐
        │                     └────► J4  P1.3 Stocks & inventaire permanent                 8 j ─┤
        │                                                                                     │
        ├──────────────► J5  P1.5 Dépôt greffe (dossier + suivi + alertes)                 6 j ─┤
        │                                                                                     │
        └──────────────► J6  P1.4 Paie & DTS « 9421 » (EFI d'abord si XSD absent)         15 j ─┤
                                                                                              │
  J7  P2.2 Cessation / cession d'activité (régimes 3 et 4)              4 j  (avançable)      │
                                                                                              ▼
  J8  P2.1 IS & liasse fiscale EDI ────────────────────────────────────────────────── 15 j  (après J3+J4+J6)
  J9  P2.3 E-facturation (après obtention du CDC DGI) ─────────────────────────────── 10 j
```

### 9.3 Jalons, livrables et critères de sortie

| Jalon | Contenu | Livrable vérifiable | Critère de sortie (definition of done) | Charge |
|---|---|---|---|---|
| **J0** ✅ | Corrections des écarts **2, 3, 5** (§ 8) + `MAX_RD_LINES` paramétrable + plan comptable garanti | relevé TVA « durci » | fichier conforme à l'exemple officiel et identique au **T2 déposé et accepté** ; tests IF 7/8 chiffres et modes de paiement verts | **2 j** |
| **J1** ✅ | **P1.1 Export PDF** (§ 9.8) | PDF bilan (brut / amortissements / net), CPC, **ESG**, **ETIC**, factures (+ duplicata), bulletins, **bordereaux TVA et greffe** | ✅ montants **identiques à l'écran au centime** (vérifié par extraction du texte) ; ✅ **PDF ≤ 10 Mo** contrôlé ; ✅ pagination testée ; ✅ mention **« PROVISOIRE »** si exercice non clôturé ; **17 tests dédiés (suite 102/102)** | **5 j** |
| **J2** ✅ | **P1.2 Immobilisations** (§ 9.9) — *ordre révisé par décision client du 22/09/2026 : P1.2 avant P1.6* | fiches, plans d'amortissement (linéaire / dégressif), dotations, cessions, mises au rebut, régularisations TVA art. 106, TVA au 34551 | ✅ Σ amortissements cumulés + VNC = valeur d'origine **au centime** (vérifié à chaque exercice) ; ✅ une cession **solde** le compte 2xxx et son 283x ; ✅ prorata temporis CGI art. 10 ; ✅ **27 tests dédiés** (suite **131/131**) | **8 j** |
| **J3** ✅ | **P1.6 Audit & traçabilité** (décalé d'un rang) | verrouillage de période, piste d'audit, rapprochement bancaire, journal exportable | ✅ piste **SHA-256 chaînée** : une altération hors application est détectée ; ✅ verrouillage de période **refusé + tentatives tracées** ; ✅ état de rapprochement bancaire `solde comptable + écarts = solde bancaire` ; ✅ clôture avec **à-nouveaux** (écart 9 corrigé) ; **17 tests dédiés** (suite **155/155**) | **7 j** |
| **J4** ✅ | **P1.3 Stocks** (§ 9.11) | articles, mouvements, CMUP/FIFO, inventaire, provisions | ✅ **Σ quantités × coût = solde du compte de stock au centime** ; ✅ FIFO vérifié sur 3 lots ; ✅ stock négatif et écriture nulle interdits ; ✅ verrouillage de période appliqué ; **15 tests dédiés** (suite **171/171**) | **8 j** |
| **J5** ✅ | **P1.5 Dépôt greffe** (§ 9.12) | dossier ZIP + bordereau, suivi des 7 états, alertes, certificat | ✅ dossier complet produit en **une action** (ZIP + manifeste des empreintes) ; ✅ **PDF ≤ 10 Mo** contrôlé par pièce ; ✅ suivi des **7 états** historisé ; ✅ alerte **« 3 jours »** née de l'approbation et éteinte au paiement ; ✅ certificat archivé avec **SHA-256** ; **25 tests dédiés** (suite **198/198**) | **6 j** |
| **J6** ✅ | **P1.4 Paie & DTS** (§ 9.13) | bulletins, écritures, DTS (EFI/EDI) | ✅ **IR de référence au dirham** (560,67 DH pour 10 500 DH bruts) ; ✅ **CNSS plafonnée** (6 000 DH) ; ✅ **Σ bulletins = écriture = DTS** (réconciliation `617x`) ; ✅ écriture équilibrée ; ✅ verrouillage P1.6 ; **21 tests dédiés** (suite **221/221**) | **15 j** |
| **J7** | **P2.2 Cessation / cession** | déclarations TVA régimes 3 et 4 | fichier conforme **V4.0** ; aucune déclaration postérieure à la cessation définitive | **4 j** |
| **J8** | **P2.1 IS & liasse EDI** | résultat fiscal, IS / cotisation minimale, liasse XML | liasse **valide au XSD** ; concordance liasse ↔ balance = 0 ; fichier **déterministe** | **15 j** |
| **J9** | **P2.3 E-facturation** | document électronique + suivi | conforme au CDC DGI (à obtenir) ; archivage probant | **10 j** |

### 9.4 Charge globale et hypothèses

| Lot | Modules | Charge |
|---|---|---|
| **Sprint 0** | corrections d'écarts (§ 8) | **2 j** |
| **P1** | PDF (5) + Audit (7) + Immo (8) + Stocks (8) + Greffe (6) + Paie (15) | **49 j** |
| **P2** | Liasse (15) + Cessation/cession (4) + E-facturation (10) | **29 j** |
| **Total** | | **80 j** |
| **Marge de sécurité (+20 %)** — allers-retours de validation expert-comptable / DGI, reprises | | **≈ 96 j** |

**Hypothèses de chiffrage** : ① **1 développeur** à temps plein sur le socle existant (aucune
reprise d'architecture) ; ② **hors** délais d'obtention des référentiels manquants
(**XSD DTS**, **CDC e-facturation** — écarts 6 et 7) ; ③ **hors** validation métier par
l'expert-comptable (à conduire **en parallèle**, pas en série) ; ④ tests et documentation de
chaque module **compris** (règle des 4 artefacts, § 2.2).

### 9.5 Quick wins à faire d'abord (faible coût, fort impact)

| Action | Coût | Bénéfice |
|---|---|---|
| écrire `<prorata>` en **pourcentage** (§ 8, écart 2) | 0,5 j | alignement sur l'exemple officiel DGI |
| normalisation **non destructive** des IF (§ 8, écart 3) | 0,5 j | supprime un risque majeur de déclaration erronée |
| vérifier/compléter les **modes de paiement 1→7** (§ 8, écart 5) | 0,5 j | conformité du relevé |
| rendre `MAX_RD_LINES` **paramétrable** (§ 8, écart 4) | 0,5 j | souplesse de dépôt (dossiers volumineux) |
| **POC PDF** (WeasyPrint vs ReportLab) | 0,5 j | dérisque le module P1.1 **et** le greffe |

### 9.6 Risques et parades

| Risque | Impact | Parade |
|---|---|---|
| **Référentiel manquant** (XSD DTS, CDC e-facturation) | module partiel | livrer en **EFI assisté** et obtenir les documents (action DGI) |
| **Mapping de la liasse** (nombreux `codeEdi`) | déclaration erronée | référentiel de codification **versionné** + tests par tableau + double contrôle expert-comptable |
| **Dépendance PDF (GTK)** sous Windows | empaquetage difficile | POC J1 + service `pdf.py` **isolant** le moteur (bascule ReportLab sans effet de bord) |
| **Dérive des barèmes (LF)** | calculs faux | barèmes **historisés en base**, jamais en dur ; test de non-régression par barème |
| **Dépôt hors délai** (TVA le 20, IS 3 mois, AG 6 mois, greffe 1 mois) | amendes / rejets | **tableau de bord d'échéances** (J2) + alertes 15/7/3 jours |
| **Perte ou altération de données** | révision impossible | sauvegardes horodatées (**outils déjà en place**) + chaînage de hachage + journal append-only |

### 9.7 Résultats du jalon J0 (réalisé le 22/09/2026)

| Livrable J0 | État | Preuve / fichier |
|---|---|---|
| **Norme IF corrigée** : 7 ou 8 chiffres, utilisé **tel quel** (zfill supprimé) | ✅ | `app/services/identifiers.py` (`FISCAL_ID_LENGTHS = (7, 8)`, `normalize_fiscal_id`) + tests dédiés (exemples `1084612`, `1086826`, IF à 8 chiffres, refus 6 et 9 chiffres) |
| **Données de production corrigées** | ✅ | société → `1234567` ; FR0001 → `1084612` ; FR0002 → `1086826` (sauvegarde `compta_ma.db.bak-20260922-024626`) |
| **`<prorata>` écrit en pourcentage** (exemple officiel DGI) | ✅ | `edi_tva._prorata_edi()` → `70`, `90`, `100`, `33.33` + tests |
| **Modes de paiement 1→7 conformes à la V4.0** | ✅ *(déjà conforme : 6 = compensation)* | `PAYMENT_METHOD_CODES` + test de non-régression |
| **Limite de lignes paramétrable** | ✅ | `settings.max_rd_lines` (défaut prudent 127) + argument `max_lignes` (API `/vat/edi/rd` et `/vat/edi/check`) + `limite_lignes()` + tests |
| **POC moteur PDF — décision D1** | ✅ | **ReportLab retenu** (120 lignes → 0,50 s / 11,5 Ko ; 1 000 lignes → 2,2 s / 86 Ko) ; WeasyPrint écarté (GTK absent) ; service `app/services/pdf.py` + `tools/poc_pdf.py` |
| **Suite de tests** | ✅ **85/85** (plancher relevé de 77 à 85) | `pytest` |
| **Relevé T2 2026 régénéré et comparé au dépôt** | ✅ | **10 écarts, tous sur les IF** (1 déclarant + 9 lignes) ; montants, dates, `<tx>`, `<mp>` et structure **identiques** ; TVA déductible T2 2026 = **198,81** |

> ⚠️ **ACTION UTILISATEUR** — Le relevé **T2 2026 déjà déposé** porte les IF à **8 chiffres**
> (`01234567`, `01084612`, `01086826`) ; le fichier régénéré porte les IF **réels à 7 chiffres**
> (`1234567`, `1084612`, `1086826`). **Vérifier auprès de la DGI l'IF exact** de la société et
> des deux fournisseurs, puis **re-déposer le T2 corrigé** si le dépôt initial a été accepté
> avec les IF erronés. Tous les relevés suivants partiront des valeurs corrigées.

---

### 9.8 Résultats du jalon J1 — Export PDF (réalisé le 22/09/2026)

**Moteur** : ReportLab (décision **D1** confirmée). Deux couches :
`app/services/pdf.py` (moteur générique : `Document`, `Tableau`, `Colonne`,
`rendre_pdf`, contrôle **10 Mo**) et `app/services/pdf_documents.py` (documents
métier). Les calculs nouveaux (ESG, ETIC, bilan CGNC) sont isolés dans
`app/services/etats_synthese.py` : **aucun module existant n'a été modifié sur le
fond** (seuls des points d'entrée et des liens d'interface ont été ajoutés).

| Livrable J1 | État | Preuve / fichier |
|---|---|---|
| **Bilan PDF brut / amortissements et provisions / net** | ✅ | `etats_synthese.bilan_normal()` (regroupement par postes CGNC) + `pdf_documents.pdf_bilan()` : contrôle d'équilibre **et** réconciliation avec l'écran **imprimés dans le document** |
| **CPC PDF** | ✅ | `reporting.income_statement()` → `pdf_cpc()` (charges, produits, résultat, bénéfice / perte) |
| **ESG PDF** (nouveau calcul) | ✅ | `etat_soldes_gestion()` : marge brute (711−611), valeur ajoutée (+712/713/714/716/718 −612/613/614), EBE (−616/617), résultat d'exploitation (−618/619 +719), courant (+73−63), net (+75−65−67) ; **contrôle ESG ↔ CPC** |
| **ETIC PDF** (nouveau calcul) | ✅ | `notes_etic()` : 9 notes annexes calculées (immobilisations, amortissements, stocks, créances, trésorerie, dettes, personnel, capitaux) + **5 informations indisponibles listées** avec leur origine (P1.2/P1.3/P1.4) |
| **Pièces PDF** | ✅ | `pdf_facture()` (mentions CGI art. 145, ventilation par taux, **original / duplicata**, statuts brouillon / annulé) et `pdf_bulletin_paie()` (**interface documentée et testée, à brancher sur P1.4**) |
| **Bordereaux PDF** | ✅ | `pdf_bordereau_tva()` (récapitulatif **exact** du XML EDI : lignes retenues, ventilation par taux, lignes écartées, anomalies, contrôles DGI, nom du fichier) et `pdf_bordereau_greffe()` (identité du déposant, **checklist par forme juridique**, portail, 10 Mo, délais loi 5-96 art. 10/93 et loi 17-95 art. 14) |
| **Critère « montants identiques à l'écran au centime »** | ✅ | les documents consomment **les mêmes services** que l'écran et les tests **extraient le texte des PDF** (`pypdf`) pour comparer aux valeurs des services ; les formateurs PDF sont vérifiés **égaux** aux filtres de l'interface (`format_amount`) |
| **Contrainte « PDF ≤ 10 Mo »** | ✅ | contrôle automatique à chaque génération (`controle_taille_pdf`) + test dédié (7 documents mesurés) |
| **Mention « provisoire / brouillon »** | ✅ | `mention_provisoire()` → mention **dans le corps** du document **et** filigrane « PROVISOIRE » tant que l'exercice n'est pas clôturé (`etats_synthese.exercice_clos`) ; test sur exercice ouvert **et** clôturé |
| **Interface et API** | ✅ | boutons PDF (bilan, ESG, ETIC, CPC, greffe), facture + duplicata, bordereau TVA ; `GET /reports/{bilan\|cpc\|esg\|etic}/pdf`, `/reports/bordereau-greffe/pdf`, `/reports/esg`, `/reports/etic`, `/invoices/{id}/pdf`, `/vat/edi/bordereau` |
| **Suite de tests** | ✅ **102/102** (plancher relevé de 85 à 102) | `tests/test_etats_pdf.py` (15 tests) + `test_web.py` + `test_api.py` |

**Points de présentation retenus (à valider par l'expert-comptable)** : ① classement
des comptes identique à l'écran (le bilan simplifié porte les amortissements au
passif) ; le PDF applique la présentation CGNC **en déduisant** ces amortissements de
l'actif, l'écart étant **affiché et contrôlé** dans le document ; ② le libellé des
postes CGNC est regroupé par racine de compte, tout compte non rattaché apparaissant
en « Autres comptes » (aucun montant perdu, équilibre vérifié) ; ③ la présentation
officielle « modèle normal » poste par poste sera affinée avec les modules
immobilisations (P1.2) et stocks (P1.3).

**Reste à faire (traçé)** : ① brancher `pdf_bulletin_paie()` sur les bulletins réels
(**P1.4**) ; ② confirmer la **liste exacte des pièces** du portail greffe à la première
adhesion (**P1.5**) ; ③ compléter l'ETIC (engagements hors bilan, effectifs,
rémunérations des dirigeants) par des **saisies** à prévoir ; ④ produire le **dossier
de dépôt complet en une action** (assembleur ZIP) — périmètre **J5**.

### 9.9 Résultats du jalon J2 — P1.2 Immobilisations & amortissements (réalisé le 22/09/2026)

**Ordre révisé** (décision client) : P1.2 est traité **avant** P1.6 ; les jalons suivants sont
décalés d'un rang. Trois couches livrées : modèle (`assets`,
`asset_depreciation_lines`, `asset_events` + migration Alembic `c1d801a10835`),
service métier (`app/services/assets.py`) et documents PDF des états du module.

| Livrable J2 | État | Preuve / fichier |
|---|---|---|
| **Fiches d'immobilisation** | ✅ | `creer_immobilisation()` : compte 2xxx, fournisseur/facture d'origine, dates d'acquisition et de mise en service, valeur d'origine, durée, mode, coefficient, valeur résiduelle, TVA, numéro automatique (`IM202600001`) |
| **Comptes PCGE dérivés (règle structurelle)** | ✅ | `comptes_amortissement()` : `amortissement = "28" + immo[1:3]`, `dotation = "619" + immo[1:3]` (ex. 2332 → 2833 / 61933, 2220 → 2822 / 61922) — **test structurel sur tout le plan** ; non amortissables identifiés (24x/25x financières, 239x en cours) ; repli documenté si le compte dérivé est absent du plan (ex. 2130) avec **avertissement** |
| **Amortissement linéaire** | ✅ | annuité constante = base / durée, **prorata temporis** fiscal (mois entiers depuis la mise en service, CGI art. 10) ou annuité pleine (option comptable) |
| **Amortissement dégressif** | ✅ | taux = (1 / durée) × coefficient appliqué à la **VNC**, **bascule en linéaire** quand plus favorable ; coefficients **paramétrables** (`settings.coefficient_degressif_*` : 1,5 / 2,0 / 2,5) — ambiguïté **A4** traitée par paramétrage, jamais codée en dur |
| **Dernière annuité plafonnée** | ✅ | la VNC ne descend jamais sous la valeur résiduelle ; les arrondis sont absorbés (Σ cumul + VNC = valeur d'origine au centime) |
| **Dotations comptabilisées** | ✅ | `comptabiliser_dotation()` → écriture **6193x / 283x** validée et numérotée + ligne de plan + événement ; **idempotence** garantie (dotation déjà constatée refusée) ; traitement **en masse** par exercice avec isolation SAVEPOINT par fiche |
| **Cessions** | ✅ | `ceder_immobilisation()` : produit (**7513/7512**, TVA de cession au 4455 le cas échéant), reprise des amortissements (**28x**), **VNA** (**6513/6512**), créance (**3481**) ou encaissement (5141) — le compte 2xxx et son 283x sont **soldés à zéro** (testé sur le grand livre) |
| **Mises au rebut** | ✅ | `mettre_au_rebut()` : motif obligatoire, aucun produit, VNA en charge, traçabilité |
| **Régularisation TVA art. 106** | ✅ | `regularisation_tva_art106()` : fractions égales sur 5 ans (meubles) / 10 ans (immeubles), durée **paramétrable** (`settings.regularisation_tva_annees_*`) ; écriture débit compte de régularisation / **crédit 34551** — ambiguïté **A5** maintenue visible (avertissement dans l'écran et le PDF) |
| **TVA 34551 vs 34552** | ✅ | l'acquisition comptabilisée par la fiche utilise le **34551** (jamais le 34552) ; **contrôle bloquant** `TVA_34552_SUR_IMMOBILISATION` qui détecte une TVA d'immobilisation logée au 34552 (assiette art. 106 et présentation du bilan) |
| **États du module** | ✅ | `etat_immobilisations()` (**brut / amortissements / net par poste**, réconcilié avec le grand livre, écarts affichés), `amortissements_deductibles()` (fiscalement déductibles, colonne « constatée »), `tableau_cessions()` (VNC, prix, plus/moins-value, régularisation TVA) — écrans + **PDF** (`pdf_etat_immobilisations`, `pdf_plan_amortissement`, `pdf_tableau_cessions`) |
| **Contrôles de cohérence** | ✅ | `controles_immobilisations()` : bien amortissable sans durée ou sans mise en service, sortie sans motif, cession sans prix, dotation de l'exercice de cession manquante (VNC surévaluée), écart fiches ↔ grand livre, TVA mal ventilée — affichés dans l'écran, l'API et les documents |
| **Intégration ETIC (P1.1)** | ✅ | l'ETIC comporte désormais une **note 2 « Immobilisations : mouvements de l'exercice »** alimentée par les fiches (l'entrée « non disponible » correspondante a été retirée) |
| **Interface et API** | ✅ | écrans `/immobilisations`, `/immobilisations/nouvelle`, `/immobilisations/{code}`, `/immobilisations/etats` + actions (dotation, cession, rebut, traitement en masse) ; API `/assets`, `/assets/{code}`, `/assets/etat`, `/assets/cessions`, `/assets/amortissements`, `/assets/controles`, `/assets/comptes/{compte}` |
| **Suite de tests** | ✅ **131/131** (plancher relevé de 102 à 131) | `tests/test_assets.py` (**27 tests**) + `test_web.py` + `test_api.py` |

**Écarts et incohérences signalés**

1. **Écart 9 (nouveau, § 8.1)** — La **clôture d'exercice ne génère pas d'écritures
   d'à-nouveaux** : les états portant sur un exercice postérieur au premier (bilan,
   CPC, état des immobilisations) ne reprennent donc pas les soldes d'ouverture.
   Contournement appliqué dans P1.2 (cumul **depuis l'origine** pour l'état des
   immobilisations, qui doit reconcilier avec le grand livre) ; correction de fond à
   prévoir avec le module de clôture (P1.6).
2. **Ambiguïtés A4 (coefficient dégressif) et A5 (durée de régularisation TVA)**
   toujours ouvertes : le code applique des **défauts prudents paramétrables** et
   affiche l'avertissement (aucune valeur fiscale n'est figée en dur).
3. **Postes d'amortissement à confirmer** : pour les immobilisations en **non-valeurs**
   (21x), le plan ne comporte pas toutes les dotations dérivées (ex. `2130` →
   `61913` absent) ; le service utilise le compte générique de la famille et le
   **signale** (l'expert-comptable doit valider le compte retenu).

**Reste à faire (tracé)** : ① **dépréciations réversibles** (6194x / 293x) non
implémentées (hors périmètre demandé, prévues par le CGNC) ; ② **compléter l'ETIC**
(effectifs, engagements hors bilan, rémunérations des dirigeants : saisies à prévoir) ;
③ rattachement automatique des **lignes de facture classe 2** à une fiche
d'immobilisation (proposition de création depuis la facture) ; ④ **verrouillage
mensuel** des dotations (P1.6, J3).

### 9.10 Résultats du jalon J3 — P1.6 Audit & traçabilité (réalisé le 22/09/2026)

| Livrable J3 | État | Preuve / fichier |
|---|---|---|
| **Écart 9 corrigé — écritures d'à-nouveaux** | ✅ | `app/services/closing.py` : `cloturer_exercice()` contrôle l'**équilibre du bilan**, passe l'exercice en `closed` puis génère l'**écriture d'ouverture** de N+1 (report des soldes des classes 1 à 5 **dans le même sens** + contrepartie du résultat au **1191** bénéficiaire / **1199** déficitaire, journal `AN`, source `opening`, référence `AN<année>`) ; test : le bilan de 2027 devient non nul et **équilibré** (trésorerie + capital + résultat reportés) |
| **Règle anti double comptage des soldes** | ✅ | `closing.soldes_a_la_date()` : mouvements de l'exercice si des à-nouveaux existent, sinon cumul depuis l'origine (compatibilité des dossiers repris) ; l'état des immobilisations (P1.2) a été migré sur cette base |
| **Verrouillage de période** | ✅ | `app/services/period_locks.py` + table `period_locks` : verrou de **mois** (`1..12`) ou d'**exercice entier**, refus **dur** de toute saisie (`create_entry`), de la **modification** et de la **suppression** d'un brouillon, **déverrouillage réservé** (ADMIN / EXPERT_COMPTABLE) **avec motif obligatoire** |
| **Journalisation des tentatives** | ✅ | action `PERIOD_LOCK_REJECTED` écrite dans une **transaction indépendante** (base fichier) pour survivre au rollback de l'opération refusée ; test : tentative refusée → refus **et** trace présente |
| **Piste d'audit fiable (chaînage)** | ✅ | `app/services/audit_trail.py` : empreinte **SHA-256** du contenu canonique de chaque écriture validée + **chaînage** (`entries.entry_hash` / `previous_hash`) calculé à la validation ; `verifier_chainage()` détecte **contenu altéré**, **chaînage rompu**, **écriture non scellée** ; `sceller_ecritures()` reconstitue la piste d'un dossier repris (idempotent) |
| **Tests d'intrusion** | ✅ | modification directe d'une ligne et suppression d'une écriture en base → **rupture détectée** (`contenu_altere`, `chainage_rompu`) |
| **Journal d'audit exploitable** | ✅ | filtres (action, entité, utilisateur, dates, recherche dans le détail), comptage, listes de valeurs distinctes, navigation **écriture → pièce d'origine** et **pièce → écritures** (`piste_ecriture`, `ecritures_de_la_piece`) |
| **Export CSV + loi 09-08** | ✅ | `export_journal_csv()` : BOM UTF-8, séparateur `;`, colonnes horodatage/utilisateur/action/entité/IP/détail, **masquage automatique des données personnelles** (nom, CIN, CNSS, e-mail, RIB…) au titre de la **loi 09-08 (CNDP)** ; export en clair possible mais explicite |
| **Rapprochement bancaire** | ✅ | `app/services/banking.py` + tables `bank_statements` / `bank_statement_lines` / `bank_reconciliations` : import **CSV normalisé** (`date;libelle;reference;debit;credit`, virgule décimale et milliers), appariement **automatique** (montant exact + date proche) puis **manuel**, **ajustements** motivés, dé-rapprochement, **état de rapprochement** (`solde comptable + écarts = solde bancaire`) et **alerte** sur les écarts de plus de **3 mois** |
| **Interface et API** | ✅ | écrans `/audit` (journal, filtres, export, contrôle du chaînage, alertes) et `/rapprochement` (import, appariement, état) ; boutons **« Clôturer + à-nouveaux »** et **« Verrouiller »** sur la page des exercices ; API `/audit` (journal, export, chaînage, scellement, piste), `/audit/verrouillages`, `/audit/cloture/{année}`, `/audit/releves` |
| **Migration** | ✅ | révision Alembic `07e35b18ce2e` (tables `period_locks`, `bank_*` + colonnes de chaînage) appliquée à la base témoin **et** à la production (sauvegarde `compta_ma.db.bak-20260922-150303`, 42 factures / 84 écritures intactes) |
| **Suite de tests** | ✅ **155/155** (plancher relevé de 131 à 155) | `tests/test_audit_trail.py` (**17 tests**), `tests/test_banking.py` (**6 tests**), `test_api.py` (contrat des endpoints d'audit) |

**Points de présentation à valider par l'expert-comptable**

1. **Bilan simplifié et perte reportée** : la présentation actuelle classe les comptes **par
   le signe** ; une **perte reportée** (compte 1199 débiteur) apparaît donc à l'**actif** du
   bilan simplifié, alors que le modèle normal du CGNC la présente **en déduction des
   capitaux propres**. Le bilan reste équilibré (contrôle automatique), seul l'affichage
   doit être affiné (même point que § 9.8).
2. **Périmètre du verrouillage** : le refus est porté par `create_entry` (saisie, facture,
   règlement, dotation, à-nouveaux) et par la modification/suppression de brouillon.
   Les **outils d'import en ligne de commande** (`tools/import_achats_fournisseurs.py`) ne
   passent pas encore par le contrôle : à brancher sur `period_locks.controler_periode`
   avant la mise en production multi-dossiers.

**Reste à faire (tracé)** : ① étendre le verrouillage aux **outils d'import** et au module
de paie à venir ; ② **tableau de bord de conformité** (échéances TVA/DTS/IS/AG/greffe avec
feux vert-orange-rouge) — brique P1.6 non livrée faute de données d'échéances (P1.4/P1.5) ;
③ **anonymisation des données personnelles** dans les tables métier (loi 09-08) et registre
des traitements CNDP, hors périmètre du jalon ; ④ `tools/verifier_piste.py` (contrôle
d'intégrité hors application, en ligne de commande) pour l'audit externe.

### 9.11 Résultats du jalon J4 — P1.3 Stocks & inventaire permanent (réalisé le 22/09/2026)

| Livrable J4 | État | Preuve / fichier |
|---|---|---|
| **Fiches articles** | ✅ | `app/services/stocks.py` + tables `stock_items` (référence, désignation, unité, famille, **compte de stock 3xxx**, comptes d'achat/vente, **seuil d'alerte**, **mode de valorisation** CMUP/FIFO) ; contrôle du plan comptable et refus du LIFO (proscrit par le CGNC) |
| **Comptes dérivés (CGNC)** | ✅ | variation : `311x → 6114`, `312x → 6124`, `313x → 7131`, `315x → 7132` ; provision : `311x → 3911`, `312x → 3912`… ; dotation **61961** ; test structurel sur les comptes du plan |
| **Valorisation CMUP** | ✅ | **CMUP recalculé après chaque entrée** : `(valeur stock + valeur entrée) / (qté + qté)` — test 10 × 100 puis 10 × 200 → CMUP **150,0000**, sortie de 5 valorisée 750 DH |
| **Valorisation FIFO** | ✅ | rejeu complet des mouvements puis consommation de la **file restante** (`couches_fifo`) — test sur **3 lots** (100/200/300) : sortie de 15 = 10 × 100 + 5 × 200 = **2 000 DH**, puis sortie de 5 = **1 000 DH** (file reconstituée) |
| **Entrées / sorties valorisées** | ✅ | `enregistrer_mouvement()` : entrée = coût de revient obligatoire (> 0), sortie = CMUP ou FIFO ; **quantité négative interdite** (option explicite `allow_negative`), **sortie non valorisée refusée** (0 DH) |
| **Écritures associées** | ✅ | inventaire permanent (CGNC titre V) : entrée **3111 / 6114**, sortie **6114 / 3111** ; **régime intermittent** : `constater_stock_final()` aligne chaque compte de stock sur la valeur du module à la clôture |
| **Inventaire physique** | ✅ | `inventaire_physique()` : théorique/physique, **écart valorisé** au CMUP, mouvement d'inventaire et écriture ; **visa obligatoire** au-delà de **5 %** de la valeur du stock (contrôle bloquant n° 4) |
| **Dépréciations (prudence)** | ✅ | `provisionner_stock()` : provision = valeur comptable − **valeur d'inventaire** ; dotation **61961 / 391x**, **reprise** l'exercice suivant (variation seule comptabilisée, non-compensation) ; motif obligatoire |
| **États** | ✅ | `etat_stocks()` (**quantité, CMUP, valeur par article**, réconciliation au grand livre, articles **sous seuil**), `inventaire_valorise()` (feuille de comptage), `variation_stocks()` (initial / entrées / sorties / final / variation), `etat_provisions()` (dotations et reprises) |
| **Contrôles de cohérence** | ✅ | `controles_stocks()` : quantité négative, **cache de fiche divergent**, mouvement non comptabilisé, article sous seuil, **écart fiches ↔ comptabilité** |
| **Verrouillage (P1.6)** | ✅ | tout mouvement passé par `period_locks.controler_periode` : **aucun mouvement rétroactif** en période verrouillée, tentative **tracée** ; écritures soumises au même contrôle |
| **Interface et API** | ✅ | écran `/stocks` (création d'article, entrées/sorties valorisées, seuils, contrôles, constatation du stock final) ; API `/stocks`, `/stocks/{référence}`, `/stocks/{référence}/mouvements`, `/stocks/{référence}/provisions`, `/stocks/etat`, `/stocks/inventaire`, `/stocks/variation`, `/stocks/provisions`, `/stocks/controles`, `/stocks/journal`, `/stocks/mouvements/comptabiliser` |
| **Migration** | ✅ | révision Alembic `8cf2d7792aa2` (`stock_items`, `stock_movements`, `stock_counts`, `stock_count_lines`, `stock_provisions`) appliquée à la base témoin **et** à la production (sauvegarde `compta.db.bak-p13-*`, données intactes) |
| **Suite de tests** | ✅ **171/171** (plancher relevé de 155 à 171) | `tests/test_stocks.py` (**15 tests**) + `test_api.py` (contrat des endpoints `/stocks`) |

**Critères d'acceptation du CDC § 3.3 — vérifiés**

1. **Σ (quantités × coût unitaire) = valeur du compte de stock au centime** : testé après
   entrées, sorties, inventaire et constatation du stock final (`etat_stocks()["conforme"]`).
2. **CMUP recalculé après chaque entrée** : testé (100 → 150 → sortie valorisée 150).
3. **FIFO** : consommation strictement dans l'ordre de la file, vérifiée sur 3 lots.
4. **L'écriture de variation ramène la balance à l'état de l'inventaire physique** : testé
   (3 000 DH → écart de 2 unités → 2 700 DH en comptabilité **et** dans le module).
5. **Provision, seuil d'alerte, verrouillage** : testés et présents dans les contrôles.

**Points de vigilance signalés**

1. **Régime de tenue par société** : le paramètre `settings` (par dossier) n'est pas encore
   exposé dans l'écran Société ; en pratique, choisir le mode **permanent** (comptabilisation
   de chaque mouvement) ou **intermittent** (constatation à la clôture) s'opère par l'appel
   ou non de `comptabiliser_mouvement` / `constater_stock_final`. **À expliciter dans
   l'interface** (paramètre de dossier) avant exploitation multi-dossiers.
2. **Champ `stock_courant` / `cmup_courant` du CDC** : implémentés comme **cache de fiche**
   (`quantity_on_hand`, `cmup`, `value_on_hand`) recalculé par le service, avec contrôle
   `CACHE_DIVERGENT` — la règle « aucune table ne duplique un solde » est donc respectée
   tout en conservant la consultation rapide prévue au § 2.3.
3. **Valorisation des écarts d'inventaire sur article jamais valorisé** : écart non valorisé
   (0 DH) → **aucune écriture** n'est passée et un **avertissement** est journalisé
   (pas de mouvement à 0 DH silencieux).
4. **Frais accessoires d'achat** : la fiche article ne porte pas encore de champ dédié ; le
   coût de revient doit être saisi **frais inclus** (documenté dans l'écran). Un
   éclatement « prix HT + frais » pourra être ajouté avec la liaison facture ↔ mouvement.

### 9.12 Résultats du jalon J5 — P1.5 Dépôt au greffe (réalisé le 22/09/2026)

| Livrable J5 | État | Preuve / fichier |
|---|---|---|
| **Dossier de dépôt par exercice** | ✅ | `app/services/greffe.py` + tables `greffe_deposits` (forme juridique, statut, date d'AG, **date limite de dépôt**, dates de soumission / approbation / limite de paiement / dépôt, taxes, amende, certificat) — **unicité par exercice** (base + service) |
| **Checklist par forme juridique** | ✅ | Catalogue `CATALOGUE_PIECES` (loi 5-96 art. 10/93, loi 17-95 art. 14, guide nov. 2025) : état de complétude `n/total`, pièce par pièce ; le **rapport du/des CAC** n'est obligatoire que pour la **SCA** (SA/SARL : « si CAC nommé »), le **tableau de financement** reste facultatif (selon seuils) |
| **Suivi des 7 états du portail** | ✅ | Nouveau, En cours, Annulé, Rejeté, **Amender**, Approuvé, Déposé : **matrice de transitions** (`GREFFE_TRANSITIONS`) + **motif obligatoire** (rejet, annulation, amender, réouverture, dépôt final) + journal `greffe_events` |
| **Alerte « paiement sous 3 jours »** | ✅ | `date_limite_paiement = approbation + 3 jours` ; alerte **urgente** dès l'approbation (rouge à 1 jour), **rejet automatique** signalé au-delà ; l'alerte **disparaît au paiement** (testé) ; le dépôt final est **refusé** tant que les taxes ne sont pas intégralement réglées |
| **Alerte amende hors délai** | ✅ | `greffe.ag_hors_delai` (AG > 6 mois, ou aucune AG passé la limite) : **avertissement** à la création, **bloquant à la soumission** (levée explicite `forcer_hors_delai`) ; état « Amender » → alerte rouge ; **provision de l'amende** : dotation **6195** / provision **1515** (CGNC), écriture unique par dossier (`source = greffe`) |
| **Contrainte PDF ≤ 10 Mo** | ✅ | Refus de tout fichier non PDF (`%PDF`) et de toute pièce > 10 Mo (`pdf.controle_taille_pdf`, message rappelant la limite du portail) ; taille et **empreinte SHA-256** archivées par pièce ; réévalué dans les contrôles et dans l'assembleur |
| **Archivage du certificat** | ✅ | `enregistrer_certificat()` : PDF ≤ 10 Mo, **SHA-256** en base, fichier hors base (`settings.greffe_racine`), référence, date d'archivage ; l'alerte « certificat manquant » apparaît après dépôt et **disparaît à l'archivage** |
| **Assembleur ZIP du dossier** | ✅ | `assembler_dossier()` : `00_bordereau_recapitulatif.pdf` + pièces `NN_piece_libelle.pdf` + `manifeste.json` (empreintes, tailles, délais, taxes) ; **refus si un contrôle bloquant subsiste** ; **intégrité vérifiée** (une pièce altérée sur le disque fait échouer l'assemblage) |
| **Pièces produites par Compta MA** | ✅ | `generer_pieces()` : états de synthèse **fusionnés** (bilan + CPC + ESG + ETIC, P1.1) en un PDF ≤ 10 Mo, **bordereau récapitulatif**, et **attestation de paiement des taxes** dès qu'un paiement existe |
| **Contrôles préalables (6 bloquants)** | ✅ | `controles_depot()` : exercice **non clos**, **bilan déséquilibré**, **checklist incomplète**, pièce > 10 Mo, **RC / IF / ICE** non conformes (`identifiers`), **re-soumission d'un dossier Déposé**, plus paiement échu |
| **Verrouillage après dépôt** | ✅ | Le passage à « Déposé » **verrouille l'exercice** (P1.6) avec motif ; un verrou déjà posé n'est pas une erreur (idempotent) |
| **Interface et API** | ✅ | Écran `/greffe` (dossier par exercice, checklist, contrôles, alertes, téléversement, suivi des états, paiement, certificat, amende, téléchargements ZIP / bordereau / attestation / certificat) et API `/greffe` (**21 routes** : dépôts, pièces, états, paiements, certificat, dossier ZIP, bordereau, attestation, amende, état, alertes, catalogue) |
| **Migration** | ✅ | révision Alembic `9ee74a029f0a` (`greffe_deposits`, `greffe_documents`, `greffe_payments`, `greffe_events`) **additive**, appliquée à la base témoin **et** à la production (sauvegarde `compta_ma.db.bak-p15-*`, données intactes : 42 factures, 84 écritures) |
| **Suite de tests** | ✅ **198/198** (plancher relevé de 171 à 198) | `tests/test_greffe.py` (**25 tests**) + `test_api.py` (contrat des routes `/greffe`) + `test_web.py` (écran `/greffe`) |

**Critères d'acceptation du CDC § 3.5 — vérifiés**

1. **Dossier complet produit en une action** (ZIP + bordereau) : testé, chaque pièce passant le
   contrôle de taille.
2. **Cycle de vie des 7 états historisé** avec motif de rejet : testé (`nouveau → en_cours →
   rejete → en_cours → approuve → depose`).
3. **Alerte « 3 jours »** déclenchée à l'approbation et **éteinte au paiement** : testée
   (y compris le passage en « rejet automatique » au-delà).
4. **Certificat archivé avec SHA-256** et accessible depuis l'exercice : testé.
5. **Tests** : checklist par forme juridique, contrôle des **10 Mo**, calcul de la **date
   limite d'AG** (clôture + 6 mois), **transitions d'état**, **alerte 3 jours**.

**Points de vigilance signalés**

1. **Liste officielle des pièces à confirmer au portail** : le guide de novembre 2025 décrit le
   processus et la contrainte PDF ≤ 10 Mo, mais la **nomenclature exacte des « types de pièce »**
   du portail ne peut être validée qu'à la première adhésion. Le catalogue est donc
   **paramétrable** et un **test d'épinglage**
   (`test_catalogue_pieces_coherent_avec_le_bordereau`) empêche toute dérive entre le
   **bordereau PDF** (J1) et le **catalogue du module** (P1.5).
2. **Montant de l'amende non fixé par le guide** : l'application **ne code en dur aucun
   barème** ; elle alerte, exige la saisie du montant notifié, puis comptabilise la
   **dotation 6195 / provision 1515** (amende **non déductible** : à rattacher dans la liasse
   fiscale — P2.1).
3. **Forme juridique du dossier** : le dossier enregistre la forme juridique utilisée pour la
   checklist (`SARL`, `SA`…) ; si la fiche **Société** n'en porte aucune, elle est **choisie à
   la création du dossier**. La base de production actuelle n'a **ni forme juridique ni RC** :
   à compléter dans l'écran Société (contrôle bloquant n° 5).
4. **Archive des pièces hors base** : les PDF (≤ 10 Mo chacun) sont stockés sous
   `settings.greffe_racine` (`media/greffe` par défaut) avec leur **empreinte** en base : la
   procédure de sauvegarde d'exploitation doit donc **inclure ce répertoire** (en plus de
   `compta_ma.db`).
5. **Verrouillage automatique de l'exercice au dépôt** : comportement prévu par le CDC (P1.6),
   mais **irréversible sans déverrouillage motivé** (ADMIN / EXPERT_COMPTABLE) : à annoncer à
   l'utilisateur avant le dépôt final.

### 9.13 Résultats du jalon J6 — P1.4 Paie & DTS « 9421 » (réalisé le 22/09/2026)

| Livrable J6 | État | Preuve / fichier |
|---|---|---|
| **Fiches salariés** | ✅ | `app/services/payroll.py` + tables `employees` (matricule, CIN, **n° CNSS**, situation de famille, enfants, dates d'entrée/sortie, contrat, RIB, **exonération art. 57-20°**) et `pay_contracts` (salaire de base, primes, avantages, taux retraite/mutuelle/assurance groupe, **date d'effet**) |
| **Calcul des bulletins** | ✅ | `calculer_bulletin()` : brut imposable, CNSS/AMO salariales, frais professionnels, **net imposable**, **IR**, retenues (avances, oppositions), **net à payer**, charges patronales et **coût employeur** ; rubriques détaillées (base, taux, gain, retenue) |
| **Barèmes IR 2026 / CNSS / AMO** | ✅ | `app/core/rates_ma.py` (additif) : **IR mensuel par annualisation** (méthode DGI), frais professionnels 35 %/25 % plafonnés, **déduction charges de famille** (600 DH/personne, max 6), CNSS 4,48 % plafonnée à 6 000 DH + AMO 2,26 % — barèmes **historisés** (`BAREMES_PAIE`) : un exercice non paramétré est **refusé** (jamais de taux deviné) |
| **Écritures comptables** | ✅ | Débit **61711/61712/61713** (rémunérations), **61741** (CNSS + AMO patronales), **61744** (prestations familiales), **61768** (taxe de formation) ; Crédit **4441** (CNSS/AMO parts salariale **et** patronale), **4443/4445/4448** (retraite, mutuelle, assurance groupe), **4452** (IR retenu), **4434** (oppositions), **3431** (avances), **4432** (**net à payer**) ; règlement `4432 → 5141/5161` (journal BQ/CA) |
| **DTS « 9421 »** | ✅ | `app/services/edi_dts.py` : modèle déclaratif (déclarant, **personnel permanent**, **salariés exonérés art. 57-20°**, cotisations, totaux), **fichier XML EDI**, **état de saisie EFI** (saisie assistée SIMPL), fiche récapitulative **PDF**, registre `tax_declarations` (fichier + **SHA-256** + accusé) |
| **États** | ✅ | Journal de paie, **livre de paie annuel** (cumuls mensuels par salarié), état des cotisations et de l'IR **par mois**, récapitulatif annuel, **bulletin de paie PDF** (gabarit P1.1, interface inchangée) |
| **Contrôles** | ✅ | `controles_paie()` et contrôles DTS : Net négatif, **opposition > net saisissable**, **Σ bulletins ≠ écriture**, **n° CNSS manquant** (bloquant), CIN manquante, **période verrouillée**, **réconciliation DTS ↔ comptes 617x** |
| **Interface et API** | ✅ | Écran `/paie` (salariés, cycle de paie, bulletins, livre, cotisations, DTS, téléchargements XML/PDF) et API `/payroll` (**22 routes** : salariés, contrats, cycles, validation, paiement, contrôles, journal, livre, cotisations, récapitulatif, bulletin PDF, DTS modèle/XML/EFI/fiche/registre) |
| **Migration** | ✅ | révision Alembic `56d9985cc7ff` (`employees`, `pay_contracts`, `payroll_runs`, `payslips`, `payslip_lines`, `tax_declarations`) **additive**, appliquée à la base témoin **et** à la production (sauvegarde `compta_ma.db.bak-p14-*`, données intactes : 42 factures, 84 écritures) |
| **Suite de tests** | ✅ **221/221** (plancher relevé de 198 à 221) | `tests/test_payroll.py` (**21 tests**) + `test_api.py` (contrat `/payroll`) + `test_web.py` (écran `/paie`) |

**Critères d'acceptation du CDC § 3.4 — vérifiés**

1. **IR d'un cas de référence au dirham** : 10 500 DH bruts (marié, 2 enfants) → cotisations
   506,10 · frais 2 625,00 · net imposable 7 368,90 → **IR 560,67** · **net 9 433,23** ·
   coût employeur 12 310,35 DH.
2. **CNSS plafonnée** : 11 500 DH bruts → assiette ramenée à **6 000 DH**, AMO non plafonnée.
3. **Σ bulletins = écriture = déclaration DTS** : l'écriture globale est **équilibrée** (débit =
   crédit = coût employeur) et la DTS se **réconcilie** avec les comptes `617x` (contrôle
   automatique).
4. **Bulletin conforme** aux mentions obligatoires (gabarit P1.1) et au **modèle 9421**.
5. **Tests** : IR/CNSS/AMO, plafonds, oppositions, **écriture équilibrée**, **verrouillage**.

**Points de vigilance signalés**

1. **Compte du net à payer : `4432`, pas `3431`** — l'énoncé du jalon mentionnait
   « **3431 (net à payer)** », mais le plan comptable de référence porte
   **`3431` = « avances et acomptes au personnel »** (compte d'**actif**) et
   **`4432` = « rémunérations dues au personnel »** (compte de **dette**) : le net à payer est une
   **dette** (CDC § 3.4 et logique CGNC). L'application crédite donc **`4432`** et utilise
   **`3431`** pour la **régularisation des avances** déjà versées. *(Correction appliquée et
   tracée ici.)*
2. **XSD de la DTS toujours absent (écart n° 6)** : la structure XML produite reprend
   l'organisation du formulaire mais **n'est pas validable** ; `valider_xsd()` renvoie
   explicitement `valide=None` (jamais « conforme ») et pointe sur `DTS_XSD_PATH`. Le mode
   **EFI assisté** (état de saisie ligne par ligne) est livré comme solution de repli.
3. **Périodicité de la DTS (ambiguïté A6)** : le module déclare **par exercice** (cumuls annuels
   par salarié) ; si la DGI exige une périodicité infra-annuelle, la déclaration se générera sur
   les périodes concernées après arbitrage (le modèle est déjà calculé par mois).
4. **Mutuelle et assurance groupe non déduites du net imposable** : seules les cotisations
   **obligatoires** (CNSS/AMO) et la **retraite complémentaire** sont déduites (choix prudent) ;
   l'incidence est signalée ici et à confirmer par l'expert-comptable.
5. **Part patronale de la retraite/mutuelle/assurance groupe** : non modélisée (les taux du
   contrat sont **salariaux**) ; à compléter si un dossier pratique des cotisations patronales
   de retraite/mutuelle.
6. **Taxe de formation professionnelle** : faute de compte dédié dans le plan, elle est
   rattachée à **`61768` « autres charges sociales diverses »** ; à reclasser si le plan du
   dossier comporte un sous-compte dédié.
7. **Aucun journal « paie »** dans le plan : l'écriture de paie est passée en **OD** et le
   règlement en **BQ**/**CA** selon le mode.

#### 9.13.1 Correctif J6 (22/09/2026) — fichier DTS aligné sur le modèle officiel V5.1

Le dépouillement du référentiel **Simpl-IR DTS V5.1** (`Simpl_IR_Cahier_des_charges_DTS_V5.1.zip` :
CC EDI, **Annexe 1 « correspondance balise ↔ déclaration »**, **Annexe 2 « codification »**,
**exemple XML officiel**) a montré que la première structure XML de J6 **n'était pas conforme**.
`build_dts_xml()` a été refondu sur l'**exemple officiel** (`EDI_DTS_Exemples_V5.1.xml`) :

| Avant (J6 v1) | Après (conforme V5.1) |
|---|---|
| racine `<DTS version=… mode=…>` | racine **`<TraitementEtSalaire>`**, `xsi:noNamespaceSchemaLocation="traitementSalaire.xsd"`, **sans namespace** |
| bloc `<declarant>` | **balises plates** : `identifiantFiscal`, `nom`, `prenom`, `raisonSociale`, `exerciceFiscalDu/Au`, `annee`, `adresse`, `numeroCNSS`, `numeroRC`, `effectifTotal`, `nbrPersoPermanent/Occasionnel/Stagiaires` |
| 2 listes (`personnelPermanent`, `salariesExoneresArt57_20`) | **3 listes officielles** : `listPersonnelPermanent` (PP), `listPersonnelOccasionnel` (PO), `listStagiaires` (STG) |
| totaux `brutImposable`/`irRetenu`/`netAPayer` | **totaux normalisés** : `totalMtRevenuBrutImposablePP`, `totalMtRevenuTotalDeductionPP` → `totalMtTotalDeductionPP`, `totalMtIrPrelevePP`, `totalMtBrutSommesPO`, `totalIrPrelevePO`, `totalMtBrutTraitSalaireSTG`, `totalMtRetenuesSTG`, `totalSommePayeRTS`, `montantPermanent/Occasionnel/Stagiaire`… |
| `nom` unique | **`nom` + `prenom`** séparés (`numCNI`, `numCE`, `adressePersonnelle`) |
| avertissement `dts.xsd_absent` | `dts.schema_absent` (renvoie à `traitementSalaire.xsd` / `DTS_XSD_PATH`) + nouveau contrôle `dts.prenom_incomplet` |

L'**état de saisie EFI** reprend les **trois onglets** du formulaire. La suite reste
**221/221**. Nouvelles ambiguïtés à trancher (voir § 8.2) :

- **A16** : la **catégorie** PP / PO / STG est déduite du **type de contrat** (`cdi`/`cdd` → PP,
  `anapec`/`interim` → PO, `stage`/`apprentissage` → STG) — **hypothèse à confirmer** ;
- **A17** : l'**exonération art. 57-20°** ne correspond pas à une liste du modèle V5.1 (elle est
  gérée comme un attribut interne du salarié permanent) ;
- **A18** : `nom` / `prenom` sont **déduits** du champ unique `nom` (1ᵉʳ mot = nom) : une colonne
  `prenom` dédiée serait préférable ;
- **A19** : les **balises de montant par salarié** (`montantRevenuBrutImposable`,
  `montantRetenues`, `montantIrPreleve`, `montantRevenuNetImposable`) sont dérivées du vocabulaire
  des totaux : à **confirmer sur l'Annexe 1** du référentiel.

---

### 9.14 Résultats du jalon J7 — P2.1 « IS & liasse EDI » (étape 1 réalisée le 22/09/2026)

**Périmètre de l'étape 1** : détermination du **résultat fiscal** et de l'**impôt dû**
(IS / cotisation minimale), reports et acomptes, puis **contrôles** — préalables à
l'**assembleur de liasse** (étape 2) et au **XML validé par XSD** (étape 3).

| Livrable | Réalisation | Vérification |
|---|---|---|
| **Résultat fiscal** | `app/services/fiscal_liasse.py` — `resultat_avant_impot()` : le résultat comptable (CPC) est retraité **hors comptes `67x`**, l'IS n'étant **pas déductible** (CGI art. 11) | `test_resultat_avant_impot_exclut_l_impot_sur_les_societes` |
| **Réintégrations / déductions** | catalogue **paramétrable** par rubrique (`code`, libellé, **référence CGI**, comptes) ; `charges_non_deductibles()` **détecte** les comptes non déductibles par nature (`6583` amendes, provisions…) et les **propose** (`origine = « détection automatique »`) ; la **saisie du comptable prévaut** | `test_reintegration_saisie_prime_sur_la_detection`, `test_charges_non_deductibles_detectees_avec_reference_cgi` |
| **Report déficitaire** | report **plafonné au bénéfice** de l'exercice, aucun report en cas de déficit ; **aucune durée codée en dur** (CGI art. 114 — ambiguïté **A21**) ; `deficit_constate` et `report_deficitaire_restant` restitués | `test_resultat_fiscal_reintegrations_et_report_deficitaire` |
| **IS vs cotisation minimale** | `compute_is` (**taux historisé** de l'exercice) comparé à `compute_cotisation_minimale` (**0,25 % du CA TTC**, plancher **3 000 DH**, exonération **36 mois**) ; **impôt dû = le plus élevé des deux** (CGI art. 144) et **CM due même en cas de déficit** | `test_cotisation_minimale_due_meme_en_deficit` |
| **Acomptes et solde** | acomptes = solde du compte **`3453`** « acomptes sur impôts sur les résultats » ; crédits d'impôt saisis ; `solde_a_payer` / `excedent_a_reporter` / `taux_effectif` | `test_is_du_et_solde_apres_acomptes`, `test_acomptes_superieurs_a_l_impot_donnent_un_excedent` |
| **Concordance comptable ↔ fiscale** | contrôle `fiscal.recap` : résultat avant impôt, réintégrations, déductions, résultat fiscal, IS, CM, impôt dû — l'**écart comptable/fiscal est explicite** | `test_dossier_is_agrege_calcul_balance_et_controles` |
| **Contrôles** | **bloquants** : `fiscal.exercice_non_clos` (**P1.6**), `fiscal.balance_desequilibree`, `fiscal.exercice_sans_ecriture` ; **avertissements** : `fiscal.reintegrations_a_examiner` (art. 11), `fiscal.cotisation_minimale_due` (art. 144), `fiscal.deficit_reportable` (art. 114) ; helper `controles_bloquants()` | `test_controles_exercice_non_clos_bloquant_puis_leve_apres_cloture`, `test_controles_cotisation_minimale_et_deficit_art_144_et_114` |
| **Préparation « Σ liasses = balance »** | `reconciliation_balance()` : équilibre de la **partie double** (Σ soldes = 0), totaux **par classe**, produits / charges / résultat et indicateur **`pret_pour_liasse`** — base de la réconciliation **tableau par tableau** de l'étape 2 | `test_reconciliation_balance_preparee_pour_la_liasse` |
| **Entrée unique** | `dossier_is()` = calcul + balance + contrôles (branchement API et écran à l'étape 2) | `test_dossier_is_agrege_calcul_balance_et_controles` |
| **Suite de tests** | ✅ **236/236** (plancher relevé de 221 à 236) | `tests/test_fiscal_liasse.py` (**15 tests**) |

**Choix de conception** : **aucun taux ni plafond codé en dur** (tout provient de
`app/core/rates_ma.py`, historisé par exercice) ; calcul **reproductible** (balance +
saisies motivées) ; les propositions de réintégration sont **toujours restituées**, même
lorsqu'elles ne sont pas retenues, afin de **tracer l'arbitrage** du comptable.

**Nuance à confirmer (base de la cotisation minimale)** : le **CA TTC** est **reconstitué**
depuis la comptabilité (CA des comptes `71x` + TVA collectée du compte `4455`) ; pour les
opérations **exonérées** ou hors champ (aucune TVA facturée), la base effectivement
retenue est donc le **montant HT**. La méthode de reconstitution du CA TTC exigée par
l'administration (et le traitement des **produits financiers et accessoires**, qui entrent
dans l'assiette de la CM) doivent être **validés par l'expert-comptable**.

**Reste à faire (étapes 2 et 3)** : tables `liasse_tables` / `liasse_cells`
(`declaration_id`, `tableau_id`, `code_edi`, `valeur`, `numero_ligne`, `extra_field`) et
alimentation depuis la balance, les **immobilisations (J2)**, les **stocks (J3)** et les
**frais de personnel DTS (J6)** ; **EFI assisté par tableau** ;
`build_liasse_xml()` (racine `groupeValeursTableau`) puis **validation XSD réelle**
(lxml) et enregistrement dans `tax_declarations` (`DECLARATION_IS` +
`DECLARATION_LIASSE`, SHA-256, accusé de réception).

---

### 9.15 Résultats du jalon J7 — P2.1 « IS & liasse EDI » (étape 2 réalisée le 22/09/2026)

**Périmètre de l'étape 2** : **assembleur de liasse** — modèle de données, lecture du
contrat des schémas officiels, référentiel de codification, alimentation depuis la
balance définitive et les modules J2/J3/J6, **EFI assisté par tableau** et persistance.

| Livrable | Réalisation | Vérification |
|---|---|---|
| **Modèle de données** | `liasse_tables` (un tableau : `declaration_id`, `modele`, `tableau_id`, libellé, `extra_field`, ordre → `tax_declarations`) et `liasse_cells` (`code_edi`, `rubrique`, `valeur`, **`valeur_numerique`**, `numero_ligne`, `extra_field`, `source` pour la piste d'audit) — migration **additive** `a7f3c51d8b42` | `test_enregistrer_liasse_persiste_cellules_et_registre` |
| **Référentiels installés** | `referentiels/liasse/` : les **4 XSD officiels DGI** (+ `LISEZ-MOI.md` et `codification_liasse.csv`) ; options `LIASSE_XSD_DIR` et `LIASSE_CODIFICATION_PATH` | `test_referentiel_et_schemas_du_projet`, `test_xsds_disponibles_dans_le_projet` |
| **Contrat lu dans le XSD** | `contrat_modele()` : racine (`Liasse`), **`modele/id` fixé par le schéma (7)** pour le modèle comptable simplifié, `tableaux` (24 ids), `codeEdi` (**1328** codes), `extraField` (11 codes), types (`valeur` = `xs:string`, `numeroLigne` = `xs:int`) — **aucun libellé n'est inventé** | `test_contrat_modele_simplifie_lu_dans_le_xsd` |
| **Référentiel `codeEdi` ↔ rubrique** | `codification_liasse.csv` (colonnes `modele`, `tableau_id`, `tableau_libelle`, `code_edi`, `rubrique`, `libelle`, `numero_ligne`, `extra_field`, `origine`) — livré avec la **seule correspondance documentée** (code `13400` = capital social, exemple officiel du CC EDI) ; un code/un tableau **hors schéma** ou une rubrique **hors catalogue** sont **bloquants** | `test_referentiel_livre_est_documente_et_conforme`, `test_code_hors_schema_est_bloquant`, `test_tableau_hors_schema_est_bloquant`, `test_rubrique_inconnue_est_bloquante` |
| **Alimentation** | rubriques `solde:<compte>`, `racine:<2-3 chiffres>`, `classe:<1-7>` (**balance définitive**), résultat fiscal / IS / CM (étape 1), **immobilisations (J2)**, **stocks (J3)**, **personnel / DTS (J6)** ; une source absente est **signalée** (`liasse.sources_indisponibles`) et la cellule reste **à compléter** | `test_rubriques_liasse_balance_et_resultat_fiscal`, `test_cellule_sans_valeur_est_signalee_mais_non_bloquante` |
| **EFI assisté par tableau** | `etat_de_saisie_efi_liasse()` : une feuille par tableau (`codeEdi`, libellé, valeur, `numeroLigne`, `extraField`, état `valeur` / `a_completer`) et export CSV (UTF-8 + BOM) pour la saisie sur SIMPL | `test_etat_de_saisie_efi_par_tableau_et_csv` |
| **Σ liasses = balance** | `reconciliation_liasse_balance()` : rapprochement de **chaque cellule de solde** avec le grand livre ; tout écart est **bloquant** | `test_reconciliation_liasse_balance_detecte_un_ecart`, `test_signe_inverse_et_reconciliation_balance` |
| **Persistance et registre** | `enregistrer_liasse()` : tableaux + cellules et **déclaration `LIASSE`** en statut **brouillon** (régime = modèle, `nb_lignes`, montant = **impôt dû**), **idempotente** ; une déclaration déjà **déposée** est **figée** ; trace d'audit `LIASSE_RECORDED` | `test_enregistrer_liasse_persiste_cellules_et_registre`, `test_liasse_enregistree_absente_et_declaration_figee` |
| **Outils** | `tools/liasse_codification.py` : `--contrat`, `--codes`, `--rubriques`, `--gabarit` (gabarit du référentiel dérivé du XSD), `--verifier` (contrôle du référentiel, sortie 1 si anomalie) | `--verifier` (référentiel livré : OK) |
| **Suite de tests** | ✅ **258/258** (plancher relevé de 236 à 258) | `tests/test_liasse.py` (**22 tests**) |

**Choix de conception** : le schéma XSD est **la loi** (codes et tableaux légaux, `id` du
modèle, types de valeurs) ; l'application **ne devine jamais** un `codeEdi` et ne compose
**aucune cellule** dont l'origine n'est pas décrite dans le référentiel de codification
(un code hors schéma bloque le dépôt, une source absente laisse la cellule « à compléter »).

**Vérifié dans le référentiel fourni** : le `réferentiel des codifications.xlsx` accompagnant
Simpl-IS ne contient **que** des données **CbCR** (aucun `codeEdi`, aucun libellé de liasse) —
l'ambiguïté **A13** est confirmée par l'ouverture du fichier.

**Nouvelle ambiguïté (A22)** : l'annexe officielle « **Codification des cellules** » et
« Codification des modèles et tableaux des Liasses » **n'est pas fournie** ; les XSD ne
portent **aucun libellé** et le CC EDI y renvoie explicitement. Le référentiel de
codification est donc un **document éditable à valider par l'expert-comptable** (l'outil
`--gabarit` en produit la trame à partir du schéma) : dans l'attente, la liasse peut être
préparée en **EFI assisté** (le téléservice affiche le libellé officiel de chaque code).

**Reste à faire (étape 3)** : `build_liasse_xml()` (racine `Liasse` → `modele/id` →
`resultatFiscal` → `groupeValeursTableau`) et **validation XSD réelle** (lxml) contre le
schéma du modèle choisi, puis branchement **API `/liasse` + écran** et accusé de réception
dans `tax_declarations`.

---

### 9.16 Résultats du jalon J7 — P2.1 « IS & liasse EDI » (étape 3 réalisée le 22/09/2026)

**Périmètre de l'étape 3** : **fichier XML EDI** conforme au schéma, **validation XSD
réelle**, API `/liasse`, écran `/liasse` et **accusé de réception** dans le registre.

| Livrable | Réalisation | Vérification |
|---|---|---|
| **`build_liasse_xml()`** | Structure exacte du schéma Simpl-IS : `Liasse` → `modele/id` (**valeur fixée par le XSD**, lue dans le contrat) → `resultatFiscal` (`identifiantFiscal`, `exerciceFiscalDu`, `exerciceFiscalAu`) → `groupeValeursTableau` → `ValeursTableau` → `tableau/id` → `groupeValeurs` → `ValeurCellule` (`cellule/codeEdi`, `valeur`, `numeroLigne`) → `extraFieldvaleurs` ; XML échappé, limite de taille contrôlée | `test_build_liasse_xml_structure_et_validation_xsd` |
| **Respect strict du schéma** | Le XSD exige **une `ValeurCellule` par tableau** : les tableaux sans cellule sont **omis** ; un document **vide** est **refusé** ; `extraFieldvaleurs` émis **vide** (sémantique des `extraField` non documentée — A22) | `test_build_liasse_xml_omet_les_tableaux_sans_cellule`, `test_build_liasse_xml_refuse_sans_cellule_ou_sans_schema` |
| **`valider_xsd()` réelle (lxml)** | Validation contre le **XSD du modèle** : `True` **conforme**, `False` **refusé** (écarts ligne par ligne), `None` **validation impossible** (schéma absent → jamais « conforme ») ; XML illisible → refusé | `test_build_liasse_xml_structure_et_validation_xsd`, `test_valider_xsd_refuse_les_ecarts_au_schema`, `test_valider_xsd_schema_absent_ne_declare_pas_conforme` |
| **`produire_liasse_xml()`** | Un seul point d'entrée : contrôles → **refus si un bloquant subsiste** → génération → **refus si le XSD rejette** ; `forcer=True` réservé aux reprises assistées (ne rend jamais un fichier « conforme ») | `test_produire_liasse_xml_refuse_tant_qu_un_bloquant_subsiste` |
| **Registre et accusé** | `enregistrer_liasse(..., xml=, validation=)` conserve **nom, taille, SHA-256** et l'état de validation ; `soumettre_declaration()` → **soumise / acceptée / rejetée** (motif conservé), date de dépôt **préservée** à l'accusé, déclaration **figée** ensuite ; audit `LIASSE_SUBMITTED` | `test_enregistrer_liasse_avec_fichier_hash_et_validation`, `test_soumettre_declaration_depot_rejet_puis_figeage`, `test_soumettre_declaration_accuse_de_reception_accepte` |
| **API `/liasse`** | `GET /liasse/declarations`, `GET /liasse/{annee}` (dossier IS + liasse + contrôles + registre), `GET /liasse/{annee}/efi` (+ `/efi.csv`), `GET /liasse/{annee}/validation-xsd`, `GET /liasse/{annee}/xml`, `POST /liasse/{annee}/enregistrer`, `POST /liasse/{annee}/depot` ; RBAC (mutations tous rôles comptables, **dépôt ADMIN / EXPERT_COMPTABLE**) | `test_api_is_et_liasse`, `test_api_liasse_refusee_sans_exercice_clos` |
| **Écran `/liasse`** | Tableau de bord IS/CM, contrôles, cellules (`codeEdi`, valeur, origine), **EFI assisté par tableau**, formulaires d'enregistrement et de dépôt, registre des liasses ; exports `/etats/liasse.xml` et `/etats/liasse-efi.csv` | `test_interface_is_et_liasse` |
| **Suite de tests** | ✅ **271/271** (plancher relevé de 258 à 271) | `tests/test_liasse.py` (**32 tests**) + `test_api.py` (2) + `test_web.py` (1) |

**Point d'attention technique (routage)** : l'API expose `GET /liasse/{annee}` ; les
**exports de l'écran** sont donc servis sous `/etats/liasse.xml` et
`/etats/liasse-efi.csv` (convention des états existante) afin qu'aucun chemin à un seul
segment ne soit capturé par le paramètre entier `{annee}` (réponse 422 au lieu de la page).

**Règle de vérité tenue** : le fichier n'est produit que si **aucun contrôle bloquant**
ne subsiste **et** que le **schéma le valide** ; la réponse de l'API
(`/liasse/{annee}/validation-xsd`) restitue séparément le **résultat XSD** et les
**contrôles** — l'application ne déclare jamais un fichier conforme sans cette preuve.

**Clôture du jalon** : l'ensemble du périmètre **P2.1 (IS & liasse EDI)** est livré —
étapes 1 (§ 9.14), 2 (§ 9.15) et 3 (ci-dessus). Le module reste marqué
**« à valider par l'expert-comptable »** pour la **sémantique des `codeEdi`**
(ambiguïté A22, annexe DGI non fournie) : la liasse se dépose en **EFI assisté** tant que
le référentiel `codification_liasse.csv` n'a pas été complété, et le fichier EDI ne
part que sur les tableaux dont la codification est documentée.

---

### 9.17 Résultats du jalon J8 — P2.2 « Cessation / cession d'activité » (réalisé le 22/09/2026)

**Périmètre** : événements de vie de l'entreprise, **TVA de la période de sortie**,
**régularisation des déductions**, **déclarations TVA des régimes 3 et 4** et fichier
**EDI du relevé des déductions** correspondant.

Base légale (CGI 2026, édition fournie par le client — articles lus dans le PDF)

| Sujet | Texte | Contenu retenu |
|---|---|---|
| **Déclaration de cession / cessation (TVA)** | **art. 114** | déclaration **dans les trente (30) jours** qui suivent la date de cession ou de cessation : liquidation de la taxe due jusqu'à cette date + **régularisation des déductions** (renvoi aux **art. 101 à 105**) ; taxe exigible dans ce délai ; **exception** fusion / scission / apport / transformation si la nouvelle entité s'engage à acquitter la taxe au fil des encaissements |
| **Déclaration de cessation, cession, fusion, scission, transformation** | **art. 150-I** | **quarante-cinq (45) jours** |
| **Cessation temporaire d'activité** | **art. 150 bis** | déclaration **dans le mois suivant la clôture du dernier exercice**, pour **deux exercices** renouvelable **un seul**, **motifs obligatoires** |
| **Régularisation des biens amortissables** | **art. 102 et 104-II-1°** | régularisation par fractions égales ; durée paramétrable (5 ans meubles / 10 ans immeubles, A5) |
| **Régime TVA de la déclaration** | **Annexe 1 EDI Simpl-TVA** (`Annexe1_EDI_Simpl-TVA_Correspondance_Balise_RD_V4.0.pdf`, installée dans `referentiels/tva/`) | `<regime>` **3** = cessation temporaire, **4** = cession ou cessation ; `<periode>` = **1** |

| Livrable | Réalisation | Vérification |
|---|---|---|
| **Modèle** | `activity_events` (`company_id`, `type` ∈ {cessation_temporaire, cession, cessation}, `date_effet`, `regime_tva`, `periode`, `motif`, repreneur (cession), `declaration_id`) — migration additive `c4b8e17f2d95` | `test_creation_cessation_temporaire_regime_3_et_delais` |
| **Événements** | `creer_evenement()` : régime déduit du type, `periode = 1`, exercice présent, **motif obligatoire** (art. 150 bis), **repreneur obligatoire** (cession), **chronologie contrôlée** (pas de doublon de date, pas d'antidatage) ; audit `ACTIVITY_EVENT_CREATED` | `test_creation_cessation_temporaire_exige_un_motif`, `test_creation_cession_exige_le_repreneur_et_type_valide`, `test_chronologie_des_evenements_est_controlee` |
| **Délais** | `echeance_tva()` (**+30 j**, art. 114), `echeance_declaration_art_150()` (**+45 j**), `echeance_cessation_temporaire()` (**mois suivant la clôture**) | `test_creation_cessation_temporaire_regime_3_et_delais` |
| **Période de sortie** | `periode_declaration()` : du **1ᵉʳ janvier** (ou du **lendemain du dernier événement**) à la **date d'effet** | `test_periode_declaration_du_debut_de_l_exercice_a_la_date_effet` |
| **TVA de sortie** | `declaration_tva_sortie()` : TVA collectée / déductible / nette (`vat_return`), **total à payer** (TVA + régularisations), crédit reportable, échéances | `test_declaration_tva_de_la_periode_de_sortie` |
| **Régularisations** | immobilisations **en service** via le calcul du module P1.2 (biens déjà sortis exclus) ; **stocks** : valeur affichée et **montant saisi** (aucun taux deviné) | `test_regularisation_des_immobilisations_en_service`, `test_regularisation_ignore_les_biens_deja_sortis`, `test_regularisation_stocks_saisie_et_total` |
| **Contrôles** | **bloquants** : `activite.motif_absent`, `activite.echeance_tva_depassee` ; **avertissements** : `activite.repreneur_absent`, `activite.regularisation_stocks_a_examiner`, `activite.tva_non_declaree`, `activite.ecritures_apres_effet` ; `activite.recap` | `test_controles_activite_signalent_les_points_a_traiter`, `test_controle_bloquant_si_echeance_de_30_jours_depassee` |
| **Registre** | `enregistrer_declaration_tva()` : déclaration **TVA** (`periode` = exercice, `regime` = 3 ou 4, montant = total à payer), **idempotente**, **figée** après dépôt ; accusé de réception (soumise / acceptée / rejetée) ; audit `ACTIVITY_TVA_RECORDED` / `_SUBMITTED` | `test_enregistrer_declaration_tva_au_registre_et_figeage` |
| **EDI** | `construire_rd_sortie()` : relevé des déductions au **régime 3 / 4** (`<periode>1`, nom de fichier `…_CessationTemporaire_1.xml` / `…_CessionCessation_1.xml`) ; `edi_tva.validate_period()` étendu (période 1 exigée) | `test_releve_des_deductions_edi_au_regime_4`, `test_releve_edi_refuse_sans_ligne_et_periodes_des_regimes_activite` |
| **Situation** | `situation()` : événements, déclaration, registre, références légales (point d'entrée API/écran) | `test_situation_de_l_activite` |
| **Référentiel** | `referentiels/tva/` : annexe 1 « correspondance balise RD V4.0 » + exemple officiel du relevé | copie vérifiée |
| **Suite de tests** | ✅ **300/300** (plancher relevé de 271 à 300) | `tests/test_activity_events.py` (**16 tests**) |

**Limites assumées** : la TVA sur **stocks et biens non amortissables** est **saisie**
(aucun taux n'est deviné) et la durée de régularisation des immobilisations reste
**paramétrable** (A5) ; l'application **ne clôture pas** l'activité : elle prépare la
déclaration, l'inscrit au registre et laisse le dépôt à l'utilisateur (EDI/EFI).
**Reste à faire** : API `/activite` et écran dédiés, et **correction des citations
« art. 106 »** existantes (A23).

---

### 9.18 Résultats du jalon J8 — P2.3 « E-facturation » (réalisé le 22/09/2026)

**Périmètre livré** : contrôle des **mentions obligatoires**, **fichier structuré**,
**canal DGI paramétrable**, **cycle de vie** du document (généré → transmis →
accepté/rejeté) et **contrôles de dossier**.

**Avertissement majeur (A24)** : le **cahier des charges e-facturation de la DGI n'est
pas fourni** (aucun document « loi 43-20 » ni schéma XML dans le référentiel reçu ;
l'édition 2026 du CGI ne contient ni « facturation électronique » ni « 43-20 » —
vérifié le 22/09/2026). Le module est donc livré **sans format officiel** : le fichier
produit est un **format interne** (`interne-v1`) portant explicitement
`<conformite>non validée (spécification DGI non publiée)</conformite>` et **ne doit pas**
être déposé tel quel comme facture électronique.

| Livrable | Réalisation | Vérification |
|---|---|---|
| **Modèle** | `e_invoice_documents` (`invoice_id`, `company_id`, `statut`, `format`, `canal`, `xml`, `hash_sha256`, `identifiant_dgi`, `accuse`, `envoye_le`, `accuse_le`) — migration additive `c4b8e17f2d95` | `test_generer_document_hash_et_regeneration` |
| **Mentions obligatoires** | catalogue de **17 mentions** (numéro séquentiel, date, identités, **IF**, **ICE**, RC, adresse, désignation, quantités/prix, taux de TVA, cohérence des montants, mode de paiement, échéance) avec **niveau** (bloquant / avertissement) et **référence vérifiable** (CGI art. 146, loi 15-95, obligation d'ICE) | `test_catalogue_des_mentions_obligatoires`, `test_facture_validee_ne_signale_aucun_bloquant` |
| **Contrôles bloquants** | facture **validée**, **numéro**, identités, lignes, désignation, quantités/prix, taux de TVA, **cohérence des montants** (recalcul par `invoicing.compute_line`) | `test_facture_brouillon_et_numero_manquant_sont_bloquants`, `test_identifiant_client_absent_est_un_avertissement` |
| **Fichier** | `build_e_invoice_xml()` : `FactureElectronique` (émetteur, destinataire, facture, lignes, totaux, pièce PDF, **conformité**) ; montants repris de la comptabilité | `test_fichier_structure_et_conformite_non_validee` |
| **Validation** | `valider_conformite()` : **`None`** sans schéma (jamais « conforme ») ; **validation réelle** (lxml) dès qu'un schéma est fourni | `test_valider_conformite_avec_schema_fourni` |
| **Cycle de vie** | `generer_document()` (refus si mention bloquante, **empreinte SHA-256**, régénérable), `envoyer()` (**canal** API / manuel / EFI, **simulation par défaut** : aucune requête réseau), `enregistrer_accuse()` (**accepté** / **rejeté motivé**, document **figé**) ; audits `E_INVOICE_GENERATED` / `_SENT` / `_ACKNOWLEDGED` | `test_envoyer_par_simulation_sans_endpoint`, `test_accuse_de_reception_accepte_puis_document_fige`, `test_rejet_exige_un_motif_et_fige_le_document` |
| **Contrôles de dossier** | `canal_non_configure`, `specification_absente`, `mentions_manquantes`, `document_manquant`, `transmission_en_attente`, `accuse_en_attente`, `rejetee`, `recap` | `test_controles_e_facturation_et_situation` |
| **Situation** | `situation()` : documents, factures sans document, catalogue des mentions, canal, simulation, format, conformité | `test_controles_e_facturation_et_situation`, `test_list_documents_filtres` |
| **Configuration** | `E_INVOICE_ENDPOINT`, `E_INVOICE_API_KEY`, `E_INVOICE_DRY_RUN` (simulation **active** par défaut) | `test_envoyer_par_simulation_sans_endpoint` |
| **Suite de tests** | ✅ **300/300** | `tests/test_e_invoice.py` (**13 tests**) |

**Reste à faire** : brancher le **schéma officiel** dès sa publication
(`valider_conformite(schema=…)` puis `E_INVOICE_ENDPOINT` réel sans simulation), API
`/e-invoice` et écran de suivi (statuts, accusés, rejets), et **facture d'avoir /
autofacturation** selon le CDC définitif.

---

## Partie 10 — Tests et validation

### 10.1 Stratégie par module (test-first sur les règles)

| Module | Tests unitaires (règles) | Tests d'intégration | Tests de conformité / format |
|---|---|---|---|
| **P1.1 PDF** | pagination, arrondis, mentions légales | PDF ↔ écran (mêmes montants) | **taille ≤ 10 Mo**, PDF/A si exigé |
| **P1.2 Immo** | linéaire, dégressif, prorata temporis, cession | dotation → balance → bilan | conformité des comptes **6193x/283x/34551** |
| **P1.3 Stocks** | CMUP, FIFO, écart d'inventaire, provision | mouvement → compte 3xxx → CPC | variation de stocks conforme (6114/6124) |
| **P1.4 Paie** | IR (barème 2026), CNSS/AMO plafonnés, oppositions | bulletin → écriture → DTS | **DTS** : Σ = bulletin ; XSD (si disponible) |
| **P1.5 Greffe** | checklist par forme, date limite d'AG, états | dossier → pièces → hash | **PDF ≤ 10 Mo** ; unicité par exercice |
| **P1.6 Audit** | verrouillage, hash & chaînage, appariement | écriture refusée + trace ; rapprochement équilibré | export du journal (CSV) immuable |
| **P2.1 Liasse** | mapping codes, IS/cotisation minimale | liasse ↔ balance ↔ états | **validation XSD** + déterminisme |
| **P2.2 Cess/Cession** | régimes 3 et 4, période 1 | arrêt des déclarations postérieures | conforme **Annexe V4.0** |
| **P2.3 E-facturation** | mentions, unicité, cycle de vie | facture → document → accusé | conforme CDC DGI (à obtenir) |

### 10.2 Tests transverses (obligatoires à chaque livraison)

1. **Non-régression globale** : `pytest` complet — **85 tests aujourd'hui = plancher** ;
2. **Équilibre** : Σ débit − Σ crédit = 0 sur le dossier de test ;
3. **TVA** : ligne à ligne = base × taux ; relevé EDI **identique** au fichier de référence
   (`ReleveDeductions_2026_T2.xml`, réellement accepté) ;
4. **Identifiants** : IF (7 **et** 8 chiffres), ICE, RC — cas valides **et** invalides ;
5. **Verrouillage** : aucune écriture possible sur période fermée (y compris via outils) ;
6. **Déterminisme** : deux générations d'un même fichier de dépôt sont **octet pour octet**
   identiques ;
7. **Piste d'audit** : de tout montant d'état → document d'origine en 2 clics.

### 10.3 Jeux de données de référence (à constituer)

| Jeu | Contenu | Usage |
|---|---|---|
| **Dossier A** | 42 factures d'achat réelles (fournisseurs BP/Orange), 2 exercices | TVA, états, imports *(existe déjà)* |
| **Dossier B** | ventes multi-taux + avoirs + règlements partiels | TVA, CPC, lettrage |
| **Dossier C** | immobilisations (linéaire + dégressif + cession) | P1.2 |
| **Dossier D** | stocks (CMUP, FIFO, inventaire avec écart) | P1.3 |
| **Dossier E** | paie (3 salariés : plafond dépassé, opposition, exonération art. 57-20°) | P1.4 |
| **Dossier F** | exercice complet clos et **déposé au greffe** (avec certificat) | P1.5 + P1.6 + P2.1 |

### 10.4 Critères de recette (validation finale par l'expert-comptable)

① **Bilan, CPC et ESG** signés conformes au modèle CGNC ; ② **relevé TVA** accepté par la
DGI pour une période réelle ; ③ **liasse** acceptée (ou validée au XSD officiel) ;
④ **DTS** acceptée ; ⑤ **dossier greffe** produit et **certificat obtenu** ; ⑥ **piste
d'audit** parcourue de bout en bout devant un tiers ; ⑦ `pytest` **vert** et nombre de tests
**supérieur** au plancher précédent.

### 10.7 Validation de la **suite P1** (23/09/2026)

| Exigence de validation | Résultat |
|---|---|
| Tests de régression par chantier | **+22 tests** : `test_reouverture_exercice.py` (7), `test_tresorerie.py` (5), `test_is_exercice_et_exoneration.py` (7), `test_paie_source_unique.py` (+2) ; `test_audit_trail.py` / `test_api.py` mis à jour (réouverture **encadrée**, API exigeant `motif`) |
| Suite complète | **348/348 tests verts** (`PREUVE_P1SUITE_TESTS.log`, code de sortie **0**) |
| Réouverture | cycle complet démontré : réouverture motivée → correction → reclôture → **régénération comparée** des à-nouveaux (écarts par compte) ; verrous, N+1 verrouillé et absence de motif ⇒ refus |
| Trésorerie | contrôle exécuté sur la base : 2025 et 2026 **conformes** (0 solde créditeur) ; reclassement `5541`/`5548` testé et idempotent |
| Exonération CM | `date_debut_exploitation = 2025-01-01` ⇒ 2025 : 12 mois, 2026 : 24 mois (exonérées jusqu'au 2028-01-01) ; expiration testée (CM 3 000 DH due **malgré un déficit**) |
| Taux IS | taux de l'exercice appliqué ; **refus explicite** pour 2025 (barème LF 2025 à fournir) |
| Données hors périmètre | **aucune écriture 2025 modifiée** : simulation en lecture seule (`P1B_SIMULATION_2025.md`) |
| Pré-requis séquence 2025 | **à fournir** : barème de paie 2025, taux d'IS 2025, paramètres de cotisation minimale 2025 |

### 10.5 Validation de la régularisation **P0** (audit J9) — 23/09/2026

| Exigence de validation | Résultat |
|---|---|
| Test de régression **par anomalie corrigée** | 24 tests ajoutés : `test_routing_isolation.py` (5), `test_ecrans_smoke.py` (8), `test_etic_notes.py` (3), `test_facture_document.py` (6), `test_edi_tva.py` (+2, dont un qui reproduit la signature exacte du défaut EDI et vérifie le **refus** de génération) |
| Suite complète | **324/324 tests verts** (plancher précédent : 300) |
| Preuve fonctionnelle **avant / après** | `PREUVE_P0.md` (`tools/p0_preuve_avant_apres.py`, lecture seule) : `/audit` 401 → **200** ; ligne EDI FA26-12 9 000/720/9 720 → **3 600/720/4 320** ; scan 48 périodes 45 → **0** incohérence ; note 9 ETIC 0 → **203 295,60 DH** ; 74 factures : **0** document incohérent produit |
| Données hors périmètre | **aucune écriture** : audit et preuve sont en lecture seule, `compta_ma.db` non modifiée (horodatage inchangé) ; la double paie de recette reste à purger en **P1** |
| Portée fonctionnelle | API REST déplacée sous `/api` (**rupture d'interface documentée**, README § 7 et § 18) ; aucune fonctionnalité retirée |

### 10.6 Validation de la régularisation **P1** — paie, source unique (23/09/2026)

| Exigence de validation | Résultat |
|---|---|
| Sauvegarde préalable | `compta_ma.db.bak-p1-20260923-150952` (1 064 Ko), **vérifiée par l'outil** avant toute écriture |
| Liste exacte des écritures concernées | `P1_INVENTAIRE_PAIE_AVANT.txt` : 13 écritures 2026 (12 `PAIE26-xx` source `import_jeu_j9` + 1 `payroll`), 1 cycle, 3 bulletins, 1 DTS |
| Réinitialisation **contrôlée** (pas de suppression silencieuse) | 13 écritures retirées avec trace `PAYROLL_RESET_SUPPRESSION` (instantané complet), cycle/DTS tracés (`PAYROLL_RESET_CYCLE`, `PAYROLL_RESET_DECLARATION`) ; piste **rescellée** : 171 écritures, **0 rupture**, `integre=True` |
| Régénération par le module | 12 cycles 2026 (préparer → valider → payer), **36 bulletins**, **24 écritures**, DTS 2026 régénérée (IR 27 607,92 DH) |
| Chaîne recalculée sans correction manuelle | Paie → Journal → Balance → CPC → ESG → Bilan → ETIC → résultat fiscal → IS (`P1_AVANT_APRES.md`) |
| Tests de régression | `tests/test_paie_source_unique.py` (2) : refus de comptabiliser la paie si une **charge hors module** existe (reproduit A2) et acceptation après régularisation ; **326/326 tests verts** (`PREUVE_P1_TESTS.log`) |
| Contrôles exigés | **Journal équilibré**, **Bilan équilibré** (actif net = passif + résultat), **CPC = ESG = Bilan**, `4432` soldé, `4441`/`4452` = 96 670,32 DH déclarés par la DTS |
| Portée | seule la paie **2026** (exercice ouvert) a été régularisée ; la paie **2025** (12 écritures, exercice **clos** avec à-nouveaux générés) reste inchangée et est **signalée** comme point d'arbitrage P1-b |

---

## Annexes

### Annexe A — Commandes du projet (mémo opérationnel)

```powershell
cd C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma

# --- Application ---
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload      # http://127.0.0.1:8000/  (docs : /docs)
#   identifiants par défaut : admin@compta.ma / Admin@2026

# --- Tests (plancher : 348 depuis P0, P1 et la suite P1) ---
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests\test_etats_pdf.py -v        # documents PDF (jalon J1)
.\.venv\Scripts\python.exe -m pytest tests\test_assets.py -v          # immobilisations (jalon J2)
.\.venv\Scripts\python.exe -m pytest tests\test_audit_trail.py tests\test_banking.py -v  # audit P1.6 (J3)
.\.venv\Scripts\python.exe -m pytest tests\test_stocks.py -v          # stocks & inventaire (jalon J4)
.\.venv\Scripts\python.exe -m pytest tests\test_greffe.py -v          # dépôt au greffe (jalon J5)
.\.venv\Scripts\python.exe -m pytest tests\test_payroll.py -v         # paie & DTS « 9421 » (jalon J6)
.\.venv\Scripts\python.exe -m pytest tests\test_fiscal_liasse.py tests\test_liasse.py -v  # IS & liasse (J7)
.\.venv\Scripts\python.exe -m pytest tests\test_activity_events.py tests\test_e_invoice.py -v  # J8 (P2.2/P2.3)
.\.venv\Scripts\python.exe -m pytest tests\test_liasse.py -v          # assembleur de liasse (jalon J7, étape 2)

# --- Référentiels de la liasse (P2.1) ---
.\.venv\Scripts\python.exe tools\liasse_codification.py --contrat "comptable simplifié"
.\.venv\Scripts\python.exe tools\liasse_codification.py --rubriques
.\.venv\Scripts\python.exe tools\liasse_codification.py --verifier
.\.venv\Scripts\python.exe tools\liasse_codification.py --gabarit "comptable simplifié" `
        --cible referentiels\liasse\codification_liasse.gabarit.csv

# --- Base de donnees (migration des immobilisations, P1.2) ---
.\.venv\Scripts\python.exe -m alembic upgrade head                    # cree assets / asset_* (revision c1d801a10835)

# --- Maintenance des données ---
.\.venv\Scripts\python.exe tools\charger_plan_comptable.py [--appliquer]        # plan PCGE (890 comptes)
.\.venv\Scripts\python.exe tools\normalize_fiscal_ids.py [--retirer-zero-initial] [--appliquer]  # IF 7 ou 8 chiffres, tel quel
.\.venv\Scripts\python.exe tools\import_achats_fournisseurs.py [--appliquer] `
        --if-societe 01234567 --ice-societe 001234567000099 [--inclure-tva-nulle]

# --- Reconstitution du plan comptable depuis le PDF officiel ---
.\.venv\Scripts\python.exe tools\plan_pdf_to_csv.py "chemin\Plan_Comptable_Marocain.pdf"
```

### Annexe B — Glossaire

| Terme | Définition |
|---|---|
| **CGNC** | Code Général de Normalisation Comptable (Maroc) : norme générale + plan comptable |
| **PCGE** | Plan Comptable Général des Entreprises (plan de comptes du CGNC) |
| **États de synthèse** | Bilan · CPC (Compte de Produits et Charges) · **ESG** (État des Soldes de Gestion) · **ETIC** (État des Informations Complémentaires = notes annexes) · tableau de financement (selon seuils) |
| **VNC** | Valeur Nette d'Amortissement = valeur d'origine − amortissements cumulés |
| **CMUP / FIFO** | Coût Moyen Unitaire Pondéré / « premier entré, premier sorti » (méthodes de valorisation des stocks) |
| **DEA** | Dotation d'Exploitation aux Amortissements (comptes **619x**) |
| **EDI / EFI** | Échange de Données Informatisé (fichier XML) / Échange de Formulaires Informatisé (saisie en ligne) — les deux modes des téléservices SIMPL de la DGI |
| **SIMPL** | Ensemble des téléservices de la DGI (SIMPL-IS, SIMPL-TVA, DTS…) |
| **DTS « 9421 »** | Déclaration des Traitements et Salaires (formulaire 9421) |
| **DRG** | Déclaration de Revenu Global (IR) |
| **RD** | Relevé des Déductions de TVA (fichier EDI de la TVA) |
| **ADC082F-15I** | Modèle officiel DGI du relevé des déductions (**art. 112 CGI**) |
| **Liasse fiscale** | Ensemble des tableaux fiscaux annuels ; en EDI : **tableaux numérotés + cellules `codeEdi`** |
| **CbCR / CBC** | *Country-by-Country Reporting* — déclaration pays par pays (format **OCDE**) |
| **Greffe** | Greffe du tribunal de commerce : dépôt légal des états de synthèse (**`depotbilan.justice.gov.ma`**) |
| **Piste d'audit fiable** | Ensemble des liens permettant de remonter d'un montant comptable à sa pièce justificative |

### Annexe C — Décisions ouvertes (à trancher avant les jalons concernés)

| # | Décision | Échéance | Qui décide |
|---|---|---|---|
| **D1** ✅ | Moteur PDF : **ReportLab retenu** (WeasyPrint écarté : runtime GTK absent) | **tranchée au J0 (22/09)** | développeur (empaquetage Windows) |
| **D2** | Durée de régularisation TVA art. 106 (5 ans / 10 ans immeubles) | avant **J3** | expert-comptable |
| **D3** | Coefficient d'amortissement **dégressif** (CGI art. 10) | avant **J3** | expert-comptable |
| **D4** | Régime de tenue des stocks par défaut (**intermittent** ou **permanent**) | avant **J4** | expert-comptable |
| **D5** | Obtention du **XSD DTS** (sinon DTS en EFI assisté) | avant **J6** | DGI / utilisateur |
| **D6** | Liste officielle des **pièces du greffe** + délai de dépôt | avant **J5** | greffe (1ʳᵉ adhésion) |
| **D7** | Obtention du **CDC e-facturation** (loi 43-20) | avant **J9** | DGI |
| **D8** | Format définitif de **`<prorata>`** (omis / pourcentage) | **J0** | expert-comptable + DGI |
| **D9** | Limite réelle de **`<ord>`** (127 ou plus) | **J0/J2** | DGI |
| **D10** | Sort des **3 lignes de frais bancaires à 27,50 DH HT** (comptabiliser ou non) | immédiat | expert-comptable |
| **D11** | **Référentiel `codeEdi` de la liasse** (table rubrique ↔ `codeEdi` dérivée des XSD officiels, ambiguïté A13) : validation comptable | avant **J7 étape 3** | expert-comptable |
| **D12** | **Durée et conditions du report déficitaire** (CGI art. 114, ambiguïté A21) | avant **J7 étape 3** | expert-comptable |
| **D13** | **Liste des charges non déductibles** à réintégrer (CGI art. 11, ambiguïté A20) | avant **J7 étape 3** | expert-comptable |
| **D14** | **Obtention du XSD de la liasse** (`liasse_modele_comptable simplifié.xsd` — présent) et du **XSD DTS** (`traitementSalaire.xsd`, manquant) | avant **J7 étape 3** | DGI / utilisateur |
| **D15** | **Cahier des charges e-facturation de la DGI** (loi 43-20 : format du fichier, canal d'échange, mentions, accusés) + **schéma XML** — **bloque la conformité** du module P2.3 (A24) | **dès publication par la DGI** | DGI / utilisateur |
| **D16** | **Correction des citations « CGI art. 106 »** (régularisation TVA des immobilisations → **art. 102 et 104-II-1°** ; mentions de facture → **art. 146**, l'**art. 145** traitant de la comptabilité) dans le module P1.2, les écrans et les documents remis au client (A23) | prochain correctif | expert-comptable (validation) |

### Annexe D — Suivi des versions du document

| Version | Date | Contenu |
|---|---|---|
| 1.0 | (session initiale) | `CAHIER_DES_CHARGES.md` : cadrage, phases 1→3, § 0 normatif |
| 2.0 | **22/09/2026** | **CDC GLOBAL** (`CAHIER_DES_CHARGES_GLOBAL.md`) : vision, architecture, modules P1/P2/P3, cohérence, référentiels, 8 écarts d'audit, feuille de route (80 j), stratégie de tests, annexes |
| 2.1 | **22/09/2026** | **Jalon J0 réalisé** (§ 9.7) : norme IF corrigée (**7 ou 8 chiffres, tel quel** — zfill supprimé), `<prorata>` en pourcentage, modes de paiement vérifiés (V4.0), limite de lignes paramétrable, **décision D1 = ReportLab** (POC mesuré), données de production corrigées, relevé T2 régénéré (**10 écarts, tous des IF**), suite de tests portée à **85/85** |
| 2.2 | **22/09/2026** | **Jalon J1 réalisé** (§ 9.8) : **export PDF complet** (bilan **brut / amortissements / net**, CPC, **ESG**, **ETIC**, factures + duplicata, bulletins, **bordereaux TVA et greffe**) sur moteur **ReportLab** ; nouveaux services `etats_synthese.py` et `pdf_documents.py` ; critère « montants identiques à l'écran au centime » vérifié par extraction du texte des PDF ; PDF **≤ 10 Mo** contrôlés ; mention **« PROVISOIRE »** tant que l'exercice n'est pas clôturé ; interface + API branchées ; suite de tests portée à **102/102** |
| 2.4 | **22/09/2026** | **Jalon J3 réalisé** (§ 9.10) : **P1.6 Audit & traçabilité** — **écart 9 corrigé** (la clôture génère l'**écriture d'à-nouveaux** de l'exercice suivant, journal `AN`, résultat au 1191/1199, règle anti double comptage des soldes), **verrouillage de période** (`period_locks`, refus dur en saisie/modification/suppression, déverrouillage motivé et tracé), **piste d'audit fiable** (empreinte **SHA-256** + chaînage par écriture, détection des altérations hors application, scellement des dossiers repris), **journal d'audit exploitable** (filtres, export CSV, **masquage loi 09-08**, navigation écriture ↔ pièce), **rapprochement bancaire** (import CSV, appariement auto/manuel, ajustements, état de rapprochement, alertes > 3 mois) ; migration `07e35b18ce2e` appliquée (sauvegarde production conservée) ; suite de tests portée à **155/155** |

| 2.3 | **22/09/2026** | **Jalon J2 réalisé** (§ 9.9) : **P1.2 Immobilisations & amortissements** — registre, plan d'amortissement, dotations, cessions, contrôles ; suite portée à **131/131** |
| 2.5 | **22/09/2026** | **Jalon J4 réalisé** (§ 9.11) : **P1.3 Stocks & inventaire permanent** — CUMP/FIFO, inventaire, dépréciations ; suite portée à **171/171** |
| 2.6 | **22/09/2026** | **Jalon J5 réalisé** (§ 9.12) : **P1.5 Dépôt au greffe du tribunal** — dossier et checklist paramétrables, amende « État Amender » (`6195`/`1515`), bordereau ; suite portée à **198/198** |
| 2.7 | **22/09/2026** | **Jalon J6 réalisé** (§ 9.13) : **P1.4 Paie & DTS « 9421 »** — salariés, contrats, bulletins, écritures de paie, livre de paie, DTS (XML, EFI, PDF, registre) ; suite portée à **221/221** |
| 2.7.1 | **22/09/2026** | **Correctif J6** (§ 9.13.1) : **DTS refondue sur le modèle officiel EDI V5.1** (racine `TraitementEtSalaire`, **sans namespace**, **3 listes PP/PO/STG**, totaux normalisés, `nom`/`prenom`) — ambiguïtés **A14 à A19** consignées ; suite maintenue à **221/221** |
| 2.8 | **22/09/2026** | **Jalon J7 — étape 1** (§ 9.14) : **P2.1 IS & liasse EDI** — **résultat fiscal** (réintégrations / déductions, hors IS non déductible), **IS vs cotisation minimale** (CGI art. 144) **due même en déficit**, **report déficitaire** (art. 114, sans durée en dur), acomptes **`3453`**, **contrôles** (exercice **clos** P1.6, concordance comptable ↔ fiscale) et **préparation de la réconciliation « Σ liasses = balance »** ; ambiguïtés **A13, A20, A21** consignées en § 8.2 ; annexes A, C et D mises à jour ; suite portée à **236/236** (`tests/test_fiscal_liasse.py`, 15 tests) |

| 2.9 | **22/09/2026** | **Jalon J7 — étape 2** (§ 9.15) : **assembleur de liasse** — tables **`liasse_tables`** / **`liasse_cells`** (migration additive `a7f3c51d8b42`), **contrat lu dans les XSD officiels** (racine `Liasse`, `modele/id` = 7, 24 tableaux, 1 328 `codeEdi` pour le modèle PME), **référentiel de codification éditable** (aucun code deviné), alimentation par la **balance définitive** et les modules **J2 / J3 / J6**, **EFI assisté par tableau** (CSV), contrôle « **Σ liasses = balance** », persistance dans le **registre `tax_declarations`** (brouillon, idempotent) ; référentiels installés dans `referentiels/liasse/` ; nouvelle ambiguïté **A22** (annexe DGI « Codification des cellules » non fournie) ; ambiguïté **A13 confirmée** (le `.xlsx` fourni est CbCR) ; § 8.2, annexes A et D mises à jour ; suite portée à **258/258** (`tests/test_liasse.py`, 22 tests) |

| 2.9.1 | **22/09/2026** | **Jalon J7 — étape 3** (§ 9.16) : **fichier XML EDI** conforme au schéma Simpl-IS (`build_liasse_xml()`), **validation XSD réelle** (lxml : conforme / refusé / validation impossible — jamais « présumé conforme »), `produire_liasse_xml()` (refus si bloquant ou refus du schéma), **API `/liasse`** (dossier, EFI, validation, XML, enregistrement, dépôt), **écran `/liasse`** (IS/CM, contrôles, cellules, EFI assisté, registre) et **accusé de réception** dans `tax_declarations` (soumise / acceptée / rejetée, empreinte SHA-256, audit) ; **P2.1 livré** (validation de la sémantique des `codeEdi` toujours attendue, A22) ; suite portée à **271/271** (`test_liasse.py` 32 tests, `test_api.py`, `test_web.py`) |

| 2.10 | **22/09/2026** | **Jalon J8 — P2.2 et P2.3** (§ 9.17 et § 9.18) : **cessation / cession d'activité** — table `activity_events` (migration additive `c4b8e17f2d95`), événements (cessation temporaire, cession, cessation) avec **régime TVA 3 / 4 et période 1** (annexe 1 RD V4.0), **délais CGI art. 114** (30 j), **art. 150-I** (45 j) et **art. 150 bis** (mois suivant la clôture), **TVA de la période de sortie**, **régularisation des déductions** (immobilisations via P1.2 ; stocks **saisis**), **relevé des déductions EDI** au régime 3/4 et **registre `tax_declarations`** avec accusé ; **e-facturation** — table `e_invoice_documents`, **17 mentions obligatoires** contrôlées (CGI art. 146, ICE, loi 15-95), fichier **interne** explicitement `non validée`, **canal DGI paramétrable** (simulation par défaut), cycle de vie (généré → transmis → **accepté / rejeté**) avec empreinte SHA-256 ; référentiel **`referentiels/tva/`** installé ; **nouvelles ambiguïtés A23** (citations d'articles erronées dans le CDC) et **A24** (CDC e-facturation absent) ; section « modules » et annexes A/C/D mises à jour ; suite portée à **300/300** (`test_activity_events.py` 16 tests, `test_e_invoice.py` 13 tests) |

> **Règle de mise à jour** : toute décision prise sur les écarts (§ 8) ou les ambiguïtés
> (§ 8.2) **doit être reportée dans ce document** à la version suivante, avec sa date et sa
> source. Un module qui ne respecte pas le présent cahier des charges **n'est pas
> réceptionné**.























