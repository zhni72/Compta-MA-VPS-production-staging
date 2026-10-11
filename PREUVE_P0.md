# Preuve fonctionnelle AVANT / APRÈS — correctifs P0

Généré par `tools/p0_preuve_avant_apres.py` (lecture seule) sur `compta_ma.db` — société « SOCIETE RECETTE MAROC SARL AU ».

## P0.1 — Collisions de routes API / interface (`/audit`, `/audit/export`, `/stocks`)

| Ecran | Avant (API a la racine) | Apres (API sous /api) |
|---|---|---|
| `/audit` | **HTTP 401** | **HTTP 200** |
| `/audit/export` | **HTTP 401** | **HTTP 200** |
| `/stocks` | **HTTP 401** | **HTTP 200** |

- Sans session (client vierge) : `/audit` -> HTTP 303 (`/connexion?next=/audit`).
- API isolee : `/api/audit` sans jeton -> HTTP 401 ; avec jeton -> HTTP 200.

## P0.2 — Relevé EDI TVA : base éligible et TVA sur la même fraction

Facture **FA26-12** : total facture 9000.00 HT / 1800.00 TVA / 10800.00 TTC — reglement de 4320.00 le 18/12/2026.

| Ligne EDI | mht | tva | ttc | tva = mht x 20 % ? |
|---|---|---|---|---|
| **Avant** (ancienne formule) | 9000.00 | 720.00 | 9720.00 | **NON** |
| **Après** (base éligible commune) | 3600.00 | 720.00 | 4320.00 | oui |

Scan complet : **24 périodes** (2025-2026), **0 ligne(s) incohérente(s)** après correctif (**45 avant correctif**, cf. audit J9).

## P0.3 — ETIC : notes 9 (617) et 4 (619)

- Ancien filtre (`account_number[:2] in ('617',)`) : **0 compte(s)** -> note 9 vide (défaut constaté en recette).
- Nouveau filtre (`startswith('617')`) : **6 compte(s)** = ['6171', '61711', '6174', '61741', '61744', '61768'].
- Note 9 après correctif : **total 203295.60 DH** sur 6 compte(s).
- Note 4 (amortissements 28x + dotations 619x) : ['2834', '6193'] (total algébrique -12000.00).

## P0.4 — Documents de facture : aucune ligne / ventilation à zéro

- 74 facture(s) balayée(s) par `pdf_facture()` : **0 refusée(s)**, 0 en incohérence détectée.
- Cas nominal (FA26-12 et les 73 autres) : le PDF contient la ligne « Détail des lignes » réconciliée avec les totaux et une ventilation de TVA non vide (balayage `tools/scan_documents_facture.py` : 74 factures, 0 anomalie PDF et 0 anomalie d'écran).
- Une ligne à montant nul, ou une facture sans ligne avec des totaux non nuls, est désormais **refusée à la validation** et le **document est refusé** (`DocumentIncoherentError`) ; l'écran de détail et l'aperçu affichent l'avertissement « Document incohérent ».
