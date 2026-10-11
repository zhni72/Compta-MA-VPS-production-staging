"""Tests du module Audit & tracabilite (P1.6) : verrouillage, chainage, journal,
a-nouveaux (correction de l'ecart 9 du CDC § 8.1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import ENTRY_STATUS_VALIDATED, AuditLog, Entry, EntryLine, FiscalYear
from app.services import audit_trail as audit
from app.services import closing as cloture
from app.services import period_locks as verrous
from app.services.accounting import (
    AccountingError,
    PeriodLockedError,
    create_entry,
    get_fiscal_year,
    get_journal,
    update_draft_entry,
)
from app.services.reporting import balance_sheet, movements, year_bounds

pytestmark = pytest.mark.usefixtures("ctx")


def _ecriture(db, ctx, jour: date, libelle: str, lignes: list[dict], journal: str = "OD"):
    """Ecriture manuelle validee (source « manual »)."""
    entry = create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=cloture.get_fiscal_year(db, ctx["company"].id, jour.year),
        journal=get_journal(db, ctx["company"].id, journal),
        entry_date=jour,
        label=libelle,
        lines=lignes,
        validate=True,
        created_by=ctx["user"].id,
    )
    return entry


@pytest.fixture()
def exercice_2027(db, ctx) -> FiscalYear:
    """Exercice 2027 ouvert (cible des a-nouveaux de 2026)."""
    exercice = FiscalYear(
        company_id=ctx["company"].id,
        year=2027,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
        status="open",
    )
    db.add(exercice)
    db.flush()
    return exercice


@pytest.fixture()
def dossier_2026(db, ctx) -> dict:
    """Dossier 2026 : capital 100 000, charges 10 000 (perte de 10 000)."""
    _ecriture(
        db,
        ctx,
        date(2026, 1, 5),
        "Apport en capital",
        [
            {"account_number": "5141", "label": "Banque", "debit": Decimal("100000.00")},
            {"account_number": "1111", "label": "Capital", "credit": Decimal("100000.00")},
        ],
        journal="BQ",
    )
    _ecriture(
        db,
        ctx,
        date(2026, 6, 30),
        "Charges externes",
        [
            {"account_number": "6131", "label": "Loyer", "debit": Decimal("10000.00")},
            {"account_number": "5141", "label": "Banque", "credit": Decimal("10000.00")},
        ],
        journal="BQ",
    )
    return {"resultat": Decimal("-10000.00")}


# ---------------------------------------------------------------------------
# Verrouillage de periode
# ---------------------------------------------------------------------------
def test_verrou_mensuel_refuse_et_trace_la_tentative(db, ctx):
    """Une ecriture sur un mois verrouille est refusee et la tentative est tracee."""
    verrous.verrouiller_periode(
        db, company_id=ctx["company"].id, year=2026, periode=6, motif="TVA de juin deposee"
    )
    assert verrous.est_verrouillee(db, ctx["company"].id, date(2026, 6, 15)) is True
    assert verrous.est_verrouillee(db, ctx["company"].id, date(2026, 7, 1)) is False

    with pytest.raises(PeriodLockedError, match="verrouillee"):
        _ecriture(
            db,
            ctx,
            date(2026, 6, 30),
            "Ecriture interdite",
            [
                {"account_number": "6131", "label": "Charge", "debit": Decimal("100.00")},
                {"account_number": "5141", "label": "Banque", "credit": Decimal("100.00")},
            ],
        )
    trace = db.execute(
        select(AuditLog).where(AuditLog.action == "PERIOD_LOCK_REJECTED")
    ).scalars().all()
    assert len(trace) == 1
    assert "ecriture" in trace[0].payload_json
    assert trace[0].company_id == ctx["company"].id
    # Hors de la periode verrouillee, la saisie reste possible.
    _ecriture(
        db,
        ctx,
        date(2026, 7, 15),
        "Ecriture autorisee",
        [
            {"account_number": "6131", "label": "Charge", "debit": Decimal("100.00")},
            {"account_number": "5141", "label": "Banque", "credit": Decimal("100.00")},
        ],
    )
    assert verrous.est_verrouillee(db, ctx["company"].id, date(2026, 6, 15)) is True


def test_verrou_annuel_doublon_et_deverrouillage_avec_motif(db, ctx):
    """Verrou annuel : refus sur toute l'annee ; deverrouillage trace avec motif."""
    verrou = verrous.verrouiller_periode(
        db, company_id=ctx["company"].id, year=2026, motif="Depot des etats de synthese"
    )
    assert verrou.periode is None
    assert verrous.est_verrouillee(db, ctx["company"].id, date(2026, 1, 1)) is True
    assert verrous.est_verrouillee(db, ctx["company"].id, date(2026, 12, 31)) is True
    with pytest.raises(verrous.PeriodLockError, match="deja pose"):
        verrous.verrouiller_periode(db, company_id=ctx["company"].id, year=2026)
    with pytest.raises(verrous.PeriodLockError, match="motif"):
        verrous.deverrouiller_periode(db, verrou, user_id=ctx["user"].id)
    trace = verrous.deverrouiller_periode(
        db, verrou, motif="Correction d'une erreur de saisie", user_id=ctx["user"].id
    )
    assert trace["periode"] is None
    assert verrous.est_verrouillee(db, ctx["company"].id, date(2026, 12, 31)) is False
    actions = [ligne.action for ligne in db.execute(select(AuditLog)).scalars()]
    assert "PERIOD_LOCKED" in actions and "PERIOD_UNLOCKED" in actions


def test_brouillon_non_modifiable_sur_periode_verrouillee(db, ctx):
    """Un brouillon d'une periode verrouillee n'est ni modifiable ni supprimable."""
    brouillon = create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=get_fiscal_year(db, ctx["company"].id, 2026),
        journal=get_journal(db, ctx["company"].id, "OD"),
        entry_date=date(2026, 5, 10),
        label="Brouillon de mai",
        lines=[
            {"account_number": "6131", "label": "Charge", "debit": Decimal("50.00")},
            {"account_number": "5141", "label": "Banque", "credit": Decimal("50.00")},
        ],
    )
    verrous.verrouiller_periode(db, company_id=ctx["company"].id, year=2026, periode=5)
    with pytest.raises(PeriodLockedError, match="modification d'un brouillon"):
        update_draft_entry(db, brouillon, label="Modification interdite")
    from app.services.accounting import delete_draft_entry

    with pytest.raises(PeriodLockedError, match="suppression d'un brouillon"):
        delete_draft_entry(db, brouillon, user_id=ctx["user"].id)


def test_resume_et_liste_des_verrous(db, ctx):
    """Synthese des verrous d'un exercice (verrou annuel + mois verrouilles)."""
    verrous.verrouiller_periode(db, company_id=ctx["company"].id, year=2026, periode=3)
    verrous.verrouiller_periode(db, company_id=ctx["company"].id, year=2026, periode=9)
    resume = verrous.resume_verrouillages(db, ctx["company"].id, 2026)
    assert resume["mois"] == [3, 9]
    assert resume["annuel"] is None
    assert resume["nb_verrous"] == 2
    assert len(verrous.periodes_verrouillees(db, ctx["company"].id)) == 2



# ---------------------------------------------------------------------------
# Piste d'audit fiable : empreinte et chainage
# ---------------------------------------------------------------------------
def test_chainage_des_ecritures_validees(db, ctx, dossier_2026):
    """Chaque ecriture validee est scellee et chainee a la precedente."""
    ecritures = list(
        db.execute(
            select(Entry).order_by(Entry.id)
        ).scalars()
    )
    assert len(ecritures) == 2
    assert ecritures[0].previous_hash is None
    assert ecritures[0].entry_hash and len(ecritures[0].entry_hash) == 64
    assert ecritures[1].previous_hash == ecritures[0].entry_hash
    assert ecritures[1].entry_hash != ecritures[0].entry_hash

    controle = audit.verifier_chainage(db, ctx["company"].id)
    assert controle["integre"] is True
    assert controle["ruptures"] == []
    assert controle["nb_ecritures"] == 2
    assert controle["nb_scellees"] == 2
    assert controle["derniere_empreinte"] == ecritures[1].entry_hash


def test_modification_en_base_casse_le_chainage(db, ctx, dossier_2026):
    """Test d'intrusion : une ecriture modifiee hors application est detectee."""
    lignes = list(db.execute(select(EntryLine).order_by(EntryLine.id)).scalars())
    ligne = lignes[0]
    # Alteration directe en base (comme un acces hors application).
    ligne.debit = ligne.debit + Decimal("1000.00")
    db.flush()
    controle = audit.verifier_chainage(db, ctx["company"].id)
    assert controle["integre"] is False
    types = {rupture["type"] for rupture in controle["ruptures"]}
    assert "contenu_altere" in types
    assert any("modifie hors application" in r["detail"] for r in controle["ruptures"])


def test_suppression_d_une_ecriture_rompt_le_chainage(db, ctx, dossier_2026):
    """Supprimer une ecriture en base rompt le chainage des suivantes."""
    premiere = db.execute(select(Entry).order_by(Entry.id)).scalars().first()
    db.delete(premiere)
    db.flush()
    controle = audit.verifier_chainage(db, ctx["company"].id)
    assert controle["integre"] is False
    assert any(
        rupture["type"] == "chainage_rompu" for rupture in controle["ruptures"]
    )


def test_sceller_ecritures_reprises_de_dossier(db, ctx, dossier_2026):
    """Reprise d'un dossier anterieur : les ecritures sont scellees dans l'ordre."""
    entries = list(db.execute(select(Entry).order_by(Entry.id)).scalars())
    expected_ids = [entry.id for entry in entries]

    for entry in entries:
        entry.entry_hash = None
        entry.previous_hash = None

    db.flush()
    avant = audit.verifier_chainage(db, ctx["company"].id)
    assert avant["integre"] is False
    assert avant["non_scellees"] == expected_ids

    resultat = audit.sceller_ecritures(db, ctx["company"].id)
    assert resultat["nb_scellees"] == 2
    controle = audit.verifier_chainage(db, ctx["company"].id)
    assert controle["integre"] is True
    assert controle["nb_scellees"] == 2

    # Le scellement est idempotent.
    assert audit.sceller_ecritures(db, ctx["company"].id)["nb_scellees"] == 0


def test_chaque_ecriture_est_immuable_apres_validation(db, ctx, dossier_2026):
    """Une ecriture validee ne se modifie pas : la correction passe par extourne."""
    from app.services.accounting import reverse_entry

    entry = db.execute(select(Entry).order_by(Entry.id)).scalars().first()
    assert entry.status == ENTRY_STATUS_VALIDATED
    derniere = db.execute(select(Entry).order_by(Entry.id.desc())).scalars().first()
    extourne = reverse_entry(
        db, entry, "Correction du libelle", user_id=ctx["user"].id
    )
    assert extourne.reversed_entry_id == entry.id
    assert extourne.source == "reversal"
    assert extourne.entry_hash is not None
    # Le chainage suit l'ordre de creation : la nouvelle ecriture est liee a la
    # derniere ecriture validee du dossier.
    assert extourne.previous_hash == derniere.entry_hash
    controle = audit.verifier_chainage(db, ctx["company"].id)
    assert controle["integre"] is True



# ---------------------------------------------------------------------------
# Journal d'audit exploitable (loi 09-08 : minimisation des donnees personnelles)
# ---------------------------------------------------------------------------
def test_journal_audit_filtres_et_valeurs_distinctes(db, ctx, dossier_2026):
    """Le journal se filtre par action, entite, utilisateur et date."""
    from app.core.audit import log_action

    log_action(
        db,
        action="TEST_ACTION",
        entity="Test",
        entity_id=1,
        user_id=ctx["user"].id,
        company_id=ctx["company"].id,
        payload={"detail": "valeur de controle"},
    )
    db.flush()
    toutes = audit.journal_audit(db, company_id=ctx["company"].id, limit=None)
    assert len(toutes) >= 3  # 2 validations + 1 action de test
    par_action = audit.journal_audit(db, company_id=ctx["company"].id, action="TEST_ACTION")
    assert len(par_action) == 1
    assert par_action[0].entity == "Test"
    par_utilisateur = audit.journal_audit(
        db, company_id=ctx["company"].id, user_id=ctx["user"].id
    )
    assert par_utilisateur
    par_date = audit.journal_audit(
        db,
        company_id=ctx["company"].id,
        date_from=date(2020, 1, 1),
        date_to=date.today(),
    )
    assert len(par_date) == len(toutes)
    par_recherche = audit.journal_audit(
        db, company_id=ctx["company"].id, search="valeur de controle"
    )
    assert len(par_recherche) == 1

    assert "TEST_ACTION" in audit.actions_journal(db, ctx["company"].id)
    utilisateurs = audit.utilisateurs_journal(db, ctx["company"].id)
    assert (ctx["user"].id, "Admin Test") in utilisateurs
    assert audit.compte_journal(db, company_id=ctx["company"].id) == len(toutes)


def test_export_csv_du_journal_anonymise_les_donnees_personnelles(db, ctx, dossier_2026):
    """Export CSV : BOM UTF-8, separateur « ; » et masquage loi 09-08."""
    from app.core.audit import log_action

    log_action(
        db,
        action="TIERS_MODIFIE",
        entity="ThirdParty",
        entity_id=7,
        user_id=ctx["user"].id,
        company_id=ctx["company"].id,
        payload={"name": "Karim Benali", "email": "karim@exemple.ma", "rib": "007780"},
    )
    db.flush()
    export = audit.export_journal_csv(db, company_id=ctx["company"].id)
    assert export.startswith("\ufeff")  # BOM pour Excel
    assert "TIERS_MODIFIE" in export
    assert "Karim Benali" not in export  # donnees personnelles masquees
    assert audit.MASQUE in export
    assert ";" in export.splitlines()[0]
    # Export en clair possible mais explicite (usage interne controle).
    brut = audit.export_journal_csv(
        db, company_id=ctx["company"].id, anonymiser=False
    )
    assert "Karim Benali" in brut


def test_piste_ecriture_remonte_a_la_piece(db, ctx):
    """Navigation ecriture -> piece d'origine et piece -> ecritures."""
    from app.services.invoicing import create_invoice, validate_invoice
    from app.services.parties import create_third_party

    client = create_third_party(
        db,
        company=ctx["company"],
        kind="client",
        name="Client Audit",
        ice="006789012000017",
    )
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 4, 2),
        lines=[
            {"designation": "Prestation", "quantity": 1, "unit_price": 1000, "vat_rate": 20}
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    ecriture = db.execute(
        select(Entry).where(Entry.source == "invoice", Entry.source_id == facture.id)
    ).scalars().one()

    piste = audit.piste_ecriture(db, ecriture)
    assert piste["source_libelle"] == "Facture"
    assert piste["piece"]["reference"] == facture.number
    assert piste["piece"]["tiers"] == "Client Audit"
    assert Decimal(str(piste["piece"]["montant"])) == Decimal("1200.00")
    assert piste["scellee"] is True
    assert piste["immuable"] is True

    chaine = audit.ecritures_de_la_piece(db, source="invoice", source_id=facture.id)
    assert [ligne["entry_id"] for ligne in chaine] == [ecriture.id]
    assert chaine[0]["empreinte"] == ecriture.entry_hash




# ---------------------------------------------------------------------------
# Ecart 9 : cloture d'exercice et ecritures d'a-nouveaux
# ---------------------------------------------------------------------------
def test_cloture_genere_les_a_nouveaux(db, ctx, dossier_2026, exercice_2027):
    """Cloture 2026 : a-nouveaux generes dans 2027, equilibres et scelles."""
    resultat = cloture.cloturer_exercice(db, ctx["company"], 2026, user_id=ctx["user"].id)
    assert resultat["statut"] == "closed"
    assert resultat["resultat_net"] == Decimal("-10000.00")
    a_nouveaux = resultat["a_nouveaux"]
    assert a_nouveaux["genere"] is True
    assert a_nouveaux["exercice_cible"] == 2027
    assert a_nouveaux["total_debit"] == a_nouveaux["total_credit"] == Decimal("100000.00")
    assert a_nouveaux["resultat_reporte"] == Decimal("-10000.00")

    entry = a_nouveaux["entry"]
    assert entry.entry_date == date(2027, 1, 1)
    assert entry.source == "opening"
    assert entry.reference == "AN2026"
    assert entry.is_balanced is True
    assert entry.entry_hash is not None
    # Reprise des soldes dans le meme sens + resultat (perte) au debit du 1199.
    soldes = {ligne.account_number: (ligne.debit, ligne.credit) for ligne in entry.lines}
    assert soldes["5141"] == (Decimal("90000.00"), Decimal("0.00"))
    assert soldes["1111"] == (Decimal("0.00"), Decimal("100000.00"))
    assert soldes["1199"] == (Decimal("10000.00"), Decimal("0.00"))

    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == ctx["company"].id, FiscalYear.year == 2026
        )
    ).scalar_one()
    assert exercice.status == "closed"
    assert exercice.closed_at is not None
    assert audit.verifier_chainage(db, ctx["company"].id)["integre"] is True


def test_bilan_de_l_exercice_suivant_inclut_les_soldes_d_ouverture(
    db, ctx, dossier_2026, exercice_2027
):
    """Ecart 9 corrige : le bilan de 2027 reprend les soldes de cloture de 2026."""
    avant = balance_sheet(db, ctx["company"].id, *year_bounds(2027))
    assert avant["total_actif"] == Decimal("0.00")  # sans a-nouveaux : exercice vide

    cloture.cloturer_exercice(db, ctx["company"], 2026, user_id=ctx["user"].id)
    apres = balance_sheet(db, ctx["company"].id, *year_bounds(2027))
    # Le bilan simplifie classe par le SIGNE : la tresorerie reportee (debit 90000)
    # et la perte reportee (debit 1199 10000) figurent a l'actif, le capital (credit
    # 100000) au passif -> total actif = total passif = 100 000, bilan equilibre.
    # La presentation CGNC (perte en deduction des capitaux propres) reste a affiner.
    assert apres["total_actif"] == Decimal("100000.00")
    assert apres["total_passif"] == Decimal("100000.00")
    assert apres["equilibre"] is True
    comptes = {ligne["account_number"]: ligne["solde"] for ligne in apres["actif"]}
    assert comptes["5141"] == Decimal("90000.00")
    assert comptes["1199"] == Decimal("10000.00")  # perte reportee (solde debiteur)
    passif = {ligne["account_number"]: ligne["solde"] for ligne in apres["passif"]}
    assert passif["1111"] == Decimal("-100000.00")


def test_cloture_refusee_si_deja_cloture_ou_desequilibre(db, ctx, dossier_2026):
    """Controles bloquants de la cloture : statut et equilibre du bilan."""
    cloture.cloturer_exercice(db, ctx["company"], 2026, user_id=ctx["user"].id)
    with pytest.raises(AccountingError, match="statut 'closed'"):
        cloture.cloturer_exercice(db, ctx["company"], 2026, user_id=ctx["user"].id)

    # Alteration directe en base : le bilan devient desequilibre -> cloture refusee.
    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == ctx["company"].id, FiscalYear.year == 2026
        )
    ).scalar_one()
    exercice.status = "open"
    db.flush()
    ligne = db.execute(select(EntryLine).order_by(EntryLine.id)).scalars().first()
    ligne.debit = ligne.debit + Decimal("500.00")
    db.flush()
    with pytest.raises(AccountingError, match="n'est pas equilibre"):
        cloture.cloturer_exercice(db, ctx["company"], 2026, user_id=ctx["user"].id)


def test_pas_de_double_generation_et_reouverture_encadree(
    db, ctx, dossier_2026, exercice_2027
):
    """Les a-nouveaux ne sont generes qu'une fois ; la reouverture est **encadree** (P1).

    Defaut corrige (audit J9, A10) : la reouverture etait soit un simple changement
    de statut (route web, sans motif ni trace), soit **totalement bloquee** des que
    des a-nouveaux existaient. Elle exige desormais un motif, verifie les verrous et
    N+1, et demande explicitement la regeneration des a-nouveaux.
    """
    cloture.cloturer_exercice(db, ctx["company"], 2026, user_id=ctx["user"].id)
    exercice_2026 = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == ctx["company"].id, FiscalYear.year == 2026
        )
    ).scalar_one()
    with pytest.raises(AccountingError, match="existent deja"):
        cloture.generer_a_nouveaux(
            db, ctx["company"], exercice_2026, user_id=ctx["user"].id
        )
    # Reouverture sans motif : refusee.
    with pytest.raises(AccountingError, match="motif"):
        cloture.reouvrir_exercice(db, ctx["company"], 2026, motif="", user_id=ctx["user"].id)
    # Reouverture avec motif mais sans regeneration des a-nouveaux : refusee (impact).
    with pytest.raises(AccountingError, match="a-nouveaux"):
        cloture.reouvrir_exercice(
            db, ctx["company"], 2026, motif="Correction de charges omises", user_id=ctx["user"].id
        )
    # Reouverture encadree : acceptee, tracee, statut ouvert.
    resultat = cloture.reouvrir_exercice(
        db,
        ctx["company"],
        2026,
        motif="Correction de charges omises",
        user_id=ctx["user"].id,
        regenerer_a_nouveaux=True,
    )
    assert resultat["statut"] == "open"
    assert resultat["statut_avant"] == "closed"
    assert resultat["a_nouveaux_suivant"]["existe"] is True

    controle = cloture.controle_a_nouveaux(db, ctx["company"], 2027)
    assert controle["existe"] is True
    assert controle["equilibre"] is True
    assert controle["scellee"] is True
    assert controle["entry_number"].startswith("EC")


def test_soldes_a_la_date_ne_double_pas_les_reports(db, ctx, dossier_2026, exercice_2027):
    """Apres generation des a-nouveaux, les soldes sont calcules sur l'exercice."""
    cloture.cloturer_exercice(db, ctx["company"], 2026, user_id=ctx["user"].id)
    soldes = cloture.soldes_a_la_date(db, ctx["company"].id, date(2027, 12, 31))
    assert soldes["5141"] == Decimal("90000.00")  # pas 180 000 (double comptage)
    assert soldes["1111"] == Decimal("-100000.00")
    # Le cumul depuis l'origine double les reports : c'est le piege evite ci-dessus.
    cumul = movements(db, ctx["company"].id, date(1900, 1, 1), date(2027, 12, 31))
    total = {ligne["account_number"]: ligne["solde"] for ligne in cumul}
    assert total["5141"] == Decimal("180000.00")
    assert audit.verifier_chainage(db, ctx["company"].id)["integre"] is True
