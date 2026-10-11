# Référentiels de la liasse fiscale (P2.1 — Simpl-IS)

Ce dossier contient **tout ce qui est nécessaire pour produire la liasse fiscale
au format EDI** :

| Fichier | Rôle |
|---|---|
| `liasse_modele_normal.xsd` | Schéma officiel DGI — modèle **normal** (modele id **7** dans le fichier XSD) |
| `liasse_modele_comptable simplifié.xsd` | Schéma officiel DGI — **comptable simplifié** (cible PME) |
| `liasse_modele_Assurances.xsd` | Schéma officiel DGI — assurances |
| `liasse_modele_établissements de crédit.xsd` | Schéma officiel DGI — établissements de crédit |
| `codification_liasse.csv` | **Table de correspondance** `codeEdi` ↔ rubrique de l'application (à compléter par l'expert-comptable) |

## Ce que le XSD contient — et ce qu'il ne contient pas

Chaque XSD déclare :

- la **racine** du fichier (`Liasse`) et son **entête** `modele/id` (valeur **fixée**
  par le schéma) + `resultatFiscal` (`identifiantFiscal`, `exerciceFiscalDu`,
  `exerciceFiscalAu`) ;
- les **identifiants de tableau** autorisés (`tableau/id`, énumération **fermée**) ;
- les **`codeEdi` de cellule** autorisés (`cellule/codeEdi`, énumération **fermée**) ;
- les **codes d'`extraField`** autorisés et le type des valeurs (`valeur` = chaîne,
  `numeroLigne` = entier).

En revanche, **le XSD ne porte aucun libellé** : il dit *quels* codes sont légaux,
**pas** à quelle rubrique de la liasse (et donc à quel compte) chacun correspond.
Cette sémantique est publiée par la DGI dans l'annexe « **Codification des
cellules** » et « **Codification des modèles et tableaux des Liasses** », qui
**n'est pas fournie** avec le référentiel technique actuel (voir CDC § 8.2,
ambiguïté **A22**). Le `réferentiel des codifications.xlsx` livré à côté est, lui,
le référentiel **CbCR** (pays par pays) et ne concerne pas la liasse.

## Conséquence : la correspondance est un référentiel **éditable**

L'application ne **devine jamais** un `codeEdi`. Elle :

1. **déduit du XSD** les codes légaux du modèle choisi (contrôle bloquant si un code
   du référentiel n'appartient pas au schéma : `liasse.code_hors_schema`) ;
2. **remplit** les cellules dont la rubrique est décrite dans `codification_liasse.csv` ;
3. produit l'**EFI assisté** (état de saisie par tableau, `codeEdi` + libellé + valeur)
   pour permettre la saisie sur le téléservice SIMPL tant que le fichier EDI n'est pas
   validé par l'annexe officielle.

## Format de `codification_liasse.csv`

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `modele` | oui | Nom du fichier XSD **sans extension** (ex. `liasse_modele_comptable simplifié`) |
| `tableau_id` | oui | Identifiant de tableau **du schéma** (ex. `61`) |
| `tableau_libelle` | non | Libellé du tableau (repris tel quel dans l'EFI et l'écran) |
| `code_edi` | oui | Code cellule **du schéma** (ex. `4562`) |
| `rubrique` | oui | Rubrique alimentée par l'application (voir la liste ci-dessous) |
| `libelle` | non | Libellé DGI de la cellule (recopié de l'annexe « Codification des cellules ») |
| `numero_ligne` | non | Numéro de ligne (`numeroLigne`) pour les tableaux à lignes répétées |
| `extra_field` | non | Code `extraField` associé (`code` du schéma) |
| `origine` | non | **Source de la correspondance** (annexe DGI, validation expert-comptable, date…) |

### Rubriques disponibles (fournies par l'application)

- `solde:<compte>` : solde (débit − crédit) de **tout compte** de la balance
  définitive — ex. `solde:1111` (capital social), `solde:3421` (clients),
  `solde:4411` (fournisseurs), `solde:3911` (dépréciation des stocks) ;
- totaux comptables et fiscaux : `classe:1` … `classe:7`, `total_produits`,
  `total_charges`, `resultat_comptable`, `resultat_avant_impot`,
  `chiffre_affaires`, `total_reintegrations`, `total_deductions`, `resultat_fiscal`,
  `is_theorique`, `cotisation_minimale`, `impot_du` ;
- **immobilisations (J2)** : `immo:brut`, `immo:amortissements`, `immo:vnc`,
  `immo:dotations`, `immo:cessions_valeur`, `immo:cessions_amortissements`,
  `immo:cessions_prix`, `immo:cessions_resultat` ;
- **stocks (J3)** : `stock:valeur`, `stock:comptable`, `stock:provisions`,
  `stock:dotations_provisions`, `stock:reprises_provisions`, `stock:variation` ;
- **personnel / DTS (J6)** : `personnel:effectif`, `personnel:permanent_effectif`,
  `personnel:occasionnel_effectif`, `personnel:stagiaires_effectif`,
  `personnel:brut_imposable`, `personnel:cotisations_sociales`,
  `personnel:ir_retenu`, `personnel:net_a_payer`, `personnel:cout_employeur` ;
- **créances et dettes** : soldes des comptes de tiers (`solde:3421`, `solde:4411`,
  `solde:3431`, `solde:4441`…), soit **directement** depuis la balance ;
- **provisions** : `solde:1515` / `solde:1555` (provisions du passif),
  `solde:6195` / `solde:7195` (dotations et reprises), dépréciations d'actif
  (`solde:29xx`, `solde:39xx`, `solde:49xx`).

> Aucune rubrique n'est inventée : si une rubrique demandée par le CSV n'existe pas
> dans cette liste, l'application **refuse la cellule** et signale
> `liasse.rubrique_inconnue` (contrôle bloquant) — la liasse n'est jamais produite
> avec une valeur dont l'origine est indéterminée.

## Outil

```powershell
# Structure du modèle (tableaux, codes, id d'entête) telle que lue dans le XSD
.\.venv\Scripts\python.exe tools\liasse_codification.py --contrat "comptable simplifié"

# Squelette de référentiel à compléter par l'expert-comptable
.\.venv\Scripts\python.exe tools\liasse_codification.py --init "comptable simplifié" `
        --cible referentiels\liasse\codification_liasse.modele-simplifie.csv

# Vérification du référentiel contre le schéma (sortie 1 si code inconnu)
.\.venv\Scripts\python.exe tools\liasse_codification.py --verifier
```
