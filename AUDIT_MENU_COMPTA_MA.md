# AUDIT MENU — COMPTA_MA (lecture seule)

> Date (UTC) : 2026-10-03 — Sources : `app/web/templates/base.html` (lignes 28-112, 12 groupes, ~50 liens), `app/web/routes.py`, `app/web/ecrans_lecture.py`, `tests/test_menu_p2.py`. Aucune modification effectuee.

## Rubriques en doublon

| # | Rubriques | Verdict |
|---|---|---|
| D1 | `IS` (`/liasse`, active `liasse`) / `Liasse fiscale` (`/liasse`, active `liasse-fiscale`) | Doublon strict a fusionner : meme route, meme handler `page_liasse` (toujours `active="liasse"`), donc `Liasse fiscale` jamais surligne. |
| D2 | `Factures de vente` (`/factures?type=vente`, Commerce) / `Factures` + `Avoirs` (`/factures?type=vente`, E-facturation) | Doublon strict : 3 libelles vers meme URL, meme `liste_factures` (active `ventes`/`achats`, jamais `factures`/`avoirs`). Aucun filtre avoir dedie cote GET. |
| D3 | `Statuts de transmission` (`/e-facturation`) / `Rejets / reemission` (`/e-facturation`) | Doublon strict : meme route `page_e_facturation` (toujours `active="e-facturation"`), aucun filtre rejet. |
| D4 | `Exercices` / `Cloture` / `Reouverture controlee` / `Verrouillage` (tous `/parametres/exercices`) | 4 rubriques vers 1 page `page_exercices` (toujours `active="exercices"`). Cloture/Reouverture/Verrouillage = actions, pas pages. Seul `A-nouveaux` est distinct. |
| D5 | `Dossier de depot` / `Paiement` / `Certificat` / `Cessation` (tous `/greffe`) + `PV d'AG` / `Rapport de gestion` (`/greffe?piece=...`) | 6 rubriques vers 1 page `page_greffe` (toujours `active="greffe"`, param `piece` ignore). Convertir en onglets/ancres ou supprimer. |
| D6 | `Salaries` / `Bulletins` / `Cycles` (`/paie`, `?vue=` ignore) ; `Articles` / `Valorisation` (`/stocks`, `?vue=` ignore) | Meme handler, param ignore, toujours `active="paie"`/`"stocks"`. Tenables comme onglets uniquement. |
| D7 | `Amortissements lineaires` / `degressifs` / `Cessions` (`/immobilisations/etats?...`) | Meme handler (toujours `active="immobilisations"`). Params lus mais cles `immobilisations-lineaire/-degressif/-cessions` mortes. |
| D8 | `Referentiels fiscaux` (`/parametres/referentiels`) / `Referentiels EDI` (`/tva/edi`) | Quasi-doublon d'intitule, pages differentes : renommer (ex. `Taux et baremes` vs `Releve TVA / EDI`). |

## Routes identiques

- `/factures?type=vente` x3 ; `/e-facturation` x2 ; `/liasse` x2 ; `/greffe` x4 + `/greffe?piece=` x2 ; `/parametres/exercices` x4 ; `/paie` x3 (`?vue=` ignore) ; `/stocks` x2 (`?vue=` ignore) ; `/immobilisations/etats` x3 ; `/audit/export` = telechargement CSV, pas une page (a retirer du menu).

## Problèmes d'état actif

1. Clés `active` mortes (jamais posées par aucun handler) : `factures`, `avoirs`, `e-facturation-rejets`, `liasse-fiscale`, `cloture`, `reouverture`, `verrouillage`, `cessation`, `greffe-paiement`, `greffe-certificat`, `greffe-pv`, `greffe-rapport`, `immobilisations-lineaire`, `immobilisations-degressif`, `immobilisations-cessions`, `stocks-valorisation`, `paie-bulletins`, `paie-cycles`, `paie-ecritures`, `paie-dts`, `audit-export`, `referentiels-edi`, `journal` (~23 clés).
2. Double surlignage réel : `base.html:40` — `Journal comptable` actif si `active in ('journal','ecritures')`, or `page_journal` pose `active="ecritures"` (routes.py:1254) comme `Saisie des écritures` => les 2 liens actifs en même temps sur `/etats/journal` (idem `?journal_code=OD` au lieu de `Écritures de paie`).
3. `?vue=` / `?piece=` décoratifs : Paie/Stocks/Greffe sans effet `active`.
4. `/audit/export` (CSV téléchargé, routes.py:2405) avec clé `audit-export` : jamais d'état à afficher.
5. `Référentiels EDI` teste `referentiels-edi` mais `page_tva_edi` pose `tva-edi` (routes.py:1392) => jamais surligné.
6. Pas de surlignage du groupe parent : 12 `group-title` statiques, aucun `aria-current`.

## Arborescence recommandée

> Principe : 1 rubrique = 1 route ; les variantes (`?vue=`, `?piece=`, `?mode=`) deviennent des onglets internes avec `active` unique + sous-onglet.

- Tableau de bord `/`
- Commerce : Tiers `/tiers` · Factures (Vente/Achat/Avoirs en onglets `/factures?type=...&doc=...`) · Règlements `/reglements`
- Comptabilité : Écritures `/ecritures` · Journal `/etats/journal` (corriger `active=journal`) · Grand livre · Balance · Plan comptable `/comptes`
- États de synthèse : Bilan · CPC · ESG · ETIC
- Immobilisations (1 page + onglets : Fiches / Linéaires / Dégressifs / Cessions)
- Stocks (1 page + onglets : Articles / Mouvements / Inventaire / Valorisation / Provisions)
- Paie (1 page + onglets : Salariés / Bulletins / Cycles ; DTS-PDF en lien séparé ; supprimer `Écritures de paie` du menu ou filtre enregistré avec `active` propre)
- Fiscalité : TVA `/tva` · Relevé/EDI `/tva/edi` · IS & Liasse `/liasse` (fusionner IS+Liasse)
- Greffe : 1 rubrique `Dossier de dépôt / Juridique` (PV, rapport, paiement, certificat, cessation en sections internes)
- Clôture : Exercices (+actions Clôture/Réouverture/Verrouillage en boutons) · À-nouveaux
- E-facturation : 1 rubrique `/e-facturation` (onglets Tous/Rejets) ; supprimer Factures/Avoirs dupliqués
- Audit : Journal `/audit` (bouton Export CSV, pas de rubrique) · Événements `/activite` · Intégrité `/audit/integrite`
- Paramètres : Société · Journaux · Utilisateurs · Référentiels fiscaux · Rapprochement bancaire (à déplacer, ex. Comptabilité/Trésorerie) · API docs (lien externe, sans état actif)

## Corrections prioritaires

1. P0 — Double actif Journal : `page_journal` -> `active="journal"` (ou condition sidebar `active == 'ecritures'` seule pour Saisie). (base.html:40, routes.py:1254)
2. P0 — Fusionner doublons stricts : IS+Liasse ; Factures/Avoirs e-facturation -> 1 entrée ; Statuts+Rejets -> 1 entrée + filtre `?statut=rejete` ; Clôture/Réouverture/Verrouillage -> boutons de `/parametres/exercices` ; Paiement/Certificat/Cessation/PV/Rapport -> sections de `/greffe`.
3. P1 — `?vue=`/`?piece=` fonctionnels : lire le param dans `page_paie`, `page_stocks`, `page_greffe` et poser `active` + onglet (ou supprimer les sous-rubriques).
4. P1 — `/audit/export` : retirer du menu, bouton dans `/audit`.
5. P1 — `Référentiels EDI` : aligner clé (`tva-edi`) ou renommer le libellé.
6. P2 — États immo : soit clés `active` distinctes réellement posées, soit 1 rubrique + onglets.
7. P2 — Parent actif + `aria-current="page"` pour l'accessibilité.
8. Tests : étendre `tests/test_menu_p2.py` — unicité `href`, `active` posé par chaque handler parmi clés du menu, aucun `active` mort, jamais 2 `.active` simultanés.

## Logique parent/enfant actuelle

- Pas de vraie hiérarchie : `base.html` = liste plate de ~50 liens `<a>` regroupés sous 12 `group-title` purement visuels (aucun `<ul>/<li>`, aucun repli, aucun `aria-expanded`, aucun marquage parent-actif).
- Le "parent" est donc décoratif : ouvrir `/paie?vue=bulletins` n'allume aucun parent Paie distinct de `/paie` (même `active="paie"`), et les 6 rubriques `/greffe` partagent le même état.
- Routage : `app/main.py` monte `web.router` (métier, `routes.py`) + `web_lecture.router` (`ecrans_lecture.py`, GET lecture seule) à la racine ; pas de préfixe par section, params `?vue=`/`?piece=` ignorés par `page_paie`/`page_stocks`/`page_greffe` (signatures : seul `year`).
- Conséquence : l'utilisateur ne peut pas savoir dans quelle sous-rubrique il se trouve ; les tests `test_menu_p2.py` ne vérifient que le statut HTTP, pas l'unicité ni l'état actif.

## Corrections UX/UI recommandées (sans changer les URLs métier)

1. Un seul niveau cliquable par section + onglets internes (Paie, Stocks, Greffe, E-facturation, Immos) avec état d'onglet visible.
2. `aria-current="page"` sur le lien actif + surlignage du `group-title` parent.
3. Retirer du menu tout ce qui n'est pas une page : `/audit/export` (CSV), actions Clôture/Réouverture/Verrouillage (boutons), `/docs` (garder en lien externe muet).
4. Renommer les quasi-doublons (`Référentiels fiscaux` vs `Référentiels EDI`, `Rapprochement bancaire` hors Paramètres).
5. Fil d'Ariane (section > page) pour les 12 groupes.


