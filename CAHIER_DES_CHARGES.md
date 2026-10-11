# Cahier des charges — Application de comptabilité marocaine (type Sage)

## 0. Règle permanente du projet

> **L'application doit être réalisée conformément aux normes comptables marocaines
> (CGNC / PCGE) et aux normes de la Direction Générale des Impôts (DGI).**
> Toute évolution est vérifiée contre ces référentiels, et la conformité fiscale
> prime sur toute considération ergonomique ou technique.

> 📘 **Document de référence à jour : `CAHIER_DES_CHARGES_GLOBAL.md` (CDC GLOBAL v2.0)** —
> vision produit, architecture cible, modules **P1** (PDF, immobilisations, stocks, paie/DTS,
> dépôt greffe, audit & traçabilité), **P2** (IS/liasse EDI, cessation-cession, e-facturation),
> **P3**, mécanisme de cohérence inter-modules, référentiels normatifs, **8 écarts d'audit**
> et feuille de route chiffrée. Le présent document v1.0 reste la référence du cadrage initial.

**Référentiels normatifs de référence (à jour dans le projet) :**

| Domaine | Document / source | Usage dans le code |
|---|---|---|
| Comptabilité | CGNC — Code Général de Normalisation Comptable + plan de comptes PCGE | `app/data/plan_comptable_cgnc.csv` (890 comptes), contrôle de la codification décimale |
| Fiscalité directe | Code Général des Impôts, Loi de Finances 2026 | `app/core/rates_ma.py` (IS 20/35/40 %, cotisation minimale, CSS) |
| TVA | CGI art. 99-A / 99-B (taux 20 % et 10 % depuis le 01/01/2026) | taux historisés en base (`vat_rates`), déclaration et ventilation |
| Formalisme des factures | CGI art. 145 (ICE obligatoire, mentions légales, numérotation continue) | `app/services/invoicing.py`, gabarits d'impression |
| **EDI TVA** | **Annexe « Correspondance des balises RD » V4.0** + **modèle officiel DGI « ADC082F-15I » (art. 112 du CGI) et son schéma XSD** (fichier de référence `TVA-EDI.xlsm`) | `app/services/edi_tva.py` : balises, types, ordre, `<tx>` en pourcentage, **IF sur 7 ou 8 chiffres utilisé tel quel** |
| EDI (général) | Cahier des charges EDI Simpl-IS v1.0 | contrôles de format : XML (jamais ZIP), taille ≤ 1 Mo, IF du déclarant |
| Social | CNSS / AMO 2026, arrêté n° 1314.25, Code du travail | barèmes et plafonds paramétrables |
| Données personnelles | Loi 09-08 (CNDP) | chiffrement, journalisation, conservation 10 ans |

---


> **Nom de projet :** Compta MA
> **Version du document :** 1.0
> **Périmètre :** comptabilité générale + facturation CGNC, mono-utilisateur d'abord, multi-utilisateurs ensuite sur serveur distant
> **Stack imposée :** Python
> **Statut :** brief de cadrage (à valider par un expert-comptable avant mise en production)

---

## 1. Contexte et objectifs

Application de comptabilité et de facturation conforme à la réglementation marocaine
(CGNC / PCGE, CGI, CNSS), équivalente fonctionnellement aux logiciels de type **Sage**
pour une PME, un cabinet comptable ou un indépendant.

Trois objectifs structurants :

1. **Phase 1 — Mono-utilisateur / mono-poste.** Un comptable tient une ou quelques
   sociétés sur son poste : plan comptable, tiers, factures, écritures, TVA, balance,
   bilan, CPC. Base SQLite, aucune infrastructure serveur.
2. **Phase 2 — Multi-utilisateurs.** Plusieurs utilisateurs simultanés, plusieurs
   dossiers (sociétés), rôles et permissions, piste d'audit, clôture et verrouillage
   des exercices. Base PostgreSQL.
3. **Phase 3 — Déploiement distant.** Application conteneurisée (Docker), servie en
   HTTPS, sauvegardes automatiques, supervision, connecteur de facturation
   électronique DGI.

**Contrainte majeure :** le passage mono → multi-utilisateurs ne doit entraîner
**aucune réécriture métier**. Il se traduit par un changement de `DATABASE_URL`,
l'activation de l'authentification et l'ajout des écrans d'administration.

---

## 2. Périmètre fonctionnel

| Module | Contenu attendu | Phase |
|---|---|---|
| Dossier / société | Raison sociale, ICE, IF, RC, patente, n° CNSS, adresse, régime TVA (mensuel/trimestriel), exercice | 1 |
| Plan comptable | PCGE / CGNC complet : comptes 4 chiffres obligatoires, divisionnaires 5 chiffres, sous-comptes libres | 1 |
| Tiers | Clients, fournisseurs, salariés ; conditions de paiement ; ICE obligatoire sur facture | 1 |
| Achats / Ventes | Devis → commande → bon de livraison → facture, avoirs, multi-taux de TVA, mentions légales | 1 |
| Règlements | Espèces, chèque, virement, effets ; lettrage, relances, balance âgée | 1 |
| Saisie comptable | Journaux (AC, VE, BQ, CA, OD), contrôle d'équilibre, brouillon → validé, contre-écriture | 1 |
| TVA | TVA facturée (4455), TVA récupérable (3455), prorata, RST TVA, déclaration TVA /10 %-20 % | 1 |
| États de synthèse | Balance, grand livre, journaux, Bilan, CPC (modèle normal et simplifié) | 1 |
| Immobilisations | Amortissements linéaire / dégressif, VNA, cessions | 2 |
| Paie | Brut → net : IR, CNSS/AMO, TFP, bulletins, livre de paie | 2 |
| Stock | Dépôts, entrées/sorties, CUMP/FIFO, inventaire | 2 |
| Fiscal annuel | IS, cotisation minimale, CSS, 4 acomptes, liasse fiscale (export EDI) | 2 |
| Facturation électronique | Connecteur DGI, génération UBL 2.1, cycle de validation (clearance) | 3 |

**Interface graphique (livrée en phase 1).** L'application comporte une interface de
gestion **en français**, conforme aux usages des logiciels comptables marocains
(Sage, Ciel) : bandeau avec dossier et utilisateur, navigation latérale par domaine,
fil d'Ariane, tableaux denses, filtres, badges d'état, montants au format
`1 234 567,50 DH` et dates `JJ/MM/AAAA`.

| Domaine | Écrans |
|---|---|
| Tableau de bord | KPI (résultat, charges, TVA de la période, trésorerie, créances, dettes), échéance TVA, dernières factures, factures non réglées, alertes de conformité (ICE manquant) |
| Commerce | Clients & fournisseurs (fiche + grand livre + documents), factures de vente / d'achat, avoirs, règlements |
| Comptabilité | Saisie des écritures avec contrôle d'équilibre en direct, journal comptable, plan comptable PCGE |
| États | Balance générale (avec récapitulatif par classe du CGNC), grand livre, CPC, bilan (contrôle d'équilibre affiché) |
| Fiscalité | Déclaration de TVA : collectée, déductible, net à payer ou crédit à reporter, échéance du 20, ventilation par taux, barème en vigueur |
| Paramètres | Fiche société (mentions légales), exercices (ouvrir / clôturer / verrouiller), utilisateurs & rôles (matrice des droits) |

L'interface et l'API partagent **exactement les mêmes services métier** : aucune règle
comptable n'est dupliquée, les contrôles (équilibre, immuabilité, ICE, exercice clos)
s'appliquent identiquement quelle que soit la voie d'accès.

**Référentiel de comptes.** Le plan comptable embarqué (`app/data/plan_comptable_cgnc.csv`,
**890 comptes**) est extrait du **plan comptable marocain officiel** remis par le client
(`Plan_Comptable_Marocain.pdf`, 24 pages, classes 0 à 9). Le convertisseur
`tools/plan_pdf_to_csv.py` reproduit la hiérarchie rubrique (2 chiffres) / poste
(3 chiffres) / compte principal (4 chiffres) / divisionnaire (5-6 chiffres) et
écarte les faux positifs (numéros de page, dates) en vérifiant l'existence du poste
**ou, à défaut, de la rubrique parente** (le plan officiel omet parfois la ligne du
poste : `2441`, `51231`, `7591x`, `91957`, `9396`, `011x`, et imprime des postes
groupés : « `613/614` Autres charges externes », « `294/295` »). Les comptes de
regroupement `3421`, `4411` et `3455` sont marqués **collectifs** : la saisie
s'effectue sur leurs divisionnaires. Ce plan doit être **validé et complété par
l'expert-comptable** du dossier avant mise en production.

**Export EDI (relevé des déductions TVA).** L'application produit le fichier XML à
déposer sur le téléservice, **validé contre le schéma XSD officiel de la DGI**
(modèle EDI « ADC082F-15I », article 112 du CGI, fichier de référence
`TVA-EDI.xlsm`) :

- ordre des balises **imposé** par le schéma : `DeclarationReleveDeduction` →
  `identifiantFiscal`, `annee`, `periode`, `regime`, `releveDeductions` → `rd`
  (`ord`, `num`, `des`, `mht`, `tva`, `ttc`, `refF` → `if`, `nom`, `ice`, `tx`,
  `mp` → `id`, `dpai`, `dfac`) ;
- **`<tx>` exprimé en pourcentage** (`<tx>20</tx>`), unité confirmée par un
  exemple accepté par la DGI (le mode ratio `0.20` reste disponible) ;
- **`<prorata>` n'est pas déclarée dans le XSD** : la balise est **omise par
  défaut** ; si elle est activée, elle est écrite **en pourcentage**, comme
  l'exemple officiel de la DGI (`<prorata>70</prorata>`) ;
- **identifiant fiscal (IF) sur 7 ou 8 chiffres, utilisé TEL QUEL** :
  `1086826` reste `1086826`, `1084612` reste `1084612` (l'ancienne règle de
  complément à 8 chiffres est **supprimée** : elle produisait un identifiant
  différent de celui attribué par la DGI) ;
- `<ord>` et `<mp><id>` étant déclarés en `xs:byte` dans le XSD (annexe V4.0 :
  « Entier »), la **limite de lignes est paramétrable** (`settings.max_rd_lines`,
  défaut prudent **127**) ;
- contrôles bloquants : IF du déclarant, cohérence `regime`/`periode`, ICE
  (15 chiffres) et IF de chaque fournisseur, absence de doublon, refus du fichier
  vide, taille ≤ 1 Mo, dates AAAA-MM-JJ, décimaux avec le point, caractères XML
  invalides filtrés. Les avoirs sont repris en **déduction négative** et les
  lignes à TVA nulle sont écartées du relevé.

**Schéma XSD officiel retenu** (extrait du modèle DGI `TVA-EDI.xlsm`,
`xl/xmlMaps.xml` — c'est la référence de validation à conserver) :

```xml
<xs:element name="DeclarationReleveDeduction">
  <xs:sequence>
    <xs:element type="xs:int"   name="identifiantFiscal"/>   <!-- IF : 7 ou 8 chiffres, tel quel -->
    <xs:element type="xs:short" name="annee"/>               <!-- 2026 -->
    <xs:element type="xs:byte"  name="periode"/>              <!-- 1..12 -->
    <xs:element type="xs:byte"  name="regime"/>               <!-- 1 = encaissement, 2 = débit -->
    <xs:element name="releveDeductions"><xs:sequence>
      <xs:element name="rd" minOccurs="0" maxOccurs="unbounded"><xs:sequence>
        <xs:element type="xs:byte"   name="ord"/>             <!-- 1..127 (byte) -->
        <xs:element type="xs:string" name="num"/>
        <xs:element type="xs:string" name="des"/>
        <xs:element type="xs:float"  name="mht"/>
        <xs:element type="xs:float"  name="tva"/>
        <xs:element type="xs:float"  name="ttc"/>
        <xs:element name="refF"><xs:sequence>
          <xs:element type="xs:int"    name="if"/>            <!-- IF fournisseur : 7 ou 8 chiffres -->
          <xs:element type="xs:string" name="nom"/>
          <xs:element type="xs:string" name="ice"/>           <!-- 15 chiffres -->
        </xs:sequence></xs:element>
        <xs:element type="xs:float"  name="tx"/>              <!-- pourcentage : 20 -->
        <!-- <prorata> : NON déclarée dans le schéma -->
        <xs:element name="mp"><xs:sequence>
          <xs:element type="xs:byte" name="id"/>              <!-- 1..7 (Annexe 1) -->
        </xs:sequence></xs:element>
        <xs:element type="xs:date" name="dpai"/>              <!-- AAAA-MM-JJ -->
        <xs:element type="xs:date" name="dfac"/>              <!-- AAAA-MM-JJ -->
      </xs:sequence></xs:element>
    </xs:sequence></xs:element>
  </xs:sequence>
</xs:element>
```

Conséquences appliquées : ordre des balises imposé (`xs:sequence`), `<tx>` en
**pourcentage** (`xs:float` accepte `20`), `<prorata>` **absente du schéma**
(omise par défaut), `<ord>` en `xs:byte` ⇒ **127 lignes maximum** par fichier.

---

## 3. Exigences réglementaires (vérifiées — exercice 2026)

### 3.1 Référentiel comptable
- **CGNC** : code général de normalisation comptable, 8 classes : 1 à 5 (bilan),
  6 à 8 (CPC et résultats).
- **PCGE** : codification décimale, clsse 1 chiffre (masse), 2 (rubrique),
  3 (poste), 4 (compte principal — obligatoire), 5 (divisionnaire — recommandé),
  6 et plus (sous-compte — libre).
- Exercice comptable des sociétés : **année civile**.
- Conservation des pièces et documents : **10 ans**.

### 3.2 TVA — barème 2026 : deux taux
| Taux | Application |
|---|---|
| **20 %** | Taux normal (par défaut), électricité réseau, transport non urbain (LF 2026) |
| **10 %** | Eau, sucre raffiné, transport routier/urbain, électricité renouvelable, restauration, hôtellerie, opérations bancaires, finance participative |
| **0 % (exonéré)** | Export, médicaments, fournitures scolaires, santé, éducation, produits agricoles de base |

Les taux de 7 % et 14 % sont **supprimés** (convergence achevée au 01/01/2026).
→ Les taux doivent être **stockés en base et historisés par date de validité**,
jamais codés en dur.

- Déclaration **mensuelle** si CA ≥ 1 000 000 MAD, **trimestrielle** en dessous.
- Échéance : **le 20** du mois suivant (mensuel) ou du mois suivant le trimestre.
- Dépôt et paiement via **SIMPL-TVA** (portail DGI).
- TVA nette = TVA collectée − TVA déductible ; crédit de TVA reportable ou
  remboursable.
- **Retenue à la source TVA** applicable sur certaines opérations (client public ou
  grande entreprise) : à gérer comme un paramètre de facture.

#### 3.2 bis TVA déductible — règles appliquées (vérifiées)

| Règle | Source normative | Mise en œuvre |
|---|---|---|
| Ventilation de la TVA récupérable | CGNC/PCGE : `34551` « TVA récupérable sur immobilisations », `34552` « TVA récupérable sur charges » | `services/invoicing.py` : compte retenu selon la classe du compte de dépense (classe 2 → 34551, sinon 34552) |
| Rattachement de la période | Modèle DGI « ADC082F-15I » (art. 112 du CGI), colonne « REGIME(Encais-1) » : la déduction s'exerce au règlement | période du relevé = **date de paiement** par défaut, option date de facture ; une facture réglée en plusieurs fois est déduite **par incréments** (aucun double emploi entre périodes) |
| Lignes exonérées | Une TVA nulle ne se déduit pas et ne figure jamais au relevé | lignes à TVA nulle **écartées et tracées** ; le tableau d'achat les exclut à l'import |
| Prorata de déduction | CGI art. 106 (activités exonérées) | champ « Prorata de déduction (%) » ; la balise `<tva>` porte la fraction réellement déductible |
| Comptes de charge | PCGE : `6147` « Services bancaires », `61473` « Frais et commissions sur services bancaires » | mapping de correction `6141` → `61473` dans l'outil d'import et dans les tests |
| Régularisation | CGI art. 106-III (immobilisations, changement d'activité) | **hors périmètre v1** : régularisation à opérer par déclaration rectificative, à valider avec l'expert-comptable |

### 3.3 IS — impôt sur les sociétés 2026
| Catégorie | Taux |
|---|---|
| Bénéfice net fiscal < 100 M MAD | **20 %** |
| BNF > 100 M MAD | **35 %** |
| Banques, assurances, réassurance, BAM, CDG | **40 %** |
| Casablanca Finance City / Zones d'accélération industrielle | **20 %** |

- **Cotisation minimale** : 0,25 % du CA TTC, plancher **3 000 MAD**,
  exonération sur les 36 premiers mois d'activité.
- **CSS** sur bénéfices : 1,5 % (1-5 M), 2,5 % (5-10 M), 3,5 % (10-40 M), 5 % (> 40 M).
- **4 acomptes** provisionnels trimestriels.

### 3.4 IR — paie (barème 2026)
| Tranche de revenu net annuel (MAD) | Taux | Somme à déduire |
|---|---|---|
| 0 — 40 000 | 0 % | 0 |
| 40 001 — 60 000 | 10 % | 4 000 |
| 60 001 — 80 000 | 20 % | 10 000 |
| 80 001 — 100 000 | 30 % | 18 000 |
| 100 001 — 180 000 | 34 % | 22 000 |
| > 180 000 | **37 %** | 27 400 |

- Frais professionnels : 35 % du brut si brut annuel ≤ 78 000 MAD (plafond 30 000),
  sinon 25 % (plafond 35 000).
- Charges de famille : 600 MAD par personne à charge, maximum 6 personnes.

### 3.5 CNSS / AMO 2026
| Branche | Part salariale | Part patronale | Plafond |
|---|---|---|---|
| Prestations sociales (CNSS) | 4,48 % | 8,98 % | 6 000 MAD/mois |
| AMO | 2,26 % | 4,11 % | sans plafond |
| Allocations familiales | — | 6,40 % | sans plafond |
| TFP (taxe formation professionnelle) | — | 1,60 % | sans plafond |
| **Total** | **6,74 %** | **21,09 %** | — |

- Télédéclaration et télépaiement **Damancom** obligatoires (sans condition d'effectif).
- Depuis le 01/10/2025 (arrêté n° 1314.25) : liste d'indemnités exclues de l'assiette
  (ex. transport domicile-travail : 500 MAD/mois en périmètre urbain, 750 MAD hors
  périmètre). Les plafonds doivent être paramétrables.

### 3.6 Facture de vente — mentions obligatoires
- Identification : raison sociale, adresse, **ICE**, **IF**, **RC**, n° patente/TP,
  n° CNSS (le cas échéant).
- **Numérotation séquentielle continue, sans trou**, par société et par exercice.
- Date, désignation, quantité, prix unitaire HT, taux de TVA, montant de TVA, total TTC.
- Conditions et mode de règlement, échéance.
- L'**ICE est obligatoire** sur les factures B2B (sanction pécuniaire prévue par le CGI
  en cas d'absence — montant à confirmer avec l'expert-comptable).
- Impression : facture originale + duplicata (mention légale), et non pas « double ».

### 3.7 Facturation électronique (art. 145 CGI, LF 2024 ; loi 43-20)
- Déploiement **par vagues selon la taille** : opérations avec l'État et grandes
  entreprises **CA > 200 M MAD dès 2026** ; PME et ETI **2027-2028** ; TPE **après
  2028** via des solutions simplifiées.
- **Le décret d'application et la spécification technique ne sont pas publiés** :
  la date exacte doit être vérifiée sur `tax.gov.ma`.
- Modèle annoncé : **clearance** (validation préalable des factures par la plateforme).
- Formats à préparer : **UBL 2.1 / XML**, signature électronique (lois 43-20 et 53-05),
  PDF signé.
- **Ne pas confondre** avec SIMPL-TVA, qui est le portail de télédéclaration fiscale.
- → Conséquence d'architecture : isoler tout cela dans un **module « connecteur »
  interchangeable**, pour absorber la spécification officielle sans refonte.

### 3.8 Données personnelles
Loi **09-08** et déclaration **CNDP** : minimisation, chiffrement, journal d'accès,
durée de conservation, droit d'accès et de rectification des salariés et des tiers.

---

## 4. Architecture technique

### 4.1 Stack Python retenue
| Couche | Choix | Justification |
|---|---|---|
| Langage | Python 3.12+ | exigence du client |
| API / web | **FastAPI** + Pydantic | typé, rapide, OpenAPI automatique, prêt pour le multi-utilisateur |
| ORM | **SQLAlchemy 2.0** (style typé `Mapped`) | abstrait SQLite **et** PostgreSQL sans changement de code |
| Migrations | **Alembic** | versionnement du schéma, indispensable en production |
| Base | **SQLite** (phase 1) → **PostgreSQL** (phases 2-3) | pilote `psycopg` |
| Tâches de fond | RQ ou Celery + Redis | e-mails, états, exports volumineux |
| PDF | WeasyPrint | factures et états de synthèse |
| Excel / EDI | openpyxl | exports comptables et liasse fiscale |
| Front | Jinja2 + HTMX, puis React si besoin | léger, rapide à livrer |
| Déploiement | Docker Compose + Nginx + HTTPS | phase 3 |
| Tests | pytest (+ httpx) | validation exigée |

### 4.2 Règles d'or du passage mono → multi-utilisateurs
1. **Un seul accès aux données** (couche services). Le basculement SQLite →
   PostgreSQL se fait par `DATABASE_URL`, sans code conditionnel.
2. **Aucun état en mémoire locale**, aucun chemin de fichier en dur : le stockage des
   pièces jointes passe par une abstraction (`local` en phase 1, S3/MinIO en phase 3).
3. **Multi-tenant dès le jour 1** : chaque table métier porte `company_id` et
   `fiscal_year_id`. C'est ce qui évite toute reprise de données en phase 2.
4. **Concurrence** : verrouillage optimiste (`row_version`), transactions courtes,
   numérotation protégée par `SELECT … FOR UPDATE`.
5. **Piste d'audit dès la phase 1** : obligatoire en comptabilité et impossible à
   reconstituer a posteriori.

### 4.3 Sécurité (phases 2 et 3)
Mot de passe haché en **Argon2id**, jeton JWT, sessions révocables, **RBAC**,
limitation de débit, 2FA optionnelle, HTTPS obligatoire, journal d'audit inaltérable
(utilisateur, action, entité, horodatage, adresse IP).

### 4.4 Rôles et permissions
| Rôle | Droits principaux |
|---|---|
| Administrateur | tout, création de sociétés et d'utilisateurs |
| Expert-comptable | validation, clôture, verrouillage d'exercice, tous les états |
| Comptable | saisie, factures, règlements, états |
| Caissier | règlements et journal de caisse uniquement |
| Commercial | devis, commandes, factures clients (pas d'écriture comptable) |
| Lecteur / Auditeur | lecture seule, exports |

**Cycle d'exercice :** `open` → `closed` → `locked`. Toute écriture sur un exercice
clos est refusée ; seule une réouverture par l'expert-comptable, tracée dans l'audit,
est possible.

---

## 5. Modèle de données (tables principales)

`companies`, `fiscal_years`, `users`, `roles`, `user_company_roles`,
`accounts` (plan comptable), `journals`, `third_parties`, `invoices` +
`invoice_lines`, `payments`, `entries` + `entry_lines`, `vat_rates` (historisés),
`vat_returns`, `assets` + `depreciations`, `payroll_runs` + `payslips`,
`items` + `stock_moves`, `numbering_sequences`, `audit_log`, `attachments`.

**Contraintes comptables structurantes :**
- Une écriture validée est **immuable** : correction uniquement par **contre-écriture**.
- Équilibre débit = crédit vérifié avant validation.
- Numérotation continue : un document annulé **conserve son numéro** (jamais réutilisé).
- Comptes de TVA imposés : **4455** (facturée), **3455** (récupérable — 34551
  immobilisations / 34552 charges), **4456** (TVA due).
- Tiers : clients **3421**, fournisseurs **4411**, banque **5141**, caisse **5161**,
  ventes **7111**.

---

## 6. Exigences non fonctionnelles

| Domaine | Exigence |
|---|---|
| Performance | affichage d'un écran < 1 s avec 100 000 écritures ; balance sur un exercice < 3 s |
| Fiabilité | transactions ACID, aucune écriture partielle, contrôles d'intégrité |
| Sauvegardes | quotidiennes automatiques + restauration testée ; export mensuel hors site |
| Traçabilité | piste d'audit complète et inaltérable sur toute opération comptable |
| Sécurité | Argon2id, HTTPS, RBAC, moindre privilège, secrets hors du code |
| Ergonomie | interface 100 % français, libellés comptables marocains, raccourcis clavier de saisie |
| Interopérabilité | exports PDF, Excel, CSV, EDI (liasse), UBL 2.1 (e-facturation) |
| Maintenabilité | code typé, migrations Alembic, tests automatisés, documentation |
| Conformité | CGNC, CGI 2026, CNSS 2026, loi 09-08 (CNDP), conservation 10 ans |
| Disponibilité | 99 % en phase 3, supervision et alertes |

---

## 7. Livrables et jalons

| Phase | Contenu | Durée indicative |
|---|---|---|
| **1 — MVP mono-utilisateur** | Interface graphique française (tableau de bord, commerce, comptabilité, états, fiscalité, paramètres), plan comptable PCGE, tiers, factures/avoirs, écritures et journaux, TVA, balance, grand livre, bilan/CPC, SQLite, tests | 6 à 8 semaines |
| **2 — Multi-utilisateurs** | PostgreSQL, authentification + RBAC, piste d'audit, clôture et verrouillage, paie, immobilisations, stock, IS/liasse | 4 à 6 semaines |
| **3 — Serveur distant** | Docker Compose, Nginx + HTTPS, sauvegardes S3, supervision, connecteur de facturation électronique | 2 à 3 semaines |

**Livrables par phase :** code source, migrations, jeu de tests, documentation
d'installation et d'exploitation, procédure de sauvegarde/restauration, guide
utilisateur, PV de recette.

---

## 8. Critères d'acceptation (extraits)

1. Une écriture déséquilibrée est **refusée**.
2. Après annulation d'une facture, la **numérotation reste continue, sans trou** et le
   numéro n'est jamais réutilisé.
3. Une facture de vente avec TVA 20 % et une ligne à 10 % génère les écritures
   correctes : **3421 débit TTC**, **7111 crédit HT**, **4455 crédit TVA** (séparée par
   taux) ; une facture d'achat génère **6111/3455 débit**, **4411 crédit TTC**.
4. La déclaration de TVA (mensuelle ou trimestrielle) est conforme au récapitulatif des
   journaux : collectée, déductible, net à payer ou crédit reportable.
5. Le **bilan est équilibré** et le résultat du **CPC** égale le solde de l'exercice.
6. Une facture de vente à un client professionnel **sans ICE est bloquée**.
7. Deux utilisateurs modifiant simultanément la même facture : le conflit est détecté
   proprement (verrouillage optimiste), sans écrasement silencieux.
8. Toute modification d'une écriture validée est impossible ; la correction passe par
   une contre-écriture référencée.
9. Aucune donnée n'est perdue après restauration d'une sauvegarde.
10. `pytest` passe intégralement sur l'ensemble des services métier.

---

## 9. Risques et points de vigilance

| Risque | Impact | Mitigation |
|---|---|---|
| Décret e-facturation non publié | refonte tardive | module « connecteur » isolé, export UBL 2.1 dès maintenant |
| Barèmes fiscaux modifiés chaque année (LF) | calculs faux | taux en base, historisés par date de validité, jamais en dur |
| Piste d'audit oubliée en phase 1 | non-conformité | implémentée dès le MVP |
| Concurrence d'accès (phase 2) | pertes de données | verrouillage optimiste + transactions courtes |
| Numérotation non continue | rejet fiscal | séquence verrouillée en base, numéro attribué à la validation |
| Sauvegardes non testées | perte définitive | restauration testée mensuellement |
| Hébergement des données (CNDP / RGPD) | risque juridique | chiffrement, localisation, contrat de sous-traitance, CNDP |
| Validation par un expert-comptable | états rejetés | recette fonctionnelle avec un expert-comptable agréé |

---

## 10. Hors périmètre (v1)

Comptabilité analytique avancée, consolidation groupe, IFRS, gestion de production,
CRM, e-commerce, application mobile, portail client. Ces sujets pourront faire l'objet
d'une v2 après validation du socle comptable.

---

*Document de cadrage — les taux et obligations cités correspondent à l'exercice 2026
(Loi de Finances 50-25, CGI, barèmes CNSS). Toute mise en production doit être validée
par un expert-comptable agréé au Maroc.*