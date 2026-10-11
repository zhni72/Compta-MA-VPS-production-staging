"""Cloture d'exercice et ecritures d'a-nouveaux (P1.6 — correction de l'ecart 9).

**Ecart 9 (CDC § 8.1)** : la cloture d'exercice ne generait pas d'ecritures
d'a-nouveaux, si bien que le bilan et le CPC d'un exercice posterieur au premier
omettaient les soldes d'ouverture. Ce service genere l'ecriture d'ouverture de
l'exercice suivant :

- report a l'identique (sens inverse) de **tous les soldes des classes 1 a 5** au
  1er janvier de l'exercice suivant ;
- **contrepartie du resultat** de l'exercice clos au compte **1191** (resultat net
  crediteur) ou **1199** (resultat net debiteur) : c'est cette ligne qui equilibre
  l'ecriture (les soldes des classes 1 a 5 se compensent a hauteur du resultat) et
  qui reconstitue le resultat dans les capitaux propres de l'exercice suivant ;
- journal **AN** (a-nouveaux), source `opening`, reference `AN<exercice>`.

**Regle de calcul des soldes (anti double comptage)** : si l'exercice a lui-meme
recu des a-nouveaux, ses mouvements suffisent ; sinon (premier exercice, dossier
anterieur a la correction de l'ecart 9) les soldes sont pris **en cumul depuis
l'origine**.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.rates_ma import money
from app.models import Company, Entry, EntryLine, FiscalYear, Journal, PeriodLock
from app.services.accounting import (
    AccountingError,
    create_entry,
    ensure_period_open,
    get_fiscal_year,
    validate_entry,
)
from app.services.reporting import balance_sheet, movements, year_bounds

SOURCE_OUVERTURE = "opening"
JOURNAL_A_NOUVEAUX = ("AN", "A-nouveaux", "general")
COMPTE_RESULTAT_CREDITEUR = "1191"  # Resultat net de l'exercice (solde crediteur)
COMPTE_RESULTAT_DEBITEUR = "1199"  # Resultat net de l'exercice (solde debiteur)
CLASSES_BILAN = (1, 2, 3, 4, 5)


def a_nouveaux_existent(db: Session, company_id: int, year: int) -> Entry | None:
    """Ecriture d'a-nouveaux de l'exercice donne (None si absente)."""
    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company_id, FiscalYear.year == year
        )
    ).scalar_one_or_none()
    if exercice is None:
        return None
    return db.execute(
        select(Entry).where(
            Entry.company_id == company_id,
            Entry.fiscal_year_id == exercice.id,
            Entry.source == SOURCE_OUVERTURE,
        )
    ).scalars().first()


def soldes_a_la_date(
    db: Session,
    company_id: int,
    jour_arrete: date,
    *,
    classes: tuple[int, ...] = CLASSES_BILAN,
    prefix: str | None = None,
) -> dict[str, Decimal]:
    """Soldes des comptes a une date d'arrete, **sans double comptage des reports**.

    - si l'exercice contient deja ses a-nouveaux : mouvements de l'exercice ;
    - sinon : cumul depuis l'origine (dossier anterieur a la correction de l'ecart 9).
    """
    ouverture = a_nouveaux_existent(db, company_id, jour_arrete.year)
    debut = date(jour_arrete.year, 1, 1) if ouverture is not None else date(1900, 1, 1)
    lignes = movements(db, company_id, debut, jour_arrete, prefix=prefix)
    return {
        ligne["account_number"]: ligne["solde"]
        for ligne in lignes
        if ligne["account_class"] in classes
    }


def resultat_de_l_exercice(db: Session, company_id: int, year: int) -> Decimal:
    """Resultat net de l'exercice (produits de classe 7 - charges de classe 6)."""
    debut, fin = year_bounds(year)
    lignes = movements(db, company_id, debut, fin)
    charges = sum((l["solde"] for l in lignes if l["account_class"] == 6), Decimal("0"))
    produits = sum((-l["solde"] for l in lignes if l["account_class"] == 7), Decimal("0"))
    return money(produits - charges)


def journal_a_nouveaux(db: Session, company_id: int) -> Journal:
    """Journal des a-nouveaux (cree s'il n'existe pas : premier dossier repris)."""
    code, libelle, type_journal = JOURNAL_A_NOUVEAUX
    journal = db.execute(
        select(Journal).where(Journal.company_id == company_id, Journal.code == code)
    ).scalar_one_or_none()
    if journal is None:
        journal = Journal(
            company_id=company_id, code=code, label=libelle, journal_type=type_journal
        )
        db.add(journal)
        db.flush()
    return journal


def generer_a_nouveaux(
    db: Session,
    company: Company,
    exercice_source: FiscalYear,
    *,
    user_id: int | None = None,
) -> dict:
    """Genere l'ecriture d'a-nouveaux de l'exercice suivant (correction ecart 9).

    L'ecriture est equilibree par construction : le report des comptes de bilan se
    compense a hauteur du resultat, dont la contrepartie est passee au 1191/1199.
    """
    year = exercice_source.year
    if a_nouveaux_existent(db, company.id, year + 1) is not None:
        raise AccountingError(
            f"Les a-nouveaux de l'exercice {year + 1} existent deja : aucune generation "
            "en double (utiliser une contre-ecriture pour les corriger)."
        )
    soldes = soldes_a_la_date(db, company.id, exercice_source.end_date)
    resultat = resultat_de_l_exercice(db, company.id, year)
    lignes: list[dict] = []
    for compte, solde in sorted(soldes.items()):
        if solde == 0:
            continue
        montant = abs(money(solde))
        # Reprise des soldes **dans le même sens** : un compte débiteur reste
        # débiteur, un compte créditeur reste créditeur (image fidèle du bilan).
        lignes.append(
            {
                "account_number": compte,
                "label": f"A-nouveau {compte} au 01/01/{year + 1}",
                **({"debit": montant} if solde > 0 else {"credit": montant}),
            }
        )
    if resultat != 0:
        benefice = resultat > 0
        lignes.append(
            {
                "account_number": (
                    COMPTE_RESULTAT_CREDITEUR if benefice else COMPTE_RESULTAT_DEBITEUR
                ),
                "label": f"Resultat de l'exercice {year} reporte",
                **({"credit": abs(resultat)} if benefice else {"debit": abs(resultat)}),
            }
        )
    total_debit = money(sum((l.get("debit", 0) for l in lignes), Decimal("0")))
    total_credit = money(sum((l.get("credit", 0) for l in lignes), Decimal("0")))
    if not lignes or total_debit == 0:
        return {
            "genere": False,
            "exercice_source": year,
            "exercice_cible": year + 1,
            "motif": "Aucun solde a reporter (dossier vierge).",
            "total_debit": total_debit,
            "total_credit": total_credit,
        }
    if total_debit != total_credit:
        raise AccountingError(
            f"A-nouveaux desequilibres : debit {total_debit} <> credit {total_credit}. "
            "Verifiez le grand livre de l'exercice avant de cloturer."
        )

    from app.db.seed import get_or_create_fiscal_year

    exercice_cible = get_or_create_fiscal_year(db, company, year + 1)
    ensure_period_open(exercice_cible)
    journal = journal_a_nouveaux(db, company.id)
    entry = create_entry(
        db,
        company_id=company.id,
        fiscal_year=exercice_cible,
        journal=journal,
        entry_date=date(year + 1, 1, 1),
        label=f"A-nouveaux de l'exercice {year + 1}",
        reference=f"AN{year}",
        source=SOURCE_OUVERTURE,
        source_id=exercice_source.id,
        created_by=user_id,
        lines=lignes,
    )
    validate_entry(db, entry, user_id=user_id)
    log_action(
        db,
        action="OPENING_ENTRY_GENERATED",
        entity="Entry",
        entity_id=entry.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "exercice_source": year,
            "exercice_cible": year + 1,
            "nb_lignes": len(lignes),
            "total_debit": total_debit,
            "resultat_reporte": resultat,
            "entry_number": entry.entry_number,
        },
    )
    return {
        "genere": True,
        "exercice_source": year,
        "exercice_cible": year + 1,
        "entry": entry,
        "entry_number": entry.entry_number,
        "nb_lignes": len(lignes),
        "total_debit": total_debit,
        "total_credit": total_credit,
        "resultat_reporte": resultat,
        "comptes_reportes": len(soldes),
    }



def cloturer_exercice(
    db: Session,
    company: Company,
    year: int,
    *,
    user_id: int | None = None,
    generer_ouverture: bool = True,
) -> dict:
    """Cloture un exercice : controle du bilan, statut « closed », a-nouveaux.

    References : CGNC (specialisation des exercices) et CDC § 3.1 (controle bloquant
    n° 1 : la cloture est refusee si le bilan n'est pas equilibre).
    """
    exercice = get_fiscal_year(db, company.id, year)
    if exercice.status != "open":
        raise AccountingError(
            f"Exercice {year} en statut '{exercice.status}' : seule la cloture d'un "
            "exercice ouvert est possible."
        )
    bilan = balance_sheet(db, company.id, *year_bounds(year))
    if not bilan["equilibre"]:
        raise AccountingError(
            f"Cloture refusee : le bilan {year} n'est pas equilibre "
            f"(actif {bilan['total_actif']} <> passif + resultat "
            f"{bilan['total_passif_avec_resultat']}). Corrigez les ecritures d'abord."
        )
    exercice.status = "closed"
    exercice.closed_at = datetime.now()
    db.flush()
    resultat: dict = {
        "exercice": year,
        "statut": "closed",
        "resultat_net": bilan["resultat_exercice"],
        "total_actif": bilan["total_actif"],
        "a_nouveaux": None,
    }
    if generer_ouverture:
        resultat["a_nouveaux"] = generer_a_nouveaux(
            db, company, exercice, user_id=user_id
        )
    log_action(
        db,
        action="FISCAL_YEAR_CLOSED",
        entity="FiscalYear",
        entity_id=exercice.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "exercice": year,
            "resultat_net": bilan["resultat_exercice"],
            "a_nouveaux_genere": bool(
                resultat["a_nouveaux"] and resultat["a_nouveaux"]["genere"]
            ),
        },
    )
    return resultat


def controle_a_nouveaux(db: Session, company: Company, year: int) -> dict:
    """Etat des a-nouveaux d'un exercice (existence, equilibre, resultat reporte)."""
    entry = a_nouveaux_existent(db, company.id, year)
    return {
        "exercice": year,
        "existe": entry is not None,
        "entry_id": None if entry is None else entry.id,
        "entry_number": None if entry is None else entry.entry_number,
        "date": None if entry is None else entry.entry_date,
        "total_debit": money(entry.total_debit) if entry is not None else money(0),
        "total_credit": money(entry.total_credit) if entry is not None else money(0),
        "equilibre": entry.is_balanced if entry is not None else None,
        "nb_lignes": len(entry.lines) if entry is not None else 0,
        "scellee": bool(entry.entry_hash) if entry is not None else False,
    }


def reouvrir_exercice(
    db: Session,
    company: Company,
    year: int,
    *,
    motif: str,
    user_id: int | None = None,
    regenerer_a_nouveaux: bool = False,
) -> dict:
    """Reouvre un exercice clos : operation **encadree** (P1, anomalie A10).

    Conditions cumulatives (sinon refus motive) :
    1. **motif** obligatoire (>= 10 caracteres) : acte de gestion justifie et trace ;
    2. l'exercice doit etre **clos** (un exercice verrouille se debloque par un
       chemin dedie, jamais par un simple changement de statut) ;
    3. **aucun verrou de periode** sur l'exercice ;
    4. si des **a-nouveaux existent dans N+1** (ou si N+1 contient des ecritures),
       la regeneration doit etre **explicitement demandee**
       (`regenerer_a_nouveaux=True`), l'impact etant restitue dans le message ;
    5. N+1 **verrouille** : reouverture refusee (ecritures intangibles).

    L'operation est tracee (`FISCAL_YEAR_REOPENED`) : motif, utilisateur, statut
    avant, impact sur N+1 et a-nouveaux concernes."""
    exercice = get_fiscal_year(db, company.id, year)
    motif = (motif or "").strip()
    if len(motif) < 10:
        raise AccountingError(
            "Reouverture refusee : un motif explicite est obligatoire "
            "(au moins 10 caracteres, trace dans la piste d'audit)."
        )
    if exercice.status == "open":
        raise AccountingError(f"Exercice {year} deja ouvert.")
    if exercice.status == "locked":
        raise AccountingError(
            f"Exercice {year} verrouille : le deverrouillage emprunte un chemin dedie "
            "(tracabilite renforcee), pas une reouverture."
        )
    apercu = apercu_reouverture(db, company, year)
    if apercu["verrous"]:
        periodes = ", ".join(str(verrou["periode"]) for verrou in apercu["verrous"])
        raise AccountingError(
            f"Reouverture refusee : la periode {periodes} de {year} est verrouillee. "
            "Deverrouillez la periode (motif requis) avant de reouvrir l'exercice."
        )
    if apercu["statut_suivant"] == "locked":
        raise AccountingError(
            f"Reouverture refusee : l'exercice {year + 1} est verrouille ; ses ecritures "
            "et ses a-nouveaux sont intangibles."
        )
    a_nouveaux = apercu["a_nouveaux_suivant"]
    impact = (
        f"{apercu['ecritures_suivant']} ecriture(s) dans {year + 1}"
        if apercu["exercice_suivant"] is not None
        else "aucun exercice suivant"
    )
    if a_nouveaux and a_nouveaux["existe"] and not regenerer_a_nouveaux:
        raise AccountingError(
            f"Reouverture refusee : les a-nouveaux de {year + 1} existent (ecriture "
            f"{a_nouveaux['entry_number']}, {a_nouveaux['total_debit']} DH). Impact : "
            f"{impact}. Relancez l'operation en demandant la regeneration des "
            "a-nouveaux (elle sera tracee et comparee avant/apres)."
        )
    ancien = exercice.status
    exercice.status = "open"
    exercice.closed_at = None
    log_action(
        db,
        action="FISCAL_YEAR_REOPENED",
        entity="FiscalYear",
        entity_id=exercice.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "exercice": year,
            "statut_avant": ancien,
            "motif": motif,
            "regeneration_a_nouveaux_demandee": bool(regenerer_a_nouveaux),
            "impact_suivant": impact,
            "a_nouveaux_suivant": a_nouveaux,
        },
    )
    db.flush()
    return {
        "exercice": year,
        "statut": "open",
        "statut_avant": ancien,
        "motif": motif,
        "impact_suivant": impact,
        "a_nouveaux_suivant": a_nouveaux,
        "resultat_exercice": apercu["resultat_exercice"],
    }


def verrouiller_exercice(
    db: Session,
    company: Company,
    year: int,
    *,
    motif: str,
    user_id: int | None = None,
) -> dict:
    """Verrouille un exercice **clos** (operation definitive et tracee)."""
    exercice = get_fiscal_year(db, company.id, year)
    motif = (motif or "").strip()
    if len(motif) < 10:
        raise AccountingError(
            "Verrouillage refuse : un motif explicite est obligatoire "
            "(au moins 10 caracteres, trace dans la piste d'audit)."
        )
    if exercice.status != "closed":
        raise AccountingError(
            f"Exercice {year} en statut '{exercice.status}' : seul un exercice clos "
            "peut etre verrouille."
        )
    ancien = exercice.status
    exercice.status = "locked"
    exercice.closed_at = datetime.now()
    log_action(
        db,
        action="FISCAL_YEAR_LOCKED",
        entity="FiscalYear",
        entity_id=exercice.id,
        user_id=user_id,
        company_id=company.id,
        payload={"exercice": year, "statut_avant": ancien, "motif": motif},
    )
    db.flush()
    return {"exercice": year, "statut": "locked", "statut_avant": ancien, "motif": motif}


def regenerer_a_nouveaux(
    db: Session,
    company: Company,
    year: int,
    *,
    motif: str,
    user_id: int | None = None,
) -> dict:
    """Remplace les a-nouveaux de ``year + 1`` et **compare** avant / apres.

    Utilise apres une reouverture suivie d'une re-cloture de ``year`` : les
    a-nouveaux precedents sont supprimes avec **instantane trace**
    (`OPENING_REGENERATED`) puis regeneres depuis les soldes definitifs de
    ``year``. Retourne le detail des **ecarts par compte** (base de la
    validation par le comptable).
    """
    from sqlalchemy import delete, select

    motif = (motif or "").strip()
    if len(motif) < 10:
        raise AccountingError("Regeneration refusee : un motif explicite est obligatoire.")
    exercice = get_fiscal_year(db, company.id, year)
    if exercice.status != "closed":
        raise AccountingError(
            f"Regeneration refusee : l'exercice {year} doit etre clos "
            f"(statut actuel '{exercice.status}')."
        )
    suivant = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company.id, FiscalYear.year == year + 1
        )
    ).scalar_one_or_none()
    if suivant is None:
        raise AccountingError(
            f"Regeneration refusee : l'exercice {year + 1} n'existe pas "
            "(aucun a-nouveaux a produire)."
        )
    if suivant.status == "locked":
        raise AccountingError(f"Regeneration refusee : l'exercice {year + 1} est verrouille.")

    ancienne = a_nouveaux_existent(db, company.id, year + 1)
    avant = None
    if ancienne is not None:
        avant = {
            "entry_number": ancienne.entry_number,
            "total_debit": money(ancienne.total_debit),
            "nb_lignes": len(ancienne.lines),
            "lignes": {
                ligne.account_number: money(ligne.debit - ligne.credit)
                for ligne in ancienne.lines
            },
        }
        log_action(
            db,
            action="OPENING_REGENERATED",
            entity="Entry",
            entity_id=ancienne.id,
            user_id=user_id,
            company_id=company.id,
            payload={"motif": motif, "exercice_source": year, "avant": avant},
        )
        db.execute(delete(EntryLine).where(EntryLine.entry_id == ancienne.id))
        db.execute(delete(Entry).where(Entry.id == ancienne.id))
        db.flush()

    generation = generer_a_nouveaux(db, company, exercice, user_id=user_id)
    nouvelles = a_nouveaux_existent(db, company.id, year + 1)
    apres = None
    if nouvelles is not None:
        apres = {
            "entry_number": nouvelles.entry_number,
            "total_debit": money(nouvelles.total_debit),
            "nb_lignes": len(nouvelles.lines),
            "lignes": {
                ligne.account_number: money(ligne.debit - ligne.credit)
                for ligne in nouvelles.lines
            },
        }
    ecarts: list[dict] = []
    if avant and apres:
        for compte in sorted(set(avant["lignes"]) | set(apres["lignes"])):
            ancien = avant["lignes"].get(compte, money(0))
            nouveau = apres["lignes"].get(compte, money(0))
            if ancien != nouveau:
                ecarts.append(
                    {
                        "compte": compte,
                        "avant": ancien,
                        "apres": nouveau,
                        "ecart": money(nouveau - ancien),
                    }
                )
    return {
        "exercice_source": year,
        "avant": avant,
        "apres": apres,
        "ecarts": ecarts,
        "generation": generation,
    }



def apercu_reouverture(db: Session, company: Company, year: int) -> dict:
    """Impact **previsionnel** d'une reouverture d'exercice (lecture seule)."""
    from sqlalchemy import func as _func, select as _select

    exercice = get_fiscal_year(db, company.id, year)
    suivant = db.execute(
        _select(FiscalYear).where(
            FiscalYear.company_id == company.id, FiscalYear.year == year + 1
        )
    ).scalar_one_or_none()
    verrous = list(
        db.execute(
            _select(PeriodLock).where(
                PeriodLock.company_id == company.id,
                PeriodLock.fiscal_year_id == exercice.id,
            )
        ).scalars()
    )
    ecritures_suivant = (
        db.execute(
            _select(_func.count())
            .select_from(Entry)
            .where(
                Entry.company_id == company.id,
                Entry.entry_date >= suivant.start_date,
                Entry.entry_date <= suivant.end_date,
            )
        ).scalar_one()
        if suivant is not None
        else 0
    )
    return {
        "exercice": year,
        "statut": exercice.status,
        "verrous": [{"periode": verrou.periode, "motif": verrou.motif} for verrou in verrous],
        "exercice_suivant": None if suivant is None else suivant.year,
        "statut_suivant": None if suivant is None else suivant.status,
        "ecritures_suivant": ecritures_suivant,
        "a_nouveaux_suivant": (
            None if suivant is None else controle_a_nouveaux(db, company, suivant.year)
        ),
        "resultat_exercice": resultat_de_l_exercice(db, company.id, year),
        "reouverture_possible": (
            exercice.status == "closed"
            and not verrous
            and (suivant is None or suivant.status != "locked")
        ),
    }



def cloturer_exercices_anterieurs(
    db: Session, company: Company, *, user_id: int | None = None
) -> list[dict]:
    """Cloture, en une action, les exercices ouverts dont **un exercice posterieur existe**.

    Utile pour la reprise d'un dossier : les exercices anterieurs non clotures
    masquent les soldes d'ouverture des exercices suivants (ecart 9).
    """
    exercices = list(
        db.execute(
            select(FiscalYear)
            .where(FiscalYear.company_id == company.id)
            .order_by(FiscalYear.year)
        ).scalars()
    )
    resultats: list[dict] = []
    for exercice in exercices:
        if exercice.status != "open":
            continue
        posterieur = a_nouveaux_existent(db, company.id, exercice.year + 1) is not None
        if not posterieur:
            continue
        resultats.append(
            cloturer_exercice(db, company, exercice.year, user_id=user_id)
        )
    return resultats

