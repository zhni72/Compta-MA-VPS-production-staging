# P2 — Réorganisation du menu : plan d'implémentation préparé (aucune modification appliquée)

**Date** : 23/09/2026 · **Statut** : préparé, **non exécuté** (ordre de travail imposé : P1B v2 d'abord).
**Contraintes respectées par construction** : aucune URL métier existante modifiée, aucune redirection
nécessaire (toutes les routes actuelles sont conservées), **aucune permission changée**, **aucun
workflow modifié**, **aucune donnée comptable touchée**. Les écrans manquants sont **en lecture seule**
et s'appuient sur les services existants (aucune logique métier nouvelle).

## 1. Arborescence cible → routes existantes / écrans à créer

| # | Section | Entrée de menu | Route | État |
|---|---|---|---|---|
| 1 | Tableau de bord | Tableau de bord | `/` | existe |
| 2 | Comptabilité | Saisie des écritures | `/ecritures` | existe |
| 2 | | **Journal comptable** | `/etats/journal` | **existe — à rendre visible au menu (exigence)** |
| 2 | | Grand livre | `/etats/grand-livre` | existe (P2 : ajouter la colonne **Pièce/Référence**) |
| 2 | | Balance générale | `/etats/balance` | existe |
| 3 | États de synthèse | Bilan | `/etats/bilan` | existe |
| 3 | | CPC | `/etats/cpc` | existe |
| 3 | | ESG | `/etats/esg` | **à créer** (lecture seule : `etats_synthese.etat_soldes_gestion`) |
| 3 | | ETIC | `/etats/etic` | **à créer** (lecture seule : `etats_synthese.notes_etic` + `NOTES_INDISPONIBLES`) |
| 4 | Immobilisations | Fiches immobilisations | `/immobilisations` | existe |
| 4 | | Amortissements linéaires | `/immobilisations/etats?mode=lineaire` | existe (filtre d'affichage à ajouter) |
| 4 | | Amortissements dégressifs | `/immobilisations/etats?mode=degressif` | idem |
| 4 | | Cessions / sorties | `/immobilisations/etats?tableau=cessions` | existe (`tableau_cessions`) |
| 5 | Stocks & provisions | Articles | `/stocks` | existe |
| 5 | | Mouvements | `/stocks/mouvements` | **à créer** (lecture seule : `stocks.list_items` + mouvements) |
| 5 | | Inventaire | `/stocks/inventaire` | **à créer** (lecture seule : `stocks.inventaire_valorise`) |
| 5 | | Valorisation | `/stocks?vue=valorisation` | existe (`etat_stocks` CMUP/FIFO) |
| 5 | | **Provisions / dépréciations** | `/stocks/provisions` | **à créer** (lecture seule : `stocks.etat_provisions`) — **écran réel, pas seulement l'API** |
| 6 | Paie | Salariés | `/paie` | existe |
| 6 | | Bulletins | `/paie?vue=bulletins` | existe (`list_bulletins`) |
| 6 | | Cycles de paie | `/paie?vue=cycles` | existe (`get_run` / contrôles) |
| 6 | | Écritures de paie | `/etats/journal?journal=OD` | existe (journal filtré sur les écritures de paie) |
| 6 | | DTS / État 9421 | `/paie/dts.xml` · `/paie/dts.pdf` | existe |
| 7 | Fiscalité | TVA | `/tva` | existe |
| 7 | | Relevé des déductions TVA / EDI | `/tva/edi` | existe |
| 7 | | IS | `/liasse?year=…` | existe |
| 7 | | Liasse fiscale | `/liasse` | existe |
| 8 | Juridique / Greffe | Dossier de dépôt | `/greffe` · `/greffe/dossier` | existe |
| 8 | | PV d'AG | `/greffe/dossier?piece=pv_ag` | existe (pièces du dossier) |
| 8 | | Rapport de gestion | `/greffe/dossier?piece=rapport_gestion` | existe |
| 8 | | Paiement | `/greffe/{id}/paiement` | existe (action tracée) |
| 8 | | Certificat / récépissé | `/greffe/{id}/certificat` | existe |
| 9 | Clôture & cessation | Exercices comptables | `/parametres/exercices` | existe |
| 9 | | Clôture | `/parametres/exercices` (action) · `/parametres/exercices/{year}/cloturer` | existe (services P1) |
| 9 | | À-nouveaux | `/parametres/a-nouveaux` | **à créer** (lecture seule : `closing.controle_a_nouveaux`) |
| 9 | | Réouverture contrôlée | `/parametres/exercices` (action **encadrée** P1) | existe |
| 9 | | Verrouillage | `/parametres/exercices` (action tracée P1) | existe |
| 9 | | Cessation | `/activite` | **à créer** (lecture seule : `activity_events`) |
| 10 | E-facturation | Factures | `/factures?type=vente` | existe |
| 10 | | Avoirs | `/factures?type=vente&avoir=1` | existe (`is_credit_note`) |
| 10 | | Statuts de transmission | `/e-facturation` | **à créer** (lecture seule : `e_invoice_documents`) |
| 10 | | Rejets / réémission | `/e-facturation?statut=rejete` | à créer (même écran, filtre) |
| 11 | Audit & traçabilité | **Journal d'audit** (distinct du Journal comptable) | `/audit` | existe (P0 : API isolée, écran rétabli) |
| 11 | | Événements système | `/audit?entity=FiscalYear` | existe (filtres) |
| 11 | | Exports / téléchargements | `/audit/export` | existe |
| 11 | | Contrôles d'intégrité | `/audit/integrite` | **à créer** (lecture seule : chaînage `audit_trail.verifier_chainage`, verrous, provisions, trésorerie `controler_tresorerie`, source unique paie) |
| 12 | Paramètres | Fiche société | `/parametres/societe` | existe (P2 : dates de constitution / début d'exploitation) |
| 12 | | Plan comptable | `/comptes` | existe |
| 12 | | Journaux | `/parametres/journaux` | **à créer** (lecture seule : table `journals`) |
| 12 | | Utilisateurs / rôles | `/parametres/utilisateurs` | existe (RBAC inchangé) |
| 12 | | Référentiels fiscaux | `/parametres/referentiels` | **à créer** (lecture seule : `rates_ma.SOURCES_REFERENTIELS`, `IS_RATES_BY_YEAR`, `BAREMES_PAIE`, `CNSS_*`, `COTISATION_MINIMALE_*`) |
| 12 | | Référentiels EDI | `/parametres/referentiels?edi=1` | à créer (même écran : limites DGI `MAX_XML_BYTES`, `max_rd_lines`, XSD liasse, formats DTS) |

**Synthèse** : 6 écrans à créer (`/etats/esg`, `/etats/etic`, `/stocks/mouvements`, `/stocks/inventaire`,
`/stocks/provisions`, `/parametres/a-nouveaux`, `/activite`, `/e-facturation`, `/audit/integrite`,
`/parametres/journaux`, `/parametres/referentiels`) — tous **lecture seule**, réutilisant les services
existants ; 2 filtres d'affichage à ajouter (immobilisations par mode, journal par journal).

## 2. Exigences strictes — conformité du plan

| Exigence | Réponse |
|---|---|
| Journal comptable **visible** au menu | oui : entrée directe `/etats/journal` dans « Comptabilité » (aujourd'hui absente du menu) |
| Audit & traçabilité **distinct** du Journal comptable | oui : deux sections différentes (§ 2 vs § 11) ; l'entrée « Journal d'audit » reste `/audit` |
| Stocks **et** Provisions = écrans réels | oui : `/stocks/provisions` (liste des dépréciations, base, valeur d'inventaire, dotation) et `/stocks/inventaire`, `/stocks/mouvements` — plus seulement l'API |
| Bilan / CPC / ESG / ETIC sous États de synthèse | oui : § 3 ; ESG et ETIC créés (ils n'existent aujourd'hui qu'en PDF) |
| TVA / IS / Liasse sous Fiscalité | oui : § 7 |
| Greffe et Clôture séparés mais cohérents | oui : § 8 (juridique) et § 9 (clôture/cessation), avec renvois croisés (le dossier de dépôt référence l'exercice clos) |
| Aucune URL métier changée sans redirection contrôlée | **aucune URL changée** : le plan **ajoute** des écrans et déplace seulement des **libellés de menu** ; aucune redirection nécessaire |
| Aucune permission changée | les écrans ajoutés restent sous **session web** (comme les écrans existants) ; les **actions** (valider, clôturer, verrouiller, déposer, payer) conservent leurs rôles existants (`ADMIN`, `EXPERT_COMPTABLE`) — aucune modification RBAC |
| Aucun workflow changé | les services et transitions ne sont pas touchés : le menu n'est qu'une navigation |
| **Smoke tests de navigation** | plan : un test paramétré par entrée de menu (≈ 60 liens) qui se connecte, appelle **chaque URL** et exige 200 ou 303 (jamais 4xx/5xx) ; les 2 filtres ajoutés sont testés dans le même balayage ; les familles de rôles sont vérifiées par un test dédié (écrans accessibles en `LECTEUR`, actions interdites) |

## 3. Ordre d'exécution proposé (P2)

1. **Menu** (base.html) : les 12 sections, entrée « Journal comptable » visible, sections vides masquées
   si le module n'est pas livré (aucune entrée morte).
2. **Écrans lecture seule** dans cet ordre : `Provisions` (exigence explicite), `À-nouveaux`,
   `Contrôles d'intégrité`, `Référentiels fiscaux` (valorise les sources P1B), `ESG`, `ETIC`,
   `Mouvements`/`Inventaire`, `Journaux`, `E-facturation`, `Activité`.
3. **Filtres d'affichage** : immobilisations par mode, journal par code de journal.
4. **Smoke tests de navigation** + test des permissions par rôle.
5. **Corrections fonctionnelles restantes** (traçables, chacune avec test de non-régression) :
   - reclassement **immobilisations** (2340 → `2332`/`23324` outillage, `2355` informatique) ;
   - **TVA sur immobilisations** (`34551` vs `34552` du jeu) ;
   - colonne **Pièce / Référence** au grand livre ;
   - **formulaire nouvel exercice** : proposer le premier exercice libre, interdire tout doublon ;
   - **`payments.entry_id`** : rattacher les règlements à leur ligne d'écriture ;
   - **liasse / DTS** : finaliser les sources manquantes et la publication EDI ;
   - **contrôles de navigation et permissions** (couverture de tous les écrans × rôles).

Chaque correction de données sera **tracée** (piste d'audit) et **jamais silencieuse**, avec un test
de non-régression reproduisant le défaut — comme pour P0 et P1.

