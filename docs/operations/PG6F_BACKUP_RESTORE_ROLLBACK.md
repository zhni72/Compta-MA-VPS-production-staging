# PG6F — Documentation opérationnelle Backup / Restore / Rollback PostgreSQL

| Élément | Valeur |
|---|---|
| Projet | `C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma` |
| Branche | `pg6f-backup-restore` |
| Domaine | **PG6F** — sauvegarde, validation, restauration et retour arrière PostgreSQL |
| Nature | Documentation opérationnelle — **aucune modification** de code, test, Docker ni base |
| Serveur et outils | PostgreSQL **18.1** — `pg_dump` **18.1**, `pg_restore` **18.1**, `psql` **18.1** |
| Base de référence (staging) | `compta_ma_staging` — 43 tables métier, 3131 lignes, révision Alembic `a50e63267636` |
| Verdict de la recette PG6F | **PG6F_DATA_PASS** |

> Ce document décrit la procédure **validée** pour sauvegarder, valider, tester et
> restaurer la base PostgreSQL de **Compta MA** en version **18.1**, ainsi que la
> stratégie de **retour arrière** en production. Il ne contient **aucun secret** :
> les noms d'hôtes, chemins, mots de passe et délais de production sont représentés
> par des **placeholders** — `<PRODUCTION_DB>`, `<ROLLBACK_DB>`, `<BACKUP_FILE>` — et
> ne doivent jamais être remplacés par des valeurs réelles dans un fichier committé.
>
> **Artéfact de référence.** Les commandes **exactes** exécutées et validées en recette
> PG6F sont décrites au §5.1 (sauvegarde), §7.3 et §14.4 (restauration). Les commandes
> présentées comme « **variante de production recommandée** » sont des **recommandations
> d'exploitation** et **ne sont pas** l'artéfact PG6F validé. Voir §5.2 pour la portée du
> SHA256 validé.

## ⚠️ RÈGLES DE SÉCURITÉ CRITIQUES — à lire avant toute opération

- **JAMAIS** restaurer directement sur la base de production en première action.
- **JAMAIS** accorder `CREATEDB` ou `SUPERUSER` à `compta_ma_migrator`.
- **JAMAIS** utiliser `compta_ma_app` pour les migrations ou les restaurations.
- **JAMAIS** placer un mot de passe PostgreSQL **littéral** dans une commande, dans un
  fichier committé ou dans un journal. (L'invite interactive `-W` reste acceptable pour
  un usage **manuel ponctuel** — cf. §3.1.)
- **JAMAIS** faire confiance à une sauvegarde au seul motif que `pg_dump` retourne `0` :
  **vérifier le SHA256 et `pg_restore --list`**.
- **TOUJOURS** réaliser un test de restauration avant de s'appuyer sur une sauvegarde.
- **TOUJOURS** prendre une sauvegarde fraîche de l'état de production courant avant
  tout retour arrière d'urgence.

---

## 1. Objet et périmètre

**Dans le périmètre :**

- sauvegarde logique d'une base **PostgreSQL 18.1** avec `pg_dump` au **format custom** ;
- validation d'intégrité de l'archive : **SHA256** + lisibilité **`pg_restore --list`** ;
- **test de restauration isolé** dans une base **neuve** (`compta_ma_restore_test` /
  `<ROLLBACK_DB>`) — jamais par-dessus la production ;
- validations structurelles et de données (tables, lignes, révision Alembic, index,
  séquences, privilèges) ;
- **stratégie de retour arrière (rollback) production** et liste de contrôle post-rollback.

**Hors périmètre :**

- aucune modification du **code applicatif**, des **tests**, des fichiers **Docker** ni
  des **bases de données** ;
- aucune exécution de `pg_dump`, `pg_restore`, `psql`, Alembic, `pytest` ou Docker dans
  le cadre de la rédaction de ce document ;
- aucune création ni suppression de base ;
- aucune exposition de mot de passe ou de secret ;
- **aucune durées de sauvegarde / restauration / RTO / RPO ne sont garanties ici** :
  elles dépendent de l'hôte, du volume de données et du réseau, **non mesurés dans ce
  dépôt**. Les valeurs de production doivent être relevées sur l'environnement réel.

Ce document s'applique à la base applicative `compta_ma` (staging de référence :
`compta_ma_staging`) et à toute base PostgreSQL 18.1 du même modèle de rôles.

---

## 2. Rôles et séparation des privilèges

| Rôle | Usage | Attributs connus | Connexion |
|---|---|---|---|
| `compta_ma_owner` | Propriétaire de la **base** et du schéma `public` | `NOLOGIN` | non |
| `compta_ma_migrator` | **Migrations Alembic**, sauvegarde et restauration | `LOGIN`, `SUPERUSER=false`, `CREATEDB=false`, **MEMBRE DE** `compta_ma_owner` | oui |
| `compta_ma_app` | Exécution applicative (**runtime**) | `LOGIN`, aucun `CREATE` sur le schéma | oui |
| rôle administratif (ex. `postgres`) | Création / suppression de base **uniquement** | superutilisateur de l'instance | oui |

Règles de séparation :

1. La **création et la suppression de base** (`CREATE DATABASE` / `DROP DATABASE`) sont
   réalisées **exclusivement** avec un **rôle administratif** tel que `postgres`.
2. `compta_ma_migrator` **n'est ni `SUPERUSER` ni `CREATEDB`**. Il ne peut donc **pas**
   créer ou supprimer une base ; il opère uniquement **à l'intérieur** d'une base
   existante (schéma, `pg_restore`, migrations).
3. `compta_ma_migrator` est **membre de** `compta_ma_owner` : il hérite des droits du
   propriétaire (création du schéma `public` par Alembic) sans jamais devenir
   superutilisateur.
4. `compta_ma_app` **ne sert jamais** à migrer ni à restaurer. Il ne dispose que de
   `CONNECT` sur la base et `USAGE` sur le schéma, plus `SELECT/INSERT/UPDATE/DELETE`
   et l'usage des séquences via les **privilèges par défaut** accordés au migrator.
5. `PUBLIC` reste **restreint** : `REVOKE ALL ... FROM PUBLIC` sur la base et le schéma,
   `REVOKE CREATE` explicite.

Référence d'implémentation : `docker/postgres/10-init-compta-roles.sh` (recette PG6E2).

---

## 3. Règles de sécurité opérationnelles

1. **Jamais de restauration directe sur la production en première action.** La première
   cible d'une restauration est **toujours** une base neuve, isolée.
2. **Jamais `CREATEDB` ni `SUPERUSER` pour `compta_ma_migrator`.**
3. **Jamais `compta_ma_app` pour migrer ou restaurer.**
4. **Jamais de mot de passe PostgreSQL littéral** dans une commande, dans un fichier
   committé ou dans un journal. La gestion des mots de passe (fichier `pgpass` /
   `PGSERVICEFILE`, invite interactive `-W`, ce qu'il faut éviter) est détaillée au
   §3.1.
5. **Ne jamais se fier au seul code de sortie `0` de `pg_dump`.** Vérifier :
   - le **SHA256** du fichier ;
   - la **lisibilité de l'archive** via `pg_restore --list`.
6. **Toujours tester une restauration** avant de s'appuyer sur une sauvegarde pour un
   rollback.
7. **Toujours prendre une sauvegarde fraîche** de l'état de production courant **avant**
   un retour arrière d'urgence.

### 3.1 Gestion des mots de passe

- **`-W` (invite interactive) est acceptable** pour les opérations **ponctuelles /
  manuelles** : PostgreSQL demande alors le mot de passe à l'opérateur et **le mot de
  passe n'est jamais inclus dans la ligne de commande** (donc absent de l'historique de
  commandes et des journaux d'invocation). C'est le mode utilisé par la **restauration
  PG6F validée** (§7.3, §14.4).
- **Ne jamais** placer un mot de passe PostgreSQL **littéral** dans une commande, dans un
  fichier committé ou dans un journal.
- **Automatisation non surveillée** : préférer un fichier **`pgpass` correctement
  protégé** lu via **`PGPASSFILE`**, ou un **service** via **`PGSERVICEFILE`**.
- **Éviter `PGPASSWORD`** pour les scripts persistants : selon l'environnement, une
  variable d'environnement peut être **exposée** à d'autres processus ou outils.
- Pour les **contrôles en lecture seule** (§4, §8), `psql -w --no-psqlrc` évite toute
  invite (pratique en automatisation) ; `-W` reste valable en **manuel ponctuel**.
- **Ne jamais documenter d'identifiant réel** (hôte, utilisateur, mot de passe, chemin)
  dans ce document ni dans un rapport : utiliser des **placeholders** (`<PRODUCTION_DB>`,
  `<ROLLBACK_DB>`, `<BACKUP_FILE>`).

Bonnes pratiques complémentaires : exécuter les commandes avec le rôle minimal
nécessaire et **ne jamais écrire de secret** dans ce document ni dans un rapport.

---

## 4. Contrôles préalables à la sauvegarde

À exécuter **avant** tout `pg_dump`. Les commandes ci-dessous utilisent `-w`
(authentification via le fichier `pgpass` / service, **sans** invite) ; pour un usage
**manuel ponctuel**, l'invite `-W` est également acceptable (cf. §3.1).

| Contrôle | Commande (rôle `compta_ma_migrator`) | Attendu |
|---|---|---|
| Rôle et base courants | `psql -w --no-psqlrc -U compta_ma_migrator -d <PRODUCTION_DB> -c "SELECT current_user, current_database();"` | `compta_ma_migrator`, `<PRODUCTION_DB>` |
| Version serveur | `psql -w --no-psqlrc -U compta_ma_migrator -d <PRODUCTION_DB> -c "SHOW server_version;"` | `18.1` |
| Encodage | `psql -w --no-psqlrc -U compta_ma_migrator -d <PRODUCTION_DB> -c "SHOW server_encoding;"` | `UTF8` |
| Locale / provider | `psql -w --no-psqlrc -U compta_ma_migrator -d <PRODUCTION_DB> -c "SELECT datlocprovider, datcollate, datctype FROM pg_database WHERE datname = current_database();"` | `c` (`libc`), `French_France.1252` |
| Révision Alembic | `psql -w --no-psqlrc -U compta_ma_migrator -d <PRODUCTION_DB> -c "SELECT version_num FROM alembic_version;"` | révision attendue (ex. `a50e63267636`) |
| Nombre de tables métier | `psql -w --no-psqlrc -U compta_ma_migrator -d <PRODUCTION_DB> -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name <> 'alembic_version';"` | 43 |
| Clients `pg_dump` / `pg_restore` | `pg_dump --version` ; `pg_restore --version` | `18.1` (alignés sur le serveur) |

Contrôles d'exploitation :

- **Écritures applicatives maîtrisées** : pour un instantané cohérent, se placer si
  possible en **maintenance** / arrêt des écritures, ou accepter la sémantique MVCC
  d'un `pg_dump` en ligne (instantané transactionnel unique).
- **Espace disque** suffisant pour l'archive et, plus tard, pour la base restaurée.
- **Chemin d'archive** (`<BACKUP_FILE>`) situé **hors** du dépôt Git et **jamais**
  committé (`backups/` est ignoré par `.gitignore`).
- **Secrets** : `pgpass` (`PGPASSFILE`) ou service (`PGSERVICEFILE`) **correctement
  protégé** pour l'automatisation ; invite `-W` acceptable en **manuel ponctuel** ;
  **éviter `PGPASSWORD`** pour les scripts persistants (cf. §3.1).

> Un `pg_dump` démarré sans ces contrôles peut produire une archive **valide mais non
> représentative** (mauvais encodage, mauvaise base, mauvaise révision). Les contrôles
> 4 et 5 sont **obligatoires**.

---

## 5. Procédure de sauvegarde

Sauvegarde logique au **format custom**, réalisée avec le rôle **`compta_ma_migrator`**
(**jamais** `compta_ma_app`, **jamais** `postgres`).

### 5.1 Commande PG6F réellement exécutée et validée (artéfact de référence)

La recette PG6F a exécuté et validé **exactement** cette commande — **sans** `--no-owner`
ni `--no-privileges` :

```powershell
# Rôle de sauvegarde : compta_ma_migrator (JAMAIS compta_ma_app, JAMAIS postgres)
pg_dump `
  -U compta_ma_migrator `
  -d compta_ma_staging `
  --format=custom `
  --no-password `
  --file="<BACKUP_FILE>"
```

- L'archive validée **contient les ACL** (les privilèges n'ont **pas** été supprimés).
- La compression observée est **gzip**, valeur **par défaut** du format custom : **aucun**
  flag `--compress` n'a été passé.
- Le **SHA256 validé** `C531BC59B8784E767554AD43F9C41F34819B7E5F18F32CC1B9006B02B770C972`
  appartient **uniquement** à **cette archive exacte** (§14.3).

### 5.2 Variante de production recommandée — *not the exact PG6F validated artifact*

La variante ci-dessous est une **recommandation d'exploitation** ; elle **n'est pas**
l'artéfact PG6F validé :

```powershell
# Recommended production variant — not the exact PG6F validated artifact.
pg_dump `
  -U compta_ma_migrator `
  -d <PRODUCTION_DB> `
  --format=custom `
  --compress=gzip `
  --no-owner `
  --no-privileges `
  --lock-wait-timeout=60s `
  --file="<BACKUP_FILE>"
```

| Option | Effet | Pourquoi (recommandation) |
|---|---|---|
| `--format=custom` | Archive PostgreSQL *custom* | Permet `pg_restore` sélectif et `--list`. Format validé PG6F. |
| `--compress=gzip` | Compression **gzip** explicite | Réduction de taille ; rend la compression **explicite** (le défaut du format custom est déjà `gzip`). |
| `--no-owner` | Pas de `ALTER ... OWNER TO` dans l'archive | La propriété est **réattribuée explicitement** à la restauration (`compta_ma_owner`). Évite les échecs si les rôles diffèrent. |
| `--no-privileges` | Pas d'ACL dans l'archive | Les `GRANT`/`REVOKE` sont **réappliqués explicitement** (§11.8), garantissant le modèle de sécurité cible. |
| `--lock-wait-timeout=60s` | Échec si un verrou bloque au-delà du délai | Évite un blocage indéfini d'une sauvegarde en ligne. |

> ⚠️ **Changer les options de `pg_dump` crée une archive différente.** En particulier,
> `--no-owner` et `--no-privileges` (absents de l'exécution PG6F validée) modifient le
> contenu de l'archive et donc son **SHA256**. Le SHA256 PG6F validé
> (`C531...770C972`) **ne doit PAS** être attendu sur un dump fraîchement généré avec une
> **autre** liste d'options.

### 5.3 Après exécution

- **vérifier le code de sortie** (`0` attendu) ;
- **ne pas** considérer la sauvegarde comme fiable sans les validations du §6.

> Note d'exploitation : `pg_dump` obtient le mot de passe depuis un fichier `pgpass` /
> service (`--no-password` en automatisation) ; pour un dump **manuel ponctuel**, l'invite
> interactive `-W` est acceptable (cf. §3.1). Le fichier produit doit rester un artefact
> d'exploitation (**hors** dépôt Git).

---

## 6. Validation SHA256 + `pg_restore --list`

Deux validations **indissociables** avant toute restauration de confiance.

**a) Empreinte SHA256 de l'archive** (Windows / PowerShell) :

```powershell
Get-FileHash -Algorithm SHA256 "<BACKUP_FILE>"
```

Équivalent Linux : `sha256sum "<BACKUP_FILE>"`.

Comparer l'empreinte obtenue à la **valeur de référence enregistrée** au moment de la
sauvegarde. Toute divergence **invalide** l'archive (corruption, transfert partiel,
mauvais fichier) : **STOP** (cf. §13).

> **Portée de la valeur de référence.** Le SHA256 PG6F validé
> (`C531...770C972`, §14.3) n'a de sens que pour **l'archive exacte** produite par la
> commande du §5.1. Toute modification des options de `pg_dump` (`--no-owner`,
> `--no-privileges`, `--compress`, filtres de schéma, etc.) produit une **archive
> différente**, donc un **SHA256 différent** : ne **jamais** comparer un dump fraîchement
> généré à la valeur PG6F si les options ont changé. La comparaison se fait **toujours**
> contre l'empreinte **enregistrée pour ce dump précis**.

**b) Lisibilité de l'archive (`pg_restore --list`, lecture seule) :**

```powershell
# Entête de l'archive (métadonnées + nombre d'entrées TOC)
pg_restore --list "<BACKUP_FILE>" | Select-Object -First 30

# Nombre d'entrées du TOC (Table Of Contents)
(pg_restore --list "<BACKUP_FILE>" | Measure-Object -Line).Lines
```

Puis vérifier des **objets critiques** présents dans le TOC :

```powershell
pg_restore --list "<BACKUP_FILE>" | Select-String "uq_period_locks_company_year_annual"
```

Attendus (valeurs **validées PG6F**, cf. §14) :

- entête indiquant `format` *custom*, `dbname` cible et **`TOC Entries: 613`** ;
- `pg_restore --list` **sans erreur** ;
- présence de l'index critique `uq_period_locks_company_year_annual`.

> `pg_restore --list` **ne modifie aucune base** : c'est une lecture d'archive. Utiliser
> la **même version majeure** (`18.1`) que le serveur cible.

---

## 7. Procédure de test de restauration vers une base NEUVE

> **Principe non négociable :** la **première** restauration vise **toujours** une base
> **neuve et isolée**, jamais la production. Base de test validée :
> `compta_ma_restore_test` ; placeholder générique : `<ROLLBACK_DB>`.

**Étape 7.1 — Créer la base neuve avec le RÔLE ADMINISTRATIF** (ex. `postgres`).
`compta_ma_migrator` n'ayant pas `CREATEDB`, cette étape **exige** un rôle
administratif. Match de l'encodage, de la locale et du propriétaire de la production :

```sql
-- Rôle : postgres (administratif, seule étape autorisée à créer une base)
CREATE DATABASE <ROLLBACK_DB>
    WITH OWNER          = compta_ma_owner
         TEMPLATE       = template0
         ENCODING       = 'UTF8'
         LOCALE_PROVIDER = libc
         LC_COLLATE     = 'French_France.1252'
         LC_CTYPE       = 'French_France.1252';
```

**Étape 7.2 — Restreindre `PUBLIC` et accorder `CONNECT`** conformément au modèle de
production (rôle administratif) :

```sql
REVOKE ALL ON DATABASE <ROLLBACK_DB> FROM PUBLIC;
GRANT CONNECT ON DATABASE <ROLLBACK_DB> TO compta_ma_app;
GRANT CONNECT ON DATABASE <ROLLBACK_DB> TO compta_ma_migrator;
```

**Étape 7.3 — Restaurer avec le RÔLE DE MIGRATION** (`compta_ma_migrator`), commande
**réellement exécutée et validée** en recette PG6F :

```powershell
# Rôle : compta_ma_migrator — commande PG6F RÉELLEMENT exécutée et validée
pg_restore `
  -U compta_ma_migrator `
  -d compta_ma_restore_test `
  -W `
  --no-owner `
  --exit-on-error `
  --single-transaction `
  "<BACKUP_FILE>"
```

> Base de test validée : `compta_ma_restore_test` ; pour un autre environnement, utiliser
> le placeholder `<ROLLBACK_DB>` (cf. étape 7.1).

| Option | Effet |
|---|---|
| `-W` | **Invite interactive** du mot de passe : acceptable pour une opération **manuelle ponctuelle** ; le mot de passe n'est **jamais** sur la ligne de commande (cf. §3.1). |
| `--no-owner` | Les objets sont créés par `compta_ma_migrator` (membre de l'owner) : aucun `ALTER OWNER` dépendant de rôles absents. |
| `--exit-on-error` | **Arrêt immédiat** au premier `SQL` en erreur — pas de restauration partielle silencieuse. |
| `--single-transaction` | Restauration **tout-ou-rien** : en cas d'erreur, rollback complet, base laissée vide et cohérente. |

> **La restauration PG6F validée n'a PAS utilisé `--no-privileges`.** L'archive validée
> contenait les **ACL** et la commande ci-dessus les restaure. Une **recommandation de
> production** peut, elle, choisir de **supprimer la restauration des ACL**
> (`--no-privileges`) puis de **réappliquer explicitement** les `GRANT`/`REVOKE` (§11.8) :
> il s'agit alors d'une **recommandation d'exploitation**, **pas** de la preuve PG6F.

**Résultat attendu :** `pg_restore` retourne le **code de sortie `0`**, et la base
restaurée contient 43 tables métier, 3131 lignes et la révision `a50e63267636`.

> Si `--exit-on-error` déclenche une erreur, **la base ne contient aucune donnée
> partielle** (`--single-transaction`). Corriger la cause (version d'outil, privilèges,
> extension) puis **recréer** la base avant de recommencer. **STOP** si la cause n'est
> pas comprise (cf. §13).

---

## 8. Validation structurelle

Toutes les requêtes ci-dessous sont en **lecture seule**, exécutées avec
`compta_ma_migrator` sur la base restaurée.

| Validation | Commande | Attendu |
|---|---|---|
| Révision Alembic | `psql -w --no-psqlrc -U compta_ma_migrator -d <ROLLBACK_DB> -c "SELECT version_num FROM alembic_version;"` | `a50e63267636` |
| Tables métier | `psql -w --no-psqlrc -U compta_ma_migrator -d <ROLLBACK_DB> -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name <> 'alembic_version';"` | **43** |
| Tables totales | `... count(*) ... table_type='BASE TABLE';` | **44** (43 métier + `alembic_version`) |
| Vues | `... table_type='VIEW';` | **0** |
| Index critique | `psql -w --no-psqlrc -U compta_ma_migrator -d <ROLLBACK_DB> -c "SELECT indexdef FROM pg_indexes WHERE indexname='uq_period_locks_company_year_annual';"` | `CREATE UNIQUE INDEX ... ON public.period_locks USING btree (company_id, fiscal_year_id) ... WHERE (periode IS NULL)` |
| Contraintes | `SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public';` | identique à la production |
| Séquences | `SELECT count(*) FROM information_schema.sequences WHERE sequence_schema='public';` | identique à la production |

L'index **critique** `uq_period_locks_company_year_annual` doit être
`UNIQUE(company_id, fiscal_year_id) WHERE periode IS NULL` : son absence invaliderait
l'unicité du verrou annuel et donc la restauration.

Contrôles complémentaires recommandés :

- **contraintes de clé étrangère** valides (`pg_constraint.convalidated = true`) ;
- **séquences** dont le `last_value` est cohérent avec `max(id)` des tables
  correspondantes (`nextval` ne doit pas rejouer un identifiant déjà utilisé) ;
- **accès du rôle applicatif** : `SET ROLE compta_ma_app;` puis `SELECT count(*)` sur
  quelques tables, et vérification qu'un `CREATE TABLE` est **refusé**.

---

## 9. Exigences de réconciliation de données

La réconciliation compare **production/staging** et **base restaurée** et exige :

| Exigence | Critère d'acceptation |
|---|---|
| Tables métier | **43 / 43** présentes et réconciliées |
| Correspondance par table | chaque table : `MATCH` (empreinte identique) |
| Écart de tables | `table_mismatch = 0` |
| Lignes cumulées | identiques des deux côtés (ex. `3131` = `3131`) |
| Séquences | `sequences_match = True` |
| Empreinte globale | `hash(staging) == hash(restore)` |
| Révision Alembic | identique des deux côtés |
| **Verdict** | **`PG6F_DATA_PASS`** |

Méthode (déjà outillée dans le dépôt) :

- outil de réconciliation : `tools/pg4_reconciliation.py` ;
- rapports générés : `PG4_RECONCILIATION_POST_*.txt` (exclus de Git : voir `.gitignore`).

L'empreinte **globale** est calculée sur l'ensemble ordonné des tables et de leurs
lignes ; elle doit être **strictement identique** entre l'état de référence et la base
restaurée. Une valeur différente invalide le test : **STOP** (cf. §13).

Valeurs de référence validées PG6F : cf. §14.

---

## 10. Procédure de nettoyage

Après un **test de restauration réussi**, la base temporaire est supprimée avec le
**rôle administratif** (seul habilité à `DROP DATABASE`). L'archive et son empreinte
SHA256 sont **conservées** comme preuves.

```sql
-- Rôle : postgres (administratif)
-- 1) Vérifier qu'aucune session ne reste connectée à la base temporaire
SELECT pid, usename, application_name
FROM pg_stat_activity
WHERE datname = '<ROLLBACK_DB>';

-- 2) (si nécessaire) Terminer les sessions résiduelles — à n'utiliser qu'en connaissance de cause
-- SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '<ROLLBACK_DB>';

-- 3) Supprimer la base temporaire de test
DROP DATABASE <ROLLBACK_DB>;
```

Règles de nettoyage :

- **Ne jamais** supprimer ou écraser la base de **production** ni la base de
  **staging** de référence (`compta_ma_staging`) ;
- **conserver** l'archive (`<BACKUP_FILE>`) et sa valeur SHA256 jusqu'à validation
  complète du cycle ;
- après nettoyage, **re-vérifier** la production/staging : nombre de tables, lignes et
  révision **inchangés**.

Cycle PG6F validé : la base temporaire `compta_ma_restore_test` a été **supprimée**
après validation, et `compta_ma_staging` est restée à **43 tables / 3131 lignes /
`a50e63267636`**.

---

## 11. Procédure de retour arrière (rollback) en production

> **Stratégie imposée :** le rollback **ne restaure jamais par-dessus la production en
> première action**. Il construit une **nouvelle base**, la valide, puis **bascule**
> l'application vers elle. L'ancienne base reste **intacte** jusqu'à validation.

Les étapes 11.1 à 11.12 sont **ordonnées** et doivent être exécutées dans cet ordre.

### 11.1 Mettre l'application en maintenance / arrêter les écritures

- Passer l'application en **mode maintenance** (écritures bloquées) ou l'**arrêter**.
- Objectif : garantir qu'aucune écriture ne survient pendant la copie/restauration.
- Acteur : exploitation applicative (hors base de données).

### 11.2 Sauvegarder l'état de production courant (sauvegarde fraîche)

Avant toute action, **archiver l'état actuel** de la production — c'est le point de
retour du rollback lui-même.

```powershell
# Rôle : compta_ma_migrator
# Recommended production variant — not the exact PG6F validated artifact
# (commande PG6F exacte : §5.1 ; portée du SHA256 : §5.2).
pg_dump -U compta_ma_migrator -d <PRODUCTION_DB> `
  --format=custom --compress=gzip --no-owner --no-privileges `
  --file="<BACKUP_FILE>"
```

> Cette variante de **production** diffère de l'exécution PG6F validée (`--no-owner` et
> `--no-privileges` ajoutés) : le dump produit est donc **un autre artéfact**, avec son
> **propre SHA256** (cf. §5.2). Pour la rollback, on peut aussi réutiliser **tel quel**
> l'artéfact PG6F validé (§5.1).

### 11.3 Vérifier le SHA256 et la lisibilité de l'archive de rollback

Appliquer **intégralement** le §6 :

```powershell
Get-FileHash -Algorithm SHA256 "<BACKUP_FILE>"
pg_restore --list "<BACKUP_FILE>" | Select-Object -First 30
```

- **STOP** si le SHA256 diverge de la valeur de référence ou si `pg_restore --list`
  échoue (cf. §13).

### 11.4 Créer une NOUVELLE base de rollback (ne jamais écraser la base vive)

```sql
-- Rôle : postgres (administratif)
CREATE DATABASE <ROLLBACK_DB>
    WITH OWNER = compta_ma_owner;
```

> La base **live** (`<PRODUCTION_DB>`) n'est **jamais** touchée à cette étape.

### 11.5 Aligner encodage / locale / propriétaire sur la production

```sql
-- Rôle : postgres (administratif)
CREATE DATABASE <ROLLBACK_DB>
    WITH OWNER          = compta_ma_owner
         TEMPLATE       = template0
         ENCODING       = 'UTF8'
         LOCALE_PROVIDER = libc
         LC_COLLATE     = 'French_France.1252'
         LC_CTYPE       = 'French_France.1252';
```

(11.4 et 11.5 peuvent être fusionnées en une **unique** `CREATE DATABASE` : voir le
bloc ci-dessus, qui crée la base avec l'encodage/locale/propriétaire de la production.)

### 11.6 Restaurer avec le rôle de MIGRATION

```powershell
# Rôle : compta_ma_migrator — commande PG6F RÉELLEMENT exécutée et validée (§7.3)
pg_restore `
  -U compta_ma_migrator `
  -d <ROLLBACK_DB> `
  -W `
  --no-owner `
  --exit-on-error `
  --single-transaction `
  "<BACKUP_FILE>"
```

> `-W` déclenche une **invite interactive** (acceptable en **manuel ponctuel** ; cf. §3.1).
> La restauration PG6F validée n'a **pas** utilisé `--no-privileges` : l'archive validée
> contient les ACL. Une **recommandation de production** peut ajouter `--no-privileges`
> pour **supprimer la restauration des ACL** et **réappliquer explicitement** les droits
> via §11.8 — c'est une **recommandation**, **pas** la preuve PG6F.

**STOP** si le code de sortie est **non nul** : la base de rollback est vide
(`--single-transaction`) et **rien** n'a été basculé (cf. §13).

---

### 11.7 Valider la base de rollback avant bascule

Exécuter les contrôles du §8 **et** du §9 sur `<ROLLBACK_DB>`, avec `compta_ma_migrator` :

- **révision Alembic** : `SELECT version_num FROM alembic_version;` → révision attendue ;
- **tables attendues** : 43 tables métier (44 avec `alembic_version`) ;
- **comptes de lignes** : conformes à la référence (ex. `3131`) ;
- **contraintes et index** : index critique
  `uq_period_locks_company_year_annual`
  (`UNIQUE(company_id, fiscal_year_id) WHERE periode IS NULL`) **présent** ;
- **séquences** : `last_value` cohérent avec `max(id)` (aucune réutilisation d'ID) ;
- **accès du rôle applicatif** : `SET ROLE compta_ma_app;` puis lectures OK, et
  `CREATE TABLE` **refusé**.

Tant qu'un de ces contrôles échoue : **ne pas basculer** (cf. §13).

### 11.8 Configurer explicitement les privilèges `CONNECT` et le schéma

Reproduire le modèle de sécurité de production (rôle **administratif** pour la base,
puis le schéma). `PUBLIC` reste **restreint**.

```sql
-- Rôle : postgres (administratif) — niveau BASE
REVOKE ALL ON DATABASE <ROLLBACK_DB> FROM PUBLIC;
GRANT CONNECT ON DATABASE <ROLLBACK_DB> TO compta_ma_app;
GRANT CONNECT ON DATABASE <ROLLBACK_DB> TO compta_ma_migrator;

-- Rôle : compta_ma_migrator (membre de compta_ma_owner) — niveau SCHÉMA
ALTER SCHEMA public OWNER TO compta_ma_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM compta_ma_app;
GRANT USAGE ON SCHEMA public TO compta_ma_app;
GRANT USAGE, CREATE ON SCHEMA public TO compta_ma_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM compta_ma_app;

-- Privilèges par défaut pour les objets créés par le migrator
ALTER DEFAULT PRIVILEGES FOR ROLE compta_ma_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO compta_ma_app;
ALTER DEFAULT PRIVILEGES FOR ROLE compta_ma_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO compta_ma_app;
ALTER DEFAULT PRIVILEGES FOR ROLE compta_ma_migrator IN SCHEMA public
    GRANT USAGE ON TYPES TO compta_ma_app;
```

> `compta_ma_app` ne reçoit **aucun** `CREATE` ; `PUBLIC` reste **sans** privilège.
> **Aucun** `CREATEDB` / `SUPERUSER` n'est accordé au migrator.

### 11.9 Test fumigène (smoke-test) de l'application sur la base restaurée

**Avant** de basculer la production, exécuter l'application **contre `<ROLLBACK_DB>`**
(instance temporaire / port distinct). Vérifier au minimum :

- démarrage de l'application (migrations **non** rejouées, schéma déjà présent) ;
- authentification et pages principales (tableau de bord, factures, grand livre) ;
- lecture **et** écriture d'une transaction de test **sur la base restaurée uniquement** ;
- aucune erreur `SQL` (contraintes, séquences) dans les journaux applicatifs.

### 11.10 Basculer `DATABASE_URL` vers la base restaurée et redémarrer l'application

Seulement **après** succès de 11.7 à 11.9 :

- mettre à jour la variable **`DATABASE_URL`** (et, si utilisée, `MIGRATION_DATABASE_URL`)
  pour pointer sur **`<ROLLBACK_DB>`** — **hors dépôt Git**, via la configuration du
  serveur / secret manager ;
- **redémarrer** l'application ;
- retirer le mode maintenance.

```text
# Exemple de cible (placeholders, aucune valeur réelle committée)
DATABASE_URL=postgresql+psycopg://compta_ma_app:<MOT_DE_PASSE>@<HOTE>:<PORT>/<ROLLBACK_DB>
```

### 11.11 Conserver l'ancienne base de production **intacte**

- **Ne pas** supprimer ni modifier l'ancienne base (`<PRODUCTION_DB>`) tant que le
  rollback n'est **pas** validé (période d'observation définie par l'exploitation) ;
- **ne pas** committer ni journaliser de secret lié à la bascule.

### 11.12 Documenter la procédure de bascule inverse

Préparer, **avant** toute bascule, la procédure inverse (retour à l'ancienne base) :

1. **Re-arrêter** les écritures / passer en maintenance ;
2. re-remettre la variable **`DATABASE_URL`** vers l'**ancienne base** (`<PRODUCTION_DB>`)
   et redémarrer l'application ;
3. si la base restaurée avait reçu des écritures, **réconcilier** ces écritures vers
   l'ancienne base (ou les rejouer) — décision d'exploitation, jamais automatique ;
4. documenter : horodatage, revision Alembic de chaque base, empreinte SHA256 des
   archives, décision et validation ;
5. `compta_ma_migrator` **ne supprime jamais** de base : toute suppression de la base
   intermédiaire se fait **plus tard**, avec le **rôle administratif**, une fois la
   validation stabilisée.

---

## 12. Liste de contrôle post-rollback

À cocher **avant** de déclarer le rollback terminé :

- [ ] Application **hors** mode maintenance et **redémarrée** sur la base cible.
- [ ] `DATABASE_URL` pointe sur **`<ROLLBACK_DB>`** (configuration hors Git).
- [ ] **Révision Alembic** identique à la référence attendue (`a50e63267636`).
- [ ] **43 tables métier** (+ `alembic_version`) présentes.
- [ ] **Comptes de lignes** conformes (ex. `3131`).
- [ ] **Index critique** `uq_period_locks_company_year_annual` présent et conforme.
- [ ] **Contraintes** validées et **séquences** cohérentes (`last_value` ≥ `max(id)`).
- [ ] **Accès `compta_ma_app`** fonctionnel ; `CREATE` toujours **refusé** à l'application.
- [ ] **`PUBLIC` restreint** ; `CONNECT` accordé uniquement à `compta_ma_app` et
      `compta_ma_migrator`.
- [ ] **Smoke-test** applicatif concluant (lectures + écritures de test).
- [ ] **Ancienne base** (`<PRODUCTION_DB>`) **conservée intacte**.
- [ ] **Sauvegardes** (fraîche + archive de rollback) et leurs **SHA256** archivés.
- [ ] **Bascule inverse** documentée et testée (au moins sur le papier).
- [ ] **Journal d'exploitation** complété (horodatage, acteurs, décisions).

---

## 13. Conditions d'arrêt d'urgence (STOP)

**Arrêter immédiatement** l'opération et **ne rien basculer** si l'un des cas suivants
se produit :

1. **SHA256** de l'archive **différent** de la valeur de référence enregistrée.
2. `pg_restore --list` **échoue** ou l'archive est **illisible** / tronquée.
3. `pg_dump` ou `pg_restore` retourne un **code de sortie non nul**.
4. La **révision Alembic** restaurée **diffère** de la révision attendue.
5. Le **nombre de tables métier** ≠ **43** (ou une table attendue manque).
6. Les **comptes de lignes** divergent de la référence (réconciliation non `MATCH`).
7. L'**index critique** `uq_period_locks_company_year_annual` est **absent**.
8. Une **contrainte** est absente/invalide ou une **séquence** est incohérente.
9. Le rôle **`compta_ma_app`** ne peut **pas** accéder aux données, **ou** dispose d'un
   droit `CREATE` (élévation de privilège inattendue).
10. Un **secret** (mot de passe) a été exposé sur une ligne de commande, dans un
    fichier committé ou dans un journal.
11. L'**hôte, la locale ou l'encodage** de la base cible ne correspondent pas à la
    production.
12. Le **smoke-test** applicatif échoue, ou des erreurs `SQL` apparaissent dans les
    journaux.

Dans tous ces cas : **conserver** l'ancienne base **intacte**, ne **pas** modifier
`DATABASE_URL`, et **escalader** vers l'exploitation / le responsable base de données.

---

## 14. Preuves PG6F validées

Toutes les valeurs ci-dessous sont issues de la **recette PG6F** et servent de
**référence** pour les contrôles des §4, §6, §8 et §9.

### 14.1 Environnement

| Élément | Valeur |
|---|---|
| Serveur PostgreSQL | **18.1** |
| `pg_dump` | **18.1** |
| `pg_restore` | **18.1** |
| `psql` | **18.1** |
| Base de staging | `compta_ma_staging` |
| Propriétaire de staging | `compta_ma_owner` |
| Rôle applicatif (runtime) | `compta_ma_app` |
| Rôle de migration / sauvegarde | `compta_ma_migrator` |
| `compta_ma_migrator` — `LOGIN` | `true` |
| `compta_ma_migrator` — `SUPERUSER` | `false` |
| `compta_ma_migrator` — `CREATEDB` | `false` |
| `compta_ma_migrator` — appartenance | **MEMBRE DE** `compta_ma_owner` |
| Création / suppression de base | **rôle administratif** uniquement (ex. `postgres`) |

### 14.2 État de staging validé

| Indicateur | Valeur |
|---|---|
| Tables métier | **43** |
| Lignes métier | **3131** |
| Révision Alembic | **`a50e63267636`** |

### 14.3 Archive PG6F validée

| Indicateur | Valeur |
|---|---|
| Format | **PostgreSQL custom** |
| Version source `pg_dump` | **18.1** |
| Entrées TOC | **613** |
| Compression | **gzip** (défaut du format custom ; **aucun** `--compress` passé) |
| Options `pg_dump` | **aucune** option `--no-owner` / `--no-privileges` — **ACL incluses** dans l'archive |
| SHA256 (validation locale) | `C531BC59B8784E767554AD43F9C41F34819B7E5F18F32CC1B9006B02B770C972` |

> **Commande exacte** ayant produit cette archive (§5.1) :
> `pg_dump -U compta_ma_migrator -d compta_ma_staging --format=custom --no-password --file=<BACKUP_FILE>`.
>
> **Portée de la valeur.** Ce **SHA256** appartient **uniquement** à **cette archive
> exacte**. Toute modification des options (ajout de `--no-owner` / `--no-privileges`,
> `--compress`, filtres, etc.) produit une **archive différente**, donc un **SHA256
> différent** : il ne faut **pas** s'attendre à retrouver le SHA256 PG6F sur un dump
> fraîchement généré avec d'**autres options**.

### 14.4 Test de restauration validé

| Indicateur | Valeur |
|---|---|
| Base temporaire | `compta_ma_restore_test` |
| Propriétaire | `compta_ma_owner` |
| Encodage | `UTF8` |
| Fournisseur de locale | `libc` |
| `LC_COLLATE` | `French_France.1252` |
| `LC_CTYPE` | `French_France.1252` |
| Commande de restauration | `pg_restore -U compta_ma_migrator -d compta_ma_restore_test -W --no-owner --exit-on-error --single-transaction "<BACKUP_FILE>"` |
| `--no-privileges` à la restauration | **Non utilisé** — les ACL de l'archive validée ont été restaurées |
| Code de sortie `pg_restore` | **0** |
| Tables métier restaurées | **43** |
| Lignes restaurées | **3131** |
| Alembic restauré | **`a50e63267636`** |
| Index critique restauré | `uq_period_locks_company_year_annual` — `UNIQUE(company_id, fiscal_year_id) WHERE periode IS NULL` |

### 14.5 Réconciliation de données

| Indicateur | Valeur |
|---|---|
| Tables métier réconciliées | **43 / 43 MATCH** |
| Lignes staging | **3131** |
| Lignes restauration | **3131** |
| `table_mismatch` | **0** |
| `sequences_match` | **True** |
| Empreinte globale staging | `543ccfab999933e9d92b62ce85bca293e3e391239f3803861df2f70e6bf411fb` |
| Empreinte globale restauration | `543ccfab999933e9d92b62ce85bca293e3e391239f3803861df2f70e6bf411fb` |
| **Verdict** | **`PG6F_DATA_PASS`** |

### 14.6 Suite du cycle

- La base temporaire `compta_ma_restore_test` a été **supprimée** après validation.
- `compta_ma_staging` est **restée** à **43 tables / 3131 lignes / `a50e63267636`**.

---

*Fin du document — PG6F, documentation opérationnelle Backup / Restore / Rollback
PostgreSQL 18.1 (aucune modification de code, test, Docker ou base n'a été effectuée).*