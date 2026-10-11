"""Facturation : calcul des totaux, numerotation, comptabilisation, reglements.

Cycle de vie : brouillon -> validation (numero + ecriture comptable) -> paiements.
Un document valide n'est plus modifiable : on emet un avoir ou une facture
d'extourne. Le numero consomme n'est jamais reutilise (numerotation sans trou).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.core.numbering import next_document_number
from app.core.rates_ma import money
from app.models import (
    INVOICE_STATUS_CANCELLED,
    INVOICE_STATUS_DRAFT,
    INVOICE_STATUS_PARTIALLY_PAID,
    INVOICE_STATUS_PAID,
    INVOICE_STATUS_VALIDATED,
    Company,
    Entry,
    FiscalYear,
    Invoice,
    InvoiceLine,
    Payment,
    ThirdParty,
)
from app.services.accounting import (
    AccountingError,
    ComplianceError,
    NotFoundError,
    create_entry,
    ensure_period_open,
    get_fiscal_year,
    get_journal,
    reverse_entry,
    validate_entry,
)


def compute_line(line: dict) -> dict:
    """Calcule HT / TVA / TTC d'une ligne de facture (arrondi commercial)."""
    quantity = Decimal(str(line.get("quantity", 1) or 0))
    unit_price = Decimal(str(line.get("unit_price", 0) or 0))
    discount = Decimal(str(line.get("discount_percent", 0) or 0))
    vat_rate = Decimal(str(line.get("vat_rate", settings.default_vat_rate)))
    ht = money(quantity * unit_price * (Decimal("1") - discount / Decimal("100")))
    vat = money(ht * vat_rate / Decimal("100"))
    return {
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_percent": discount,
        "vat_rate": vat_rate,
        "line_ht": ht,
        "line_vat": vat,
        "line_ttc": money(ht + vat),
    }


def add_line(
    db: Session,
    invoice: Invoice,
    *,
    designation: str,
    quantity: Decimal | int | float | str = 1,
    unit_price: Decimal | int | float | str = 0,
    vat_rate: Decimal | int | float | str | None = None,
    discount_percent: Decimal | int | float | str = 0,
    account_number: str | None = None,
    position: int | None = None,
) -> InvoiceLine:
    """Ajoute une ligne a une facture brouillon."""
    if invoice.status != INVOICE_STATUS_DRAFT:
        raise AccountingError(
            "Facture validee : ajoutez une ligne via un avoir ou une nouvelle facture"
        )
    if account_number is None:
        account_number = (
            settings.default_sales_account
            if invoice.invoice_type == "vente"
            else settings.default_purchase_account
        )
    computed = compute_line(
        {
            "quantity": quantity,
            "unit_price": unit_price,
            "discount_percent": discount_percent,
            "vat_rate": settings.default_vat_rate if vat_rate is None else vat_rate,
        }
    )
    line = InvoiceLine(
        invoice_id=invoice.id,
        position=len(invoice.lines) if position is None else position,
        designation=designation,
        account_number=str(account_number),
        **computed,
    )
    db.add(line)
    invoice.lines.append(line)
    db.flush()
    recalculate(db, invoice)
    return line


def recalculate(db: Session, invoice: Invoice) -> Invoice:
    """Recalcule les totaux de la facture a partir de ses lignes."""
    invoice.total_ht = money(sum((l.line_ht for l in invoice.lines), Decimal("0")))
    invoice.total_vat = money(sum((l.line_vat for l in invoice.lines), Decimal("0")))
    invoice.total_ttc = money(sum((l.line_ttc for l in invoice.lines), Decimal("0")))
    db.flush()
    return invoice


def create_invoice(
    db: Session,
    *,
    company: Company,
    invoice_type: str,
    partner: ThirdParty,
    invoice_date: date,
    lines: list[dict] | None = None,
    due_date: date | None = None,
    payment_mode: str | None = None,
    is_credit_note: bool = False,
    reference: str | None = None,
    notes: str | None = None,
) -> Invoice:
    """Cree une facture en brouillon (numero attribue a la validation)."""
    if invoice_type not in ("vente", "achat"):
        raise AccountingError("Type de facture invalide (vente ou achat)")
    if partner.company_id != company.id:
        raise AccountingError("Le tiers n'appartient pas a cette societe")
    if partner.kind == "client" and invoice_type == "achat":
        raise AccountingError("Un client ne peut pas recevoir une facture d'achat")
    if partner.kind == "fournisseur" and invoice_type == "vente":
        raise AccountingError("Un fournisseur ne peut pas recevoir une facture de vente")

    fiscal_year = get_fiscal_year(db, company.id, invoice_date.year)
    ensure_period_open(fiscal_year)
    invoice = Invoice(
        company_id=company.id,
        fiscal_year_id=fiscal_year.id,
        invoice_type=invoice_type,
        is_credit_note=is_credit_note,
        partner_id=partner.id,
        invoice_date=invoice_date,
        due_date=due_date or invoice_date + timedelta(days=partner.payment_terms_days),
        payment_mode=payment_mode,
        reference=reference,
        notes=notes,
    )
    db.add(invoice)
    db.flush()
    for raw in lines or []:
        add_line(
            db,
            invoice,
            designation=raw["designation"],
            quantity=raw.get("quantity", 1),
            unit_price=raw.get("unit_price", 0),
            vat_rate=raw.get("vat_rate"),
            discount_percent=raw.get("discount_percent", 0),
            account_number=raw.get("account_number"),
        )
    recalculate(db, invoice)
    return invoice


def document_type(invoice: Invoice) -> str:
    """Type de document pour la sequence de numerotation."""
    prefix = "AVOIR" if invoice.is_credit_note else "FACTURE"
    return f"{prefix}_{invoice.invoice_type.upper()}"


def tva_deductible_account(account_number: str | None) -> str:
    """Compte de TVA recuperable selon la nature de la depense (CGNC/PCGE).

    - `34551` « Etat - TVA recuperable sur immobilisations » lorsque la depense
      est portee par un compte d'immobilisation (classe 2) ;
    - `34552` « Etat - TVA recuperable sur charges » pour les achats de biens et
      de services (classe 6).

    Le plan comptable marocain impose cette distinction : une TVA
    d'immobilisation logee dans le 34552 fausse la presentation du bilan (poste
    Etat - TVA recuperable) et l'assiette des regularisations (CGI art. 106).
    """
    if account_number and str(account_number).strip().startswith("2"):
        return settings.vat_deductible_asset_account
    return settings.vat_deductible_charge_account


def _post_invoice_entry(
    db: Session, invoice: Invoice, company: Company, partner: ThirdParty
) -> Entry:
    """Genere l'ecriture comptable de la facture (partie double CGNC)."""
    journal = get_journal(db, company.id, "VE" if invoice.invoice_type == "vente" else "AC")
    fiscal_year = db.get(FiscalYear, invoice.fiscal_year_id)
    vente = invoice.invoice_type == "vente"
    reverse = invoice.is_credit_note  # un avoir inverse le sens de l'ecriture

    def side(amount: Decimal, debit_side: bool) -> dict:
        go_debit = debit_side != reverse
        return {"debit": amount} if go_debit else {"credit": amount}

    lines: list[dict] = []
    # TVA recuperable ventilee par (compte, taux) : le CGNC separe la TVA sur
    # immobilisations (34551) de la TVA sur charges (34552).
    vat_par_compte: dict[tuple[Decimal, str], Decimal] = {}
    for line in invoice.lines:
        # Vente : le produit est credite ; achat : la charge est debitee.
        lines.append(
            {
                "account_number": line.account_number,
                "label": line.designation,
                "vat_rate": line.vat_rate,
                **side(line.line_ht, debit_side=not vente),
            }
        )
        if line.line_vat:
            compte_tva = (
                settings.vat_collected_account
                if vente
                else tva_deductible_account(line.account_number)
            )
            cle = (line.vat_rate, compte_tva)
            vat_par_compte[cle] = vat_par_compte.get(cle, Decimal("0")) + line.line_vat

    for (rate, account), vat_amount in sorted(
        vat_par_compte.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        libelle = f"TVA {rate.normalize()} %"
        if not vente and account == settings.vat_deductible_asset_account:
            libelle += " sur immobilisations"
        lines.append(
            {
                "account_number": account,
                "label": libelle,
                "vat_rate": rate,
                # Vente : TVA collectee (creditee) ; achat : TVA recuperable (debitee).
                **side(money(vat_amount), debit_side=not vente),
            }
        )

    lines.append(
        {
            "account_number": partner.account_number,
            "third_party_id": partner.id,
            "label": f"{partner.name} - {invoice.number or 'brouillon'}",
            **side(invoice.total_ttc, debit_side=vente),
        }
    )
    return create_entry(
        db,
        company_id=company.id,
        fiscal_year=fiscal_year,
        journal=journal,
        entry_date=invoice.invoice_date,
        label=f"{'Facture' if not invoice.is_credit_note else 'Avoir'} "
        f"{invoice.number or ''} - {partner.name}".strip(),
        reference=invoice.number,
        source="invoice",
        source_id=invoice.id,
        lines=lines,
    )


def controles_coherence_facture(invoice: Invoice) -> list[str]:
    """Controles **bloquants** de coherence d'une facture (lignes <-> totaux).

    Appliques avant toute emission d'un document (PDF, apercu avant impression,
    validation) : le document transmis ne doit **jamais** presenter une ligne ou
    une ventilation de TVA a zero alors que les totaux sont corrects (defaut A4
    de la recette J9), ni des totaux qui ne reconciliant pas les lignes.

    Retourne la liste des anomalies (vide si la facture est coherente).
    """
    anomalies: list[str] = []
    lignes = list(invoice.lines)
    total_ht = money(sum((ligne.line_ht for ligne in lignes), Decimal("0")))
    total_vat = money(sum((ligne.line_vat for ligne in lignes), Decimal("0")))
    total_ttc = money(sum((ligne.line_ttc for ligne in lignes), Decimal("0")))
    entete_ht = money(invoice.total_ht)
    entete_vat = money(invoice.total_vat)
    entete_ttc = money(invoice.total_ttc)

    if not lignes:
        if entete_ht or entete_vat or entete_ttc:
            anomalies.append(
                "aucune ligne de facturation alors que les totaux sont non nuls "
                f"(HT {entete_ht}, TVA {entete_vat}, TTC {entete_ttc})"
            )
        return anomalies

    if total_ht != entete_ht:
        anomalies.append(f"somme des lignes HT ({total_ht}) <> total HT ({entete_ht})")
    if total_vat != entete_vat:
        anomalies.append(f"somme des lignes TVA ({total_vat}) <> total TVA ({entete_vat})")
    if total_ttc != entete_ttc:
        anomalies.append(f"somme des lignes TTC ({total_ttc}) <> total TTC ({entete_ttc})")
    if entete_ttc != money(entete_ht + entete_vat):
        anomalies.append(
            f"total TTC ({entete_ttc}) <> total HT + total TVA "
            f"({money(entete_ht + entete_vat)})"
        )
    for index, ligne in enumerate(lignes, start=1):
        if not (money(ligne.line_ht) or money(ligne.line_vat) or money(ligne.line_ttc)):
            anomalies.append(
                f"ligne {index} « {ligne.designation} » : montants HT/TVA/TTC a zero"
            )
    return anomalies


def validate_invoice(db: Session, invoice: Invoice, user_id: int | None = None) -> Invoice:
    """Valide une facture : controle legal, numerotation, comptabilisation."""
    if invoice.status != INVOICE_STATUS_DRAFT:
        raise AccountingError(
            f"Facture en statut '{invoice.status}' : "
            "seule une facture brouillon peut etre validee"
        )
    company = db.get(Company, invoice.company_id)
    partner = db.get(ThirdParty, invoice.partner_id)
    if company is None or partner is None:
        raise NotFoundError("Societe ou tiers de la facture introuvable")
    fiscal_year = db.get(FiscalYear, invoice.fiscal_year_id)
    ensure_period_open(fiscal_year)
    recalculate(db, invoice)
    if not invoice.lines:
        raise AccountingError("Impossible de valider une facture sans ligne")
    if invoice.total_ttc <= 0:
        raise AccountingError("Impossible de valider une facture d'un montant nul")

    # Coherence lignes / totaux : refuse notamment les lignes a montant nul
    # (une ligne « designee » a 0,00 produisait un document incoherent alors que
    # les totaux etaient corrects - defaut A4 de la recette J9).
    incoherences = controles_coherence_facture(invoice)
    if incoherences:
        raise AccountingError(
            "Facture incoherente, validation refusee : " + " ; ".join(incoherences)
        )

    # Obligation CGI : ICE sur les factures entre professionnels.
    if (
        invoice.invoice_type == "vente"
        and company.require_ice
        and settings.require_ice_on_sales
        and partner.requires_ice
        and not partner.ice
    ):
        raise ComplianceError(
            f"ICE obligatoire : le tiers {partner.code} - {partner.name} "
            "doit etre identifie par son ICE avant validation de la facture"
        )

    invoice.number = next_document_number(
        db, invoice.company_id, document_type(invoice), invoice.invoice_date.year
    )
    entry = _post_invoice_entry(db, invoice, company, partner)
    validate_entry(db, entry, user_id=user_id)
    invoice.entry_id = entry.id
    invoice.status = INVOICE_STATUS_VALIDATED
    invoice.row_version += 1
    db.flush()
    log_action(
        db,
        action="INVOICE_VALIDATED",
        entity="Invoice",
        entity_id=invoice.id,
        user_id=user_id,
        company_id=invoice.company_id,
        payload={
            "number": invoice.number,
            "total_ttc": invoice.total_ttc,
            "partner": partner.code,
        },
    )
    return invoice


def cancel_invoice(
    db: Session, invoice: Invoice, reason: str, user_id: int | None = None
) -> Invoice:
    """Annule une facture : contre-ecriture si elle etait comptabilisee.

    Le numero reste consomme (numerotation continue, sans trou).
    """
    if invoice.status == INVOICE_STATUS_CANCELLED:
        raise AccountingError("Facture deja annulee")
    if invoice.paid_amount > 0:
        raise AccountingError(
            "Facture partiellement ou totalement reglee : "
            "emettez un avoir plutot qu'une annulation"
        )
    if invoice.status != INVOICE_STATUS_DRAFT and invoice.entry_id:
        entry = db.get(Entry, invoice.entry_id)
        if entry is not None and entry.is_validated:
            reverse_entry(
                db,
                entry,
                reason=f"Annulation facture {invoice.number} - {reason}",
                user_id=user_id,
            )
    invoice.status = INVOICE_STATUS_CANCELLED
    invoice.notes = f"{invoice.notes or ''}\nAnnulee : {reason}".strip()
    invoice.row_version += 1
    db.flush()
    log_action(
        db,
        action="INVOICE_CANCELLED",
        entity="Invoice",
        entity_id=invoice.id,
        user_id=user_id,
        company_id=invoice.company_id,
        payload={"number": invoice.number, "reason": reason},
    )
    return invoice


def register_payment(
    db: Session,
    invoice: Invoice,
    *,
    amount: Decimal | int | float | str,
    payment_date: date | None = None,
    method: str = "virement",
    reference: str | None = None,
    user_id: int | None = None,
) -> Payment:
    """Enregistre un reglement et genere l'ecriture de tresorerie associee."""
    if invoice.status not in (
        INVOICE_STATUS_VALIDATED,
        INVOICE_STATUS_PARTIALLY_PAID,
    ):
        raise AccountingError(
            f"Reglement impossible : facture en statut '{invoice.status}'"
        )
    montant = money(amount)
    if montant <= 0:
        raise AccountingError("Le montant du reglement doit etre positif")
    remaining = money(invoice.total_ttc - invoice.paid_amount)
    if montant > remaining:
        raise AccountingError(
            f"Montant superieur au reste a payer ({remaining} {settings.currency})"
        )

    company = db.get(Company, invoice.company_id)
    partner = db.get(ThirdParty, invoice.partner_id)
    jour = payment_date or date.today()
    fiscal_year = get_fiscal_year(db, invoice.company_id, jour.year)
    ensure_period_open(fiscal_year)

    espece = method == "espece"
    treasury_account = settings.cash_account if espece else settings.bank_account
    journal = get_journal(db, invoice.company_id, "CA" if espece else "BQ")
    vente = invoice.invoice_type == "vente"
    lines = [
        {
            "account_number": treasury_account,
            "label": f"Reglement {invoice.number} - {partner.name}",
            **({"debit": montant} if vente else {"credit": montant}),
        },
        {
            "account_number": partner.account_number,
            "third_party_id": partner.id,
            "label": f"Reglement {invoice.number}",
            **({"credit": montant} if vente else {"debit": montant}),
        },
    ]
    entry = create_entry(
        db,
        company_id=invoice.company_id,
        fiscal_year=fiscal_year,
        journal=journal,
        entry_date=jour,
        label=f"Reglement {invoice.number} - {partner.name} ({method})",
        reference=invoice.number,
        source="payment",
        source_id=invoice.id,
        created_by=user_id,
        lines=lines,
    )
    validate_entry(db, entry, user_id=user_id)

    payment = Payment(
        company_id=invoice.company_id,
        fiscal_year_id=fiscal_year.id,
        invoice_id=invoice.id,
        partner_id=partner.id,
        payment_date=jour,
        amount=montant,
        method=method,
        reference=reference,
        treasury_account=treasury_account,
        entry_id=entry.id,
    )
    db.add(payment)

    invoice.paid_amount = money(invoice.paid_amount + montant)
    invoice.status = (
        INVOICE_STATUS_PAID
        if invoice.paid_amount >= invoice.total_ttc
        else INVOICE_STATUS_PARTIALLY_PAID
    )
    invoice.row_version += 1
    db.flush()
    log_action(
        db,
        action="PAYMENT_REGISTERED",
        entity="Invoice",
        entity_id=invoice.id,
        user_id=user_id,
        company_id=invoice.company_id,
        payload={"amount": montant, "method": method, "status": invoice.status},
    )
    return payment