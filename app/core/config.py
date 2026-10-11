"""Configuration centrale de l'application.

Le choix de la base se fait UNIQUEMENT par la variable d'environnement
`DATABASE_URL` :
  - Phase 1 (mono-utilisateur) : sqlite:///./compta_ma.db
  - Phase 2/3 (multi-utilisateurs sur serveur) :
        postgresql+psycopg://user:pass@host:5432/compta_ma

Aucun code metier ne doit dependre du SGBD choisi.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

# Valeur d'exemple de `SECRET_KEY` (documentation / developpement). Elle est
# explicitement INTERDITE en production (cf. PG6E1) : un secret reel doit etre
# genere hors du depot.
PLACEHOLDER_SECRET_KEY = "compta-ma-secret-a-remplacer-en-production-32"
# Longueur minimale exigee pour `SECRET_KEY` en production (signature HS256).
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environnement d'execution ---
    # Pilote les controles de securite : en `production`, certaines valeurs par
    # defaut (DEBUG, SQLite, SECRET_KEY d'exemple) sont refusees au demarrage.
    environment: Literal["development", "test", "staging", "production"] = (
        "development"
    )

    app_name: str = "Compta MA"
    debug: bool = True

    # --- Base de donnees ---
    database_url: str = f"sqlite:///{(BASE_DIR / 'compta_ma.db').as_posix()}"

    # --- Migrations (Alembic) ---
    # Facultatif : si absente, Alembic reutilise `database_url` (comportement
    # historique, y compris SQLite). En production, elle peut cibler un role
    # dedie aux migrations (compta_ma_migrator) sans exposer ces identifiants a
    # l'application runtime. Elle n'est JAMAIS requise pour demarrer l'app.
    migration_database_url: str | None = None

    # --- Securite (phase 2) ---
    secret_key: str = PLACEHOLDER_SECRET_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # --- EDI (releve des deductions TVA) ---
    # Limite de lignes par fichier (balise <ord>) : le XSD du modele officiel
    # declare xs:byte (127) alors que l'annexe V4.0 declare « Entier ». La limite
    # est parametrable pour ne pas bloquer un depot legitime.
    max_rd_lines: int = 127

    # --- Parametres comptables marocains ---
    currency: str = "MAD"
    default_vat_rate: str = "20.00"
    default_customer_account: str = "3421"
    default_supplier_account: str = "4411"
    default_sales_account: str = "7111"
    default_purchase_account: str = "6111"
    vat_collected_account: str = "4455"
    vat_deductible_account: str = "3455"
    # CGNC : la TVA recuperable est ventilee selon la nature de la depense.
    vat_deductible_charge_account: str = "34552"  # sur charges (achats 6xxx)
    vat_deductible_asset_account: str = "34551"  # sur immobilisations (2xxx)
    bank_account: str = "5141"
    cash_account: str = "5161"
    require_ice_on_sales: bool = True

    # --- Immobilisations (P1.2) ---
    # Amortissement degressif (CGI art. 10) : le coefficient multiplicateur depend
    # de la duree d'utilisation. Il est PARAMETRABLE et jamais code en dur
    # (ambiguite A4 du CDC : a confirmer sur l'edition 2026 du CGI).
    coefficient_degressif_court: str = "1.5"  # duree de 3 a 4 ans
    coefficient_degressif_moyen: str = "2.0"  # duree de 5 a 6 ans
    coefficient_degressif_long: str = "2.5"  # duree superieure a 6 ans
    # Regularisation de la TVA sur immobilisations (CGI art. 106) : duree de la
    # periode de regularisation par fractions egales (ambiguite A5 du CDC : a
    # confirmer — defaut prudent 5 ans pour les meubles, 10 ans pour les immeubles).
    regularisation_tva_annees_meubles: int = 5
    regularisation_tva_annees_immeubles: int = 10
    compte_regularisation_tva: str = "6513"
    # Prorata temporis fiscal par defaut sur la premiere annuite (CGI art. 10).
    immo_prorata_temporis: bool = True
    # Comptes par defaut des cessions d'immobilisations (CGNC).
    compte_cession_a_recevoir: str = "3481"  # creances sur cessions d'immobilisations
    compte_produit_cession_corporelle: str = "7513"
    compte_produit_cession_incorporelle: str = "7512"
    compte_vna_cession_corporelle: str = "6513"
    compte_vna_cession_incorporelle: str = "6512"

    # --- Chemins ---
    data_dir: Path = BASE_DIR / "app" / "data"
    media_dir: Path = BASE_DIR / "media"
    # --- Pieces et certificats du depot au greffe (P1.5) : archives **hors base**
    # (un PDF peut atteindre 10 Mo). `None` -> `media_dir / "greffe"`.
    greffe_dir: Path | None = None
    # --- DTS « 9421 » (P1.4) : schema XSD officiel de la DGI, quand il sera
    # fourni (ecart n° 6) : il active la validation du fichier EDI.
    dts_xsd_path: Path | None = None
    # --- Liasse fiscale EDI (P2.1) : **dossier** des schemas officiels DGI
    # (`liasse_modele_normal.xsd`, `liasse_modele_comptable simplifié.xsd`...).
    # `None` -> `referentiels/liasse` du projet. Les XSD fournissent les codes
    # legaux de chaque modele ; la correspondance `codeEdi` <-> rubrique est un
    # referentiel editable (ambiguite A22 du CDC).
    liasse_xsd_dir: Path | None = None
    # Table de correspondance `codeEdi` <-> rubrique comptable (CSV). `None` ->
    # `liasse_racine / "codification_liasse.csv"`.
    liasse_codification_path: Path | None = None

    # --- E-facturation (P2.3) : specification DGI en attente de publication -----
    # Le canal DGI est PARAMETRABLE : sans `e_invoice_endpoint`, l'application
    # prepare le fichier et laisse le depot manuel (EFI). La simulation est active
    # par defaut : aucune requete reseau n'est envoyee sans configuration explicite.
    e_invoice_endpoint: str | None = None
    e_invoice_api_key: str | None = None
    e_invoice_dry_run: bool = True

    @property
    def liasse_racine(self) -> Path:
        """Dossier des referentiels de la liasse fiscale (P2.1)."""
        return self.liasse_xsd_dir or (BASE_DIR / "referentiels" / "liasse")

    @property
    def liasse_codification(self) -> Path:
        """Fichier de correspondance `codeEdi` <-> rubrique comptable."""
        return self.liasse_codification_path or (
            self.liasse_racine / "codification_liasse.csv"
        )

    @property
    def greffe_racine(self) -> Path:
        """Racine de stockage des pieces du depot au greffe (P1.5)."""
        return self.greffe_dir or (self.media_dir / "greffe")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def alembic_database_url(self) -> str:
        """URL utilisee par Alembic : `MIGRATION_DATABASE_URL` sinon `DATABASE_URL`."""
        return self.migration_database_url or self.database_url

    @model_validator(mode="after")
    def _valider_configuration_production(self) -> Settings:
        """Refuse une configuration dangereuse lorsque `environment == 'production'`.

        Les valeurs par defaut de developpement ne sont jamais rejetees : ce
        controle ne s'active qu'en production.
        """
        if self.environment != "production":
            return self

        problemes: list[str] = []
        if self.debug:
            problemes.append("DEBUG doit etre desactive (false) en production.")
        if self.is_sqlite:
            problemes.append("DATABASE_URL ne doit pas cibler SQLite en production.")
        if self.secret_key == PLACEHOLDER_SECRET_KEY:
            problemes.append(
                "SECRET_KEY utilise encore la valeur d'exemple : generez un "
                "secret reel hors du depot."
            )
        if len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
            problemes.append(
                f"SECRET_KEY doit comporter au moins {MIN_SECRET_KEY_LENGTH} "
                "caracteres."
            )
        if problemes:
            raise ValueError(
                "Configuration de production invalide : " + " ".join(problemes)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()