"""Schemas Pydantic de la paie (P1.4) : salaries, contrats, cycles et DTS."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EmployeeCreate(BaseModel):
    """Fiche salarie (donnees personnelles : loi 09-08)."""

    matricule: str = Field(..., max_length=20)
    nom: str = Field(..., max_length=160)
    date_entree: date
    cin: str | None = Field(default=None, max_length=20)
    cnss: str | None = Field(default=None, max_length=20)
    situation_familiale: str = Field(default="celibataire")
    enfants: int = Field(default=0, ge=0, le=30)
    type_contrat: str = Field(default="cdi")
    fonction: str | None = Field(default=None, max_length=120)
    adresse: str | None = Field(default=None, max_length=255)
    rib: str | None = Field(default=None, max_length=40)
    banque: str | None = Field(default=None, max_length=80)
    mode_paiement: str = Field(default="virement")
    exoneration_art_57_20: bool = Field(
        default=False, description="Nouveau recrutement exonere (art. 57-20° du CGI)"
    )
    exoneration_fin: date | None = None
    notes: str | None = None


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    matricule: str
    nom: str
    cin: str | None = None
    cnss: str | None = None
    situation_familiale: str
    enfants: int
    date_entree: date
    date_sortie: date | None = None
    type_contrat: str
    fonction: str | None = None
    banque: str | None = None
    rib: str | None = None
    mode_paiement: str
    exoneration_art_57_20: bool
    exoneration_fin: date | None = None
    actif: bool


class PayContractCreate(BaseModel):
    """Element contractuel de remuneration (taux en pourcentage : 3.00 = 3 %)."""

    salaire_base: Decimal = Field(..., gt=0)
    date_effet: date
    prime_transport: Decimal = Field(default=Decimal("0"), ge=0)
    prime_logement: Decimal = Field(default=Decimal("0"), ge=0)
    autres_primes: Decimal = Field(default=Decimal("0"), ge=0)
    indemnite_representation: Decimal = Field(default=Decimal("0"), ge=0)
    avantages_nature: Decimal = Field(default=Decimal("0"), ge=0)
    taux_retraite: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    taux_mutuelle: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    taux_assurance_groupe: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    mode_paiement: str | None = None
    notes: str | None = None


class PayContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    salaire_base: Decimal
    prime_transport: Decimal
    prime_logement: Decimal
    autres_primes: Decimal
    indemnite_representation: Decimal
    avantages_nature: Decimal
    taux_retraite: Decimal
    taux_mutuelle: Decimal
    taux_assurance_groupe: Decimal
    date_effet: date
    mode_paiement: str


class PayrollPrepareRequest(BaseModel):
    """Preparation (calcul) de la paie d'une periode ; variables par matricule."""

    periode: str = Field(..., description="AAAA-MM", pattern=r"^\d{4}-\d{2}$")
    date_paie: date | None = None
    variables: dict[str, dict] | None = Field(
        default=None,
        description=(
            "Variables par matricule : primes, heures_sup, jours_absence, "
            "avances, oppositions"
        ),
    )


class PayrollPayRequest(BaseModel):
    """Reglement du net a payer (banque ou caisse)."""

    date_paiement: date | None = None
    mode: str = Field(default="virement", description="virement, cheque ou especes")


class PayslipLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordre: int
    code: str
    libelle: str
    base: Decimal
    taux: Decimal | None = None
    gain: Decimal
    retenue: Decimal
    compte: str | None = None


class PayslipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    employee_id: int
    periode: str
    date_paie: date
    brut: Decimal
    brut_imposable: Decimal
    frais_professionnels: Decimal
    base_cnss: Decimal
    net_imposable: Decimal
    personnes_a_charge: int
    cnss_salariale: Decimal
    amo_salariale: Decimal
    retraite: Decimal
    mutuelle: Decimal
    assurance_groupe: Decimal
    cotisations_salariales: Decimal
    ir: Decimal
    avances: Decimal
    oppositions: Decimal
    net: Decimal
    cnss_patronale: Decimal
    amo_patronale: Decimal
    prestations_familiales: Decimal
    taxe_formation: Decimal
    cout_employeur: Decimal
    entry_id: int | None = None


class PayrollRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    periode: str
    date_paie: date
    statut: str
    total_brut: Decimal
    total_cotisations: Decimal
    total_ir: Decimal
    total_net: Decimal
    total_employeur: Decimal
    entry_id: int | None = None
    paiement_entry_id: int | None = None
    mode_paiement: str
    date_paiement: date | None = None
    created_at: datetime | None = None


class DtsSoumissionRequest(BaseModel):
    """Depot de la DTS (et accuse de reception, le cas échéant)."""

    jour: date | None = None
    accuse_le: date | None = None
    motif_rejet: str | None = None


class TaxDeclarationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    type: str
    periode: str
    regime: str | None = None
    mode_depot: str
    statut: str
    montant: Decimal
    nb_lignes: int
    fichier_nom: str | None = None
    fichier_hash: str | None = None
    fichier_taille: int
    deposant: str | None = None
    motif_rejet: str | None = None
    notes: str | None = None
    soumise_le: date | None = None
    accuse_le: date | None = None
