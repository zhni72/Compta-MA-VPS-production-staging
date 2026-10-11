"""P1 greffe — controle de contenu des pieces et generation des documents reels.

Outil de **verification** (lecture seule sauf l'option `--ecrire` qui reste
reservee a un GO explicite) : il analyse le dossier de depot de recette, montre
les anomalies de contenu (pieces vides / pages blanches / doublons) et verifie
que le **rapport de gestion** et le **PV d'AG** generes contiennent bien le
contenu metier attendu.

Usage :
    python tools/p1_greffe_controle_contenu.py            # analyse lecture seule
    python tools/p1_greffe_controle_contenu.py --ecrire   # genere les pieces (GO)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Company  # noqa: E402
from app.models.greffe import GreffeDeposit  # noqa: E402
from app.services import greffe  # noqa: E402
from app.services.pdf_documents import pdf_pv_ag, pdf_rapport_gestion  # noqa: E402


def main() -> int:
    ecrire = "--ecrire" in sys.argv
    db = SessionLocal()
    try:
        company = db.scalars(select(Company).order_by(Company.id)).first()
        if company is None:
            print("Aucune societe en base : rien a controler.")
            return 1
        depots = list(
            db.scalars(
                select(GreffeDeposit).order_by(GreffeDeposit.exercice.desc())
            ).all()
        )
        if not depots:
            print("Aucun dossier de depot en base : rien a controler.")
            return 1
        for depot in depots:
            print(f"\n=== Dossier #{depot.id} — exercice {depot.exercice} "
                  f"({depot.forme_juridique}, {depot.statut}, AG "
                  f"{depot.date_ag or 'non renseignee'}) ===")
            for ligne in greffe.checklist(db, depot):
                etat = "OK " if ligne["fournie"] else "NOK"
                print(
                    f"  [{etat}] {ligne['code']:<22} {ligne['libelle'][:42]:<42} "
                    f"statut={ligne['statut']:<12} "
                    f"taille={ligne['taille_octets'] or 0:>7} octets "
                    f"{(ligne['analyse'] or '')}"
                )
                if ligne.get("anomalie"):
                    print(f"        -> anomalie : {ligne['anomalie']}")
            controles = greffe.controles_depot(db, depot)
            bloquants = greffe.controles_bloquants(controles)
            print(f"  Controles : {len(controles)} "
                  f"(bloquants : {len(bloquants)})")
            for controle in controles:
                print(f"    - [{controle['niveau']}] {controle['message']}")
            print(f"  Completude : {greffe.taux_completude(db, depot)}")
            # Simulation **lecture seule** : le PV n'est produit que si une date
            # d'assemblee existe (aucune date n'est inventee).
            contenus = [
                ("RAPPORT DE GESTION", pdf_rapport_gestion(db, company, depot.exercice))
            ]
            if depot.date_ag is not None:
                contenus.append(
                    (
                        "PV D'AG",
                        pdf_pv_ag(
                            db,
                            company,
                            depot.exercice,
                            date_ag=depot.date_ag,
                            date_limite=depot.date_limite_depot,
                        ),
                    )
                )
            else:
                print(
                    "  PV D'AG : non produit (aucune date d'assemblee enregistree — "
                    "aucune date n'est inventee)."
                )
            for libelle, contenu in contenus:
                analyse = greffe.analyser_piece_pdf(contenu)
                print(f"  {libelle} genere : {len(contenu)} octets — {analyse.resume()}")
        if ecrire:
            date_arg = None
            for index, argument in enumerate(sys.argv):
                if argument == "--date-ag" and index + 1 < len(sys.argv):
                    date_arg = date.fromisoformat(sys.argv[index + 1])
            depot = depots[0]
            assemblee = date_arg or depot.date_ag
            if assemblee is None:
                print(
                    "\n--ecrire exige la **date de l'assemblee generale** "
                    "(--date-ag AAAA-MM-JJ) : aucune date n'est inventee."
                )
                return 2
            print(
                f"\n--ecrire : generation des pieces reelles du dossier #{depot.id} "
                f"(exercice {depot.exercice}, AG du {assemblee})."
            )
            resultat = greffe.generer_pieces(
                db,
                depot,
                company=company,
                date_ag=assemblee,
            )
            db.commit()
            for document in resultat["documents"]:
                print(
                    f"  {document.piece_code:<22} {document.nom_fichier:<38} "
                    f"{document.taille_octets:>8} octets  "
                    f"sha256={document.hash_sha256[:16]}…"
                )
            print(f"  Completude : {resultat['taux_completude']}")
        else:
            print("\nLecture seule (ajouter --ecrire --date-ag AAAA-MM-JJ pour regenerer).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
