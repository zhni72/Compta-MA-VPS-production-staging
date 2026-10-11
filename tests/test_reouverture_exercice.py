"""Non-regression P1 : reouverture d'exercice **encadree** (anomalie A10 de l'audit J9).

Defauts reproduits :
- la reouverture se faisait par un **simple changement de statut** (route web) :
  ni motif, ni utilisateur, ni trace, ni controle de N+1 ;
- le service refusait *toute* reouverture des que des a-nouveaux existaient,
  sans chemin de **regeneration controlee et comparee**.

Correction : `closing.reouvrir_exercice(motif=..., regenerer_a_nouveaux=...)`,
`closing.verrouiller_exercice(motif=...)` et
`closing.regenerer_a_nouveaux(...)` (comparaison avant/apres par compte).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.seed import get_or_create_fiscal_year
from app.services.accounting import AccountingError, create_entry, get_journal
from app.services.closing import (
    apercu_reouverture,
    cloturer_exercice,
    controle_a_nouveaux,
    regenerer_a_nouveaux,
    reouvrir_exercice,
    verrouiller_exercice,
)
from app.services.period_locks import verrouiller_periode

pytestmark = pytest.mark.usefixtures("ctx")

MOTIF = "Regulation de charges omises en 2025 (facture fournisseur)"


def _ecriture(db, ctx, annee: int, montant: str = "1000", jour: int = 15):
    company = ctx["company"]
    exercice = get_or_create_fiscal_year(db, company, annee)
    return create_entry(
        db,
        company_id=company.id,
        fiscal_year=exercice,
        journal=get_journal(db, company.id, "OD"),
        entry_date=date(annee, 6, jour),
        label=f"Charge {annee}",
        lines=[
            {"account_number": "6148", "label": "Charge externe", "debit": montant},
            {"account_number": "4411", "label": "Fournisseur", "credit": montant},
        ],
        validate=True,
    )


def _exercice_clos(db, ctx, annee: int = 2025):
    """Parcours complet : ecriture puis cloture (a-nouveaux de N+1 generes)."""
    get_or_create_fiscal_year(db, ctx["company"], annee + 1)
    _ecriture(db, ctx, annee)
    resultat = cloturer_exercice(db, ctx["company"], annee, user_id=ctx["user"].id)
    db.commit()  # l'etat doit etre persiste (les appels HTTP utilisent la meme session)
    return resultat


def test_reouverture_refusee_sans_motif(db, ctx):
    _exercice_clos(db, ctx)
    for motif in ("", "   ", "court"):
        with pytest.raises(AccountingError) as exc:
            reouvrir_exercice(db, ctx["company"], 2025, motif=motif, user_id=ctx["user"].id)
        assert "motif" in str(exc.value).lower()


def test_reouverture_refusee_si_a_nouveaux_existent(db, ctx):
    """Le refus restitue l'impact : ecriture d'ouverture et ecritures de N+1."""
    _exercice_clos(db, ctx)
    ouverture = controle_a_nouveaux(db, ctx["company"], 2026)
    assert ouverture["existe"] is True

    with pytest.raises(AccountingError) as exc:
        reouvrir_exercice(db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id)
    message = str(exc.value)
    assert ouverture["entry_number"] in message
    assert "Impact" in message
    # l'exercice est reste clos (aucun changement de statut silencieux)
    assert apercu_reouverture(db, ctx["company"], 2025)["statut"] == "closed"


def test_reouverture_refusee_si_periode_verrouillee(db, ctx):
    _exercice_clos(db, ctx)
    verrouiller_periode(
        db,
        company_id=ctx["company"].id,
        year=2025,
        periode=6,
        motif="Controle interne",
        user_id=ctx["user"].id,
    )
    db.flush()
    with pytest.raises(AccountingError) as exc:
        reouvrir_exercice(
            db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id,
            regenerer_a_nouveaux=True,
        )
    assert "verrouillee" in str(exc.value)


def test_reouverture_refusee_si_n_plus_1_verrouille(db, ctx):
    _exercice_clos(db, ctx)
    suivant = get_or_create_fiscal_year(db, ctx["company"], 2026)
    suivant.status = "locked"
    db.flush()
    with pytest.raises(AccountingError) as exc:
        reouvrir_exercice(
            db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id,
            regenerer_a_nouveaux=True,
        )
    assert "verrouille" in str(exc.value)


def test_cycle_complet_reouverture_correction_recloture_regeneration(db, ctx):
    """Reouverture -> correction -> recloture -> regeneration : ecarts chiffres."""
    resultat = _exercice_clos(db, ctx)
    assert resultat["statut"] == "closed"
    ouverture_avant = controle_a_nouveaux(db, ctx["company"], 2026)
    total_avant = ouverture_avant["total_debit"]
    resultat_2025 = resultat["resultat_net"]

    # 1. Reouverture encadree (motif + regeneration explicitement demandee)
    reouverture = reouvrir_exercice(
        db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id,
        regenerer_a_nouveaux=True,
    )
    assert reouverture["statut"] == "open"
    assert reouverture["statut_avant"] == "closed"
    assert reouverture["impact_suivant"].endswith("2026")

    # 2. Correction comptable dans l'exercice reouvert (charge omise)
    _ecriture(db, ctx, 2025, montant="500", jour=20)

    # 3. Re-cloture (controle du bilan ; a-nouveaux regeneres a l'etape 4)
    recloture = cloturer_exercice(
        db, ctx["company"], 2025, user_id=ctx["user"].id, generer_ouverture=False
    )
    assert recloture["statut"] == "closed"
    assert recloture["resultat_net"] == resultat_2025 - Decimal("500.00")

    # 4. Regeneration controlee des a-nouveaux de 2026 + comparaison par compte.
    # Les a-nouveaux ne reprennent que les comptes de bilan et le resultat : la
    # perte supplementaire de 500 DH augmente donc le debit de 500 DH (1199).
    comparaison = regenerer_a_nouveaux(
        db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id
    )
    assert comparaison["avant"]["total_debit"] == total_avant
    assert comparaison["apres"]["total_debit"] == Decimal(total_avant) + Decimal("500.00")
    ecarts = {ecart["compte"]: ecart for ecart in comparaison["ecarts"]}
    assert "1199" in ecarts  # resultat debiteur (perte) ajuste
    assert ecarts["1199"]["ecart"] == Decimal("500.00")
    for ecart in ecarts.values():
        assert ecart["ecart"] == ecart["apres"] - ecart["avant"]

    # 5. Les a-nouveaux regeneres restent equilibres
    apres = controle_a_nouveaux(db, ctx["company"], 2026)
    assert apres["existe"] and apres["equilibre"] is True
    assert apres["total_debit"] == apres["total_credit"]

    # 6. Une nouvelle reouverture reste encadree (motif + regeneration requis)
    with pytest.raises(AccountingError):
        reouvrir_exercice(db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id)


def test_verrouillage_exige_motif_et_exercice_clos(db, ctx):
    get_or_create_fiscal_year(db, ctx["company"], 2025)
    with pytest.raises(AccountingError) as exc:
        verrouiller_exercice(db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id)
    assert "clos" in str(exc.value)

    _exercice_clos(db, ctx)
    with pytest.raises(AccountingError):
        verrouiller_exercice(db, ctx["company"], 2025, motif="court", user_id=ctx["user"].id)
    resultat = verrouiller_exercice(
        db, ctx["company"], 2025, motif=MOTIF, user_id=ctx["user"].id
    )
    assert resultat["statut"] == "locked"
    assert apercu_reouverture(db, ctx["company"], 2025)["reouverture_possible"] is False


def test_ecran_refuse_la_reouverture_sans_motif(client, db, ctx):
    """La route web passe par le service : motif vide -> operation refusee."""
    _exercice_clos(db, ctx)
    client.post(
        "/connexion",
        data={"email": "admin@test.ma", "password": "MotDePasse123"},
        follow_redirects=False,
    )
    reponse = client.post(
        "/parametres/exercices/2025/open", data={"motif": ""}, follow_redirects=False
    )
    assert reponse.status_code == 303
    assert "Op%C3%A9ration+refus%C3%A9e" in reponse.headers["location"]
    exercice = get_or_create_fiscal_year(db, ctx["company"], 2025)
    db.refresh(exercice)
    assert exercice.status == "closed"


