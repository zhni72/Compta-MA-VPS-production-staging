# AUDIT ENVIRONNEMENT TECHNIQUE LOCAL — compta_ma (lecture seule)

Audit unique, en **lecture seule** : aucun fichier de code, aucune base, aucune configuration, aucune
dépendance n'a été modifiée, installée ou migrée. Aucune valeur de secret n'est reproduite.

```
Python        = 3.13.9 (64 bits, build MSC v.1944 AMD64) — interpréteur .venv\Scripts\python.exe — pip 26.2.1
Framework     = FastAPI 0.141.1 / Starlette 1.6.0 / Pydantic 2.13.5 (+ pydantic-settings 2.15.0)
Serveur local = Uvicorn 0.53.0 — `uvicorn app.main:app --reload` — port 8000, host 127.0.0.1
ORM           = SQLAlchemy 2.0.54 (future=True, pool_pre_ping)
DB actuelle   = SQLite (compta_ma.db, 1 163 264 octets) — DB ACTUELLE = SQLite
Migrations    = Alembic 1.20.0 — 9 migrations — révision en base = head = p1c1a2b3d4e5
Templates     = Jinja2 3.1.6 — 35 gabarits (app/web/templates) + 1 CSS statique
Authentification = cookie de session HttpOnly (JWT HS256, PyJWT 2.14.0) + Bearer sur /api + Argon2 (argon2-cffi 25.1.0)
PDF           = ReportLab 5.0.1 (rendu) + pypdf 6.19.0 (analyse/contrôle de contenu)
XML / EDI     = lxml 6.1.3 (+ xml.etree) — XSD DGI locaux dans `referentiels/` — CSV via csv, archives via zipfile
Stockage      = media/ (pièces Greffe) + app/data/ (référentiel PCGE) ; base = fichier du dossier projet
Background    = aucun (pas de Celery / Redis / RQ / APScheduler / BackgroundTasks) → Background externe requis actuellement : NON
Services externes = aucun appel réel : DGI / CNSS / CMI / Greffe = simulation locale ou URL documentaire
OS développement = Windows (win32) — Python 64 bits MSVC ; aucun code Windows-only dans app/
```

---

## 1. Environnement Python

| Élément | Valeur |
|---|---|
| Version exacte | **3.13.9** (`tags/v3.13.9:8183fa5, Oct 14 2025, 14:09:13 [MSC v.1944 64 bit (AMD64)]`) |
| Architecture | **64 bits** (AMD64) |
| Interpréteur utilisé | `.venv\Scripts\python.exe` (chemin absolu du projet) |
| Environnement virtuel | **`.venv` actif** (`VIRTUAL_ENV` = `.venv` du projet) ; interpréteur système associé : `AppData\Local\Programs\Python\Python313` |
| pip | **26.2.1** |

Versions exactes installées (extrait de `pip freeze`) :

| Bibliothèque | Version | Bibliothèque | Version |
|---|---|---|---|
| FastAPI | 0.141.1 | pytest | 9.1.1 |
| Starlette | 1.6.0 | httpx | 0.28.1 |
| Uvicorn | 0.53.0 | PyJWT (JWT) | 2.14.0 |
| SQLAlchemy | 2.0.54 | argon2-cffi / bindings | 25.1.0 / 26.1.0 |
| Alembic | 1.20.0 | python-multipart | 0.0.32 |
| Jinja2 | 3.1.6 | ReportLab | 5.0.1 |
| Pydantic | 2.13.5 | pypdf | 6.19.0 |
| pydantic-settings | 2.15.0 | lxml | 6.1.3 |
| python-dotenv | 1.2.3 | psycopg / psycopg-binary | 3.3.6 / 3.3.6 |
| Mako (Alembic) | 1.4.1 | PyYAML | 6.0.3 |
| anyio / h11 / httpcore | 4.15.1 / 0.16.0 / 1.0.9 | httptools / watchfiles / websockets | 0.8.0 / 1.2.0 / 17.1 |
| pillow | 12.3.0 | **weasyprint** | **70.0** |
| cssselect2 / tinycss2 / tinyhtml5 / webencodings | 0.10.1 / 1.5.1 / 2.1.0 / 0.6.1 | pydyf / pyphen / fonttools / zopfli / brotli | 0.12.1 / 0.18.1 / 4.65.0 / 0.4.3 / 1.2.0 |

## 2. Dépendances (examen unique : `requirements.txt` présent ; `pyproject.toml`, `poetry.lock`, `Pipfile`, `setup.py` **absents**)

| Package | Version installée | Déclaré | Utilisé par le code | Nécessaire en production |
|---|---|---|---|---|
| fastapi | 0.141.1 | oui (`>=0.115`) | oui (44 imports) | oui |
| uvicorn[standard] | 0.53.0 | oui (`>=0.32`) | via CLI (serveur) | oui |
| jinja2 | 3.1.6 | oui | oui (via FastAPI templating) | oui |
| sqlalchemy | 2.0.54 | oui | oui (170 imports) | oui |
| alembic | 1.20.0 | oui | via CLI + `alembic/env.py` | oui |
| pydantic / pydantic-settings | 2.13.5 / 2.15.0 | oui | oui | oui |
| pyjwt | 2.14.0 | oui | oui (`jwt`) | oui |
| argon2-cffi | 25.1.0 | oui | oui (`argon2`) | oui |
| python-multipart | 0.0.32 | oui | indirect (formulaires FastAPI) | oui |
| reportlab | 5.0.1 | oui | oui (6 imports) | oui |
| pypdf | 6.19.0 | oui | oui (4 imports) | oui |
| lxml | 6.1.3 | oui | oui (3 imports) | oui |
| pytest | 9.1.1 | oui | oui (30 fichiers de tests) | non (développement) |
| httpx | 0.28.1 | oui | oui (TestClient) | non (développement) |
| psycopg / psycopg-binary | 3.3.6 | oui (`psycopg[binary]`) | **non** | phase 2 seulement (PostgreSQL) |
| **weasyprint** | **70.0** | **non** | `tools/poc_pdf.py` (diagnostic) uniquement | non |
| python-dotenv | 1.2.3 | **non** | indirect (lecture `.env` par pydantic-settings) | oui |
| pillow, tinycss2, cssselect2, pydyf, pyphen, fonttools, zopfli, brotli, tinyhtml5, webencodings | 12.3.0 → 0.4.3 | non | non (dépendances de weasyprint) | non |
| Mako, PyYAML, colorama, watchfiles, httptools, websockets, anyio, certifi, idna, cffi, pycparser, greenlet, typing_extensions… | selon `pip freeze` | non | indirect (SQLAlchemy / Alembic / uvicorn / argon2) | oui (transitives) |

Constats :
- **utilisée mais non déclarée** : `weasyprint` (outil de diagnostic) et `python-dotenv` ;
- **déclarée mais non utilisée aujourd'hui** : `psycopg[binary]` (phase 2) ;
- **aucune version n'est épinglée** (`>=` partout) → l'environnement validé par les tests n'est pas
  reproductible à l'identique ;
- **incompatibilité Linux potentielle** : `weasyprint` (+ pile pillow/tinycss2/pydyf/fonttools)
  exige des bibliothèques **système** Linux (GTK/pango, `libgobject-2.0-0`) — explicitement écarté
  par le dépôt ; `lxml` et `psycopg[binary]` disposent de wheels manylinux (compilation système
  requise seulement sans wheel) ; `reportlab` et `pypdf` sont purs Python.
  Aucune installation n'a été effectuée.

## 3. Base de données actuelle

**DB ACTUELLE = SQLite** (aucune autre base configurée : `DATABASE_URL` est en `sqlite`).

| Élément | Valeur |
|---|---|
| Moteur | SQLite (fichier local) |
| Fichier | `compta_ma.db` (dossier du projet) |
| Chemin | `…\chat\compta_ma\compta_ma.db` |
| Taille | **1 163 264 octets** |
| SHA-256 | **52fc68c77aed0369be424d628a39d07db953f61b1ca3cf7b18689fcbcfb58743** |
| Date de modification | 2026-09-24 02:55:05 |
| Engine SQLAlchemy | `create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False})` ; `PRAGMA foreign_keys=ON` à chaque connexion SQLite |
| Configuration Alembic | `alembic.ini` (`script_location`, `prepend_sys_path`, `sqlalchemy.url`) + `alembic/env.py` (URL issue de `settings.database_url`, `render_as_batch` si SQLite) |
| Révision en base | **p1c1a2b3d4e5** |
| Head du code | **p1c1a2b3d4e5** → base **à jour** |
| Nombre de migrations | **9** (`91754af8ef74` → `c1d801a10835` → `07e35b18ce2e` → `8cf2d7792aa2` → `9ee74a029f0a` → `56d9985cc7ff` → `a7f3c51d8b42` → `c4b8e17f2d95` → `p1c1a2b3d4e5`) |
| Sauvegardes présentes | 14 fichiers `compta_ma.db.bak-*` à la racine (copies manuelles horodatées) |

PostgreSQL : **prévu par le code** (`settings.database_url`, `psycopg` déclaré, `docker-compose.yml`
avec `postgres:16-alpine`) mais **non configuré ni utilisé**. Aucune migration n'a été lancée.

## 4. Architecture application (composants réellement présents)

```
Navigateur (HTML, 1 feuille CSS)                                Client API
        │ cookie de session HttpOnly (JWT HS256)                │ Bearer JWT
        ▼                                                        ▼
FastAPI  app.main:app  ── /health, /docs, /redoc, /openapi.json
        ├── app/web/routes.py            → écrans Jinja2 (35 gabarits)
        │   app/web/ecrans_lecture.py    → 11 écrans lecture seule (GET)
        ├── app/api/routers/*.py (14)    → API REST montée sous /api + app/api/deps.py (rôles)
        ├── app/core/                    → config, security (JWT/Argon2), audit, rates_ma
        ▼
Services métier  app/services/*.py (25 modules) — aucune logique métier dans les routeurs
        ▼
SQLAlchemy 2.0 (app/db/session.py ; app/models/*.py — 20 modules de modèles)
        ▼
SQLite  compta_ma.db   ──(phase 2 prévue)──►  PostgreSQL (psycopg + docker-compose)

Transverse : migrations Alembic (9) en CLI (base = head) ; audit trail append-only (audit_log,
chaînage SHA-256, export CSV anonymisé) ; rôles ADMIN / EXPERT_COMPTABLE / COMPTABLE / CAISSIER /
COMMERCIAL / LECTEUR (+ superadmin) ; stockage fichiers hors base (media/) ; 428 tests (35 fichiers).
```

## 5. Modules métier présents (inventaire ; aucun test métier rejoué)

| Module | Route principale | Service principal | Tables principales |
|---|---|---|---|
| Comptabilité / saisie | `/ecritures` | `accounting.py` | `entries`, `entry_lines`, `journals`, `accounts`, `fiscal_years` |
| Plan comptable | `/comptes` | `accounts.py` | `accounts` |
| Journal comptable | `/etats/journal` | `reporting.py` | `entries`, `entry_lines` |
| Grand livre | `/etats/grand-livre` | `reporting.py` | `entry_lines` |
| Balance générale | `/etats/balance` | `reporting.py` | `entry_lines`, `accounts` |
| Bilan | `/etats/bilan` | `etats_synthese.bilan_normal`, `reporting.balance_sheet` | `entry_lines` |
| CPC | `/etats/cpc` | `etats_synthese`, `reporting.income_statement` | `entry_lines` |
| ESG | `/etats/esg` | `etats_synthese.etat_soldes_gestion` | `entry_lines` |
| ETIC | `/etats/etic` | `etats_synthese.notes_etic` | `entry_lines` |
| Immobilisations | `/immobilisations` | `assets.py` | `assets`, `asset_depreciation_lines`, `asset_disposals` |
| Stocks | `/stocks`, `/stocks/mouvements` | `stocks.py` | `stock_items`, `stock_movements` |
| Provisions | `/stocks/provisions` | `stocks.etat_provisions` | `stock_provisions` |
| Paie | `/paie`, `/paie?vue=bulletins` | `payroll.py` | `employees`, `pay_contracts`, `payroll_runs`, `payslips` |
| DTS / État 9421 | `/paie/dts.pdf` | `edi_dts.py` | `declarations`, `payslips` |
| TVA | `/tva` | `vat.py` | `vat_rates`, `vat_declarations` |
| EDI TVA | `/tva/edi` | `edi_tva.py` | `vat_declarations` |
| IS | `/liasse` | `fiscal_liasse.py` | `liasse_tables`, `liasse_cells` |
| Liasse fiscale | `/liasse` | `liasse_edi.py`, `fiscal_liasse.py` | `liasse_tables`, `liasse_cells`, `declarations` |
| Greffe | `/greffe` | `greffe.py` | `greffe_deposits`, `greffe_documents`, `greffe_payments`, `greffe_events` |
| Cessation / activité | `/activite` | `activity_events.py` | `activity_events` |
| E-facturation | `/e-facturation` | `e_invoice.py` | `e_invoice_documents` |
| Audit & traçabilité | `/audit`, `/audit/integrite` | `audit_trail.py` | `audit_log` |
| Exercices / clôture / à-nouveaux | `/parametres/exercices`, `/parametres/a-nouveaux` | `closing.py`, `period_locks.py` | `fiscal_years`, `period_locks` |
| Facturation / tiers | `/factures`, `/tiers` | `invoicing.py`, `parties.py` | `invoices`, `invoice_lines`, `third_parties` |
| Rapprochement / règlements / trésorerie | `/rapprochement`, `/reglements` | `banking.py`, `tresorerie.py` | `bank_reconciliations` (+ modèles `bank.py`, `invoice.py`) |
| PDF (états et documents) | toutes impressions | `pdf.py` (moteur), `pdf_documents.py` (contenus) | — |
| Référentiels / identifiants | `/parametres/referentiels` | `identifiers.py`, `core/rates_ma.py` | `vat_rates` (+ `numbering.py`) |

## 6. PDF / XML / EDI / Documents

| Élément | Détail |
|---|---|
| Moteur PDF | **ReportLab 5.0.1** (`app/services/pdf.py` : `Document`, `Tableau`, `rendre_pdf`, contrôle « PDF ≤ 10 Mo ») |
| Contrôles de contenu PDF | **pypdf 6.19.0** (`greffe.analyser_piece_pdf`, empreintes SHA-256) |
| XML / XSD | **lxml 6.1.3** + `xml.etree` — validation contre les XSD DGI de `referentiels/` (`liasse_modele_*.xsd`, `dts_9421_2026.xml`, `releve_deduction_2025_06.xml`) |
| CSV | module standard `csv` (séparateur `;`, BOM UTF-8 pour Excel : journal d'audit, état de saisie EFI, plan comptable) |
| ZIP | module standard `zipfile` (assemblage du dossier Greffe : bordereau + pièces + `manifeste.json`) |
| Empreintes | `hashlib` SHA-256 (pièces Greffe, certificat, chaînage d'audit) |
| Génération Greffe | `greffe.py` + `pdf_documents` (`pdf_rapport_gestion`, `pdf_pv_ag`, `pdf_bordereau_greffe`, `pdf_recapitulatif_dossier`) ; pièces stockées dans `media/greffe/<société>/<dossier>/` |
| Génération factures | `pdf_documents.pdf_facture` (+ `pdf_bulletin_paie`, `pdf_bordereau_tva`, bilan/CPC/ESG/ETIC, immobilisations, cessions) |
| Liasse / EDI | `edi_tva.py` (relevé des déductions), `liasse_edi.py` (liasse, état de saisie EFI), `edi_dts.py` (DTS 9421) |
| Contrainte système Linux | **weasyprint** (+ pillow / tinycss2 / pydyf / fonttools) : GTK-pango requis → inutilisable sur un VPS nu ; **lxml** : wheels manylinux (compilation source → libxml2/libxslt) ; **ReportLab** et **pypdf** : aucune dépendance système |

## 7. Stockage local

| Chemin | Contenu | Persistant | À sauvegarder sur futur VPS |
|---|---|---|---|
| `compta_ma.db` | base SQLite (données métier) | oui | **oui (critique)** |
| `compta_ma.db.bak-*` (14 fichiers, racine) | copies manuelles horodatées | oui | non (à archiver hors déploiement) |
| `media/greffe/<société>/<dossier>/` (5 PDF, 30 598 octets) | pièces du dossier de dépôt Greffe | oui | **oui** |
| `app/data/plan_comptable_cgnc.csv` | référentiel PCGE (seed) | oui | oui (fourni avec le code) |
| `referentiels/` | XSD DGI, exemples XML/CSV, annexes EDI | oui | oui (fourni avec le code) |
| `recette_j9/` | jeux de recette (relevés bancaires CSV, XML DTS/synthèse) | non (développement) | non |
| `PREUVE_*.log`, rapports `*.md` (racine) | preuves d'audit et documentation | non (développement) | non |
| Répertoires `logs/`, `exports/`, `backups/` | **inexistants** | — | à définir côté VPS |
| Fichiers temporaires | via `tempfile` (outils de contrôle) | non | non |

## 8. Windows → futur Linux (recherche unique)

| Résultat | Fichier | Classement |
|---|---|---|
| Chemins absolus `C:\Users\…` | `lancer_compta.bat` (ligne `cd /d`), `audit_env_local_compta_ma.ps1` | **OUTIL DEV UNIQUEMENT** (non appelés par l'application) |
| Commandes `.\.venv\Scripts\python.exe` en documentation d'usage | docstrings `tools/*.py` (`j9_audit_anomalies`, `p1b_simulation_2025*`, `p1_inventaire_paie`, `p1_rapport_avant_apres`, `p1_reinitialiser_paie`, `scan_documents_facture`) | **OUTIL DEV UNIQUEMENT** |
| `cmd.exe` / PowerShell | aucun dans `app/` (uniquement `.bat` et `.ps1`) | **OUTIL DEV UNIQUEMENT** |
| `.exe` / `Scripts\python` dans le code applicatif | **aucun** dans `app/` | — |
| `os.sep`, `os.name`, `winreg`, `startfile`, `platform.system` | **aucun** | — |
| Chemins de données | `BASE_DIR` calculé depuis `__file__` (`data_dir`, `media_dir`, `greffe_dir`) → **portable** | — |
| SQLite `check_same_thread` | conditionné à `settings.database_url.startswith("sqlite")` | — |
| Dépendances Windows-only | aucune | — |
| **BLOQUANT VPS** | **aucun identifié dans `app/`** | — |

## 9. Tâches background

| Technologie | Présence |
|---|---|
| Celery / Redis / RQ / APScheduler / crontab | **aucune occurrence** |
| FastAPI `BackgroundTasks` | **aucune occurrence** |
| Tâche périodique | aucune |

**Background externe requis actuellement : NON** (traitements déclenchés à la demande : impressions,
exports EDI, assemblage d'archives, contrôles Greffe).

## 10. Services externes

| Intégration | État réel |
|---|---|
| DGI (SIMPL, Simpl-TVA, e-facturation) | **simulation / documentation** : XSD et exemples locaux dans `referentiels/`, aucun appel réseau ; e-facturation en `dry-run` (`e_invoice_dry_run = True`, endpoint non renseigné) |
| Greffe du tribunal | **URL documentaire uniquement** (`depotbilan.justice.gov.ma`) ; aucune soumission : le certificat reste un fichier fourni par le greffe |
| CNSS / AMO | **barèmes internes** (`core/rates_ma.py`) — aucun service en ligne |
| CMI (paiement) | saisie manuelle (`greffe_payments`, `moyen="cmi"`) — aucune transaction réseau |
| SMTP | **absent** (aucune configuration, aucun import `smtplib`) |
| Autres APIs HTTP | **aucun appel sortant dans `app/`** (pas de `requests`) |

## 11. Variables d'environnement et secrets (noms uniquement, aucune valeur)

Noms présents dans `.env.example` : `DATABASE_URL`, `APP_NAME`, `DEBUG`, `SECRET_KEY`,
`ACCESS_TOKEN_EXPIRE_MINUTES`, `CURRENCY`, `DEFAULT_VAT_RATE`, `DEFAULT_CUSTOMER_ACCOUNT`,
`DEFAULT_SUPPLIER_ACCOUNT`, `VAT_COLLECTED_ACCOUNT`, `VAT_DEDUCTIBLE_ACCOUNT`, `BANK_ACCOUNT`,
`CASH_ACCOUNT`.

Autres paramètres de `app/core/config.py` (surchargeables par variable d'environnement) :
`algorithm`, `media_dir`, `data_dir`, `greffe_dir`, `dts_xsd_path`, `liasse_xsd_dir`,
`liasse_codification_path`, `e_invoice_endpoint`, `e_invoice_api_key`, `e_invoice_dry_run`,
comptes par défaut, coefficients d'amortissement dégressif.

Signalements (aucun contenu n'est reproduit) :
- **`SECRET_KEY` a une valeur par défaut dans le code** (45 caractères) et `DEBUG` vaut `True` par
  défaut : sans variable d'environnement, l'application démarre avec ces valeurs ;
- **aucun fichier `.env` n'existe** (seul `.env.example` est présent) alors que `docker-compose.yml`
  en attend un ;
- **aucun dépôt Git** dans le projet (`git rev-parse` → « not a git repository ») : la question
  « `.env` versionné » est **non applicable** en l'état ;
- `e_invoice_endpoint` / `e_invoice_api_key` **non renseignés** (mode simulation assumé) ;
- `dts_xsd_path` et `liasse_xsd_dir` **vides** (`None`) alors que les XSD sont livrés dans
  `referentiels/` ;
- `docker-compose.yml` contient des **valeurs par défaut de démonstration** pour
  `POSTGRES_PASSWORD` et `SECRET_KEY` — à considérer avant tout déploiement réel.

## 12. Serveur actuel

| Élément | Valeur |
|---|---|
| Commande locale | `uvicorn app.main:app --reload` (via `lancer_compta.bat` ou `.venv\Scripts\uvicorn.exe`) |
| Serveur | Uvicorn 0.53.0 (ASGI), rechargement automatique |
| Port / host | **8000** / **127.0.0.1** (défauts Uvicorn) |
| Healthcheck | `GET /health` **présent** (`tags=["systeme"]`) |
| Documentation | `/docs` (Swagger), `/redoc`, `/openapi.json` — exposés par défaut |
| API | REST montée sous `/api` (`API_PREFIX = "/api"`) ; écrans web hors schéma OpenAPI |
| Gunicorn | **absent** |
| Nginx | **absent** |
| systemd | non applicable (Windows) |
| Docker | **présents** : `Dockerfile` (python:3.13-slim, utilisateur non privilégié, `EXPOSE 8000`, `HEALTHCHECK` sur `/health`, `CMD uvicorn --host 0.0.0.0 --port 8000`) et `docker-compose.yml` (app + `postgres:16-alpine`, volume `media`, `restart: unless-stopped`) |

## 13. Tests

| Élément | Valeur |
|---|---|
| Framework | **pytest 9.1.1** — `pytest.ini` : `testpaths = tests`, `pythonpath = .`, `addopts = -q --strict-markers` |
| Nombre de tests | **428** (collection complète) — dernière exécution complète : succès (code de sortie 0) |
| Structure | 35 fichiers `tests/test_*.py` + `tests/conftest.py` (SQLite **en mémoire**, société et administrateur de test, client `TestClient`) |
| Suite rejouée pendant cet audit | non |