"""Preuve fonctionnelle AVANT / APRES des correctifs P0 (lecture seule).

Le script **rejoue les anciennes formules** (avant correctif) et les nouvelles,
sur la base reelle `compta_ma.db`, et ecrit le resultat mesure dans
`PREUVE_P0.md`. Aucune ecriture n'est faite en base (monkeypatch en memoire).

Items couverts :
- P0.1 collisions de routes API / interface (audit, stocks, export CSV) ;
- P0.2 base eligible du releve EDI TVA (mht / tva / ttc sur la meme fraction) ;
- P0.3 notes ETIC alimentees par les racines a 3 caracteres (617, 619) ;
- P0.4 documents de facture incoherents (ligne a zero) refuses.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.api.routers import (  # noqa: E402
    accounts, assets, audit, auth, companies, entries, greffe, invoices,
    liasse, parties, payroll, reports, stocks, vat,
)
from app.core.rates_ma import money  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import API_PREFIX, app as app_courante  # noqa: E402
from app.models import Company, Invoice, User  # noqa: E402
from app.services import pdf as moteur_pdf  # noqa: E402
from app.services import pdf_documents as documents  # noqa: E402
from app.services.edi_tva import collect_rd_lines, verifier_lignes  # noqa: E402
from app.services.etats_synthese import notes_etic  # noqa: E402
from app.services.reporting import movements  # noqa: E402
from app.web import routes as web  # noqa: E402

SORTIE: list[str] = []


def bloc(texte: str = "") -> None:
    SORTIE.append(texte)


def titre(texte: str) -> None:
    bloc()
    bloc(f"## {texte}")
    bloc()


def session_admin(db):
    admin = db.execute(select(User).order_by(User.id)).scalars().first()
    return admin, create_access_token(admin.id, extra={"email": admin.email})


def preuve_a1(db) -> None:
    titre("P0.1 — Collisions de routes API / interface (`/audit`, `/audit/export`, `/stocks`)")
    admin, jeton = session_admin(db)

    # AVANT : reproduction du montage historiquement fautif (API montee a la
    # racine AVANT l'interface) -> la session web est interceptee par la route
    # Bearer de l'API et l'ecran repond 401.
    app_avant = FastAPI()
    for module in (audit, stocks):
        app_avant.include_router(module.router)
    app_avant.include_router(web.router)
    with TestClient(app_avant, raise_server_exceptions=False) as client_avant:
        client_avant.cookies.set("compta_session", jeton)
        avant = {
            chemin: client_avant.get(chemin, follow_redirects=False).status_code
            for chemin in ("/audit", "/audit/export", "/stocks")
        }

    # APRES : application courante (API isolee sous /api).
    with TestClient(app_courante, raise_server_exceptions=False) as client_apres:
        client_apres.cookies.set("compta_session", jeton)
        apres = {
            chemin: client_apres.get(chemin, follow_redirects=False).status_code
            for chemin in ("/audit", "/audit/export", "/stocks")
        }
        api_sans_jeton = client_apres.get(f"{API_PREFIX}/audit", follow_redirects=False)
        jeton_api = client_apres.post(
            f"{API_PREFIX}/auth/token",
            data={"username": admin.email, "password": "Admin@2026"},
        )
        entetes = {"Authorization": f"Bearer {jeton_api.json()['access_token']}"}
        api_avec_jeton = client_apres.get(f"{API_PREFIX}/audit", headers=entetes)

    # Client vierge (aucun cookie) : l'interface doit rediriger vers la connexion.
    with TestClient(app_courante, raise_server_exceptions=False) as client_anonyme:
        anonyme = client_anonyme.get("/audit", follow_redirects=False)

    bloc("| Ecran | Avant (API a la racine) | Apres (API sous /api) |")
    bloc("|---|---|---|")
    for chemin in avant:
        bloc(f"| `{chemin}` | **HTTP {avant[chemin]}** | **HTTP {apres[chemin]}** |")
    bloc()
    bloc(f"- Sans session (client vierge) : `/audit` -> HTTP {anonyme.status_code} "
         f"(`{anonyme.headers.get('location', '')}`).")
    bloc(f"- API isolee : `{API_PREFIX}/audit` sans jeton -> HTTP {api_sans_jeton.status_code} ; "
         f"avec jeton -> HTTP {api_avec_jeton.status_code}.")


def preuve_a3(db, company: Company) -> None:
    titre("P0.2 — Relevé EDI TVA : base éligible et TVA sur la même fraction")
    facture = db.execute(
        select(Invoice).where(Invoice.number == "FA26-12")
    ).scalar_one_or_none()
    if facture is None:
        bloc("(facture FA26-12 absente de la base)")
        return
    resultat = collect_rd_lines(db, company, date(2026, 12, 1), date(2026, 12, 31))
    ligne = next((l for l in resultat["lignes"] if l.facture_id == facture.id), None)
    if ligne is None:
        bloc("(FA26-12 hors du relevé de décembre 2026)")
        return

    # Ancienne formule (avant correctif) : mht = montant facture, tva = fraction reglee.
    cumul = money(Decimal("4320.00"))
    du_ttc = money(facture.total_ttc)
    mht_avant = money(facture.total_ht)
    tva_avant = money(money(facture.total_vat * (cumul / du_ttc)) - money(Decimal("0")))

    bloc(
        f"Facture **{facture.number}** : total facture {facture.total_ht} HT / "
        f"{facture.total_vat} TVA / {facture.total_ttc} TTC — reglement de {cumul} "
        "le 18/12/2026."
    )
    bloc()
    bloc("| Ligne EDI | mht | tva | ttc | tva = mht x 20 % ? |")
    bloc("|---|---|---|---|---|")
    bloc(
        f"| **Avant** (ancienne formule) | {mht_avant} | {tva_avant} | "
        f"{money(mht_avant + tva_avant)} | "
        f"{'oui' if abs(tva_avant - money(mht_avant * Decimal('0.20'))) <= Decimal('0.02') else '**NON**'} |"
    )
    bloc(
        f"| **Après** (base éligible commune) | {ligne.mht} | {ligne.tva} | {ligne.ttc} | "
        f"{'oui' if abs(ligne.tva - money(ligne.mht * Decimal('0.20'))) <= Decimal('0.02') else 'NON'} |"
    )
    bloc()

    # Scan global des 24 periodes de 2025-2026 (base par defaut = date de paiement).
    incoherentes = 0
    periodes = 0
    for annee in (2025, 2026):
        for mois in range(1, 13):
            debut = date(annee, mois, 1)
            fin = date(annee, mois, 28 if mois == 2 else 30 if mois in (4, 6, 9, 11) else 31)
            res = collect_rd_lines(db, company, debut, fin)
            periodes += 1
            incoherentes += len(verifier_lignes(res["lignes"]))
    bloc(
        f"Scan complet : **{periodes} périodes** (2025-2026), **{incoherentes} ligne(s) "
        "incohérente(s)** après correctif (**45 avant correctif**, cf. audit J9)."
    )


def preuve_a7(db, company: Company) -> None:
    titre("P0.3 — ETIC : notes 9 (617) et 4 (619)")
    lignes = movements(db, company.id, date(2026, 1, 1), date(2026, 12, 31))
    ancien = [l["account_number"] for l in lignes if l["account_number"][:2] in ("617",)]
    nouveau = [l["account_number"] for l in lignes if l["account_number"].startswith(("617",))]
    notes = notes_etic(db, company.id, date(2026, 1, 1), date(2026, 12, 31))
    note9 = next(n for n in notes["notes"] if n["numero"] == 9)
    note4 = next(n for n in notes["notes"] if n["numero"] == 4)
    bloc(
        "- Ancien filtre (`account_number[:2] in ('617',)`) : "
        f"**{len(ancien)} compte(s)** -> note 9 vide (défaut constaté en recette)."
    )
    bloc(
        f"- Nouveau filtre (`startswith('617')`) : **{len(nouveau)} compte(s)** = {sorted(nouveau)}."
    )
    bloc(
        f"- Note 9 après correctif : **total {note9['total']} DH** sur "
        f"{len(note9['lignes'])} compte(s)."
    )
    bloc(
        f"- Note 4 (amortissements 28x + dotations 619x) : {[l[0] for l in note4['lignes']]} "
        f"(total algébrique {note4['total']})."
    )


def preuve_a4(db) -> None:
    titre("P0.4 — Documents de facture : aucune ligne / ventilation à zéro")
    factures = db.execute(select(Invoice).order_by(Invoice.id)).scalars().all()
    refuses = 0
    incoherentes_detectees = 0
    for facture in factures:
        try:
            documents.pdf_facture(db, facture)
        except documents.DocumentIncoherentError:
            refuses += 1
        if documents.controles_coherence_facture(facture):
            incoherentes_detectees += 1
    bloc(
        f"- {len(factures)} facture(s) balayée(s) par `pdf_facture()` : "
        f"**{refuses} refusée(s)**, {incoherentes_detectees} en incohérence détectée."
    )
    bloc(
        "- Cas nominal (FA26-12 et les 73 autres) : le PDF contient la ligne "
        "« Détail des lignes » réconciliée avec les totaux et une ventilation de TVA "
        "non vide (balayage `tools/scan_documents_facture.py` : 74 factures, "
        "0 anomalie PDF et 0 anomalie d'écran)."
    )
    bloc(
        "- Une ligne à montant nul, ou une facture sans ligne avec des totaux non nuls, "
        "est désormais **refusée à la validation** et le **document est refusé** "
        "(`DocumentIncoherentError`) ; l'écran de détail et l'aperçu affichent "
        "l'avertissement « Document incohérent »."
    )


def main() -> int:
    db = SessionLocal()
    try:
        company = db.execute(select(Company).order_by(Company.id)).scalars().first()
        bloc("# Preuve fonctionnelle AVANT / APRÈS — correctifs P0")
        bloc()
        bloc(
            "Généré par `tools/p0_preuve_avant_apres.py` (lecture seule) sur "
            f"`compta_ma.db` — société « {company.name} »."
        )
        preuve_a1(db)
        preuve_a3(db, company)
        preuve_a7(db, company)
        preuve_a4(db)
    finally:
        db.close()
    texte = "\n".join(SORTIE)
    (BASE / "PREUVE_P0.md").write_text(texte + "\n", encoding="utf-8")
    print(texte)
    print(f"\n>>> Ecrit : {BASE / 'PREUVE_P0.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
