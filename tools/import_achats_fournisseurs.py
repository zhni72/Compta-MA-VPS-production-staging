"""Injection du tableau d'achat fournisseurs dans un dossier Compta MA.

Le fichier source (colonnes separees par « | ») decrit des factures d'achat
reelles : date, numero, IF/ICE du fournisseur, montants, mode et date de
reglement, comptes de charge et de TVA. L'outil :

1. corrige le mapping des comptes de charge selon le PCGE : le fichier source
   utilise 6141 « Etudes, recherches et documentation » pour des frais
   bancaires, le compte correct est 61473 « Frais et commissions sur services
   bancaires » (ou 6147 « Services bancaires ») ;
2. ecarte les lignes a TVA nulle (frais exoneres) : une TVA nulle ne se deduit
   pas et ne figure jamais au releve des deductions ;
3. cree les tiers manquants (IF cadre sur 8 chiffres, ICE 15 chiffres) ;
4. cree les exercices comptables manquants (l'annee de la facture) ;
5. valide les factures (journal des achats) puis enregistre les reglements
   (tresorerie) : c'est le reglement qui declenche la deduction en TVA ;
6. journalise chaque ligne (importee / ecartee / rejetee) dans un CSV.

Securite : par defaut l'outil SIMULE (`--appliquer` pour ecrire). Avant toute
ecriture, la base SQLite cible est copiee dans un fichier .bak-<horodatage>.
La societe cible est la premiere du dossier, ou celle passee en `--societe-id`.

Usage :
    python tools/import_achats_fournisseurs.py                  # simulation
    python tools/import_achats_fournisseurs.py --appliquer      # ecriture reelle
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJET = Path(__file__).resolve().parents[1]
DOSSIER = Path(__file__).resolve().parent
SOURCE_DEFAUT = DOSSIER / "data" / "achats_fournisseurs_2025_2026.txt"

# Correction de plan comptable appliquee au fichier source (PCGE).
MAPPING_COMPTES = {
    "6141": "61473",  # frais bancaires (le fichier utilise « Etudes et recherches »)
}
# Libelles attendus, pour tracer la correction dans le journal.
LIBELLES_ATTENDUS = {
    "61473": "Frais et commissions sur services bancaires",
    "61455": "Frais de telephone",
}
MODES = {
    "1": "espece",
    "2": "cheque",
    "3": "prelevement",
    "4": "virement",
    "5": "effet",
}
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse la ligne de commande (la base est resolue avant tout import)."""
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--db", default=None, help="base cible (chemin SQLite)")
    parseur.add_argument(
        "--source", default=str(SOURCE_DEFAUT), help="fichier | du tableau d'achat"
    )
    parseur.add_argument("--societe-id", type=int, default=None, help="societe cible")
    parseur.add_argument("--if-societe", default=None, help="IF du declarant (8 chiffres)")
    parseur.add_argument("--ice-societe", default=None, help="ICE du declarant (15 chiffres)")
    parseur.add_argument(
        "--inclure-tva-nulle",
        action="store_true",
        help="importer aussi les lignes a TVA nulle (par defaut : ecartees)",
    )
    parseur.add_argument(
        "--sans-sauvegarde", action="store_true", help="ne pas copier la base avant ecriture"
    )
    parseur.add_argument("--appliquer", action="store_true", help="ecrire reellement")
    return parseur.parse_args(argv)


def resoudre_base(chemin: str | None) -> Path | None:
    """Fixe DATABASE_URL avant l'import de l'application et retourne le fichier."""
    if chemin:
        cible = Path(chemin)
        if not cible.is_absolute():
            cible = (Path.cwd() / cible).resolve()
        os.environ["DATABASE_URL"] = f"sqlite:///{cible.as_posix()}"
        return cible
    if os.environ.get("DATABASE_URL"):
        return None
    return PROJET / "compta_ma.db"


def montant(texte: str) -> Decimal:
    """Convertit « 1 234,56 » en Decimal (virgule decimale francaise)."""
    try:
        return Decimal(
            texte.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        )
    except InvalidOperation as exc:
        raise ValueError(f"Montant illisible : {texte!r}") from exc


def if_numerique(valeur: str) -> str:
    """« 108 6826 » et « 1086826 » designent le meme identifiant fiscal."""
    return valeur.strip().replace(" ", "").replace("\u00a0", "")


def identifiants_equivalents(valeur: str | None, numero: str) -> bool:
    """Vrai si les deux valeurs designent le meme IF.

    **Norme** : l'IF comporte 7 ou 8 chiffres et s'utilise **tel quel** — aucune
    valeur n'est transformee. **Tolerance de migration** : un IF de 7 chiffres et
    le meme IF precede d'un zero (forme produite par l'ancienne regle zfill,
    « 01084612 » pour « 1084612 ») sont reconnus comme le meme fournisseur, afin
    de **ne pas creer de doublon** tant que la correction des donnees n'a pas ete
    appliquee (`tools/normalize_fiscal_ids.py --retirer-zero-initial --appliquer`).
    """
    if not valeur:
        return False
    gauche, droite = if_numerique(valeur), if_numerique(numero)
    if gauche == droite:
        return True
    if gauche.isdigit() and droite.isdigit():
        return gauche.lstrip("0") == droite.lstrip("0")
    return False


def lire_source(chemin: Path) -> list[dict]:
    """Lit le tableau d'achat (colonnes separees par « | »)."""
    lignes: list[dict] = []
    with chemin.open(encoding="utf-8") as flux:
        for numero, ligne in enumerate(csv.DictReader(flux, delimiter="|"), start=2):
            if not (ligne.get("date") or "").strip():
                continue
            jour, mois, annee = (int(x) for x in ligne["date"].split("/"))
            pai, pm, pa = (int(x) for x in ligne["date_paiement"].split("/"))
            lignes.append(
                {
                    "ligne": numero,
                    "date_facture": date(annee, mois, jour),
                    "date_paiement": date(pa, pm, pai),
                    "num": ligne["num"].strip(),
                    "if_frs": if_numerique(ligne["if_frs"]),
                    "ice": ligne["ice"].strip(),
                    "fournisseur": ligne["fournisseur"].strip(),
                    "ht": montant(ligne["ht"]),
                    "taux": montant(ligne["taux"]),
                    "tva": montant(ligne["tva"]),
                    "ttc": montant(ligne["ttc"]),
                    "mode": MODES.get(ligne["mode"].strip(), "autre"),
                    "compte_source": ligne["cpt_charge"].strip(),
                    "nature": ligne["nature"].strip(),
                    "rc": ligne["rc"].strip(),
                }
            )
    return lignes


def compte_pcge(compte: str) -> tuple[str, str]:
    """Compte de charge corrige selon le PCGE + motif de correction."""
    cible = MAPPING_COMPTES.get(compte, compte)
    if cible == compte:
        return compte, ""
    return cible, (
        f"compte de charge corrige {compte} -> {cible} "
        f"({LIBELLES_ATTENDUS.get(cible, 'PCGE')})"
    )


ENTETES = (
    "ligne_source",
    "date_facture",
    "num_fournisseur",
    "fournisseur",
    "ht",
    "tva",
    "ttc",
    "compte_source",
    "compte_pcge",
    "facture_id",
    "entree_id",
    "statut",
    "motif",
)


def sauvegarder(chemin: Path) -> Path:
    """Copie la base SQLite avant ecriture (retourne le fichier de sauvegarde)."""
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    sauvegarde = chemin.with_name(f"{chemin.name}.bak-{horodatage}")
    shutil.copy2(chemin, sauvegarde)
    return sauvegarde


def preparer_societe(db, societe, args) -> list[str]:  # noqa: ANN001
    """Renseigne l'identite du declarant (IF 7 ou 8 chiffres, tel quel) si demande."""
    from app.services.identifiers import normalize_fiscal_id

    remarques: list[str] = []
    if args.if_societe:
        attendu = normalize_fiscal_id(args.if_societe)
        if societe.fiscal_id != attendu:
            remarques.append(f"societe : IF « {societe.fiscal_id} » -> « {attendu} »")
            societe.fiscal_id = attendu
    if args.ice_societe:
        attendu = args.ice_societe.strip()
        if societe.ice != attendu:
            remarques.append(f"societe : ICE « {societe.ice} » -> « {attendu} »")
            societe.ice = attendu
    if societe.fiscal_id is None:
        remarques.append(
            "societe sans IF : le relevé EDI sera refuse (--if-societe requis)"
        )
    if remarques:
        db.flush()
    return remarques


def creer_tiers(db, societe, lignes_source) -> tuple[dict, list[str]]:  # noqa: ANN001
    """Cree ou met a jour les fournisseurs du tableau d'achat (IF sur 8 chiffres)."""
    from sqlalchemy import select

    from app.models import ThirdParty
    from app.services.identifiers import normalize_fiscal_id
    from app.services.parties import create_third_party

    remarques: list[str] = []
    existants = list(
        db.execute(
            select(ThirdParty).where(ThirdParty.company_id == societe.id)
        ).scalars()
    )

    def retrouver(numero: str):  # noqa: ANN202
        for tiers in existants:
            if identifiants_equivalents(tiers.fiscal_id, numero):
                return tiers
        return None

    fournisseurs: dict = {}
    for ligne in lignes_source:
        numero = ligne["if_frs"]
        if numero in fournisseurs:
            continue
        tiers = retrouver(numero)
        if tiers is None:
            tiers = create_third_party(
                db,
                company=societe,
                kind="fournisseur",
                name=ligne["fournisseur"],
                ice=ligne["ice"],
                fiscal_id=numero,
                rc=ligne["rc"],
                payment_terms_days=0,
            )
            existants.append(tiers)
            remarques.append(f"fournisseur cree : {tiers.code} {tiers.name} (IF {tiers.fiscal_id})")
        elif tiers.fiscal_id != normalize_fiscal_id(numero):
            ancien = tiers.fiscal_id
            tiers.fiscal_id = normalize_fiscal_id(numero)
            remarques.append(
                f"fournisseur {tiers.code} {tiers.name} : IF « {ancien} » "
                f"-> « {tiers.fiscal_id} »"
            )
        fournisseurs[numero] = tiers
    db.flush()
    return fournisseurs, remarques



def preparer_comptes(db, lignes_source) -> list[str]:  # noqa: ANN001
    """Verifie que les comptes utilises existent (contrainte FK du plan comptable).

    `invoice_lines.account_number` et `entry_lines.account_number` referencent
    `accounts.number` : un compte absent du dossier fait echouer l'import. Les
    comptes standards sont crees a la volee si le plan n'a pas ete recharge.
    """
    from app.services.accounts import ensure_account, find_account

    comptes = {
        "34551": "Etat - TVA recuperable sur immobilisations",
        "34552": "Etat - TVA recuperable sur charges",
        "4411": "Fournisseurs",
        "5141": "Banques (debits)",
        "5161": "Caisses (debits)",
    }
    for ligne in lignes_source:
        compte, _ = compte_pcge(ligne["compte_source"])
        comptes.setdefault(compte, LIBELLES_ATTENDUS.get(compte, f"Compte {compte}"))
    crees: list[str] = []
    for numero, libelle in sorted(comptes.items()):
        if find_account(db, numero) is None:
            ensure_account(db, numero, libelle)
            crees.append(numero)
    db.flush()
    return crees


def importer_lignes(db, societe, utilisateur, lignes_source, fournisseurs, args, appliquer):  # noqa: ANN001
    """Valide les factures puis enregistre les reglements ; retourne le journal."""
    from sqlalchemy import select

    from app.db.seed import get_or_create_fiscal_year
    from app.models import INVOICE_STATUS_CANCELLED, Invoice
    from app.services.invoicing import create_invoice, register_payment, validate_invoice

    journal: list[dict] = []
    for ligne in lignes_source:
        compte, motif_compte = compte_pcge(ligne["compte_source"])
        commun = {
            "ligne_source": ligne["ligne"],
            "date_facture": ligne["date_facture"].isoformat(),
            "num_fournisseur": ligne["num"],
            "fournisseur": ligne["fournisseur"],
            "ht": ligne["ht"],
            "tva": ligne["tva"],
            "ttc": ligne["ttc"],
            "compte_source": ligne["compte_source"],
            "compte_pcge": compte,
        }

        if ligne["tva"] == 0 and not args.inclure_tva_nulle:
            journal.append(
                {
                    **commun,
                    "facture_id": "",
                    "entree_id": "",
                    "statut": "ECARTEE",
                    "motif": "TVA nulle (exonere) : hors releve des deductions",
                }
            )
            continue

        tiers = fournisseurs[ligne["if_frs"]]
        existante = db.execute(
            select(Invoice).where(
                Invoice.company_id == societe.id,
                Invoice.partner_id == tiers.id,
                Invoice.reference == ligne["num"],
                Invoice.status != INVOICE_STATUS_CANCELLED,
            )
        ).scalar_one_or_none()
        if existante is not None:
            journal.append(
                {
                    **commun,
                    "facture_id": existante.id,
                    "entree_id": existante.entry_id or "",
                    "statut": "DEJA IMPORTEE",
                    "motif": "facture deja presente (meme numero et meme fournisseur)",
                }
            )
            continue

        if not appliquer:
            journal.append(
                {
                    **commun,
                    "facture_id": "",
                    "entree_id": "",
                    "statut": "SIMULEE",
                    "motif": motif_compte,
                }
            )
            continue

        try:
            get_or_create_fiscal_year(db, societe, ligne["date_facture"].year)
            facture = create_invoice(
                db,
                company=societe,
                invoice_type="achat",
                partner=tiers,
                invoice_date=ligne["date_facture"],
                payment_mode=ligne["mode"],
                reference=ligne["num"],
                lines=[
                    {
                        "designation": ligne["nature"],
                        "quantity": 1,
                        "unit_price": ligne["ht"],
                        "vat_rate": ligne["taux"],
                        "account_number": compte,
                    }
                ],
            )
            validate_invoice(db, facture, user_id=utilisateur.id if utilisateur else None)
            register_payment(
                db,
                facture,
                amount=ligne["ttc"],
                payment_date=ligne["date_paiement"],
                method=ligne["mode"],
                reference=ligne["num"],
                user_id=utilisateur.id if utilisateur else None,
            )
            db.commit()
            journal.append(
                {
                    **commun,
                    "facture_id": facture.id,
                    "entree_id": facture.entry_id or "",
                    "statut": "OK",
                    "motif": motif_compte,
                }
            )
        except Exception as exc:  # noqa: BLE001 - journalisation d'import
            db.rollback()
            journal.append(
                {
                    **commun,
                    "facture_id": "",
                    "entree_id": "",
                    "statut": "REJETE",
                    "motif": f"{type(exc).__name__}: {exc}",
                }
            )
    return journal



def ecrire_journal(journal: list[dict], chemin: Path) -> Path:
    """Ecrit le journal d'import (CSV « ; ») et retourne son chemin."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8-sig", newline="") as flux:
        writer = csv.DictWriter(flux, fieldnames=list(ENTETES), delimiter=";")
        writer.writeheader()
        for ligne in journal:
            writer.writerow({cle: ligne.get(cle, "") for cle in ENTETES})
    return chemin


def controle_final(db, societe) -> list[str]:  # noqa: ANN001
    """Controles de coherence comptable apres import (factures, TVA, tiers)."""
    from sqlalchemy import func, select

    from app.models import EntryLine, Invoice, Payment, ThirdParty

    messages: list[str] = []
    lignes = db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.total_ht), 0),
            func.coalesce(func.sum(Invoice.total_vat), 0),
            func.coalesce(func.sum(Invoice.total_ttc), 0),
        ).where(Invoice.company_id == societe.id, Invoice.invoice_type == "achat")
    ).one()
    messages.append(
        f"factures d'achat : {lignes[0]}  |  HT {lignes[1]}  |  TVA {lignes[2]}  |  TTC {lignes[3]}"
    )
    reglements = db.execute(
        select(func.count(Payment.id)).where(Payment.company_id == societe.id)
    ).scalar_one()
    fournisseurs = db.execute(
        select(func.count(ThirdParty.id)).where(
            ThirdParty.company_id == societe.id, ThirdParty.kind == "fournisseur"
        )
    ).scalar_one()
    messages.append(f"reglements : {reglements}  |  fournisseurs : {fournisseurs}")

    soldes = db.execute(
        select(
            EntryLine.account_number,
            func.coalesce(func.sum(EntryLine.debit - EntryLine.credit), 0),
        )
        .where(EntryLine.account_number.in_(("34551", "34552", "6147", "61473", "61455", "4411")))
        .group_by(EntryLine.account_number)
        .order_by(EntryLine.account_number)
    ).all()
    for numero, solde in soldes:
        messages.append(f"compte {numero} : solde debiteur {solde}")
    return messages


def main(argv: list[str] | None = None) -> int:
    """Point d'entree : simulation par defaut, ecriture reelle avec --appliquer."""
    args = parse_args(argv)
    chemin_base = resoudre_base(args.db)
    source = Path(args.source)
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.exists():
        print(f"Tableau d'achat introuvable : {source}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(PROJET))
    from sqlalchemy import select  # noqa: PLC0415

    from app.core.config import settings  # noqa: PLC0415
    from app.db.base import creer_tables_dev  # noqa: PLC0415
    from app.db.seed import get_or_create_fiscal_year  # noqa: PLC0415
    from app.db.session import SessionLocal, engine  # noqa: PLC0415
    from app.models import Company, User  # noqa: PLC0415

    creer_tables_dev(engine)
    lignes_source = lire_source(source)
    mode = "ECRITURE REELLE" if args.appliquer else "SIMULATION (aucune ecriture)"
    print(f"Base cible   : {settings.database_url}")
    print(f"Tableau achat: {source}  ({len(lignes_source)} lignes)")
    print(f"Mode         : {mode}\n")

    if args.appliquer and not args.sans_sauvegarde and chemin_base and chemin_base.exists():
        print(f"Sauvegarde   : {sauvegarder(chemin_base)}\n")

    with SessionLocal() as db:
        if args.societe_id:
            societe = db.get(Company, args.societe_id)
        else:
            societe = db.execute(select(Company).order_by(Company.id)).scalars().first()
        if societe is None:
            print("Aucune societe dans le dossier : amorcez le dossier d'abord.", file=sys.stderr)
            return 2
        utilisateur = db.execute(select(User).order_by(User.id)).scalars().first()
        print(f"Societe cible: {societe.id} — {societe.name} (regime {societe.vat_regime})")

        for remarque in preparer_societe(db, societe, args):
            print(f"  * {remarque}")
        fournisseurs, remarques_tiers = creer_tiers(db, societe, lignes_source)
        for remarque in remarques_tiers:
            print(f"  * {remarque}")

        # Les referentiels (societe, tiers, comptes, exercices) sont valides AVANT
        # la boucle d'import : chaque ligne est ensuite commitee ou annulee
        # independamment, sans detruire ces referentiels.
        comptes_crees = preparer_comptes(db, lignes_source)
        if comptes_crees:
            print(f"  * comptes crees (absents du plan) : {', '.join(comptes_crees)}")
        for annee in sorted({ligne["date_facture"].year for ligne in lignes_source}):
            get_or_create_fiscal_year(db, societe, annee)
        if args.appliquer:
            db.commit()
        else:
            db.rollback()

        journal = importer_lignes(
            db, societe, utilisateur, lignes_source, fournisseurs, args, args.appliquer
        )
        if args.appliquer:
            db.commit()
        else:
            db.rollback()

        definitif = {cle: 0 for cle in ("OK", "SIMULEE", "ECARTEE", "DEJA IMPORTEE", "REJETE")}
        for ligne in journal:
            definitif[ligne["statut"]] = definitif.get(ligne["statut"], 0) + 1
        importees = [l for l in journal if l["statut"] in ("OK", "SIMULEE")]
        print("\nResultats")
        for statut, nombre in definitif.items():
            if nombre:
                print(f"  {statut:13} {nombre}")
        print(
            f"  totaux       HT {sum(l['ht'] for l in importees)}  |  "
            f"TVA {sum(l['tva'] for l in importees)}  |  "
            f"TTC {sum(l['ttc'] for l in importees)}"
        )
        corrigees = [l for l in journal if l["compte_pcge"] != l["compte_source"]]
        print(f"  comptes de charge corriges (PCGE) : {len(corrigees)}")

        sortie = ecrire_journal(
            journal,
            Path(os.environ.get("TEMP", str(DOSSIER)))
            / "compta_ma_import"
            / "journal_import_achats.csv",
        )
        print(f"\nJournal : {sortie}")
        if args.appliquer:
            print("\nControles comptables")
            for message in controle_final(db, societe):
                print(f"  {message}")
            for line in journal:
                if line["statut"] == "REJETE":
                    print(f"  REJET ligne {line['ligne_source']} : {line['motif']}")
    return 1 if any(l["statut"] == "REJETE" for l in journal) else 0


if __name__ == "__main__":
    raise SystemExit(main())

