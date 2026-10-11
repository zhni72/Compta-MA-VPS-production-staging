"""Facture électronique : documents et suivi du canal DGI (P2.3).

Modele (§ 2.3 du CDC) : `e_invoice_documents` — le **document électronique** d'une
facture de vente (`invoice_id`), son **statut** dans le cycle de vie, le **XML**
produit, l'**identifiant DGI** et l'**accusé** de réception.

Etat du référentiel (à la date de ce jalon)
-------------------------------------------
Le **cahier des charges e-facturation de la DGI n'est pas fourni** (aucun document
« loi 43-20 » ni schéma XML dans le référentiel technique reçu ; le CGI 2026 ne
mentionne ni « facturation électronique » ni « 43-20 ») : le cycle de vie est donc
implémenté **sans schéma officiel**. Le XML produit est un **format interne**
(`version = "interne-v1"`), explicitement **non déclaré conforme** tant que la
spécification DGI n'est pas publiée (incohérence **A24** du CDC) ; le **canal DGI**
reste paramétrable (endpoint + clé) et fonctionne en **simulation** par défaut.

Point de droit vérifié le 22/09/2026 sur l'édition 2026 du CGI fournie par le
client : l'**article 145** traite de la **tenue de la comptabilité** (y compris
« sous format électronique ») et **non** des mentions obligatoires de la facture
(le CDC citait « art. 145 » pour les mentions — voir **A23**). Les mentions
retenues sont celles vérifiables dans le dossier : identités et identifiants
(IF, **ICE**, RC), numéro séquentiel, date, désignation, quantités, prix HT,
taux et montant de TVA, totaux, mode de paiement (CGI art. 146 pièces
justificatives ; loi 15-95 code de commerce et obligation d'ICE).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# --- Cycle de vie du document électronique ---------------------------------
STATUT_A_GENERER = "a_generer"
STATUT_GENERE = "genere"
STATUT_ENVOYE = "envoye"
STATUT_ACCEPTE = "accepte"
STATUT_REJETE = "rejete"
E_INVOICE_STATUTS = (
    STATUT_A_GENERER,
    STATUT_GENERE,
    STATUT_ENVOYE,
    STATUT_ACCEPTE,
    STATUT_REJETE,
)
E_INVOICE_STATUT_LABELS = {
    STATUT_A_GENERER: "À générer",
    STATUT_GENERE: "Généré (fichier prêt, non transmis)",
    STATUT_ENVOYE: "Transmis à la DGI (accusé en attente)",
    STATUT_ACCEPTE: "Accepté par la DGI",
    STATUT_REJETE: "Rejeté (à corriger)",
}
STATUTS_TERMINAUX = (STATUT_ACCEPTE, STATUT_REJETE)

# --- Canaux de transmission -------------------------------------------------
CANAL_MANUEL = "manuel"  # téléversement sur le portail SIMPL par l'utilisateur
CANAL_API = "api"  # appel du service DGI (endpoint paramétrable)
CANAL_EFI = "efi"  # saisie assistée (repli tant que la spécification n'est pas publiée)
E_INVOICE_CANAUX = (CANAL_MANUEL, CANAL_API, CANAL_EFI)
E_INVOICE_CANAL_LABELS = {
    CANAL_MANUEL: "Manuel (téléversement sur le portail DGI)",
    CANAL_API: "API DGI (endpoint paramétrable)",
    CANAL_EFI: "EFI / saisie assistée (repli)",
}

# --- Format du fichier ------------------------------------------------------
FORMAT_INTERNE = "interne-v1"
CONFORMITE_NON_VALIDEE = "non validée (spécification DGI non publiée)"


class EInvoiceDocument(Base):
    """Document électronique d'une facture (un document par facture)."""

    __tablename__ = "e_invoice_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    statut: Mapped[str] = mapped_column(String(20), default=STATUT_A_GENERER, index=True)
    format: Mapped[str] = mapped_column(String(20), default=FORMAT_INTERNE)
    canal: Mapped[str | None] = mapped_column(String(20), default=None)
    xml: Mapped[str | None] = mapped_column(Text, default=None)
    hash_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    identifiant_dgi: Mapped[str | None] = mapped_column(String(60), default=None)
    accuse: Mapped[str | None] = mapped_column(Text, default=None)
    envoye_le: Mapped[date | None] = mapped_column(Date, default=None)
    accuse_le: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    @property
    def statut_libelle(self) -> str:
        """Libellé français du statut du document."""
        return E_INVOICE_STATUT_LABELS.get(self.statut, self.statut)

    @property
    def canal_libelle(self) -> str:
        """Libellé du canal de transmission utilisé."""
        return E_INVOICE_CANAL_LABELS.get(self.canal or "", "—")

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<EInvoiceDocument facture={self.invoice_id} {self.statut}>"
