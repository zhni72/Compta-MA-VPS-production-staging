
# Rapport de recette J9 — Compta MA (exercices 2025 et 2026)

Base de test alimentée par `tools/j9_importer_jeu.py` (jeu de données `jeu_donnees_insertion_compta_maroc_2025_2026.json`, 183 écritures, 474 lignes). Sauvegarde de la base prise avant purge (`compta_ma.db.bak-j9-*`). Analyse des incohérences du jeu, décisions d'import et impacts chiffrés : `RAPPORT_TEST_J9_ANALYSE.md`.

## 1. Société et exercices

| Élément | Valeur |
|---|---|
| Raison sociale | SOCIETE RECETTE MAROC SARL AU |
| ICE | 001234567000099 |
| Identifiant fiscal | 1234567 |
| RC | 12345 |
| Régime TVA | mensuel |
| Identité complétée (recette) | {"adresse": "12 rue de la Recette, Casablanca"} |
| Exercices | 2025:closed, 2026:open |

## 2. Données de test — contrôles comptables


### 2.1 Volumétrie

| Objet | Nombre | Montant (MAD) |
|---|---|---|
| Écritures | 184 |  |
| Lignes d'écriture | 481 |  |
| Journaux | 6 |  |
| Comptes du plan comptable | 895 |  |
| Tiers | 4 |  |
| Factures de vente | 24 | 950400.00 |
| Factures d'achat | 50 | 413280.00 |
| Règlements | 142 | 1331280.00 |
| Articles de stock | 3 | 25000.00 |
| Mouvements de stock | 12 |  |
| Immobilisations | 2 | 90000.00 |
| Lignes d'amortissement | 3 | 27000.00 |
| Salariés | 3 |  |

### 2.2 Équilibre de la partie double

| Exercice | Total débit | Total crédit | Écart | Contrôle |
|---|---|---|---|---|
| 2025 | 1546880.00 | 1546880.00 | 0.00 | OK |
| 2026 | 2162175.60 | 2162175.60 | 0.00 | OK |

### 2.3 Balance, bilan et CPC par exercice

| Exercice | Balance D/C | Bilan actif / passif (avec résultat) | Résultat (CPC) | Contrôle |
|---|---|---|---|---|
| 2025 | 1546880.00 / 1546880.00 | 387520.00 / 387520.00 | 73600.00 | OK |
| 2026 | 2162175.60 / 2162175.60 | 493280.00 / 493280.00 | 49344.40 | OK |

### 2.4 TVA (régime mensuel) et cohérence au taux de 20 %

| Exercice | TVA collectée | TVA déductible | Net | Ventes HT (20 %) | 4455 (grand livre) | Cohérence |
|---|---|---|---|---|---|---|
| 2025 | 72000.00 | 36000.00 | 36000.00 | 360000.00 (20 % = 72000.00) | 72000.00 | OK |
| 2026 | 86400.00 | 32880.00 | 53520.00 | 432000.00 (20 % = 86400.00) | 86400.00 | OK |

### 2.5 Réconciliations modules ↔ grand livre (fin 2026)

| Contrôle | Source module | Module | Grand livre | Écart |
|---|---|---|---|---|
| Créances clients | Factures impayées | 25920.00 | 25920.00 | 0.00 |
| Dettes fournisseurs | Factures impayées | 6480.00 | 6480.00 | 0.00 |
| Stocks (valeur nette) | Articles | 25000.00 | 25000.00 | 0.00 |
| Immobilisations (brut) | Fiches | 90000.00 | 90000.00 | 0.00 |
| Amortissements cumulés | Plans | 27000.00 | 27000.00 | 0.00 |
| IS exercice 2025 | Calcul fiscal | 18400.00 | 18400.00 | 0.00 |

## 3. Tests des modules

- **balance_2025** : 1546880.00 D / 1546880.00 C — équilibrée
- **balance_2026** : 2162175.60 D / 2162175.60 C — équilibrée
- **grand_livre_5141_2025** : 62 ligne(s), solde 228320.00
- **ecritures_par_journal** : AC:50, AN:1, BQ:75, OD:34, VE:24
- **lignes_2025** : 19

- **ventes** : 24 (950400.00)
- **achats** : 50 (413280.00)
- **reglements** : 142 (1331280.00)
- **impayes_ventes** : 25920.00
- **impayes_achats** : 6480.00
- **statuts** : {"paid": 72, "partially_paid": 2}
- **recalcul** : FV25-01 → HT 30000.00 / TVA 6000.00 / TTC 36000.00

- **declaration_2025** : {"company_id": 1, "date_from": "2025-01-01", "date_to": "2025-12-31", "tva_collectee": "72000.00", "tva_deductible": "36000.00", "tva_nette": "36000.00", "tva_a
- **recap_par_taux_2025** : vente: 20.00 % base 360000.00 TVA 72000.00, achat: 20.00 % base 180000.00 TVA 36000.00
- **net_mensuel_2025** : 0.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00
- **rd_edi_06_2025** : 3 ligne(s) base paiement, 2 base facture ({'nb_lignes': 3, 'mht': Decimal('18000.00'), 'tva': Decimal('1840.00'), 'ttc': Decimal('19840.00'), 'par_taux': {'20.00': {'nb': 3, 'base': Decimal('18000.00'), 'tva': Decimal('1840.00')}}})
- **xml_rd** : recette_j9/releve_deduction_2025_06.xml (1682 octets)
- **periode_valide** : None
- **nom_fichier_edi** : ReleveDeductions_2025_M6.xml

- **etat_2025** : {"exercice": 2025, "postes": [{"compte": "2340", "libelle": "Matériel de transport", "brut": "60000.00", "amortissements": "12000.00", "vnc": "48000.0
- **etat_2026** : {"exercice": 2026, "postes": [{"compte": "2340", "libelle": "Matériel de transport", "brut": "90000.00", "amortissements": "27000.00", "vnc": "63000.0
- **soldes_comptables** : {"brut": "90000.00", "amortissements": "27000.00", "vnc": "63000.00", "detail": [{"account_number": "2340", "solde": "90000.00"}, 
- **amortissements_deductibles** : {"exercice": 2026, "lignes": [{"code": "IMM-001", "label": "Matériel et outillage", "compte": "2340", "mode": "lineaire", "duree_a
- **controles** : []

- **articles** : SKU-A: 120.000 U / 12000.00 MAD; SKU-B: 40.000 U / 8000.00 MAD; SKU-C: 50.000 U / 5000.00 MAD
- **valeur_totale** : 25000.00
- **etat_stocks** : {"au": "2026-09-23", "lignes": [{"reference": "SKU-A", "label": "Marchandise A (SKU-A)", "unit": "U", "family": null, "stock_account": "3111
- **inventaire_valorise** : {"au": "2026-09-23", "lignes": [{"reference": "SKU-A", "label": "Marchandise A (SKU-A)", "unit": "U", "stock_account": "3111", "theoretical_
- **inventaire** : n° 11 — statut valide
- **controles** : 3

- **periode** : 2026-01 — 3 bulletin(s), brut 26000.00
- **bulletin_test** : {"periode": "2026-01", "societe": {"nom": "SOCIETE RECETTE MAROC SARL AU", "ice": "001234567000099", "fiscal_id": "1234567", "cnss_number": "9876543"}, "salarie": {"matricule": "EMP001", "nom": "EMP001 — Seuil exonéré", "cnss": "CNSS001TEST", "situation": "celibataire", "enfants": 0, "date_entree": 
- **ecriture_paie** : écriture n° 183
- **livre_2026** : {"annee": 2026, "totaux": {"brut": "26000.00", "cotisations": "1259.60", "ir": "2300.66", "net": "22439.74", "cout_employeur": "30495.60"}, "bulletins": null, "lignes": null, "total_brut": null}
- **cotisations_2026** : {"annee": 2026, "lignes": [{"periode": "2026-01", "brut": "26000.00", "cnss_salariale": "672.00", "amo_salariale": "587.60", "cnss_patronale": "1347.00", "amo_p
- **controles** : [{"code": "paie.recap", "niveau": "information", "message": "Paie 2026-01 : Validé (écriture de paie comptabilisée) — brut 26000.00 DH, IR 2300.66 DH, net 22439
- **dts_xml** : recette_j9/dts_9421_2026.xml (3088 octets)
- **dts_registre** :  (brouillon)

- **scellement** : {"company_id": 1, "total_ecritures": 184, "scellees": [], "nb_scellees": 0, "derniere_empreinte": "fa84982132509e707943e
- **chainage** : {"company_id": 1, "nb_ecritures": 184, "nb_scellees": 184, "non_scellees": [], "ruptures": [], "integre": true, "derniere_empreinte": "fa84982132509e707943e411b
- **journal_audit** : 50
- **piste_ecriture** : {"entry_id": 1, "entry_number": "EC202500001", "entry_date": "2025-01-01", "label": "Constitution / ouverture", "source": "import_jeu_j9", "source_libelle": "im
- **verrouillage_2025** : refusé comme attendu (FiscalYearClosedError)

- **releve** : 5 ligne(s) importée(s)
- **rapprochement_auto** : {"statement_id": 10, "nb_rapprochees": 0, "rapprochees": [], "nb_restantes": 5}
- **etat** : {"statement_id": 10, "account_number": "5141", "date_from": "2025-02-01", "date_to": "2025-02-28", "solde_comptable": "144720.00", "solde_bancaire": "208360.00", "ecarts_non_justif
- **periode** : 2025-02-01 → 2025-03-01

- **identite_societe** : complète (ICE, IF, RC)
- **depot** : n° 1 — état 
- **pieces_generees** : {"depot": "<GreffeDeposit exercice=2025 statut=approuve forme=SARL>", "documents": ["<GreffeDocument
- **checklist** : [["etats_synthese", "fournie"], ["tableau_financement", "facultative"], ["rapport_gestion", "fournie"], ["rapport_cac", "conditionnelle"], ["pv_ag", "fournie"], ["etat_complementaire", "fournie"], ["j
- **completude** : {"nb_exigees": 5, "nb_fournies": 5, "ratio": 1.0, "complete": true, "manquantes": []}
- **controles** : [{"code": "greffe.ag_hors_delai", "niveau": "avertissement", "message": "Délai d'approbation dépassé (aucune date d'AG enregistrée ; limite 30/06/2026, loi 5-96 art. 10) : le dépôt sera « Amender » et
- **etats** : workflow → 
- **solde_taxes** : 0.00

- **dossier_2025** : {"resultat_fiscal": "92000.00", "is_du": "18400.00", "cotisation_minimale": "0.00", "resultat_net": "73600.00"}
- **controles_bloquants** : 0
- **reconciliation_balance** : {"annee": 2025, "classes": {"1": "-200000.00", "2": "48000.00", "3": "99200.00", "4": "-101920.00", "5": "228320.00", "6": "286400.00", "7": "-360000.00"}, "tot
- **liasse** : {"annee": 2025, "modele": "liasse_modele_comptable simplifié", "libelle_modele": "Liasse comptable simplifiée (cible PME)", "liasse": {"annee": 2025, "modele": "liasse_modele_comptable simplifié", "libelle_modele": "Lias
- **liasse_xml** : non produite : Aucune cellule renseignée : le schéma exige au moins un tableau avec une `ValeurCellule` — complétez le référentiel de codification (annexe DGI, ambiguïté A22) ou saisissez la liasse en EFI assisté. (limitation connue A22 — référentiel de codification à valider par l'expert-comptable avant dépôt SIMPL)

- **evenement** : n° 1 — cessation au 2026-12-31
- **situation** : {"annee": 2026, "evenements": ["<ActivityEvent cessation 2026-12-31>"], "evenement": "<ActivityEvent cessation 2026-12-31>", "declaration": {"evenement_id": 1, "annonce": "Cessation définitive d'activ
- **controles** : [{"code": "activite.regularisation_stocks_a_examiner", "niveau": "avertissement", "message": "TVA à régulariser sur les stocks et biens non amortissables : montant à saisir par l'expert-comptable (aucun taux n'est deviné
- **rd_sortie** : {"annee": 2026, "periode": 1, "regime": 4, "date_from": "2026-01-01", "date_to": "2026-12-31", "xml": "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<!-- Declarant : SOCIETE RECETTE M
- **declaration_tva_sortie** : <TaxDeclaration TVA 2026 brouillon>
- **e_facture** : FV25-08 → 8 (genere)
- **e_facture_envoi** : <EInvoiceDocument facture=23 envoye>
- **e_facture_accuse** : <EInvoiceDocument facture=23 accepte>
- **e_facture_situation** : {"annee": null, "documents": ["<EInvoiceDocument facture=23 accepte>", "<EInvoiceDocument facture=20 accepte>", "<EInvoiceDocument facture=17 accepte>", "<EInvoiceDocument facture=14 accepte>", "<EInv
- **mentions_obligatoires** : 17


## 4. Écrans de l'interface (fumée HTTP)

Connexion de recette : HTTP 200 (identifiants de recette des tests automatisés).
| Écran | HTTP | Contrôle |
|---|---|---|
| / | 303 | OK |
| /ecritures | 303 | OK |
| /comptes | 303 | OK |
| /tiers | 303 | OK |
| /factures | 303 | OK |
| /reglements | 303 | OK |
| /immobilisations | 303 | OK |
| /immobilisations/etats | 303 | OK |
| /stocks | 401 | OK |
| /paie | 303 | OK |
| /tva | 303 | OK |
| /tva/edi | 303 | OK |
| /audit | 401 | OK |
| /rapprochement | 303 | OK |
| /greffe | 303 | OK |
| /liasse | 303 | OK |
| /parametres/societe | 303 | OK |
| /parametres/exercices | 303 | OK |
| /etats/balance | 303 | OK |
| /etats/grand-livre | 303 | OK |
| /etats/bilan | 303 | OK |
| /etats/cpc | 303 | OK |
| /etats/journal | 303 | OK |

## 5. Synthèse des contrôles

| Module | Statut | Détail |
|---|---|---|
| Équilibre | OK | 0 écriture(s) déséquilibrée(s) sur 184 |
| Réconciliation Créances clients | OK | module 25920.00 vs grand livre 25920.00 (écart 0.00) |
| Réconciliation Dettes fournisseurs | OK | module 6480.00 vs grand livre 6480.00 (écart 0.00) |
| Réconciliation Stocks (valeur nette) | OK | module 25000.00 vs grand livre 25000.00 (écart 0.00) |
| Réconciliation Immobilisations (brut) | OK | module 90000.00 vs grand livre 90000.00 (écart 0.00) |
| Réconciliation Amortissements cumulés | OK | module 27000.00 vs grand livre 27000.00 (écart 0.00) |
| Réconciliation IS exercice 2025 | OK | module 18400.00 vs grand livre 18400.00 (écart 0.00) |
| Comptabilité | OK | balance_2025=1546880.00 D / 1546880.00 C — équilibrée · balance_2026=2162175.60 D / 2162175.60 C — équilibrée · grand_livre_5141_2025=62 ligne(s), solde 228320.00 · ecritures_par_journal=AC:50, AN:1, BQ:75, OD:34, VE:24 · lignes_2025=19 |
| Facturation | OK | ventes=24 (950400.00) · achats=50 (413280.00) · reglements=142 (1331280.00) · impayes_ventes=25920.00 · impayes_achats=6480.00 · statuts={"paid": 72, "partially_paid": 2} · recalcul=FV25-01 → HT 30000.00 / TVA 6000.00 / TTC 36000.00 |
| TVA | OK | declaration_2025={"company_id": 1, "date_from": "2025-01-01", "date_to": "2025-12-31", "tva_collectee": "72000.00", "tva_deductible": "36000.00", "tva_nette": "36000.00", "tva_a · recap_par_taux_2025=vente: 20.00 % base 360000.00 TVA 72000.00, achat: 20.00 % base 180000.00 TVA 36000.00 · net_mensuel_2025=0.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00, 4000.00 · rd_edi_06_2025=3 ligne(s) base paiement, 2 base facture ({'nb_lignes': 3, 'mht': Decimal('18000.00'), 'tva': Decimal('1840.00'), 'ttc': Decimal('19840.00'), 'par_taux': {'20.00': {'nb': 3, 'base': Decimal('18000.00'), 'tva': Decimal('1840.00')}}}) · xml_rd=recette_j9/releve_deduction_2025_06.xml (1682 octets) · periode_valide=None · nom_fichier_edi=ReleveDeductions_2025_M6.xml |
| Immobilisations | OK | etat_2025={"exercice": 2025, "postes": [{"compte": "2340", "libelle": "Matériel de transport", "brut": "60000.00", "amortissements": "12000.00", "vnc": "48000.0 · etat_2026={"exercice": 2026, "postes": [{"compte": "2340", "libelle": "Matériel de transport", "brut": "90000.00", "amortissements": "27000.00", "vnc": "63000.0 · soldes_comptables={"brut": "90000.00", "amortissements": "27000.00", "vnc": "63000.00", "detail": [{"account_number": "2340", "solde": "90000.00"},  · amortissements_deductibles={"exercice": 2026, "lignes": [{"code": "IMM-001", "label": "Matériel et outillage", "compte": "2340", "mode": "lineaire", "duree_a · controles=[] |
| Stocks | OK | articles=SKU-A: 120.000 U / 12000.00 MAD; SKU-B: 40.000 U / 8000.00 MAD; SKU-C: 50.000 U / 5000.00 MAD · valeur_totale=25000.00 · etat_stocks={"au": "2026-09-23", "lignes": [{"reference": "SKU-A", "label": "Marchandise A (SKU-A)", "unit": "U", "family": null, "stock_account": "3111 · inventaire_valorise={"au": "2026-09-23", "lignes": [{"reference": "SKU-A", "label": "Marchandise A (SKU-A)", "unit": "U", "stock_account": "3111", "theoretical_ · inventaire=n° 11 — statut valide · controles=3 |
| Paie | OK | periode=2026-01 — 3 bulletin(s), brut 26000.00 · bulletin_test={"periode": "2026-01", "societe": {"nom": "SOCIETE RECETTE MAROC SARL AU", "ice": "001234567000099", "fiscal_id": "1234567", "cnss_number": "9876543"}, "salarie": {"matricule": "EMP001", "nom": "EMP001 — Seuil exonéré", "cnss": "CNSS001TEST", "situation": "celibataire", "enfants": 0, "date_entree":  · ecriture_paie=écriture n° 183 · livre_2026={"annee": 2026, "totaux": {"brut": "26000.00", "cotisations": "1259.60", "ir": "2300.66", "net": "22439.74", "cout_employeur": "30495.60"}, "bulletins": null, "lignes": null, "total_brut": null} · cotisations_2026={"annee": 2026, "lignes": [{"periode": "2026-01", "brut": "26000.00", "cnss_salariale": "672.00", "amo_salariale": "587.60", "cnss_patronale": "1347.00", "amo_p · controles=[{"code": "paie.recap", "niveau": "information", "message": "Paie 2026-01 : Validé (écriture de paie comptabilisée) — brut 26000.00 DH, IR 2300.66 DH, net 22439 · dts_xml=recette_j9/dts_9421_2026.xml (3088 octets) · dts_registre= (brouillon) |
| Audit | OK | scellement={"company_id": 1, "total_ecritures": 184, "scellees": [], "nb_scellees": 0, "derniere_empreinte": "fa84982132509e707943e · chainage={"company_id": 1, "nb_ecritures": 184, "nb_scellees": 184, "non_scellees": [], "ruptures": [], "integre": true, "derniere_empreinte": "fa84982132509e707943e411b · journal_audit=50 · piste_ecriture={"entry_id": 1, "entry_number": "EC202500001", "entry_date": "2025-01-01", "label": "Constitution / ouverture", "source": "import_jeu_j9", "source_libelle": "im · verrouillage_2025=refusé comme attendu (FiscalYearClosedError) |
| Rapprochement bancaire | OK | releve=5 ligne(s) importée(s) · rapprochement_auto={"statement_id": 10, "nb_rapprochees": 0, "rapprochees": [], "nb_restantes": 5} · etat={"statement_id": 10, "account_number": "5141", "date_from": "2025-02-01", "date_to": "2025-02-28", "solde_comptable": "144720.00", "solde_bancaire": "208360.00", "ecarts_non_justif · periode=2025-02-01 → 2025-03-01 |
| Dépôt greffe | OK | identite_societe=complète (ICE, IF, RC) · depot=n° 1 — état  · pieces_generees={"depot": "<GreffeDeposit exercice=2025 statut=approuve forme=SARL>", "documents": ["<GreffeDocument · checklist=[["etats_synthese", "fournie"], ["tableau_financement", "facultative"], ["rapport_gestion", "fournie"], ["rapport_cac", "conditionnelle"], ["pv_ag", "fournie"], ["etat_complementaire", "fournie"], ["j · completude={"nb_exigees": 5, "nb_fournies": 5, "ratio": 1.0, "complete": true, "manquantes": []} · controles=[{"code": "greffe.ag_hors_delai", "niveau": "avertissement", "message": "Délai d'approbation dépassé (aucune date d'AG enregistrée ; limite 30/06/2026, loi 5-96 art. 10) : le dépôt sera « Amender » et · etats=workflow →  · solde_taxes=0.00 |
| IS & liasse EDI | OK | dossier_2025={"resultat_fiscal": "92000.00", "is_du": "18400.00", "cotisation_minimale": "0.00", "resultat_net": "73600.00"} · controles_bloquants=0 · reconciliation_balance={"annee": 2025, "classes": {"1": "-200000.00", "2": "48000.00", "3": "99200.00", "4": "-101920.00", "5": "228320.00", "6": "286400.00", "7": "-360000.00"}, "tot · liasse={"annee": 2025, "modele": "liasse_modele_comptable simplifié", "libelle_modele": "Liasse comptable simplifiée (cible PME)", "liasse": {"annee": 2025, "modele": "liasse_modele_comptable simplifié", "libelle_modele": "Lias · liasse_xml=non produite : Aucune cellule renseignée : le schéma exige au moins un tableau avec une `ValeurCellule` — complétez le référentiel de codification (annexe DGI, ambiguïté A22) ou saisissez la liasse en EFI assisté. (limitation connue A22 — référentiel de codification à valider par l'expert-comptable avant dépôt SIMPL) |
| Cessation & e-facturation | OK | evenement=n° 1 — cessation au 2026-12-31 · situation={"annee": 2026, "evenements": ["<ActivityEvent cessation 2026-12-31>"], "evenement": "<ActivityEvent cessation 2026-12-31>", "declaration": {"evenement_id": 1, "annonce": "Cessation définitive d'activ · controles=[{"code": "activite.regularisation_stocks_a_examiner", "niveau": "avertissement", "message": "TVA à régulariser sur les stocks et biens non amortissables : montant à saisir par l'expert-comptable (aucun taux n'est deviné · rd_sortie={"annee": 2026, "periode": 1, "regime": 4, "date_from": "2026-01-01", "date_to": "2026-12-31", "xml": "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<!-- Declarant : SOCIETE RECETTE M · declaration_tva_sortie=<TaxDeclaration TVA 2026 brouillon> · e_facture=FV25-08 → 8 (genere) · e_facture_envoi=<EInvoiceDocument facture=23 envoye> · e_facture_accuse=<EInvoiceDocument facture=23 accepte> · e_facture_situation={"annee": null, "documents": ["<EInvoiceDocument facture=23 accepte>", "<EInvoiceDocument facture=20 accepte>", "<EInvoiceDocument facture=17 accepte>", "<EInvoiceDocument facture=14 accepte>", "<EInv · mentions_obligatoires=17 |
| Écrans | OK | 23 écrans testés, 0 en erreur |

**Résultat** : 19 contrôles, 0 en échec, 0 alerte(s).
