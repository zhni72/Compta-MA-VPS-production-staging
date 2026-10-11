"""P2 — Ecrans **lecture seule** de navigation (aucune mutation comptable).

Ce module met en oeuvre la reorganisation de menu validee (P2) : il **ajoute**
des ecrans d'information alimentes par les **services existants** — aucune
ecriture, aucune transition d'etat, aucune modification de permission n'est
introduite ici (`GET` uniquement).

Ecrans :
- `/etats/esg` : etat des soldes de gestion (CGNC) ;
- `/etats/etic` : notes annexes calculables + informations non disponibles ;
- `/stocks/mouvements` : mouvements de stock (entrees / sorties) ;
- `/stocks/inventaire` : inventaire valorise (feuille de comptage) ;
- `/stocks/provisions` : provisions / depreciations de stocks ;
- `/parametres/a-nouveaux` : a-nouveaux de l'exercice (controle) ;
- `/parametres/journaux` : journaux comptables et volumetrie ;
- `/parametres/referentiels` : referentiels fiscaux et leurs sources ;
- `/audit/integrite` : controles d'integrite (chainage, equilibre, journaux) ;
- `/e-facturation` : factures electroniques et statuts de transmission ;
- `/activite` : journal d'activite (e-facturation et evenements).

Toutes ces pages utilisent le gabarit unique `ecran_lecture.html` : un titre,
des indicateurs, des tableaux et des notes — aucune logique metier nouvelle.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rates_ma import (
    COTISATION_MINIMALE_BY_YEAR,
    IS_RATES_BY_YEAR,
    SOURCES_REFERENTIELS,
)
from app.db.session import get_db
from app.models import Company, Entry, EntryLine, Invoice, Journal, StockMovement, User
from app.models.e_invoice import (
    E_INVOICE_STATUT_LABELS,
    EInvoiceDocument,
)
from app.services import audit_trail as piste
from app.services import closing as cloture
from app.services import e_invoice
from app.services import etats_synthese
from app.services import reporting
from app.services import stocks as magasin
from app.services.reporting import year_bounds
from app.web.deps import get_web_company, get_web_user, render

router = APIRouter(include_in_schema=False)


def _societe(company: Company | None) -> RedirectResponse | None:
    """Sans societe, aucune donnee : retour a la creation du dossier."""
    if company is None:
        return RedirectResponse("/parametres/societe?msg=Société requise", status_code=303)
    return None


def _page(
    request: Request,
    *,
    user: User,
    company: Company,
    titre: str,
    active: str,
    sous_titre: str = "",
    kpis: list[dict] | None = None,
    tableaux: list[dict] | None = None,
    notes: list[str] | None = None,
) -> HTMLResponse:
    """Rend un ecran lecture seule (gabarit unique)."""
    return render(
        request,
        "ecran_lecture.html",
        user=user,
        company=company,
        title=titre,
        active=active,
        titre=titre,
        sous_titre=sous_titre,
        kpis=kpis or [],
        tableaux=tableaux or [],
        notes=notes or [],
    )


def _montant(valeur: object) -> str:
    """Montant au format « 1 234,56 » (identique aux etats PDF)."""
    return f"{Decimal(str(valeur or 0)):,.2f}".replace(",", " ").replace(".", ",")


def _cellule(valeur: object) -> str:
    """Cellule de tableau : les montants sont formates, les textes restent tels quels."""
    if isinstance(valeur, (Decimal, int, float)):
        return _montant(valeur)
    return "" if valeur is None else str(valeur)


def _ligne_total(colonnes: list, montant: object) -> list[str] | None:
    """Ligne de total **alignee** sur les colonnes du tableau (derniere colonne).

    Le gabarit `ecran_lecture.html` itere les cellules de `tableau.total` : un
    total scalaire (defaut de recette P2 : `/etats/etic` en HTTP 500,
    « 'decimal.Decimal' object is not iterable ») doit donc etre converti en
    ligne de cellules — « Total » aligne sur l'avant-derniere colonne et le
    montant dans la derniere.
    """
    if montant is None:
        return None
    if len(colonnes) <= 2:
        return ["Total", _cellule(montant)]
    return [""] * (len(colonnes) - 2) + ["Total", _cellule(montant)]



def _exercice(company: Company, db: Session, year: int | None) -> int:
    """Exercice affiche par defaut : le plus recent du dossier (lecture seule)."""
    from app.web.routes import current_year  # noqa: PLC0415 - evite un cycle d'import

    return year or current_year(company, db)


# ---------------------------------------------------------------------------
# Etats de synthese — ESG et ETIC (les PDF existaient, pas les ecrans)
# ---------------------------------------------------------------------------
@router.get("/etats/esg", response_class=HTMLResponse)
def page_esg(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """ESG (etat des soldes de gestion) : marge, valeur ajoutee, EBE, resultats."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    exercice = _exercice(company, db, year)
    debut, fin = year_bounds(exercice)
    esg = etats_synthese.etat_soldes_gestion(db, company.id, debut, fin)
    return _page(
        request,
        user=user,
        company=company,
        titre=f"Etat des soldes de gestion (ESG) — exercice {exercice}",
        active="esg",
        sous_titre=f"Du {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')} — CGNC",
        kpis=[
            {"label": "Valeur ajoutee", "valeur": _montant(esg["valeur_ajoutee"])},
            {"label": "EBE", "valeur": _montant(esg["ebe"])},
            {
                "label": "Resultat net",
                "valeur": _montant(esg["resultat_net"]),
                "niveau": "positive" if esg["resultat_net"] >= 0 else "negative",
            },
            {
                "label": "Coherence CPC",
                "valeur": "coherent" if esg["coherent_avec_cpc"] else "ecart a expliquer",
                "niveau": "positive" if esg["coherent_avec_cpc"] else "negative",
            },
        ],
        tableaux=[
            {
                "titre": "Soldes de gestion",
                "colonnes": ["Solde", "Montant (DH)"],
                "lignes": [[libelle, _montant(valeur)] for libelle, valeur in esg["soldes"]],
                "alignement": "right",
            },
            {
                "titre": "Detail par famille de comptes (classes 6 et 7)",
                "colonnes": ["Famille", "Montant (DH)"],
                "lignes": [
                    [famille, _montant(valeur)]
                    for famille, valeur in sorted(esg["familles"].items())
                ],
                "alignement": "right",
            },
        ],
        notes=[
            "Ecran de consultation : aucune ecriture n'est generee ici.",
            "Les etats officiels (PDF) restent disponibles depuis Etats de synthese.",
        ],
    )


@router.get("/etats/etic", response_class=HTMLResponse)
def page_etic(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """ETIC : notes annexes calculables + informations explicitement indisponibles."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    exercice = _exercice(company, db, year)
    debut, fin = year_bounds(exercice)
    etic = etats_synthese.notes_etic(db, company.id, debut, fin)
    tableaux: list[dict] = []
    for note in etic.get("notes", []):
        colonnes = list(note.get("colonnes", []))
        tableaux.append(
            {
                "titre": f"Note {note.get('numero', '')} — {note.get('titre', '')}".strip(),
                "colonnes": colonnes,
                "lignes": [
                    [_cellule(cellule) for cellule in ligne]
                    for ligne in note.get("lignes", [])
                ],
                "total": _ligne_total(colonnes, note.get("total")),
                "alignement": "right",
            }
        )
    indisponibles = list(etic.get("indisponibles", []))
    return _page(
        request,
        user=user,
        company=company,
        titre=f"ETIC — exercice {exercice}",
        active="etic",
        sous_titre="Notes annexes : informations calculables et donnees non disponibles",
        kpis=[
            {"label": "Notes produites", "valeur": str(len(tableaux))},
            {
                "label": "Informations indisponibles",
                "valeur": str(len(indisponibles)),
                "niveau": "negative" if indisponibles else "positive",
            },
        ],
        tableaux=tableaux,
        notes=indisponibles
        or ["Toutes les informations requises par l'ETIC sont disponibles dans le dossier."],
    )


# ---------------------------------------------------------------------------
# Stocks — mouvements, inventaire, provisions (exigence P2 : ecrans reels)
# ---------------------------------------------------------------------------
@router.get("/stocks/mouvements", response_class=HTMLResponse)
def page_mouvements_stock(
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Mouvements de stock (entrees / sorties) : lecture seule."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    articles = {item.id: item for item in magasin.list_items(db, company.id)}
    mouvements = list(
        db.execute(
            select(StockMovement)
            .where(StockMovement.company_id == company.id)
            .order_by(StockMovement.movement_date.desc(), StockMovement.id.desc())
            .limit(500)
        ).scalars()
    )
    return _page(
        request,
        user=user,
        company=company,
        titre="Mouvements de stocks",
        active="stocks-mouvements",
        sous_titre="Entrees et sorties enregistrees (500 derniers mouvements)",
        kpis=[
            {"label": "Mouvements", "valeur": str(len(mouvements))},
            {"label": "Articles suivis", "valeur": str(len(articles))},
        ],
        tableaux=[
            {
                "titre": "Mouvements valorises",
                "colonnes": [
                    "Date", "Article", "Sens", "Motif", "Quantite", "Cout unitaire",
                    "Valeur", "Reference",
                ],
                "lignes": [
                    [
                        m.movement_date.strftime("%d/%m/%Y") if m.movement_date else "—",
                        articles[m.item_id].reference if m.item_id in articles else "—",
                        "Entree" if (m.quantity or 0) > 0 else "Sortie",
                        m.reason or "—",
                        _montant(m.quantity),
                        _montant(m.unit_cost),
                        _montant(m.value),
                        m.reference or "—",
                    ]
                    for m in mouvements
                ],
                "alignement": "right",
            }
        ],
        notes=[
            "Ecran de consultation : les mouvements sont saisis depuis Stocks & inventaire.",
            "Un mouvement comptabilise porte sa piece (entry_id) dans le grand livre.",
        ],
    )


@router.get("/stocks/inventaire", response_class=HTMLResponse)
def page_inventaire(
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Inventaire valorise : quantites theoriques, CMUP et valeur (lecture seule)."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    inventaire = magasin.inventaire_valorise(db, company.id)
    return _page(
        request,
        user=user,
        company=company,
        titre="Inventaire valorise",
        active="stocks-inventaire",
        sous_titre=f"Situation au {inventaire['au'].strftime('%d/%m/%Y')}",
        kpis=[
            {"label": "Articles", "valeur": str(len(inventaire["lignes"]))},
            {
                "label": "Valeur theorique",
                "valeur": _montant(inventaire["total_valeur_theorique"]),
            },
        ],
        tableaux=[
            {
                "titre": "Feuille de comptage (quantites theoriques)",
                "colonnes": [
                    "Reference", "Article", "Unite", "Compte", "Quantite theorique",
                    "CMUP", "Valeur theorique",
                ],
                "lignes": [
                    [
                        ligne["reference"],
                        ligne["label"],
                        ligne["unit"],
                        ligne["stock_account"],
                        _montant(ligne["theoretical_quantity"]),
                        _montant(ligne["cmup"]),
                        _montant(ligne["theoretical_value"]),
                    ]
                    for ligne in inventaire["lignes"]
                ],
                "alignement": "right",
            }
        ],
        notes=[
            "La saisie de l'inventaire physique (ecarts et comptabilisation) se fait "
            "depuis Stocks & inventaire.",
        ],
    )


@router.get("/stocks/provisions", response_class=HTMLResponse)
def page_provisions_stock(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Provisions / depreciations de stocks : base, valeur d'inventaire, dotation."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    exercice = _exercice(company, db, year)
    etat = magasin.etat_provisions(db, company.id, exercice)
    return _page(
        request,
        user=user,
        company=company,
        titre=f"Provisions / depreciations de stocks — exercice {exercice}",
        active="stocks-provisions",
        sous_titre="Valeur comptable, valeur d'inventaire, provision et dotation",
        kpis=[
            {"label": "Articles provisionnes", "valeur": str(len(etat["lignes"]))},
            {"label": "Total provisions", "valeur": _montant(etat["total_provision"])},
            {"label": "Dotations", "valeur": _montant(etat["total_dotation"])},
            {"label": "Reprises", "valeur": _montant(etat["total_reprise"])},
        ],
        tableaux=[
            {
                "titre": "Etat des depreciations",
                "colonnes": [
                    "Reference", "Article", "Compte stock", "Compte provision",
                    "Valeur comptable", "Valeur d'inventaire", "Provision", "Dotation",
                    "Motif",
                ],
                "lignes": [
                    [
                        ligne["reference"],
                        ligne["label"],
                        ligne["compte_stock"],
                        ligne["compte_provision"],
                        _montant(ligne["book_value"]),
                        _montant(ligne["inventory_value"]),
                        _montant(ligne["provision"]),
                        _montant(ligne["dotation"]),
                        ligne["motif"] or "—",
                    ]
                    for ligne in etat["lignes"]
                ],
                "alignement": "right",
            }
        ],
        notes=[
            "La constatation d'une provision (dotation / reprise) s'effectue depuis "
            "Stocks & inventaire : elle genere une ecriture comptable tracee.",
        ],
    )


# ---------------------------------------------------------------------------
# Cloture & cessation — a-nouveaux, journaux, referentiels fiscaux
# ---------------------------------------------------------------------------
@router.get("/parametres/a-nouveaux", response_class=HTMLResponse)
def page_a_nouveaux(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """A-nouveaux de l'exercice : existence, equilibre, scellement (lecture seule)."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    exercice = _exercice(company, db, year)
    controle = cloture.controle_a_nouveaux(db, company, exercice)
    precedent = cloture.controle_a_nouveaux(db, company, exercice - 1)
    return _page(
        request,
        user=user,
        company=company,
        titre=f"A-nouveaux — exercice {exercice}",
        active="a-nouveaux",
        sous_titre="Reprise des soldes d'ouverture (report a nouveau et resultat)",
        kpis=[
            {
                "label": "Ecriture d'a-nouveaux",
                "valeur": "presente" if controle["existe"] else "absente",
                "niveau": "positive" if controle["existe"] else "negative",
            },
            {"label": "Lignes", "valeur": str(controle["nb_lignes"])},
            {
                "label": "Equilibre",
                "valeur": "equilibre" if controle["equilibre"] else "desequilibre",
                "niveau": "positive" if controle["equilibre"] else "negative",
            },
            {"label": "Scellee", "valeur": "oui" if controle["scellee"] else "non"},
        ],
        tableaux=[
            {
                "titre": f"Controle de l'exercice {exercice}",
                "colonnes": ["Element", "Valeur"],
                "lignes": [
                    ["Ecriture", controle["entry_number"] or "aucune"],
                    [
                        "Date",
                        controle["date"].strftime("%d/%m/%Y") if controle["date"] else "—",
                    ],
                    ["Total debit", _montant(controle["total_debit"])],
                    ["Total credit", _montant(controle["total_credit"])],
                    ["Nombre de lignes", str(controle["nb_lignes"])],
                ],
                "alignement": "right",
            },
            {
                "titre": f"Exercice precedent ({exercice - 1}) — reference",
                "colonnes": ["Element", "Valeur"],
                "lignes": [
                    ["Ecriture", precedent["entry_number"] or "aucune"],
                    ["Total debit", _montant(precedent["total_debit"])],
                    ["Total credit", _montant(precedent["total_credit"])],
                    ["Equilibre", "oui" if precedent["equilibre"] else "non"],
                ],
                "alignement": "right",
            },
        ],
        notes=[
            "La generation des a-nouveaux se fait depuis Exercices (action tracee) : "
            "cet ecran ne modifie rien.",
        ],
    )


@router.get("/parametres/journaux", response_class=HTMLResponse)
def page_journaux(
    request: Request,
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Journaux comptables : code, libelle, type et volumetrie des ecritures."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    from app.models import Entry  # noqa: PLC0415 - import local (modele volumineux)

    journaux = list(
        db.execute(
            select(Journal).where(Journal.company_id == company.id).order_by(Journal.code)
        ).scalars()
    )
    volumetrie = dict(
        db.execute(
            select(Entry.journal_id, func.count(Entry.id))
            .where(Entry.company_id == company.id)
            .group_by(Entry.journal_id)
        ).all()
    )
    return _page(
        request,
        user=user,
        company=company,
        titre="Journaux comptables",
        active="journaux",
        sous_titre="Codes CGNC, type d'ecriture et nombre d'ecritures enregistrees",
        kpis=[
            {"label": "Journaux", "valeur": str(len(journaux))},
            {"label": "Ecritures", "valeur": str(sum(volumetrie.values()))},
        ],
        tableaux=[
            {
                "titre": "Journaux du dossier",
                "colonnes": ["Code", "Libelle", "Type", "Ecritures"],
                "lignes": [
                    [
                        journal.code,
                        journal.label,
                        getattr(journal, "journal_type", None)
                        or getattr(journal, "type", "—"),
                        str(volumetrie.get(journal.id, 0)),
                    ]
                    for journal in journaux
                ],
                "alignement": "right",
            }
        ],
        notes=[
            "Les journaux sont crees avec la societe (referentiel CGNC) : cet ecran "
            "n'autorise aucune modification.",
            "Le detail des ecritures est consultable dans Journal comptable et Grand livre.",
        ],
    )


@router.get("/parametres/referentiels", response_class=HTMLResponse)
def page_referentiels(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Referentiels fiscaux et leurs sources : taux, exercices couverts, provenance."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    exercices = sorted(set(IS_RATES_BY_YEAR) | set(COTISATION_MINIMALE_BY_YEAR))
    lignes_is = [
        [
            str(annee),
            " | ".join(f"{tranche} : {taux} %" for tranche, taux in rates.items()),
        ]
        for annee, rates in sorted(IS_RATES_BY_YEAR.items())
    ]
    lignes_cm = [
        [
            str(annee),
            " | ".join(f"{cle} = {valeur}" for cle, valeur in sorted(params.items())),
        ]
        for annee, params in sorted(COTISATION_MINIMALE_BY_YEAR.items())
    ]
    sources: list[list[str]] = []
    for annee in exercices:
        for source in SOURCES_REFERENTIELS.get(annee, []):
            sources.append(
                [
                    str(annee),
                    source.get("parametre", ""),
                    source.get("valeur", ""),
                    source.get("base", ""),
                    source.get("source", ""),
                    source.get("statut", ""),
                ]
            )
    return _page(
        request,
        user=user,
        company=company,
        titre="Referentiels fiscaux",
        active="referentiels",
        sous_titre="Taux parametres par exercice, avec source et statut de provenance",
        kpis=[
            {"label": "Exercices parametres", "valeur": str(len(exercices))},
            {"label": "Exercice affiche", "valeur": str(_exercice(company, db, year))},
        ],
        tableaux=[
            {
                "titre": "IS (impot sur les societes) par exercice",
                "colonnes": ["Exercice", "Detail par tranche"],
                "lignes": lignes_is,
            },
            {
                "titre": "Cotisation minimale par exercice",
                "colonnes": ["Exercice", "Parametres"],
                "lignes": lignes_cm,
            },
            {
                "titre": "Sources des referentiels (aucun taux sans source)",
                "colonnes": ["Exercice", "Parametre", "Valeur", "Base", "Source", "Statut"],
                "lignes": sources,
            },
        ],
        notes=[
            "Un exercice sans parametre officiel est refuse par le calcul (aucun taux "
            "n'est extrapole) : la ligne doit etre completee avec sa source.",
            "Baremes de paie, cotisations CNSS/AMO et TFP suivent la meme regle de source.",
        ],
    )


# ---------------------------------------------------------------------------
# Audit & tracabilite — controles d'integrite
# ---------------------------------------------------------------------------
@router.get("/audit/integrite", response_class=HTMLResponse)
def page_integrite(
    request: Request,
    year: int | None = Query(default=None),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Controles d'integrite : chainage d'audit, equilibre du bilan, pieces."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    exercice = _exercice(company, db, year)
    debut, fin = year_bounds(exercice)
    chainage = piste.verifier_chainage(db, company.id)
    bilan = reporting.balance_sheet(db, company.id, debut, fin)
    ecritures = db.execute(
        select(func.count(func.distinct(Entry.id)))
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .where(Entry.company_id == company.id)
        .group_by(Entry.id)
        .having(func.abs(func.sum(EntryLine.debit - EntryLine.credit)) > Decimal("0.004"))
    ).all()
    return _page(
        request,
        user=user,
        company=company,
        titre=f"Controles d'integrite — exercice {exercice}",
        active="integrite",
        sous_titre="Piste d'audit, equilibre comptable et ecritures desequilibrees",
        kpis=[
            {
                "label": "Chainage d'audit",
                "valeur": "fiable" if chainage.get("fiable", True) else "anomalie",
                "niveau": "positive" if chainage.get("fiable", True) else "negative",
            },
            {
                "label": "Bilan equilibre",
                "valeur": "oui" if bilan["equilibre"] else "non",
                "niveau": "positive" if bilan["equilibre"] else "negative",
            },
            {
                "label": "Ecritures desequilibrees",
                "valeur": str(len(ecritures)),
                "niveau": "negative" if ecritures else "positive",
            },
        ],
        tableaux=[
            {
                "titre": "Piste d'audit",
                "colonnes": ["Controle", "Resultat"],
                "lignes": [
                    [cle, str(valeur)] for cle, valeur in sorted(chainage.items())
                ],
            },
            {
                "titre": f"Equilibre du bilan au {fin.strftime('%d/%m/%Y')}",
                "colonnes": ["Element", "Montant (DH)"],
                "lignes": [
                    ["Total actif", _montant(bilan["total_actif"])],
                    ["Total passif", _montant(bilan["total_passif"])],
                    ["Resultat de l'exercice", _montant(bilan["resultat_exercice"])],
                    ["Total passif avec resultat", _montant(bilan["total_passif_avec_resultat"])],
                ],
                "alignement": "right",
            },
        ],
        notes=[
            "Ces controles sont en lecture seule : aucune correction automatique n'est "
            "appliquee (toute regularisation passe par une ecriture tracee).",
        ],
    )


# ---------------------------------------------------------------------------
# E-facturation et journal d'activite (lecture seule)
# ---------------------------------------------------------------------------
@router.get("/e-facturation", response_class=HTMLResponse)
def page_e_facturation(
    request: Request,
    annee: int | None = Query(default=None),
    statut: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Factures electroniques : statut de transmission, rejets et reemissions."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    situation = e_invoice.situation(db, company, annee=annee)
    documents = e_invoice.list_documents(db, company.id, statut=statut or None)
    factures = {
        facture.id: facture
        for facture in db.execute(
            select(Invoice).where(Invoice.company_id == company.id)
        ).scalars()
    }
    statuts: dict[str, int] = {}
    for document in documents:
        statuts[document.statut] = statuts.get(document.statut, 0) + 1
    return _page(
        request,
        user=user,
        company=company,
        titre="E-facturation — statuts de transmission",
        active="e-facturation",
        sous_titre=(
            "Statuts des factures electroniques : a generer, transmis, acceptes, rejetes"
            + (f" — filtre : {statut}" if statut else "")
        ),
        kpis=[
            {"label": "Documents", "valeur": str(len(documents))},
            {"label": "Acceptes", "valeur": str(statuts.get("accepte", 0))},
            {
                "label": "Rejetes",
                "valeur": str(statuts.get("rejete", 0)),
                "niveau": "negative" if statuts.get("rejete") else "positive",
            },
        ],
        tableaux=[
            {
                "titre": "Factures electroniques",
                "colonnes": [
                    "Facture", "Date", "Statut", "Canal", "Identifiant DGI", "Envoye le",
                    "Accuse le",
                ],
                "lignes": [
                    [
                        factures[d.invoice_id].number if d.invoice_id in factures else "—",
                        factures[d.invoice_id].invoice_date.strftime("%d/%m/%Y")
                        if d.invoice_id in factures and factures[d.invoice_id].invoice_date
                        else "—",
                        E_INVOICE_STATUT_LABELS.get(d.statut, d.statut),
                        d.canal or "—",
                        d.identifiant_dgi or "—",
                        d.envoye_le.strftime("%d/%m/%Y") if d.envoye_le else "—",
                        d.accuse_le.strftime("%d/%m/%Y") if d.accuse_le else "—",
                    ]
                    for d in documents
                ],
            },
            {
                "titre": "Situation par statut",
                "colonnes": ["Statut", "Nombre"],
                "lignes": [
                    [E_INVOICE_STATUT_LABELS.get(statut, statut), str(nombre)]
                    for statut, nombre in sorted(statuts.items())
                ],
                "alignement": "right",
            },
        ],
        notes=list(situation.get("notes", []))
        + [
            "L'application fonctionne en simulation par defaut : aucun fichier n'est "
            "transmis sans configuration explicite du canal.",
            "Un rejet doit etre corrige puis reemis depuis la facture concernee.",
        ],
    )


@router.get("/activite", response_class=HTMLResponse)
def page_activite(
    request: Request,
    contexte: str = Query(default=""),
    user: User = Depends(get_web_user),
    company: Company | None = Depends(get_web_company),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Journal d'activite : evenements recents du dossier (e-facturation comprise)."""
    redirection = _societe(company)
    if redirection is not None:
        return redirection
    entrees = piste.journal_audit(db, company_id=company.id, limit=200)
    # Libelles des utilisateurs presents dans le journal (identifiant -> nom/email) :
    # `journal_audit` retourne des lignes `AuditLog` (ORM) et non des dictionnaires.
    utilisateurs = dict(piste.utilisateurs_journal(db, company.id))
    e_invoices = list(
        db.execute(
            select(EInvoiceDocument)
            .where(EInvoiceDocument.company_id == company.id)
            .order_by(EInvoiceDocument.id.desc())
            .limit(50)
        ).scalars()
    )
    return _page(
        request,
        user=user,
        company=company,
        titre="Journal d'activite" if contexte != "cessation" else "Cessation (vue provisoire)",
        active="cessation" if contexte == "cessation" else "activite",
        sous_titre=(
            "Evenements recents du dossier (e-facturation et operations tracees)"
            if contexte != "cessation"
            else "Vue provisoire : la rubrique Cessation pointe vers /activite?contexte=cessation "
            "en attendant une route metier dediee (P1). Aucune logique metier ajoutee."
        ),
        kpis=[
            {"label": "Evenements recents", "valeur": str(len(entrees))},
            {"label": "Documents e-facturation", "valeur": str(len(e_invoices))},
        ],
        tableaux=[
            {
                "titre": "Documents d'e-facturation",
                "colonnes": ["Document", "Statut", "Canal", "Envoye le", "Accuse le"],
                "lignes": [
                    [
                        str(document.id),
                        E_INVOICE_STATUT_LABELS.get(document.statut, document.statut),
                        document.canal or "—",
                        document.envoye_le.strftime("%d/%m/%Y") if document.envoye_le else "—",
                        document.accuse_le.strftime("%d/%m/%Y") if document.accuse_le else "—",
                    ]
                    for document in e_invoices
                ],
            },
            {
                "titre": "Derniers evenements traces",
                "colonnes": ["Date", "Action", "Entite", "Utilisateur"],
                "lignes": [
                    [
                        entre.created_at.strftime("%d/%m/%Y %H:%M")
                        if entre.created_at
                        else "—",
                        entre.action,
                        f"{entre.entity} {entre.entity_id or ''}".strip(),
                        utilisateurs.get(entre.user_id, "systeme"),
                    ]
                    for entre in entrees[:100]
                ],
            },
        ],
        notes=[
            "Le journal d'audit complet (filtres et export) reste accessible dans "
            "Audit & tracabilite.",
        ],
    )








