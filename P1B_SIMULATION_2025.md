# P1-b — Simulation (lecture seule) de la régularisation de la paie 2025

Généré par `tools/p1b_simulation_2025.py` : **aucune écriture n'est créée ni modifiée**. Les projections servent de base de validation avant la séquence réelle (réouverture → régularisation → reclôture → régénération des à-nouveaux 2026).

## 1. État actuel de l'exercice 2025 (référence)

- Statut de l'exercice 2025 : **closed** ; verrous de période : aucun
- Écritures de charges de personnel 2025 hors module : **12** (sources : ['import_jeu_j9'])
- Charges de personnel 2025 (617x) : **144,000.00 DH**
- Résultat comptable 2025 : **73,600.00 DH** (benefice)
- À-nouveaux 2026 : écriture EC202600001 — débit 387,520.00 DH, 11 lignes, équilibre True
- Exonération de cotisation minimale 2025 : True (12 mois d'activité depuis 2025-01-01, fin d'exonération 2028-01-01)

## 2. Faisabilité de la séquence (pré-requis)

| Pré-requis | État | Commentaire |
|---|---|---|
| Barème de paie 2025 (`BAREMES_PAIE`) | **À FOURNIR** | sans le barème officiel 2025 (IR/CNSS/AMO), la paie 2025 ne peut pas être **régénérée par le module** (`app/core/rates_ma.py`) |
| Taux d'IS 2025 (`IS_RATES_BY_YEAR`) | **À FOURNIR** | le recalcul fiscal 2025 exige le taux de l'exercice (loi de finances 2025) : aucun taux n'est deviné |
| Paramètres de cotisation minimale 2025 | **À FOURNIR** | taux 0,25 %, plancher 3 000 DH et exonération : à confirmer pour 2025 |
| Réouverture encadrée + régénération des à-nouveaux | **OK** | livré et testé en P1 (motif, verrous, comparaison avant/après) |

## 3. Impact projeté (illustration — barème 2026 faute de barème 2025)

- Charges de personnel 2025 : 144,000.00 → **365,947.20 DH** (+221,947.20 DH)
- Résultat 2025 : 73,600.00 → **-148,347.20 DH** (perte)
- IS 2025 : **calcul refusé** — Taux d'IS non paramétré pour l'exercice 2025 : aucun taux n'est deviné. Ajoutez le barème officiel de l'exercice (loi de finances) dans `IS_RATES_BY_YEAR` (`app/core/rates_ma.py`) avant tout calcul fiscal.
- À-nouveaux 2026 : report à nouveau ajusté de +221,947.20 DH (total actuel 387,520.00 DH) — comparaison avant/après restituée par `closing.regenerer_a_nouveaux`
- Impact 2026 : recalcul intégral (Balance → CPC → ESG → Bilan → ETIC → IS) sur les nouveaux à-nouveaux, sans correction manuelle.

## 4. Séquence proposée (à valider avant exécution)

1. Fournir le **barème de paie 2025** et le **taux d'IS 2025** (paramétrage).
2. `reouvrir_exercice(2025, motif=…, regenerer_a_nouveaux=True)` — opération tracée.
3. Retirer les 12 écritures de paie synthétiques 2025 (réinitialisation contrôlée et tracée) puis générer les **12 paies 2025 par le module**.
4. `cloturer_exercice(2025)` puis `regenerer_a_nouveaux(2025)` : écarts par compte restitués pour validation.
5. Recalcul complet 2026 et contrôle de l'équilibre des à-nouveaux avant validation définitive.

**Tant que les étapes 1 à 5 ne sont pas validées, aucune écriture 2025 n'est touchée** (exigence du donneur d'ordre).
