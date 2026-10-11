"""Piste d'audit fiable et journal d'audit exploitable (P1.6).

Deux responsabilites :

1. **Piste d'audit fiable** — chaque ecriture validee recoit une **empreinte
   SHA-256** calculee sur son contenu canonique, **chainee** avec l'empreinte de
   l'ecriture precedente : toute modification faite hors application (test
   d'intrusion, edition directe de la base) **casse le chainage** et devient
   detectable (`verifier_chainage`). Reference : CGNC « organisation de la
   comptabilite » (livres sans blanc ni alteration) et CGI (conservation 10 ans).
2. **Journal d'audit exploitable** — interrogation avec filtres, export CSV, et
   **minimisation des donnees personnelles** a l'export (loi 09-08 / CNDP).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ENTRY_STATUS_DRAFT, ENTRY_STATUS_VALIDATED, AuditLog, Entry, User

# Champs consideres comme des donnees personnelles (loi 09-08) : masques a l'export.
CHAMPS_PERSONNELS = (
    "name",
    "nom",
    "cnss",
    "cin",
    "email",
    "phone",
    "telephone",
    "address",
    "adresse",
    "rib",
    "iban",
)

MASQUE = "***masque (loi 09-08)***"


def contenu_canonique(entry: Entry, *, previous_hash: str | None) -> str:
    """Representation canonique d'une ecriture (base de l'empreinte SHA-256)."""
    contenu = {
        "company_id": entry.company_id,
        "entry_number": entry.entry_number,
        "entry_date": entry.entry_date.isoformat(),
        "journal_id": entry.journal_id,
        "label": entry.label,
        "reference": entry.reference,
        "source": entry.source,
        "source_id": entry.source_id,
        "lines": [
            {
                "account_number": ligne.account_number,
                "third_party_id": ligne.third_party_id,
                "debit": str(ligne.debit),
                "credit": str(ligne.credit),
                "position": ligne.position,
            }
            for ligne in sorted(entry.lines, key=lambda l: (l.position, l.id or 0))
        ],
        "previous_hash": previous_hash,
    }
    return json.dumps(contenu, sort_keys=True, ensure_ascii=False)


def empreinte_ecriture(entry: Entry, *, previous_hash: str | None = None) -> str:
    """Empreinte SHA-256 d'une ecriture (contenu + empreinte precedente)."""
    return hashlib.sha256(
        contenu_canonique(entry, previous_hash=previous_hash).encode("utf-8")
    ).hexdigest()


def derniere_empreinte(db: Session, company_id: int) -> str | None:
    """Empreinte de la derniere ecriture scellee du dossier (maillon courant)."""
    return db.execute(
        select(Entry.entry_hash)
        .where(
            Entry.company_id == company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
            Entry.entry_hash.is_not(None),
        )
        .order_by(Entry.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def chainer_ecriture(db: Session, entry: Entry) -> str:
    """Scelle une ecriture validee : empreinte + chainage (appele a la validation)."""
    precedente = entry.previous_hash or derniere_empreinte(db, entry.company_id)
    entry.previous_hash = precedente
    entry.entry_hash = empreinte_ecriture(entry, previous_hash=precedente)
    db.flush()
    return entry.entry_hash


def sceller_ecritures(db: Session, company_id: int) -> dict:
    """Scelle les ecritures validees anterieures au chainage (reprise de dossier).

    Les ecritures validees avant la mise en place de la piste d'audit n'ont pas
    d'empreinte : elles sont scellees **dans l'ordre chronologique** (id croissant),
    ce qui reconstitue un chainage coherent de bout en bout.
    """
    ecritures = list(
        db.execute(
            select(Entry)
            .where(
                Entry.company_id == company_id,
                Entry.status == ENTRY_STATUS_VALIDATED,
            )
            .order_by(Entry.id)
        ).scalars()
    )
    scellees: list[int] = []
    precedente: str | None = None
    for entry in ecritures:
        if entry.entry_hash and entry.previous_hash == precedente:
            precedente = entry.entry_hash
            continue
        entry.previous_hash = precedente
        entry.entry_hash = empreinte_ecriture(entry, previous_hash=precedente)
        precedente = entry.entry_hash
        scellees.append(entry.id)
    db.flush()
    return {
        "company_id": company_id,
        "total_ecritures": len(ecritures),
        "scellees": scellees,
        "nb_scellees": len(scellees),
        "derniere_empreinte": precedente,
    }


def verifier_chainage(db: Session, company_id: int) -> dict:
    """Verifie l'integrite de la piste : toute rupture = dossier altere hors application."""
    ecritures = list(
        db.execute(
            select(Entry)
            .where(
                Entry.company_id == company_id,
                Entry.status == ENTRY_STATUS_VALIDATED,
            )
            .order_by(Entry.id)
        ).scalars()
    )
    ruptures: list[dict] = []
    non_scellees: list[int] = []
    precedente: str | None = None
    for entry in ecritures:
        if not entry.entry_hash:
            non_scellees.append(entry.id)
            ruptures.append(
                {
                    "entry_id": entry.id,
                    "entry_number": entry.entry_number,
                    "type": "non_scellee",
                    "detail": "Ecriture validee sans empreinte : a sceller.",
                }
            )
            continue
        if entry.previous_hash != precedente:
            ruptures.append(
                {
                    "entry_id": entry.id,
                    "entry_number": entry.entry_number,
                    "type": "chainage_rompu",
                    "detail": (
                        f"Empreinte precedente attendue {precedente or 'None'}, "
                        f"trouvee {entry.previous_hash or 'None'} : une ecriture a ete "
                        "inseree, supprimee ou deplacee hors application."
                    ),
                }
            )
        recalcul = empreinte_ecriture(entry, previous_hash=entry.previous_hash)
        if recalcul != entry.entry_hash:
            ruptures.append(
                {
                    "entry_id": entry.id,
                    "entry_number": entry.entry_number,
                    "type": "contenu_altere",
                    "detail": (
                        f"Empreinte attendue {recalcul}, trouvee {entry.entry_hash} : "
                        "le contenu de l'ecriture a ete modifie hors application."
                    ),
                }
            )
        precedente = entry.entry_hash
    return {
        "company_id": company_id,
        "nb_ecritures": len(ecritures),
        "nb_scellees": len([e for e in ecritures if e.entry_hash]),
        "non_scellees": non_scellees,
        "ruptures": ruptures,
        "integre": not ruptures,
        "derniere_empreinte": precedente,
    }



# ---------------------------------------------------------------------------
# Journal d'audit exploitable
# ---------------------------------------------------------------------------
def journal_audit(
    db: Session,
    *,
    company_id: int | None = None,
    action: str | None = None,
    entity: str | None = None,
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    limit: int | None = 200,
    offset: int = 0,
) -> list[AuditLog]:
    """Journal d'audit filtre (qui a fait quoi, quand, sur quoi)."""
    requete = select(AuditLog)
    if company_id is not None:
        requete = requete.where(AuditLog.company_id == company_id)
    if action:
        requete = requete.where(AuditLog.action == action)
    if entity:
        requete = requete.where(AuditLog.entity == entity)
    if user_id is not None:
        requete = requete.where(AuditLog.user_id == user_id)
    if date_from is not None:
        requete = requete.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        requete = requete.where(AuditLog.created_at < _lendemain(date_to))
    if search:
        motif = f"%{search.strip()}%"
        requete = requete.where(AuditLog.payload_json.ilike(motif))
    requete = requete.order_by(AuditLog.id.desc()).offset(offset)
    if limit is not None:
        requete = requete.limit(limit)
    return list(db.execute(requete).scalars())


def _lendemain(jour: date) -> date:
    """Lendemain d'une date (bornes de filtre inclusives)."""
    from datetime import timedelta

    return jour + timedelta(days=1)


def compte_journal(db: Session, **filtres: object) -> int:
    """Nombre d'entrees correspondant aux filtres (pagination de l'ecran)."""
    filtres.pop("limit", None)
    filtres.pop("offset", None)
    return len(journal_audit(db, limit=None, **filtres))  # type: ignore[arg-type]


def actions_journal(db: Session, company_id: int | None = None) -> list[str]:
    """Actions presentes dans le journal (alimente les listes deroulantes)."""
    requete = select(AuditLog.action).distinct().order_by(AuditLog.action)
    if company_id is not None:
        requete = requete.where(AuditLog.company_id == company_id)
    return [action for action in db.execute(requete).scalars()]


def utilisateurs_journal(db: Session, company_id: int | None = None) -> list[tuple[int, str]]:
    """Utilisateurs presents dans le journal (identifiant + libelle)."""
    requete = (
        select(User.id, User.full_name, User.email)
        .join(AuditLog, AuditLog.user_id == User.id)
        .distinct()
        .order_by(User.full_name)
    )
    if company_id is not None:
        requete = requete.where(AuditLog.company_id == company_id)
    return [
        (identifiant, nom or email)
        for identifiant, nom, email in db.execute(requete).all()
    ]


def anonymiser_payload(payload_json: str | None) -> str | None:
    """Masque les donnees personnelles d'une charge utile (loi 09-08 / CNDP).

    La journalisation doit permettre la tracabilite des **acces** sans exposer les
    donnees personnelles (salaries, tiers) : a l'export, toute clef reconnue comme
    personnelle est remplacee par un marqueur.
    """
    if not payload_json:
        return payload_json
    try:
        contenu = json.loads(payload_json)
    except (TypeError, ValueError):
        return payload_json
    if not isinstance(contenu, dict):
        return payload_json
    for cle in list(contenu):
        if cle.lower() in CHAMPS_PERSONNELS:
            contenu[cle] = MASQUE
    return json.dumps(contenu, ensure_ascii=False, sort_keys=True)


def export_journal_csv(
    db: Session,
    *,
    company_id: int | None = None,
    anonymiser: bool = True,
    **filtres: object,
) -> str:
    """Export CSV du journal (separateur « ; », BOM UTF-8 pour Excel).

    ``anonymiser = True`` (defaut) applique la minimisation des donnees
    personnelles exigee par la loi 09-08.
    """
    entrees = journal_audit(db, company_id=company_id, limit=None, **filtres)  # type: ignore[arg-type]
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(
        [
            "horodatage",
            "utilisateur_id",
            "action",
            "entite",
            "entite_id",
            "societe_id",
            "adresse_ip",
            "detail",
        ]
    )
    for entree in entrees:
        detail = entree.payload_json
        if anonymiser:
            detail = anonymiser_payload(detail)
        ecrivain.writerow(
            [
                entree.created_at.strftime("%Y-%m-%d %H:%M:%S") if entree.created_at else "",
                entree.user_id if entree.user_id is not None else "",
                entree.action,
                entree.entity,
                entree.entity_id or "",
                entree.company_id if entree.company_id is not None else "",
                entree.ip_address or "",
                (detail or "").replace("\n", " "),
            ]
        )
    return "\ufeff" + tampon.getvalue()



def piste_ecriture(db: Session, entry: Entry) -> dict:
    """Tracabilite d'une ecriture : piece d'origine, empreinte et chainage.

    Repond a l'exigence CGNC / CGI : pouvoir **remonter a la piece justificative**
    (facture, reglement, fiche d'immobilisation, a-nouveaux...) et redescendre de la
    piece vers les ecritures qu'elle a produites.
    """
    from app.models import Asset, Invoice, Payment, ThirdParty

    piece: dict | None = None
    libelles = {
        "manual": "Saisie manuelle",
        "invoice": "Facture",
        "payment": "Reglement",
        "reversal": "Contre-ecriture",
        "opening": "A-nouveaux",
        "closing": "Cloture",
        "asset_acquisition": "Acquisition d'immobilisation",
        "asset_dotation": "Dotation aux amortissements",
        "asset_cession": "Cession d'immobilisation",
        "asset_rebut": "Mise au rebut",
    }
    if entry.source == "invoice":
        facture = db.get(Invoice, entry.source_id)
        if facture is not None:
            tiers = db.get(ThirdParty, facture.partner_id)
            piece = {
                "type": "Facture",
                "reference": facture.number or f"brouillon-{facture.id}",
                "date": facture.invoice_date,
                "tiers": getattr(tiers, "name", None),
                "montant": facture.total_ttc,
                "statut": facture.status,
            }
    elif entry.source == "payment":
        reglement = db.get(Payment, entry.source_id)
        if reglement is not None:
            piece = {
                "type": "Reglement",
                "reference": f"RGT{reglement.id}",
                "date": reglement.payment_date,
                "tiers": None,
                "montant": reglement.amount,
                "statut": reglement.method,
            }
    elif entry.source.startswith("asset"):
        actif = db.get(Asset, entry.source_id)
        if actif is not None:
            piece = {
                "type": "Fiche d'immobilisation",
                "reference": actif.code,
                "date": actif.acquisition_date,
                "tiers": actif.label,
                "montant": actif.valeur_origine,
                "statut": actif.statut,
            }
    elif entry.source == "opening":
        piece = {
            "type": "A-nouveaux",
            "reference": entry.reference,
            "date": entry.entry_date,
            "tiers": None,
            "montant": entry.total_debit,
            "statut": "ouverture",
        }
    return {
        "entry_id": entry.id,
        "entry_number": entry.entry_number,
        "entry_date": entry.entry_date,
        "label": entry.label,
        "source": entry.source,
        "source_libelle": libelles.get(entry.source, entry.source),
        "source_id": entry.source_id,
        "piece": piece,
        "empreinte": entry.entry_hash,
        "empreinte_precedente": entry.previous_hash,
        "scellee": entry.entry_hash is not None,
        "immuable": entry.status != ENTRY_STATUS_DRAFT,
    }


def ecritures_de_la_piece(db: Session, *, source: str, source_id: int) -> list[dict]:
    """Navigation inverse : toutes les ecritures produites par une piece."""
    ecritures = db.execute(
        select(Entry)
        .where(Entry.source == source, Entry.source_id == source_id)
        .order_by(Entry.id)
    ).scalars()
    return [
        {
            "entry_id": entry.id,
            "entry_number": entry.entry_number,
            "entry_date": entry.entry_date,
            "label": entry.label,
            "status": entry.status,
            "empreinte": entry.entry_hash,
        }
        for entry in ecritures
    ]

