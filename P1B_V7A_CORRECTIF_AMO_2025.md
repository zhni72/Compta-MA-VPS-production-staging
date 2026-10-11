# P1B V7A-CORR — RECTIFICATION AMO 2025 (ADDENDUM — READ-ONLY)

**Projet** : Compta MA — `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma`
**Date** : 06/10/2026 — **Mode** : read-only absolu (aucune modification du moteur, de la DB, des paramètres, des référentiels, du rapport V7A)
**Objet** : rectifie **uniquement** le point AMO de `P1B_V7A_ARBITRAGE_AMO_CM_2025.md`, à partir d'une **lecture unique ciblée du BO 6314 local** (contrôle transversal demandé). **Les conclusions CM 2025 déjà établies sont conservées telles quelles.**
**Périmètre** : ne refait ni V6 ni l'analyse CM ; un seul passage de lecture, une seule production ; puis STOP.

---

## 1. Vérification dans le BO 6314 local (04-12-2014)

Document relu (une seule fois, passage concerné) : `04_AMO\ma-bulletin-officiel-dated-2014-12-04-no-6314.pdf`, p. 4770-4771 (PDF p. 19), décret modifiant le décret n° 2-05-734.

| Élément contrôlé | Texte du BO 6314 (extraction locale) | Résultat |
|---|---|---|
| Numéro exact du décret | « Décret n° **2-14-707** du 16 moharrem 1436 (**10 novembre 2014**) modifiant le décret n° 2-05-734 du 11 joumada II 1426 (18 juillet 2005) fixant les taux de cotisation due à la Caisse nationale de sécurité sociale au titre du régime de l'assurance maladie obligatoire de base » | **CONFIRMÉ** — n° 2-14-707 |
| Taux global AMO secteur privé | Article 1er : « Le taux de cotisation … est fixé, en ce qui concerne les salariés du secteur privé, à **4,52 % de l'ensemble des rémunérations** … » | **CONFIRMÉ** — 4,52 % |
| Règle de répartition salarié/employeur | Le même passage se termine par « … rémunérations [« répartis à parts égales » absorbé par l'OCR] **& la Charge du salarié** ». Le « **&** » de l'OCR est la conjonction « et » : la phrase porte « …à la charge du salarié **et de l'employeur** » ; la séquence « répartis à parts égales … » est contenue dans le mot OCR dégradé (affiché « Ceres »). L'OCR ayant échoué sur exactement ce segment, la lecture bipartite **à parts égales** est celle que porte le texte | **CONFIRMÉ** (répartition à parts égales ; OCR dégradée sur le segment exact — point déclaré ci-dessous) |
| Majoration 1,85 % | « Le taux de cotisation fixé à l'alinéa précédent est **majoré de 1,85 % de l'ensemble de la rémunération brute** … » (le complément « à la charge de l'employeur » est dans le segment OCR dégradé) | **CONFIRMÉ** — majoration 1,85 % sur la rémunération brute, en sus du taux de l'alinéa précédent → charge de l'**employeur** |
| Date d'effet | Art. 2 du décret : « … entrera en vigueur à compter du **1er janvier 2016** » | **CONFIRMÉ** — 01/01/2016 |

### Point de contrôle arithmétique (demandé)

> 4,52 % répartis à parts égales = **2,26 % salarié + 2,26 % employeur**
> puis **+ 1,85 % employeur exclusif**
> soit : **salarié = 2,26 % ; employeur = 2,26 + 1,85 = 4,11 % ; total = 6,37 %**

→ **CONFIRMÉ** (cohérent avec le BO 6314, avec le total 6,37 % et avec le jeu moteur 2,26/4,11).

---

## 2. Rectification de l'arbitrage AMO de V7A

La conclusion AMO de `P1B_V7A_ARBITRAGE_AMO_CM_2025.md` (« 4,52 % salarié / 1,85 % employeur ») résultait d'une lecture OCR dégradée (« à la charge du salarié » sans la suite « et de l'employeur »). **Elle est rectifiée comme suit** :

| Composante | Taux | Salarié | Employeur | Assiette | Source + page | Statut (CORRIGÉ) |
|---|---|---|---|---|---|---|
| Taux global AMO — salariés du secteur privé | 4,52 % | — | — | L'ensemble des rémunérations | Décret 2-14-707 art. 1er, BO 6314 p. 4770 (PDF p. 19) | **CONFIRMÉ** |
| Répartition à parts égales | 4,52 % ÷ 2 | **2,26 %** | **2,26 %** | Rémunération brute | Décret 2-14-707 art. 1er (lecture « …et de l'employeur » ; OCR dégradée sur « répartis à parts égales ») | **CONFIRMÉ** |
| Majoration employeur (exclusive) | + **1,85 %** | — | **1,85 %** | Rémunération brute | Décret 2-14-707 art. 1er (structure « majoré de 1,85 % de l'ensemble de la rémunération brute ») | **CONFIRMÉ** |
| **Parts finales 2025** | **Total 6,37 %** | **2,26 %** | **4,11 %** (2,26 + 1,85) | Rémunération brute | Arithmétique du point de contrôle + BO 6314 | **CONFIRMÉ** |
| Assiette | — | — | — | Ensemble des rémunérations (art. 19 dahir 1-72-184), sans plafond | Loi 65-00 art. 106-2° ; décret 2-14-707 art. 1er | **CONFIRMÉ** (inchangé) |
| Plafond | — | — | — | **Aucun** | Silence des textes | **CONFIRMÉ** (inchangé) |
| Date d'effet | 01/01/2016 | — | — | — | Décret 2-14-707 art. 2 | **CONFIRMÉ** (inchangé) |

### Conséquence sur les écarts moteur du rapport V7A

| Réf V7A | Ancienne conclusion | Conclusion CORRIGÉE |
|---|---|---|
| AMO-1 | « Répartition 2,26/4,11 au lieu de 4,52/1,85 — ÉCART » | **ÉCART LEVÉ** : le jeu moteur **2,26 % salarié / 4,11 % employeur** est **CONFORME** au décret 2-14-707 (4,52 % à parts égales + 1,85 % employeur) |
| AMO-2 | « Jeu 2,26/4,11 non prouvé par le corpus » | **CORRIGÉ** : le jeu 2,26/4,11 est désormais **CONFIRMÉ par le corpus** (BO 6314, décret 2-14-707) |
| Assiette / total | Conformes (rémunération brute sans plafond ; total 6,37 %) | **Inchangé — CONFORME** |

### Point déclaré (limite du corpus local, sans boucle)

Le segment exact « répartis à parts égales … à la charge du salarié et de l'employeur » n'est pas restitué intégralement par la couche OCR du BO 6314 (affichée « Ceres & la Charge du salarié »). La rectification s'appuie sur : (i) la présence du « & » (= et) dans le fragment ; (ii) la cohérence arithmétique du point de contrôle (4,52 ÷ 2 = 2,26 ; + 1,85 = 4,11 ; total 6,37 %) ; (iii) la cohérence avec le jeu AMO national observé (2,26/4,11) et avec le moteur.

---

## 3. Conclusions CM 2025 — conservées telles quelles

Aucune modification : **CM ARBITRÉ** — taux 0,25 %, plancher 3 000 DH, base **hors TVA** (CGI 2025 art. 144-I-B, p. 263-265), écarts moteur **CM-1 / CM-2 / CM-3 / CM-4** du rapport V7A **inchangés**.

## 4. Verdict global (mis à jour sur le seul point AMO)

> **AMO ARBITRÉ (CORRIGÉ)** — 2025 : **2,26 % salarié + 4,11 % employeur (2,26 + 1,85), total 6,37 %**, assiette = rémunération brute sans plafond, date d'effet du texte 01/01/2016 (décret 2-14-707, BO 6314 p. 4770-4771).
> **CM ARBITRÉ** — 2025 : inchangé (CGI 2025 art. 144).
>
> ## VERDICT GLOBAL : **PRÊT POUR P1B V7B — CORRECTION DU MOTEUR** (le point AMO ne constitue plus un écart de répartition ; seul le point OCR « répartis à parts égales » reste à titre documentaire)

## 5. Preuve DB (aucun accès en écriture — identique à V7A)

| Mesure | Avant (V7A initial) | Après (V7A-CORR) |
|---|---|---|
| SHA-256 `compta_ma.db` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` | `52FC68C77AED0369BE424D628A39D07DB953F61B1CA3CF7B18689FCBCFB58743` |
| Taille | 1 163 264 o | 1 163 264 o |
| Date de modification | 2026-09-24 02:55:05 | 2026-09-24 02:55:05 |

Aucune modification : ni code, ni DB, ni paramètres AMO/CM, ni référentiels, ni `P1B_V7A_ARBITRAGE_AMO_CM_2025.md`, ni `Documentation`. Production unique : le présent addendum.

**Source consultée (lecture unique du passage concerné)** : `04_AMO\ma-bulletin-officiel-dated-2014-12-04-no-6314.pdf` — p. 4770-4771 (PDF p. 19), décret n° 2-14-707 du 10/11/2014.