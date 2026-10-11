"""Paie, bulletins et declarations sociales (P1.4).

Modele (§ 2.3 du CDC) :

- `employees` : fiche salarie (matricule, CIN, **n° CNSS**, situation de
  famille, nombre d'enfants, dates d'entree/sortie, contrat, coordonnees
  bancaires) — **donnees personnelles** au sens de la **loi 09-08** (acces
  restreint, journalisation, conservation 10 ans) ;
- `pay_contracts` : element contractuel (salaire de base, primes, avantages,
  taux de retraite complementaire / mutuelle / assurance groupe, date d'effet) ;
- `payroll_runs` : **cycle de paie** d'une periode (etat brouillon/valide/paye,
  totaux, ecriture globale) — ajout au modele : le CDC decrit les bulletins et
  l'**ecriture globale de paie par periode** sans porter cet objet ; ce cycle
  est ce qui rend l'ecriture, le paiement et la DTS reconciliables ;
- `payslips` / `payslip_lines` : bulletin par salarie et par periode (brut, IR,
  CNSS/AMO salariales, net, cout employeur, `entry_id`) et detail des rubriques
  (libelle, base, taux, gain, retenue, compte PCGE) ;
- `tax_declarations` (avec le module `declaration`) : **registre unique des
  declarations** (ici la **DTS « 9421 »** : periode, regime, etat, fichier,
  empreinte, accuse de reception).

References : **CGI / LF 2026** (bareme IR, art. 57 et suivants : retenue a la
source sur traitements et salaires), **CNSS / AMO 2026**, **Code du travail**,
**guide DGI « Declaration des traitements et salaries » (9421)** et **loi 09-08**
(CNDP). Les taux et baremes sont **historisés** dans `app/core/rates_ma.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.types import Money

# --- Etats du cycle de paie (brouillon -> valide -> paye) -------------------
PAYROLL_STATUS_DRAFT = "brouillon"
PAYROLL_STATUS_VALIDATED = "valide"
PAYROLL_STATUS_PAID = "paye"
PAYROLL_STATUSES = (PAYROLL_STATUS_DRAFT, PAYROLL_STATUS_VALIDATED, PAYROLL_STATUS_PAID)
PAYROLL_STATUS_LABELS = {
    PAYROLL_STATUS_DRAFT: "Brouillon (calcul provisoire)",
    PAYROLL_STATUS_VALIDATED: "Validé (écriture de paie comptabilisée)",
    PAYROLL_STATUS_PAID: "Payé (virement/caisse comptabilisé)",
}

# --- Situations de famille (IR : deduction pour charges de famille) ---------
SITUATIONS_FAMILIALES = ("celibataire", "marie", "divorce", "veuf")
SITUATION_LABELS = {
    "celibataire": "Célibataire",
    "marie": "Marié(e)",
    "divorce": "Divorcé(e)",
    "veuf": "Veuf(ve)",
}

# --- Types de contrat ------------------------------------------------------
CONTRATS = ("cdi", "cdd", "anapec", "interim", "stage", "apprentissage")
CONTRAT_LABELS = {
    "cdi": "Contrat à durée indéterminée (CDI)",
    "cdd": "Contrat à durée déterminée (CDD)",
    "anapec": "Contrat ANAPEC (insertion)",
    "interim": "Intérim",
    "stage": "Stage",
    "apprentissage": "Apprentissage",
}

# --- Modes de paiement du net ----------------------------------------------
PAIEMENTS_PAIE = ("virement", "cheque", "especes")
PAIEMENT_PAIE_LABELS = {
    "virement": "Virement bancaire",
    "cheque": "Chèque",
    "especes": "Espèces (caisse)",
}

# --- Rubriques du bulletin (code, libelle, sens) ---------------------------
RUBRIQUE_SALAIRE_BASE = "100"
RUBRIQUE_PRIMES = "110"
RUBRIQUE_INDEMNITES = "120"
RUBRIQUE_HEURES_SUP = "130"
RUBRIQUE_AVANTAGES = "140"
RUBRIQUE_CNSS = "200"
RUBRIQUE_AMO = "210"
RUBRIQUE_RETRAITE = "220"
RUBRIQUE_MUTUELLE = "230"
RUBRIQUE_ASSURANCE_GROUPE = "240"
RUBRIQUE_AVANCES = "250"
RUBRIQUE_OPPOSITIONS = "260"
RUBRIQUE_IR = "300"
RUBRIQUE_NET = "900"
RUBRIQUE_LABELS = {
    RUBRIQUE_SALAIRE_BASE: "Salaire de base",
    RUBRIQUE_PRIMES: "Primes et gratifications",
    RUBRIQUE_INDEMNITES: "Indemnités et avantages divers",
    RUBRIQUE_HEURES_SUP: "Heures supplémentaires",
    RUBRIQUE_AVANTAGES: "Avantages en nature",
    RUBRIQUE_CNSS: "CNSS - part salariale",
    RUBRIQUE_AMO: "AMO - part salariale",
    RUBRIQUE_RETRAITE: "Retraite complémentaire (CIMR)",
    RUBRIQUE_MUTUELLE: "Mutuelle",
    RUBRIQUE_ASSURANCE_GROUPE: "Assurance groupe",
    RUBRIQUE_AVANCES: "Avances et acomptes",
    RUBRIQUE_OPPOSITIONS: "Oppositions sur salaires",
    RUBRIQUE_IR: "Impôt sur le revenu retenu à la source",
    RUBRIQUE_NET: "NET À PAYER",
}


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
class Employee(Base):
    """Fiche salarie (donnees personnelles : loi 09-08, acces restreint)."""

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "matricule", name="uq_employees_company_matricule"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    matricule: Mapped[str] = mapped_column(String(20), index=True)
    nom: Mapped[str] = mapped_column(String(160))
    cin: Mapped[str | None] = mapped_column(String(20), default=None)
    cnss: Mapped[str | None] = mapped_column(String(20), default=None)
    situation_familiale: Mapped[str] = mapped_column(String(20), default="celibataire")
    enfants: Mapped[int] = mapped_column(Integer, default=0)
    date_entree: Mapped[date] = mapped_column(Date)
    date_sortie: Mapped[date | None] = mapped_column(Date, default=None)
    type_contrat: Mapped[str] = mapped_column(String(20), default="cdi")
    fonction: Mapped[str | None] = mapped_column(String(120), default=None)
    adresse: Mapped[str | None] = mapped_column(String(255), default=None)
    rib: Mapped[str | None] = mapped_column(String(40), default=None)
    banque: Mapped[str | None] = mapped_column(String(80), default=None)
    mode_paiement: Mapped[str] = mapped_column(String(20), default="virement")
    # Onglet « salariés bénéficiant de l'exonération » du formulaire 9421
    # (art. 57-20° du CGI : nouveaux recrutements, 36 premiers mois).
    exoneration_art_57_20: Mapped[bool] = mapped_column(Boolean, default=False)
    exoneration_fin: Mapped[date | None] = mapped_column(Date, default=None)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    contrats: Mapped[list["PayContract"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    bulletins: Mapped[list["Payslip"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )

    @property
    def personnes_a_charge(self) -> int:
        """Personnes a charge pour l'IR : conjoint (si marié) + enfants."""
        personnes = max(0, int(self.enfants or 0))
        if self.situation_familiale == "marie":
            personnes += 1
        return personnes

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<Employee {self.matricule} {self.nom}>"


class PayContract(Base):
    """Element contractuel de remuneration (date d'effet : historisation)."""

    __tablename__ = "pay_contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    salaire_base: Mapped[Decimal] = mapped_column(Money)
    prime_transport: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    prime_logement: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    autres_primes: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    indemnite_representation: Mapped[Decimal] = mapped_column(
        Money, default=Decimal("0")
    )
    avantages_nature: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taux_retraite: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taux_mutuelle: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taux_assurance_groupe: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    date_effet: Mapped[date] = mapped_column(Date)
    mode_paiement: Mapped[str] = mapped_column(String(20), default="virement")
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    employee: Mapped[Employee] = relationship(back_populates="contrats")

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<PayContract salarie={self.employee_id} base={self.salaire_base}>"


class PayrollRun(Base):
    """Cycle de paie d'une periode (etats brouillon / valide / paye)."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "periode", name="uq_payroll_runs_company_periode"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    fiscal_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("fiscal_years.id", ondelete="SET NULL"), default=None
    )
    periode: Mapped[str] = mapped_column(String(7), index=True)  # AAAA-MM
    date_paie: Mapped[date] = mapped_column(Date)
    statut: Mapped[str] = mapped_column(String(20), default=PAYROLL_STATUS_DRAFT)
    total_brut: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_cotisations: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_ir: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_net: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_employeur: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    paiement_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    mode_paiement: Mapped[str] = mapped_column(String(20), default="virement")
    date_paiement: Mapped[date | None] = mapped_column(Date, default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    bulletins: Mapped[list["Payslip"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    @property
    def annee(self) -> int:
        """Exercice de la periode de paie (`AAAA-MM`)."""
        return int(self.periode[:4])

    @property
    def mois(self) -> int:
        """Mois de la periode de paie (`AAAA-MM`)."""
        return int(self.periode[5:7])

    @property
    def statut_libelle(self) -> str:
        """Libelle francais de l'etat du cycle de paie."""
        return PAYROLL_STATUS_LABELS.get(self.statut, self.statut)

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<PayrollRun {self.periode} {self.statut}>"


class Payslip(Base):
    """Bulletin de paie d'un salarie pour une periode (cumuls + ecriture)."""

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "employee_id", name="uq_payslips_run_employee"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    periode: Mapped[str] = mapped_column(String(7), index=True)
    date_paie: Mapped[date] = mapped_column(Date)

    # Base imposable et calcul (methode DGI, barème historisé)
    brut: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    brut_imposable: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    frais_professionnels: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    base_cnss: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    net_imposable: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    personnes_a_charge: Mapped[int] = mapped_column(Integer, default=0)

    cnss_salariale: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amo_salariale: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    retraite: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    mutuelle: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    assurance_groupe: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cotisations_salariales: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    ir: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    avances: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    oppositions: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    net: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))

    # Charges patronales (cout employeur)
    cnss_patronale: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amo_patronale: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    prestations_familiales: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taxe_formation: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cout_employeur: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))

    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped[PayrollRun] = relationship(back_populates="bulletins")
    employee: Mapped[Employee] = relationship(back_populates="bulletins")
    lignes: Mapped[list["PayslipLine"]] = relationship(
        back_populates="payslip", cascade="all, delete-orphan"
    )

    @property
    def net_a_payer(self) -> Decimal:
        """Net verse au salarie (net - avances - oppositions)."""
        return self.net

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<Payslip {self.periode} salarie={self.employee_id} net={self.net}>"


class PayslipLine(Base):
    """Rubrique du bulletin (libelle, base, taux, gain, retenue, compte PCGE)."""

    __tablename__ = "payslip_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    payslip_id: Mapped[int] = mapped_column(
        ForeignKey("payslips.id", ondelete="CASCADE"), index=True
    )
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(10), default="")
    libelle: Mapped[str] = mapped_column(String(120))
    base: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taux: Mapped[Decimal | None] = mapped_column(Money, default=None)
    gain: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    retenue: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    compte: Mapped[str | None] = mapped_column(String(12), default=None)

    payslip: Mapped[Payslip] = relationship(back_populates="lignes")

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<PayslipLine {self.code} {self.libelle} gain={self.gain}>"
