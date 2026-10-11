# J7 — IS & Liasse EDI : plan validé, contrat XSD relevé et correctifs J6

> **But de ce fichier** : reprendre J7 **sans refaire la reconnaissance** (contrat des schémas
> déjà extrait ci-dessous) et corriger le fichier DTS de J6, devenu non conforme au modèle EDI
> officiel V5.1.

## 0. État de référence

- Suite de tests au départ de J7 : **221/221 verts** (J6 livré, CDC v2.7).
- À maintenir : **221 tests verts + nouveaux tests J7**.
- Référentiels (machine de travail) :
  `C:\Users\Belyazid\Desktop\image\compta_maroc\deepsesk\Documentation\RÉFÉRENTIEL TECHNIQUE DGI\`

## 0 bis. Ordre de reprise validé par le client (session suivante)

1. **Corriger d'abord J6** : `app/services/edi_dts.py` → racine **`TraitementEtSalaire`**, champs
   **plats** (voir la clarification ci-dessous), **3 catégories PP / PO / STG**, totaux
   **normalisés**, `nom`/`prenom` **séparés**, **sans namespace** ; adapter les assertions DTS ;
   vérifier que les **221 tests restent verts**.
2. **J7 — étape 1** : résultat fiscal + **IS / cotisation minimale** + contrôles.
3. **J7 — étape 2** : assembleur de liasse (`liasse_tables` / `liasse_cells`).
4. **J7 — étape 3** : EDI XML **validé XSD** (lxml) + registre `tax_declarations`.

> ⚠️ **Clarification « bloc `declarant` »** : l'**exemple officiel** `EDI_DTS_Exemples_V5.1.xml`
> ne comporte **aucun** élément `<declarant>` — les informations du déclarant sont **des balises
> plates directement sous la racine** (`identifiantFiscal`, `nom`, `prenom`, `raisonSociale`,
> `exerciceFiscalDu`, `exerciceFiscalAu`, `annee`, `commune/code`, `adresse`, `numeroCIN`,
> `numeroCNSS`, `numeroCE`, `numeroRC`, `identifiantTP`, `numeroFax`, `numeroTelephone`, `email`,
> `effectifTotal`, `nbrPersoPermanent`, `nbrPersoOccasionnel`, `nbrStagiaires`,
> `dateObtentionStatusCFC`). **Le modèle interne** (`construire_dts`) continue de porter une
> section `declarant` (dict Python) : c'est elle qui alimente les balises plates — les deux
> demandes sont ainsi respectées, sans introduire d'élément non prévu par le schéma.

**Cibles de tests à adapter lors du correctif J6** (doivent rester vertes) :
`tests/test_payroll.py::test_dts_xml_structure_et_validation_xsd_absente` (balises
`<DTS `/`<declarant>`/`<irRetenu>` → racine/valeurs du nouveau modèle),
`test_dts_refusee_si_cnss_salarie_manquant`, `test_dts_etat_efi_et_registre_des_declarations`,
`test_dts_modele_et_reconciliation_comptable`, `test_dts_rejet_motive_et_exercice_sans_paie`,
`test_dts_fiche_pdf`, et `tests/test_api.py::test_api_paie_et_dts`
(assertions `<DTS ` / `<irRetenu>560.67</irRetenu>`), ainsi que
`tests/test_web.py::test_interface_paie_et_dts` (`b"<DTS "`).

## 1. Contrat du schéma de liasse (relevé dans le XSD réel)

| Modèle | Fichier | Taille |
|---|---|---|
| Normal | `ir\liasse_modele_normal.xsd` | 57 Ko |
| **Comptable simplifié (cible PME)** | `ir\liasse_modele_comptable simplifié.xsd` | 45 Ko |
| Assurances | `ir\liasse_modele_Assurances.xsd` | 74 Ko |
| Établissements de crédit | `ir\liasse_modele_établissements de crédit.xsd` | 71 Ko |

Structure (lue ligne à ligne, `liasse_modele_comptable simplifié.xsd`, 135 lignes / 44 896 car.) :

```xml
<groupeValeursTableau>                      <!-- ELEMENT RACINE -->
  <ValeursTableau>
    <tableau><id>61</id></tableau>          <!-- id : enumeration FERMEE -->
    <groupeValeurs>                         <!-- 1..n -->
      <ValeurCellule>
        <cellule><codeEdi>4562</codeEdi></cellule>   <!-- enumeration FERMEE -->
        <valeur/>                                   <!-- ref global -->
        <numeroLigne minOccurs="0"/>
      </ValeurCellule>
    </groupeValeurs>
    <extraFieldvaleurs>
      <ExtraFieldValeur><extraField>…</extraField>…</ExtraFieldValeur>
    </extraFieldvaleurs>
  </ValeursTableau>
</groupeValeursTableau>
```

- **Ids de tableau déclarés** (extrait) : `5, 7, 10, 12, 23, 26, 27, 28, 32, 34, 36, 37, 38, 39,
  40, 41, 61, 65, 78, 161, 180, 200, 240, 320…` (bilan, CPC, ESG, immobilisations,
  amortissements, stocks, personnel, créances/dettes, provisions).
- **`codeEdi`** : énumération fermée très étendue (ex. `4562…4657`, `14068…14415`,
  `15005…15054`, `17929`).
- **Décision de conception** : la table `rubrique ↔ codeEdi` sera **dérivée des énumérations des
  XSD** (garantie conforme), et **non** du `réferentiel des codifications.xlsx` — voir A13.
- Nouvelle option de configuration prévue : **`LIASSE_XSD_DIR`** (dossier des XSD de liasse), sur
  le modèle de `dts_xsd_path` (J6).

## 2. Plan J7 validé (ordre d'exécution)

1. **Résultat fiscal + IS / cotisation minimale + contrôles** (utilisable immédiatement) :
   réintégrations / déductions, report déficitaire, **IS vs cotisation minimale**
   (`compute_is` / `compute_cotisation_minimale` de `rates_ma` existent déjà), crédits et
   acomptes ; contrôles : exercice **clos** (P1.6), concordance résultat comptable ↔ résultat
   fiscal, **Σ liasses = balance** par poste suivi.
2. **Assembleur de liasse** : `liasse_tables` / `liasse_cells` (CDC § 2.3 : `declaration_id`,
   `tableau_id`, `code_edi`, `valeur`, `numero_ligne`, `extra_field`), alimentés par la
   **balance définitive** + **immos (J2)** + **stocks (J3)** + **frais de personnel (J6/DTS)** ;
   deux modèles (normal, comptable simplifié) ; **EFI assisté** (état de saisie par tableau avec
   `codeEdi`).
3. **EDI XML validé XSD** : `build_liasse_xml()` conforme à la structure ci-dessus et
   `valider_xsd()` **réelle** (lxml) contre le schéma du modèle choisi — **jamais « présumé
   conforme »** ; registre `tax_declarations` (`IS` + `LIASSE`) avec **SHA-256** et accusé.
4. **API `/liasse` + écran `/liasse` + tests + docs** (CDC v2.8 § 9.14, README § 15).

## 3. Correctif J6 découvert : fichier DTS non conforme au modèle officiel

Source : `%TEMP%\audit_tva\dts_referentiel\Simpl_IR_Cahier_des_charges_DTS_V5.1\` (extrait de
`Downloads\les+cahiers+de+charges+et+annexes+IR\…\Simpl_IR_Cahier_des_charges_DTS_V5.1.zip`).

Le zip **ne contient aucun XSD**, mais contient **le contrat réel** :

- `Simpl-IR_Cahier_des_charges_DTS_EDI_V5.1.pdf` (CC EDI) ;
- `Annexe1_EDI_DTS_Correspondance_Balise_Déclaration_V5.1.pdf` (**balise ↔ rubrique**) ;
- `Annexe2_EDI_DTS_Simpl-IR_Codification_Référentiel_V5.1.pdf` (**codification**) ;
- `EDI_DTS_Exemples_V5.1.zip` → `EDI_DTS_Exemples_V5.1.xml` (**exemple officiel**, 7 344 car.).

**Modèle officiel (à appliquer dans `app/services/edi_dts.py`)** :

```xml
<TraitementEtSalaire xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                     xsi:noNamespaceSchemaLocation="traitementSalaire.xsd">
  <identifiantFiscal/> <nom/> <prenom/> <raisonSociale/>
  <exerciceFiscalDu/> <exerciceFiscalAu/> <annee/>
  <commune><code/></commune> <adresse/> <numeroCIN/> <numeroCNSS/> <numeroCE/> <numeroRC/>
  <identifiantTP/> <numeroFax/> <numeroTelephone/> <email/>
  <effectifTotal/> <nbrPersoPermanent/> <nbrPersoOccasionnel/> <nbrStagiaires/>
  <dateObtentionStatusCFC/>
  <totalMtRevenuBrutImposablePP/> <totalMtRevenuNetImposablePP/> <totalMtTotalDeductionPP/>
  <totalMtIrPrelevePP/> <totalMtBrutSommesPO/> <totalIrPrelevePO/>
  <totalMtBrutTraitSalaireSTG/> <totalMtBrutIndemnitesSTG/> <totalMtRetenuesSTG/>
  <totalMtRevenuNetImpSTG/> <totalSommePayeRTS/> <totalmtAnuuelRevenuSalarial/>
  <totalmtAbondement/> <montantPermanent/> <montantOccasionnel/> <montantStagiaire/>
  <listPersonnelPermanent>
    <PersonnelPermanent><nom/> <prenom/> <adressePersonnelle/> <numCNI/> <numCE/> …</PersonnelPermanent>
  </listPersonnelPermanent>
  <!-- autres listes : personnel occasionnel (PO), stagiaires (STG) -->
</TraitementEtSalaire>
```

**Écarts constatés vs le fichier produit par J6** (tests à ajuster) :

1. racine `DTS` → **`TraitementEtSalaire`** (schéma `traitementSalaire.xsd`, **sans namespace**) ;
2. `declarant/…` → **champs plats** (`identifiantFiscal`, `raisonSociale`, `numeroCNSS`…) ;
3. **trois catégories de personnel** : **permanent (PP)**, **occasionnel (PO)**, **stagiaires
   (STG)** — J6 ne gérait que « permanent » + « exonérés art. 57-20° » ;
4. totaux **normalisés** (`totalMtIrPrelevePP`…) au lieu de `irRetenu` ;
5. `nom` / `prenom` **séparés** (J6 : un seul champ `nom`).

**Action recommandée** : refondre `build_dts_xml()` sur ce modèle, **copier l'exemple officiel
comme fixture de test** (`tests/fixtures/EDI_DTS_Exemples_V5.1.xml`), remplacer l'avertissement
`dts.xsd_absent` par un **contrôle de conformité structurelle** (balises et ordre) et conserver
`DTS_XSD_PATH` pour la validation XSD dès que `traitementSalaire.xsd` sera obtenu.

## 4. Incohérences à tracer (CDC § 8.2)

| # | Constat | Conséquence | Recommandation |
|---|---|---|---|
| **A13** | `réferentiel des codifications.xlsx` (dossier `simple-is\`) est entouré des artefacts **CbCR** (`CBC_XSD_DGI.xsd`, `isocbctypes`, `oecdcbctypes`, `Exemple_XML_CBC.xml`) : ce n'est **pas** le référentiel de la liasse IS | sémantique `rubrique ↔ codeEdi` non documentée par un référentiel exploitable | **dériver les `codeEdi` des énumérations des XSD** (solution retenue) et faire **valider la sémantique des rubriques** (bilan, CPC, ESG) par l'expert-comptable |
| **A14** | Aucun **XSD** dans le référentiel DTS V5.1 (CC + annexes + exemple XML seulement) | la DTS ne peut pas être **validée** par l'application | aligner la structure sur l'**exemple officiel** (§ 3) + contrôle structurel ; **obtenir `traitementSalaire.xsd`** auprès de la DGI pour la validation complète |
| **A15** | Exemple DTS : `xsi:noNamespaceSchemaLocation="traitementSalaire.xsd"` ⇒ **aucun namespace** | un fichier avec namespace serait rejeté | générer **sans namespace** (écart n° 1 du § 3) |

## 5. Prochaines actions (à la reprise, dans l'ordre)

**État au 22/09/2026** — ✅ fait, ⏳ restant :

| # | Action | État |
|---|---|---|
| 1 | Copier les référentiels dans le projet : `referentiels/liasse/*.xsd` et `referentiels/dts/EDI_DTS_Exemples_V5.1.xml` (fixture de test) | ✅ XSD de la liasse installés (`referentiels/liasse/`, 4 schémas + `codification_liasse.csv` + `LISEZ-MOI.md`) ; ⏳ fixture DTS V5.1 (aucun XML de liasse fourni par la DGI) |
| 2 | Ajouter `liasse_xsd_dir` dans `app/core/config.py` (à côté de `dts_xsd_path`) | ✅ `liasse_xsd_dir` + `liasse_codification_path` (+ propriétés `liasse_racine` / `liasse_codification`) |
| 3 | **Étape 1** du § 2 : résultat fiscal + IS/CM + contrôles **avec ses tests** | ✅ `app/services/fiscal_liasse.py` + `tests/test_fiscal_liasse.py` (**15 tests**) — CDC **v2.8 § 9.14** |
| 4 | Assembleur de liasse (**étape 2**) puis **EDI XML validé XSD** (étape 3) | ✅ étape 2 : `app/services/liasse_edi.py`, `liasse_tables`/`liasse_cells` (migration `a7f3c51d8b42`), `referentiels/liasse/`, `tools/liasse_codification.py`, EFI assisté — CDC **v2.9 § 9.15** ; ✅ étape 3 : `build_liasse_xml()`, **validation XSD réelle** (lxml), `produire_liasse_xml()`, **API `/liasse`**, **écran `/liasse`**, **accusé de réception** — CDC **§ 9.16**, **P2.1 livré** |
| 5 | Correctif J6 du § 3 (DTS alignée sur le modèle officiel V5.1) + non-régression | ✅ suite **221/221** maintenue après correctif (CDC § 9.13.1, README § 14) |
| 6 | Documentation : **CDC v2.9 § 9.14 à § 9.16**, ambiguïtés **A13→A22** (§ 8.2), annexes **A/C/D**, **README § 15 et § 7** | ✅ fait ; **P2.1 ✅ livré** (la validation de la sémantique des `codeEdi` reste à la charge de l'expert-comptable, A22) |

**Incohérence majeure découverte à l'étape 2 (A22)** : l'annexe officielle « **Codification
des cellules** » / « Codification des modèles et tableaux des Liasses » **n'est pas fournie**.
Les quatre XSD ne contiennent que des **énumérations** (`tableau/id`, `cellule/codeEdi`,
`extraField/code`) **sans aucun libellé** et le CC EDI y renvoie explicitement ; le
`réferentiel des codifications.xlsx` livré est le référentiel **CbCR** (vérifié : aucune
occurrence de `codeEdi`, de code de cellule ni de libellé de liasse). Conséquence : **la
correspondance `rubrique` ↔ `codeEdi` ne peut pas être dérivée automatiquement** — elle est
portée par un **référentiel éditable** `codification_liasse.csv` (trame générée depuis le
schéma par `tools/liasse_codification.py --gabarit`) et **validée par l'expert-comptable** ;
l'**EFI assisté** reste le mode de dépôt opérationnel en attendant l'annexe.

**Correctif de cohérence documentaire appliqué** : le CDC ne comportait **aucune entrée**
de version pour les jalons **J2 (2.3)**, **J4 (2.5)**, **J5 (2.6)**, **J6 (2.7)** et le
**correctif J6 (2.7.1)** ; les lignes manquantes ont été ajoutées (Annexe D) et le mémo de
l'Annexe A a été remis à jour (plancher de tests **236**, commandes par jalon).


