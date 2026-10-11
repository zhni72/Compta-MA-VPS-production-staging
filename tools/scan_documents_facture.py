"""Controle de coherence des documents de facture (lecture seule).

Pour **chaque** facture de la base :
1. le PDF est genere (`pdf_documents.pdf_facture`) et ses tableaux sont captures :
   la somme des lignes « Detail des lignes » doit egaler les totaux de l'en-tete
   et la ventilation de TVA par taux doit egaler le total de TVA ;
2. les ecrans `/factures/{id}` et `/factures/{id}/impression` sont rendus via le
   client HTTP et leurs lignes sont controlees (aucune cellule a zero).

Usage :
    .\\.venv\\Scripts\\python.exe tools\\scan_documents_facture.py
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, Invoice, User  # noqa: E402
from app.services import pdf as moteur_pdf  # noqa: E402
from app.services import pdf_documents as documents  # noqa: E402


def _nombre(valeur: str) -> Decimal:
    """« 9 000,00 » -> Decimal('9000.00')."""
    propre = valeur.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(propre)
    except InvalidOperation:
        return Decimal("0")


def scan_pdf(db, facture: Invoice, captures: dict) -> list[str]:
    """Controle des tableaux du document PDF d'une facture."""
    captures.clear()
    documents.pdf_facture(db, facture)
    document = captures.get("document")
    if document is None:
        return ["document PDF non capture"]
    table_lignes, table_tva = document.tableaux[0], document.tableaux[1]
    lignes = table_lignes.lignes
    anomalies: list[str] = []
    if not lignes and facture.total_ht:
        anomalies.append("aucune ligne de detail alors que le total HT est non nul")
    somme_ht = sum((_nombre(l[3]) for l in lignes), Decimal("0"))
    somme_ttc = sum((_nombre(l[5]) for l in lignes), Decimal("0"))
    if lignes and abs(somme_ht - _nombre(str(facture.total_ht))) > Decimal("0.01"):
        anomalies.append(f"somme des lignes HT {somme_ht} <> total HT {facture.total_ht}")
    if lignes and abs(somme_ttc - _nombre(str(facture.total_ttc))) > Decimal("0.01"):
        anomalies.append(f"somme des lignes TTC {somme_ttc} <> total TTC {facture.total_ttc}")
    if not table_tva.lignes and facture.total_vat:
        anomalies.append("ventilation de TVA vide alors que le total de TVA est non nul")
    tva_ventilee = sum((_nombre(l[2]) for l in table_tva.lignes), Decimal("0"))
    if table_tva.lignes and abs(tva_ventilee - _nombre(str(facture.total_vat))) > Decimal("0.01"):
        anomalies.append(f"ventilation TVA {tva_ventilee} <> total TVA {facture.total_vat}")
    for index, ligne in enumerate(facture.lines, start=1):
        if not (ligne.line_ht or ligne.line_vat or ligne.line_ttc):
            anomalies.append(f"ligne {index} a montant nul")
    return anomalies


def cellules(html: str) -> list[list[str]]:
    """Lignes de tableau d'une page HTML (cellules nettoyees)."""
    resultat: list[list[str]] = []
    for ligne in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S):
        valeurs = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cellule)).strip()
            for cellule in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", ligne, flags=re.S)
        ]
        if valeurs:
            resultat.append(valeurs)
    return resultat


def scan_ecrans(client: TestClient, facture: Invoice) -> list[str]:
    """Controle des lignes affichees par les ecrans detail et impression."""
    anomalies: list[str] = []
    for suffixe, nom in (("", "detail"), ("/impression", "impression")):
        reponse = client.get(f"/factures/{facture.id}{suffixe}")
        if reponse.status_code != 200:
            anomalies.append(f"{nom} : HTTP {reponse.status_code}")
            continue
        lignes = [
            l
            for l in cellules(reponse.text)
            if len(l) >= 6 and any(("Achat" in c or "Prestation" in c or "—" in c) for c in l)
        ]
        if not lignes and facture.total_ht:
            anomalies.append(f"{nom} : aucune ligne de facture rendue")
        for ligne in lignes:
            if any(c.replace("\u00a0", "") in ("0,00", "0,00 DH") for c in ligne[-4:]):
                anomalies.append(f"{nom} : cellule a zero -> {ligne}")
    return anomalies


def main() -> int:
    db = SessionLocal()
    captures: dict = {}
    original = moteur_pdf.rendre_pdf

    def capture(document, *args, **kwargs):  # noqa: ANN001
        captures["document"] = document
        return original(document, *args, **kwargs)

    moteur_pdf.rendre_pdf = capture
    documents.rendre_pdf = capture
    total_pdf = total_ecrans = 0
    nb_factures = 0
    try:
        company = db.query(Company).order_by(Company.id).first()
        factures = db.query(Invoice).filter(Invoice.company_id == company.id).all()
        nb_factures = len(factures)
        admin = db.query(User).order_by(User.id).first()
        jeton = create_access_token(admin.id, extra={"email": admin.email})
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("compta_session", jeton)
            for facture in factures:
                for anomalie in scan_pdf(db, facture, captures):
                    print(f"  KO {facture.number or facture.id} (PDF) : {anomalie}")
                    total_pdf += 1
                for anomalie in scan_ecrans(client, facture):
                    print(f"  KO {facture.number or facture.id} (ecran) : {anomalie}")
                    total_ecrans += 1
    finally:
        moteur_pdf.rendre_pdf = original
        documents.rendre_pdf = original
        db.close()
    print(
        f"\n{nb_factures} facture(s) : {total_pdf} anomalie(s) PDF, "
        f"{total_ecrans} anomalie(s) d'ecran."
    )
    return 0 if total_pdf + total_ecrans == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

