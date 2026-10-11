"""Facture électronique : cycle de vie, mentions et canal DGI (P2.3).

Ce module couvre la **facture électronique** côté client : contrôle des **mentions
obligatoires**, production d'un **fichier structuré**, transmission au **canal DGI**
(paramétrable) et suivi des **accusés de réception** dans `e_invoice_documents`.

État du référentiel — à lire avant toute mise en production
-----------------------------------------------------------
Le **cahier des charges e-facturation de la DGI n'est pas fourni** : aucun document
« loi 43-20 » ni schéma XML n'est présent dans le référentiel technique transmis, et
l'édition 2026 du CGI fournie par le client **ne contient ni** « facturation
électronique » **ni** « 43-20 » (vérifié le 22/09/2026). Conséquences assumées :

1. le fichier produit est un **format interne** (`interne-v1`) portant explicitement
   `<conformite>non validée (spécification DGI non publiée)</conformite>` : il **ne
   doit pas** être déposé tel quel comme facture électronique ;
2. `valider_conformite()` renvoie **`None`** (jamais « conforme ») tant qu'aucun
   schéma officiel n'est fourni ;
3. le **canal DGI** est **paramétrable** (`e_invoice_endpoint`, `e_invoice_api_key`)
   et fonctionne par défaut en **simulation** (`e_invoice_dry_run = true`) : aucune
   requête réseau n'est envoyée sans configuration explicite ;
4. le **repli EFI** (dépôt manuel de la facture PDF + XML sur le portail SIMPL) est
   disponible immédiatement.

Incohérence consignée (**A23**) : le CDC citait « **CGI art. 145** » pour les
mentions obligatoires de la facture ; l'article 145 de l'édition 2026 traite de la
**tenue de la comptabilité** (y compris « sous format électronique »). Les mentions
retenues sont celles **vérifiables dans le dossier** : identités et identifiants
(IF, RC, **ICE**), numéro séquentiel, date, échéance, désignation, quantités et prix,
taux de TVA, totaux HT/TVA/TTC, mode de paiement (CGI art. 146 pièces
justificatives ; loi 15-95 code de commerce ; obligation d'ICE).
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.core.rates_ma import money
from app.models import (
    CANAL_API,
    CANAL_EFI,
    CANAL_MANUEL,
    CONFORMITE_NON_VALIDEE,
    E_INVOICE_CANAUX,
    FORMAT_INTERNE,
    INVOICE_STATUS_DRAFT,
    STATUTS_TERMINAUX,
    STATUT_ACCEPTE,
    STATUT_A_GENERER,
    STATUT_ENVOYE,
    STATUT_GENERE,
    STATUT_REJETE,
    Company,
    EInvoiceDocument,
    Invoice,
)
from app.services.accounting import AccountingError


class EInvoiceError(AccountingError):
    """Erreur de facturation électronique (mentions manquantes, état incompatible)."""


# ---------------------------------------------------------------------------
# Mentions obligatoires (controle de contenu)
# ---------------------------------------------------------------------------
MENTIONS_OBLIGATOIRES: tuple[dict, ...] = (
    {"code": "facture_validee", "libelle": "Facture validée (comptabilisée)",
     "niveau": "bloquant", "reference": "CGI art. 146 (pièces justificatives)"},
    {"code": "numero", "libelle": "Numéro de la facture (séquentiel, sans trou)",
     "niveau": "bloquant", "reference": "Loi 15-95 (code de commerce) ; CGI art. 146"},
    {"code": "date", "libelle": "Date d'émission",
     "niveau": "bloquant", "reference": "Loi 15-95 (code de commerce)"},
    {"code": "vendeur_identite", "libelle": "Identité du vendeur (nom ou raison sociale)",
     "niveau": "bloquant", "reference": "Loi 15-95 (code de commerce)"},
    {"code": "vendeur_if", "libelle": "Identifiant fiscal du vendeur",
     "niveau": "bloquant", "reference": "CGI art. 146 ; identifiants du dossier"},
    {"code": "vendeur_ice", "libelle": "ICE du vendeur (identifiant commun)",
     "niveau": "avertissement", "reference": "Obligation d'ICE (identifiant commun)"},
    {"code": "vendeur_rc", "libelle": "Registre de commerce du vendeur",
     "niveau": "avertissement", "reference": "Loi 15-95 (code de commerce)"},
    {"code": "vendeur_adresse", "libelle": "Adresse du vendeur",
     "niveau": "avertissement", "reference": "Loi 15-95 (code de commerce)"},
    {"code": "client_identite", "libelle": "Identité du client (nom ou raison sociale)",
     "niveau": "bloquant", "reference": "Loi 15-95 (code de commerce)"},
    {"code": "client_if", "libelle": "Identifiant fiscal du client",
     "niveau": "avertissement", "reference": "CGI art. 146 (facturation aux assujettis)"},
    {"code": "lignes", "libelle": "Au moins une ligne de facturation",
     "niveau": "bloquant", "reference": "CGI art. 146"},
    {"code": "designation", "libelle": "Désignation des biens ou services",
     "niveau": "bloquant", "reference": "CGI art. 146"},
    {"code": "quantite_prix", "libelle": "Quantités et prix unitaires hors taxe",
     "niveau": "bloquant", "reference": "CGI art. 146"},
    {"code": "taux_tva", "libelle": "Taux de TVA appliqué par ligne",
     "niveau": "bloquant", "reference": "CGI art. 88 et 146"},
    {"code": "montants", "libelle": "Montants HT, TVA et TTC cohérents avec les lignes",
     "niveau": "bloquant", "reference": "CGI art. 146 (contrôle de cohérence)"},
    {"code": "mode_paiement", "libelle": "Mode de paiement",
     "niveau": "avertissement", "reference": "CGI art. 146 ; annexe 2 RD V2.0 (paiements)"},
    {"code": "echeance", "libelle": "Date d'échéance de règlement",
     "niveau": "avertissement", "reference": "Loi 15-95 (code de commerce)"},
)
MENTIONS_PAR_CODE = {mention["code"]: mention for mention in MENTIONS_OBLIGATOIRES}


def mentions_obligatoires() -> list[dict]:
    """Catalogue des mentions controlees (code, libelle, niveau, reference)."""
    return [dict(mention) for mention in MENTIONS_OBLIGATOIRES]


def _present(valeur: object) -> bool:
    """Une mention est presente si la valeur est renseignee (et non nulle)."""
    if valeur is None:
        return False
    if isinstance(valeur, str):
        return bool(valeur.strip())
    if isinstance(valeur, Decimal):
        return valeur != 0
    return True


def controles_mentions(
    db: Session, company: Company, invoice: Invoice
) -> list[dict]:
    """Controle les **mentions obligatoires** d'une facture de vente.

    Retourne une ligne par mention (`present` vrai/faux, `niveau`, `reference`) :
    les mentions **bloquantes** manquantes interdisent la generation du document
    electronique ; les **avertissements** sont signales a l'utilisateur.
    """
    from app.models import ThirdParty  # noqa: PLC0415 - import local
    from app.services.invoicing import compute_line  # noqa: PLC0415 - import local

    partenaire = db.get(ThirdParty, invoice.partner_id) if invoice.partner_id else None
    lignes = list(invoice.lines)
    montants = [compute_line(
        {
            "quantity": ligne.quantity,
            "unit_price": ligne.unit_price,
            "discount_percent": ligne.discount_percent,
            "vat_rate": ligne.vat_rate,
        }
    ) for ligne in lignes]
    total_ht = money(sum((ligne["line_ht"] for ligne in montants), Decimal("0")))
    total_tva = money(sum((ligne["line_vat"] for ligne in montants), Decimal("0")))
    total_ttc = money(sum((ligne["line_ttc"] for ligne in montants), Decimal("0")))
    coherent = (
        lignes
        and total_ht == money(invoice.total_ht)
        and total_tva == money(invoice.total_vat)
        and total_ttc == money(invoice.total_ttc)
    )

    controles: list[dict] = []

    def ajouter(code: str, present: object) -> None:
        mention = MENTIONS_PAR_CODE[code]
        est_present = bool(present)
        controles.append(
            {
                "code": code,
                "libelle": mention["libelle"],
                "niveau": mention["niveau"],
                "reference": mention["reference"],
                "present": est_present,
                "message": (
                    None
                    if est_present
                    else f"Mention manquante : {mention['libelle']} "
                    f"({mention['reference']})"
                ),
            }
        )

    ajouter("facture_validee", invoice.status != INVOICE_STATUS_DRAFT)
    ajouter("numero", invoice.number)
    ajouter("date", invoice.invoice_date)
    ajouter("vendeur_identite", company.name)
    ajouter("vendeur_if", company.fiscal_id)
    ajouter("vendeur_ice", company.ice)
    ajouter("vendeur_rc", company.rc)
    ajouter("vendeur_adresse", company.address or company.city)
    ajouter("client_identite", partenaire.name if partenaire else None)
    ajouter(
        "client_if",
        (partenaire.fiscal_id or partenaire.ice) if partenaire else None,
    )
    ajouter("lignes", lignes)
    ajouter("designation", bool(lignes) and all(ligne.designation for ligne in lignes))
    ajouter(
        "quantite_prix",
        bool(lignes)
        and all(
            Decimal(str(ligne.quantity)) > 0 and Decimal(str(ligne.unit_price)) >= 0
            for ligne in lignes
        ),
    )
    ajouter(
        "taux_tva",
        bool(lignes) and all(Decimal(str(ligne.vat_rate)) >= 0 for ligne in lignes),
    )
    ajouter("montants", coherent)
    ajouter("mode_paiement", invoice.payment_mode)
    ajouter("echeance", invoice.due_date)
    return controles


def controles_bloquants(controles: list[dict]) -> list[dict]:
    """Mentions **bloquantes** manquantes (interdisent la generation du document)."""
    return [
        controle
        for controle in controles
        if controle["niveau"] == "bloquant" and not controle["present"]
    ]


def mentions_manquantes(controles: list[dict]) -> list[dict]:
    """Toutes les mentions manquantes (bloquantes et avertissements)."""
    return [controle for controle in controles if not controle["present"]]


# ---------------------------------------------------------------------------
# Fichier de facture electronique (format interne, non conforme DGI)
# ---------------------------------------------------------------------------
def xml_filename(company: Company, invoice: Invoice) -> str:
    """Nom du fichier de facture electronique (deterministe)."""
    numero = (invoice.number or f"F{invoice.id}").replace("/", "-").replace(" ", "_")
    return f"FactureElectronique_{numero}.xml"


def _balise(nom: str, valeur: object, *, niveau: int) -> str:
    """Balise XML indentee (valeur echappee ; balise vide omise)."""
    if valeur is None or valeur == "":
        return ""
    if isinstance(valeur, Decimal):
        texte = f"{valeur:.2f}"
    elif hasattr(valeur, "isoformat"):
        texte = valeur.isoformat()
    else:
        texte = str(valeur)
    return f"{'  ' * niveau}<{nom}>{escape(texte)}</{nom}>"


def _bloc(nom: str, elements: list[str], *, niveau: int) -> list[str]:
    """Ouvre/ferme un bloc XML en conservant les elements non vides."""
    contenu = [element for element in elements if element]
    if not contenu:
        return []
    return [
        f"{'  ' * niveau}<{nom}>",
        *contenu,
        f"{'  ' * niveau}</{nom}>",
    ]


def build_e_invoice_xml(
    db: Session, company: Company, invoice: Invoice, *, pdf_nom: str | None = None
) -> str:
    """Construit le fichier de **facture electronique** (format **interne**).

    ATTENTION : la specification DGI n'etant pas publiee, le fichier porte
    explicitement `<conformite>non validée (spécification DGI non publiée)</conformite>`
    et **ne doit pas** etre depose tel quel : il sert a preparer les donnees, a
    l'archive interne et au **repli EFI** (televersement sur le portail SIMPL).

    Structure : entete (emetteur, destinataire, facture), lignes, totaux, pieces,
    conformite. Les montants reproduisent ceux de la comptabilite (aucun recalcul
    divergent : le controle de coherence des montants est bloquant en amont).
    """
    from app.models import ThirdParty  # noqa: PLC0415 - import local

    partenaire = db.get(ThirdParty, invoice.partner_id) if invoice.partner_id else None
    lignes = list(invoice.lines)
    parties: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    parties.append(
        f'<FactureElectronique version="{FORMAT_INTERNE}" '
        f'type="{"avoir" if invoice.is_credit_note else invoice.invoice_type}">'
    )
    parties.extend(
        _bloc(
            "emetteur",
            [
                _balise("nom", company.name, niveau=3),
                _balise("identifiantFiscal", company.fiscal_id, niveau=3),
                _balise("ice", company.ice, niveau=3),
                _balise("registreCommerce", company.rc, niveau=3),
                _balise("adresse", company.address, niveau=3),
                _balise("ville", company.city, niveau=3),
            ],
            niveau=2,
        )
    )
    if partenaire is not None:
        parties.extend(
            _bloc(
                "destinataire",
                [
                    _balise("nom", partenaire.name, niveau=3),
                    _balise("identifiantFiscal", partenaire.fiscal_id, niveau=3),
                    _balise("ice", partenaire.ice, niveau=3),
                    _balise("adresse", partenaire.address, niveau=3),
                    _balise("ville", partenaire.city, niveau=3),
                ],
                niveau=2,
            )
        )
    parties.extend(
        _bloc(
            "facture",
            [
                _balise("numero", invoice.number, niveau=3),
                _balise("date", invoice.invoice_date, niveau=3),
                _balise("echeance", invoice.due_date, niveau=3),
                _balise(
                    "type",
                    "avoir" if invoice.is_credit_note else invoice.invoice_type,
                    niveau=3,
                ),
                _balise("modePaiement", invoice.payment_mode, niveau=3),
                _balise("reference", invoice.reference, niveau=3),
            ],
            niveau=2,
        )
    )
    lignes_xml: list[str] = []
    for position, ligne in enumerate(lignes, start=1):
        montant_ht = money(
            Decimal(str(ligne.quantity))
            * Decimal(str(ligne.unit_price))
            * (Decimal("1") - Decimal(str(ligne.discount_percent or 0)) / Decimal("100"))
        )
        montant_tva = money(montant_ht * Decimal(str(ligne.vat_rate)) / Decimal("100"))
        lignes_xml.extend(
            _bloc(
                "ligne",
                [
                    _balise("numero", position, niveau=3),
                    _balise("designation", ligne.designation, niveau=3),
                    _balise("quantite", Decimal(str(ligne.quantity)), niveau=3),
                    _balise("prixUnitaireHT", Decimal(str(ligne.unit_price)), niveau=3),
                    _balise(
                        "remisePourcent",
                        Decimal(str(ligne.discount_percent or 0)),
                        niveau=3,
                    ),
                    _balise("tauxTva", Decimal(str(ligne.vat_rate)), niveau=3),
                    _balise("montantHT", montant_ht, niveau=3),
                    _balise("montantTva", montant_tva, niveau=3),
                    _balise("montantTtc", money(montant_ht + montant_tva), niveau=3),
                    _balise("compte", ligne.account_number, niveau=3),
                ],
                niveau=2,
            )
        )
    parties.extend(_bloc("lignes", lignes_xml, niveau=1) or ["  <lignes></lignes>"])
    parties.extend(
        _bloc(
            "totaux",
            [
                _balise("totalHT", invoice.total_ht, niveau=2),
                _balise("totalTva", invoice.total_vat, niveau=2),
                _balise("totalTtc", invoice.total_ttc, niveau=2),
                _balise("devise", settings.currency, niveau=2),
            ],
            niveau=1,
        )
    )
    if pdf_nom:
        parties.extend(_bloc("pieces", [_balise("piece", pdf_nom, niveau=2)], niveau=1))
    parties.append(f"  <conformite>{escape(CONFORMITE_NON_VALIDEE)}</conformite>")
    parties.append("</FactureElectronique>")
    return "\n".join(partie for partie in parties if partie) + "\n"


def valider_conformite(xml: str, *, schema: str | None = None) -> dict:
    """Validation du fichier de facture electronique : **jamais « conforme » a ce jour**.

    Sans schema officiel publie, la fonction retourne `valide = None` : le fichier est
    un **format interne**. Des qu'un schema DGI (ou de place de marche) est fourni, il
    doit etre passe en `schema` : la validation devient alors **reelle** (`lxml`, meme
    doctrine que la DTS et la liasse).
    """
    if not schema:
        return {
            "valide": None,
            "message": (
                "Spécification e-facturation de la DGI non publiée (aucun schéma "
                "fourni) : le fichier est un format interne et ne doit pas être déposé "
                "tel quel comme facture électronique (incohérence A24)."
            ),
            "schema": None,
        }
    try:  # pragma: no cover - dépend d'un schéma externe non fourni
        from lxml import etree

        validateur = etree.XMLSchema(etree.parse(schema))
        document = etree.fromstring(xml.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - schéma ou fichier illisible
        return {
            "valide": False,
            "message": f"Validation impossible ({schema}) : {exc}",
            "schema": schema,
        }
    if validateur.validate(document):
        return {
            "valide": True,
            "message": f"Fichier conforme à {schema}.",
            "schema": schema,
        }
    erreurs = " ; ".join(
        f"ligne {erreur.line} : {erreur.message}" for erreur in list(validateur.error_log)[:5]
    )
    return {
        "valide": False,
        "message": f"Écarts au schéma : {erreurs}",
        "schema": schema,
    }


# ---------------------------------------------------------------------------
# Cycle de vie du document electronique
# ---------------------------------------------------------------------------
def document(db: Session, company_id: int, invoice_id: int) -> EInvoiceDocument | None:
    """Document electronique d'une facture (None si non genere)."""
    return db.execute(
        select(EInvoiceDocument).where(
            EInvoiceDocument.company_id == company_id,
            EInvoiceDocument.invoice_id == invoice_id,
        )
    ).scalar_one_or_none()


def generer_document(
    db: Session,
    company: Company,
    invoice: Invoice,
    *,
    pdf_nom: str | None = None,
    user_id: int | None = None,
) -> EInvoiceDocument:
    """Genere (ou regenere) le document electronique d'une facture.

    Refuse la generation si une **mention obligatoire bloquante** manque (le message
    liste les mentions a completer) ; un document **accepte** ou **rejete** par la
    plateforme est **fige**. L'empreinte **SHA-256** du fichier est conservee.
    """
    if invoice.company_id != company.id:
        raise EInvoiceError("Facture hors du dossier courant.")
    controles = controles_mentions(db, company, invoice)
    bloquants = controles_bloquants(controles)
    if bloquants:
        details = " ; ".join(controle["message"] for controle in bloquants)
        raise EInvoiceError(
            f"Facture {invoice.number or invoice.id} inéligible à la facturation "
            f"électronique : {details}"
        )
    xml = build_e_invoice_xml(db, company, invoice, pdf_nom=pdf_nom)
    validation = valider_conformite(xml)
    objet = document(db, company.id, invoice.id)
    if objet is not None and objet.statut in STATUTS_TERMINAUX:
        raise EInvoiceError(
            f"Le document de la facture {invoice.number or invoice.id} est déjà "
            f"« {objet.statut_libelle} » : il ne peut plus être régénéré."
        )
    if objet is None:
        objet = EInvoiceDocument(
            invoice_id=invoice.id, company_id=company.id, statut=STATUT_A_GENERER
        )
        db.add(objet)
        db.flush()
    objet.statut = STATUT_GENERE
    objet.format = FORMAT_INTERNE
    objet.xml = xml
    objet.hash_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    objet.notes = validation["message"]
    db.flush()
    log_action(
        db,
        action="E_INVOICE_GENERATED",
        entity="EInvoiceDocument",
        entity_id=objet.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "invoice_id": invoice.id,
            "numero": invoice.number,
            "format": objet.format,
            "hash": objet.hash_sha256,
            "conformite": validation["valide"],
        },
    )
    return objet


def envoyer(
    db: Session,
    objet: EInvoiceDocument,
    *,
    canal: str = CANAL_API,
    endpoint: str | None = None,
    api_key: str | None = None,
    dry_run: bool | None = None,
    jour: date | None = None,
    user_id: int | None = None,
) -> EInvoiceDocument:
    """Transmet le document au **canal DGI** (ou prepare le depot manuel / EFI).

    Le canal **API** n'appelle un service distant que si un **endpoint** est configure
    **et** que la **simulation** est desactivee (`e_invoice_dry_run = false`) : par
    defaut l'application ne fait **aucune requete reseau** et enregistre un etat
    « transmis (simulation) », a deposer sur le portail (repli EFI).
    """
    if objet.statut in STATUTS_TERMINAUX:
        raise EInvoiceError(
            f"Document déjà « {objet.statut_libelle} » : aucune nouvelle transmission."
        )
    if not objet.xml:
        raise EInvoiceError("Document non généré : produisez le fichier avant l'envoi.")
    if canal not in E_INVOICE_CANAUX:
        raise EInvoiceError(
            f"Canal « {canal} » inconnu (valeurs admises : {', '.join(E_INVOICE_CANAUX)})."
        )
    endpoint = endpoint or settings.e_invoice_endpoint
    api_key = api_key or settings.e_invoice_api_key
    simulation = settings.e_invoice_dry_run if dry_run is None else dry_run
    jour = jour or date.today()
    identifiant_dgi: str | None = None
    if canal == CANAL_API and endpoint and not simulation:
        import httpx  # noqa: PLC0415 - import local (dépendance optionnelle)

        entetes = {"Content-Type": "application/xml"}
        if api_key:
            entetes["Authorization"] = f"Bearer {api_key}"
        try:
            reponse = httpx.post(
                endpoint, content=objet.xml.encode("utf-8"), headers=entetes, timeout=30
            )
        except Exception as exc:  # noqa: BLE001 - erreur réseau : message explicite
            raise EInvoiceError(f"Transmission impossible ({endpoint}) : {exc}") from exc
        try:
            donnees = reponse.json()
        except Exception:  # noqa: BLE001 - réponse non JSON
            donnees = {}
        identifiant_dgi = donnees.get("identifiantDgi") or donnees.get("identifiant")
        objet.accuse = f"HTTP {reponse.status_code} — {reponse.text[:500]}"
    else:
        objet.accuse = (
            "Transmission non effectuée par l'application : "
            f"canal {canal} (simulation={simulation}, endpoint="
            f"{endpoint or 'non configuré'}) — dépôt à effectuer sur le portail DGI "
            "(repli EFI)."
        )
    objet.statut = STATUT_ENVOYE
    objet.canal = canal
    objet.envoye_le = jour
    if identifiant_dgi:
        objet.identifiant_dgi = str(identifiant_dgi)
    db.flush()
    log_action(
        db,
        action="E_INVOICE_SENT",
        entity="EInvoiceDocument",
        entity_id=objet.id,
        user_id=user_id,
        company_id=objet.company_id,
        payload={
            "canal": canal,
            "simulation": simulation,
            "identifiant_dgi": objet.identifiant_dgi,
            "envoye_le": objet.envoye_le.isoformat() if objet.envoye_le else None,
        },
    )
    return objet


def enregistrer_accuse(
    db: Session,
    objet: EInvoiceDocument,
    *,
    identifiant_dgi: str | None = None,
    accuse: str | None = None,
    accepte: bool = True,
    jour: date | None = None,
    user_id: int | None = None,
) -> EInvoiceDocument:
    """Enregistre l'**accuse de reception** de la plateforme (accepte ou rejete)."""
    if objet.statut in STATUTS_TERMINAUX:
        raise EInvoiceError(
            f"Document déjà « {objet.statut_libelle} » : aucun nouvel accusé possible."
        )
    if objet.statut != STATUT_ENVOYE:
        raise EInvoiceError("Accusé impossible : le document n'a pas encore été transmis.")
    if not accepte and not (accuse or "").strip():
        raise EInvoiceError("Un rejet doit être motivé (accusé obligatoire).")
    objet.statut = STATUT_ACCEPTE if accepte else STATUT_REJETE
    objet.accuse_le = jour or date.today()
    if identifiant_dgi:
        objet.identifiant_dgi = str(identifiant_dgi)
    if accuse:
        objet.accuse = accuse
    db.flush()
    log_action(
        db,
        action="E_INVOICE_ACKNOWLEDGED",
        entity="EInvoiceDocument",
        entity_id=objet.id,
        user_id=user_id,
        company_id=objet.company_id,
        payload={
            "statut": objet.statut,
            "identifiant_dgi": objet.identifiant_dgi,
            "accuse_le": objet.accuse_le.isoformat() if objet.accuse_le else None,
        },
    )
    return objet


# ---------------------------------------------------------------------------
# Etats, controles de dossier et situation
# ---------------------------------------------------------------------------
def list_documents(
    db: Session,
    company_id: int,
    *,
    statut: str | None = None,
    invoice_id: int | None = None,
) -> list[EInvoiceDocument]:
    """Documents electroniques du dossier (filtres par statut et/ou facture)."""
    requete = select(EInvoiceDocument).where(EInvoiceDocument.company_id == company_id)
    if statut:
        requete = requete.where(EInvoiceDocument.statut == statut)
    if invoice_id is not None:
        requete = requete.where(EInvoiceDocument.invoice_id == invoice_id)
    return list(db.execute(requete.order_by(EInvoiceDocument.id.desc())).scalars())


def _factures_vente(db: Session, company_id: int, annee: int | None) -> list[Invoice]:
    """Factures de vente du dossier (filtre par exercice de la date de facture)."""
    requete = select(Invoice).where(
        Invoice.company_id == company_id,
        Invoice.invoice_type == "vente",
    )
    if annee is not None:
        requete = requete.where(
            Invoice.invoice_date >= date(annee, 1, 1),
            Invoice.invoice_date <= date(annee, 12, 31),
        )
    return list(db.execute(requete.order_by(Invoice.invoice_date, Invoice.id)).scalars())


def controles_e_facturation(
    db: Session, company: Company, *, annee: int | None = None
) -> list[dict]:
    """Controles du dossier de facturation electronique (CDC § 4.1 et § 6.5).

    - `efacture.canal_non_configure` (**information**) : `E_INVOICE_ENDPOINT` vide →
      depot manuel / EFI ;
    - `efacture.specification_absente` (**information**) : specification DGI non
      publiee, aucun fichier declare conforme (A24) ;
    - `efacture.mentions_manquantes` (**avertissement**) : factures validees dont une
      mention bloquante manque (transmission impossible en l'etat) ;
    - `efacture.document_manquant`, `efacture.transmission_en_attente`,
      `efacture.accuse_en_attente`, `efacture.rejetee` (**avertissements**) ;
    - `efacture.recap` (**information**).
    """
    controles: list[dict] = []

    def ajouter(code: str, niveau: str, message: str) -> None:
        controles.append({"code": code, "niveau": niveau, "message": message})

    if not settings.e_invoice_endpoint:
        ajouter(
            "efacture.canal_non_configure",
            "information",
            "Aucun endpoint DGI configuré (E_INVOICE_ENDPOINT) : les documents sont "
            "préparés puis déposés manuellement (repli EFI) sur le portail SIMPL.",
        )
    ajouter(
        "efacture.specification_absente",
        "information",
        "Spécification e-facturation de la DGI non publiée : le fichier produit est un "
        "format interne (`interne-v1`) et n'est **pas** déclaré conforme (A24).",
    )
    factures = _factures_vente(db, company.id, annee)
    validees = [facture for facture in factures if facture.status != INVOICE_STATUS_DRAFT]
    sans_document: list[str] = []
    mentions: list[str] = []
    for facture in validees:
        objet = document(db, company.id, facture.id)
        reference = facture.number or f"#{facture.id}"
        if objet is None or objet.statut == STATUT_A_GENERER:
            sans_document.append(reference)
        bloquants = controles_bloquants(controles_mentions(db, company, facture))
        if bloquants:
            mentions.append(f"{reference} ({len(bloquants)} mention(s) bloquante(s))")
    if sans_document:
        ajouter(
            "efacture.document_manquant",
            "avertissement",
            f"{len(sans_document)} facture(s) de vente validée(s) sans document "
            f"électronique : {', '.join(sans_document[:5])}"
            + ("…" if len(sans_document) > 5 else ""),
        )
    if mentions:
        ajouter(
            "efacture.mentions_manquantes",
            "avertissement",
            f"{len(mentions)} facture(s) dont une mention obligatoire bloquante manque : "
            f"{', '.join(mentions[:5])}" + ("…" if len(mentions) > 5 else ""),
        )
    documents = list_documents(db, company.id)
    generes = [objet for objet in documents if objet.statut == STATUT_GENERE]
    if generes:
        ajouter(
            "efacture.transmission_en_attente",
            "avertissement",
            f"{len(generes)} document(s) généré(s) non transmis (facture(s) "
            f"{', '.join(str(objet.invoice_id) for objet in generes[:5])}).",
        )
    en_attente = [
        objet
        for objet in documents
        if objet.statut == STATUT_ENVOYE and objet.accuse_le is None
    ]
    if en_attente:
        ajouter(
            "efacture.accuse_en_attente",
            "avertissement",
            f"{len(en_attente)} document(s) transmis en attente d'accusé de réception.",
        )
    rejetes = [objet for objet in documents if objet.statut == STATUT_REJETE]
    if rejetes:
        ajouter(
            "efacture.rejetee",
            "avertissement",
            f"{len(rejetes)} document(s) rejeté(s) : corrigez la facture puis régénérez "
            "le document.",
        )
    ajouter(
        "efacture.recap",
        "information",
        f"Facturation électronique {annee or 'toutes années'} : {len(factures)} "
        f"facture(s) de vente, {len(validees)} validée(s), {len(documents)} document(s) — "
        + ", ".join(
            f"{statut} {len([o for o in documents if o.statut == statut])}"
            for statut in (STATUT_GENERE, STATUT_ENVOYE, STATUT_ACCEPTE, STATUT_REJETE)
        )
        + ".",
    )
    return controles


def controles_bloquants_dossier(controles: list[dict]) -> list[dict]:
    """Controles bloquants du dossier (aucun a ce jour : specification non publiee)."""
    return [controle for controle in controles if controle["niveau"] == "bloquant"]


def situation(db: Session, company: Company, *, annee: int | None = None) -> dict:
    """Situation de la facturation electronique d'un dossier (lecture seule).

    Restitue les documents (statut, canal, empreinte), les factures de vente sans
    document, le catalogue des mentions controlees et les controles de dossier.
    """
    factures = _factures_vente(db, company.id, annee)
    documents = list_documents(db, company.id)
    associes = {objet.invoice_id for objet in documents}
    return {
        "annee": annee,
        "documents": documents,
        "factures": factures,
        "sans_document": [facture for facture in factures if facture.id not in associes],
        "mentions": mentions_obligatoires(),
        "controles": controles_e_facturation(db, company, annee=annee),
        "canal": settings.e_invoice_endpoint or "non configuré (dépôt manuel / EFI)",
        "simulation": settings.e_invoice_dry_run,
        "format": FORMAT_INTERNE,
        "conformite": CONFORMITE_NON_VALIDEE,
    }