"""Verification **independante** (lecture seule) du dossier Greffe 2025.

Relaie, sans passer par l'application, l'etat du dossier et de ses pieces tel
qu'il est **reellement** enregistre (base + disque) : statut, date d'AG, chemins,
tailles, empreintes SHA-256, taxes payees, absence de depot/certificat, et
**absence de toute ecriture comptable** creee par l'operation.

Usage :
    python tools/p1_greffe_verif_2025.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, Entry  # noqa: E402
from app.models.greffe import GreffeDeposit, GreffeDocument, GreffeEvent, GreffePayment  # noqa: E402
from app.services import greffe  # noqa: E402

EXERCICE = 2025


def main() -> int:
    with SessionLocal() as db:
        company = db.scalars(select(Company).order_by(Company.id)).first()
        depot = db.scalars(
            select(GreffeDeposit).where(GreffeDeposit.exercice == EXERCICE)
        ).first()
        if company is None or depot is None:
            print(f"Aucun dossier {EXERCICE} : rien a verifier.")
            return 1
        pieces = list(
            db.scalars(
                select(GreffeDocument)
                .where(GreffeDocument.deposit_id == depot.id)
                .order_by(GreffeDocument.piece_code)
            )
        )
        paiements = db.scalars(
            select(GreffePayment).where(GreffePayment.deposit_id == depot.id)
        ).all()
        evenements = db.scalars(
            select(GreffeEvent).where(GreffeEvent.deposit_id == depot.id)
        ).all()
        ecritures = db.execute(
            select(func.count(Entry.id)).where(Entry.company_id == company.id)
        ).scalar_one()

        print(f"Dossier #{depot.id} — exercice {depot.exercice} — statut {depot.statut}")
        print(
            f"  date d'AG            : {depot.date_ag}\n"
            f"  date de soumission   : {depot.date_soumission}\n"
            f"  date limite AG/depot : {depot.date_limite_depot}\n"
            f"  date de depot        : {depot.date_depot} (doit rester None)\n"
            f"  reference certificat : {depot.reference_certificat} (doit rester None)\n"
            f"  certificat_path      : {depot.certificat_path} (doit rester None)\n"
            f"  taxes du dossier     : {depot.montant_taxes}\n"
            f"  paiements enregistres: {len(paiements)}\n"
            f"  evenements de dossier: {len(evenements)}\n"
            f"  ecritures comptables : {ecritures}"
        )
        print("\nPieces (base + disque) :")
        for piece in pieces:
            chemin = greffe.racine_stockage() / piece.chemin
            sur_disque = chemin.is_file()
            empreinte = (
                hashlib.sha256(chemin.read_bytes()).hexdigest() if sur_disque else "—"
            )
            coherent = sur_disque and empreinte == piece.hash_sha256
            print(
                f"  [{'OK ' if coherent else 'NOK'}] {piece.piece_code:<22} "
                f"{piece.nom_fichier:<40} {piece.taille_octets:>7} o  "
                f"base={piece.hash_sha256[:16]}… disque={empreinte[:16]}… "
                f"source={piece.source}"
            )
        rapport = next((p for p in pieces if p.piece_code == greffe.PIECE_RAPPORT_GESTION), None)
        pv = next((p for p in pieces if p.piece_code == greffe.PIECE_PV_AG), None)
        print(
            "\nSynthese : "
            f"rapport={'present' if rapport else 'ABSENT'} "
            f"({rapport.taille_octets if rapport else 0} o) ; "
            f"pv={'present' if pv else 'ABSENT'} ({pv.taille_octets if pv else 0} o) ; "
            f"empreintes distinctes="
            f"{bool(rapport and pv and rapport.hash_sha256 != pv.hash_sha256)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
