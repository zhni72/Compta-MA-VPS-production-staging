# Recette J9 — analyse du jeu de données, décisions et incohérences

Complément de `RAPPORT_TEST_J9.md` (généré par `tools/j9_recette.py`).
Base : `compta_ma.db` · sauvegarde avant purge : **`compta_ma.db.bak-j9-20260923-030303`** (884 Ko).
Jeu de données : `jeu_donnees_insertion_compta_maroc_2025_2026.json`
(SHA-256 `82c08ae2923632c6…`, 183 écritures / 474 lignes, exercices 2025-2026).

## 1. Outils livrés (rejouables)

| Outil | Rôle |
|---|---|
| `tools/j9_purge_donnees.py` | purge des données métier (simulation par défaut, sauvegarde automatique) — conserve plan comptable, TVA, société, rôles, utilisateurs |
| `tools/j9_importer_jeu.py` | injection du jeu par phases : `societe`, `2025`, `cloture`, `2026`, `complement`, `factures`, `documents`, `nettoyer` |
| `tools/j9_recette.py` | contrôles comptables + **tests des 11 modules** + fumée des 23 écrans → écrit `RAPPORT_TEST_J9.md` |
| `recette_j9/` | livrables EDI produits : relevé de déduction TVA 06/2025 (XML), DTS 9421 2026 (XML), relevé bancaire 02/2025 (CSV) |

Phases exécutées : `societe` → `2025` → **`cloture` (application)** → `2026` → `complement` → `factures` → `documents`.
La **clôture 2025 a été faite par l'application** (`closing.cloturer_exercice`) : résultat net **73 600,00 DH**,
à-nouveaux **387 520,00 DH** équilibrés (11 lignes, 10 comptes reportés) — identiques aux montants du jeu.

## 2. Décisions d'import (et pourquoi)

1. **Identifiants du jeu inexploitables.** Le jeu fournit `ICE-TEST-000000000000001` et `IF-TEST-000001`.
   Les contrôles de l'application (ICE 15 chiffres, IF 7-8 chiffres) les **refusent** : tous les modules
   EDI (TVA, DTS, liasse, greffe) auraient été bloqués. ⇒ Raison sociale, devise et régime repris du jeu ;
   **ICE/IF/RC conformes du dossier conservés** ; RC, adresse, ville, n° CNSS complétés par des
   placeholders de recette (`tools/j9_recette.py`, fonction `preparer_societe`).
2. **Statut d'exercice** `open_for_test` (jeu) normalisé en `open` (valeur gérée par l'application).
3. **Journaux** : le jeu utilise `ACH / VTE / BNQ / PAI`, l'application 5 journaux standards ⇒ mapping
   `ACH→AC`, `VTE→VE`, `BNQ→BQ`, `PAI→BQ`, `OD→OD`. La **pièce du jeu est conservée en référence**
   (`OUV-2025`, `FA25-01`, `FV25-01`, `PAIE25-01`…) : la traçabilité est intacte (piste d'audit `source=import_jeu_j9`).
4. **Écritures d'à-nouveaux du jeu** : `OUV-2026` **non importée** (l'application l'a générée) ;
   `STK-OUV-2026` **importée** (ce n'est pas un à-nouveaux mais la contre-passation du stock initial 2026,
   sans laquelle le stock 3111 aurait été doublé : 45 000 au lieu de 25 000).
5. **Factures reconstruites depuis le grand livre.** Le jeu ne fournit que 3 factures de vente : toutes les
   factures (24 ventes + 50 achats) ont été **reconstruites pièce par pièce** et rattachées à leur écriture
   (`entry_id`), **sans créer d'écriture**. Les règlements (encaissements `3421`, décaissements `4411`,
   règlements **comptant** portés aux journaux d'achat/vente) sont affectés en **FIFO pluriannuel**.
   Résultat : réconciliations **exactes à 0,00 DH** (créances 25 920, dettes fournisseurs 6 480).
6. **Immobilisations / stocks / salariés** créés **sans comptabilisation** (le grand livre du jeu porte déjà
   acquisitions, dotations et variation de stock). Les lignes du plan d'amortissement sont rattachées aux
   écritures de dotation du jeu (`AMO-2025`, `AMO-2026`) pour que les états du module réconcilient le grand livre.

## 3. Incohérences détectées dans le jeu (signalées, non masquées)

| # | Constat dans le jeu | Traitement retenu | Impact |
|---|---|---|---|
| 1 | ICE/IF factices (`…TEST…`) refusés par les contrôles DGI | identifiants conformes du dossier conservés | aucun (sinon tous les EDI bloqués) |
| 2 | Statut `open_for_test` non géré par l'application | normalisé en `open` | aucun |
| 3 | Paie **globale** (6171 = 10 000 DH/mois en 2025, 12 000 en 2026) **sans bulletins ni CNSS/IR** | module paie testé avec les 3 salariés du jeu (cas de test IR) + paie 01/2026 calculée et validée | +30 495,60 DH de charges 2026 (écriture de recette, réversible) |
| 4 | Salaires des 3 salariés de test (3 000 / 7 000 / 16 000 DH) ≠ masse salariale du grand livre | écart documenté : le jeu traite la paie en forfait | à arbitrer |
| 5 | TVA sur immobilisations logée au **34552** (charges) au lieu du compte dédié **34551** | fiches immo saisies avec `tva_compte=34551` et `tva_montant` (12 000 / 6 000) sans écriture | écart de ventilation à arbitrer (pas d'impact fiscal) |
| 6 | Journal `PAI` (paie) distinct de `BNQ` | les deux mappés sur `BQ` (la pièce `PAIE25-xx` conserve la distinction) | lisibilité uniquement |
| 7 | CA 2025 = 360 000 DH (< 1 M DH ⇒ régime **trimestriel** suggéré) mais flux **mensuels** | régime `mensuel` retenu pour la recette | à confirmer avec l'expert-comptable |
| 8 | Aucune facture d'achat fournie | reconstruction depuis le grand livre | aucune (réconcilié à 0,00 DH) |
| 9 | Stock fourni sous forme de **résumé** annuel, pas de mouvements datés | mouvements reconstitués (achat juin / vente décembre) au coût du jeu | stocks finaux identiques au grand livre (20 000 / 25 000) |
| 10 | Aucune donnée banque, greffe, déclaration TVA, IS/liasse, cessation, e-facturation | créées **par la recette** (relevé bancaire dérivé du 5141, dossier greffe + 2 pièces PDF, déclarations, événement de cessation, 1 e-facture) | jeux de recette listés au § 5 |
| 11 | Résultat 2025 reporté au **1161** (report à nouveau) par le jeu | l'application clôture via son module J3 (`1191/1199` selon paramétrage) | présentation du bilan à valider (A25 proposée) |
| 12 | A22 déjà connue : annexe DGI « Codification des cellules » absente | liasse **non produite** par l'application (refus explicite) | blocage assumé avant validation expert-comptable |

## 4. Résultats de la recette (axe comptable)

| Contrôle | 2025 | 2026 |
|---|---|---|
| Équilibre partie double | 1 546 880,00 = 1 546 880,00 | 2 162 175,60 = 2 162 175,60 |
| Bilan actif = passif (avec résultat) | 387 520,00 | 493 280,00 |
| Résultat (CPC) | **73 600,00** (jeu : 73 600 ✓) | **49 344,40** (jeu : 79 840 ; écart = paie de recette 30 495,60) |
| TVA collectée / déductible / à payer | 72 000 / 36 000 / 36 000 | 86 400 / 32 880 / 53 520 |
| Cohérence TVA (20 % des ventes HT) | 72 000 = 360 000 × 20 % ✓ | 86 400 = 432 000 × 20 % ✓ |

Réconciliations modules ↔ grand livre (fin 2026) : **créances clients 25 920**, **dettes fournisseurs 6 480**,
**stocks 25 000**, **immobilisations 90 000** (amortissements 27 000, VNC 63 000), **IS 2025 18 400** —
**écart 0,00 DH sur les 6 contrôles**. Audit : chaîne scellée **184/184, 0 rupture**, écriture dans un exercice
clos **refusée** (`FiscalYearClosedError`). Écrans : **23/23 sans erreur** (connexion HTTP 200).

## 5. Écritures et objets de recette (à purger à l'étape 6)

Paie 01/2026 (bulletins + écriture comptable, coût employeur 30 495,60 DH) · déclarations TVA/EDI (registre
`tax_declarations`) · dossier greffe 2025 + 2 pièces PDF · relevés bancaires 01 et 02/2025 · 3 inventaires
physiques · 1 facture électronique (canal DGI en simulation) · événement de cessation au 31/12/2026 ·
scellement de la chaîne d'audit.

**Procédure de nettoyage** (sur votre validation) :

```powershell
# 1) retour à l'état d'avant recette (si souhaité) :
Copy-Item compta_ma.db.bak-j9-20260923-030303 compta_ma.db -Force
# 2) ou purge complète des données métier (sauvegarde automatique) :
.\.venv\Scripts\python.exe tools\j9_purge_donnees.py --appliquer
# 3) ou nettoyage des seuls documents reconstruits :
.\.venv\Scripts\python.exe tools\j9_importer_jeu.py --phase nettoyer --appliquer
```

## 6. Reste à faire (non bloquant pour la recette)

1. **Validation A22** du référentiel `referentiels/liasse/codification_liasse.csv` (production de la liasse XML).
2. API et écrans des modules J8 (`/activite`, `/e-invoice`) : testés ici **par les services** uniquement.
3. Schéma DGI de facturation électronique (A24) et branchement du canal réel (`E_INVOICE_ENDPOINT`).
4. Arbitrages à confirmer : régime TVA mensuel/trimestriel, ventilation 34551/34552, compte d'affectation du
   résultat à l'ouverture (A25), méthode de valorisation des stocks attendue (CMUP retenu).


