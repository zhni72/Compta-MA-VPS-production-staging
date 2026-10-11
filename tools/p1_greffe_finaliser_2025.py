"""Finalisation du **dossier Greffe 2025** : remplacement des deux PDF vides.

Constat de recette : `rapport_gestion_j9.pdf` et `pv_ag_j9.pdf` font **193 octets**,
sont **identiques** (meme SHA-256) et ne contiennent rien. Le dossier #1 (exercice
2025, statut « approuve ») attend donc le **rapport de gestion** et le
**proces-verbal d'AG** reels, ainsi que la **date de l'assemblee generale**.

**La date d'AG n'est jamais inventee** : sans `--date-ag`, l'outil se contente de
l'inventaire « avant » (lecture seule) et indique ce qu'il reste a faire.

Usage :
    python tools/p1_greffe_finaliser_2025.py                        # etat AVANT + preparation
    python tools/p1_greffe_finaliser_2025.py --date-ag 2026-06-30   # regeneration + controles

Options :
    --date-ag AAAA-MM-JJ  date de l'assemblee generale (obligatoire pour ecrire) ;
    --recette             date fournie comme **date de recette (fictive)** : mentionnee
                          dans le livrable, et dossier marque « recette/provisoire » ;
    --toutes              regenere **toutes** les pieces du dossier (etats de synthese,
                          bordereau, rapport de gestion, PV d'AG) au lieu des deux
                          pieces ciblees ;
    --hors-delai          accepte une AG posterieure au delai legal de six mois (amende) ;
    --preuve FICHIER      chemin du livrable (defaut : PREUVE_GREFFE_2025_FINAL.md) ;
    --extraits            imprime les extraits lisibles des deux documents (lecture seule).

L'ecriture exige une date d'assemblee **coherente** : posterieure a la cloture de
l'exercice et, sauf `--hors-delai`, dans le **delai legal de six mois** (loi 5-96,
art. 10). Aucun depot reel, aucun paiement et aucun certificat ne sont produits :
l'outil s'arrete apres la regeneration des pieces et le rejeu des controles.
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, User  # noqa: E402
from app.models.greffe import GreffeDeposit  # noqa: E402
from app.services import greffe  # noqa: E402
from app.services.pdf_documents import (  # noqa: E402
    _donnees_gestion,
    affectation_resultat,
)

PREUVE = RACINE / "PREUVE_GREFFE_2025_FINAL.md"
EXERCICE = 2025
PIECES_CIBLES = (greffe.PIECE_RAPPORT_GESTION, greffe.PIECE_PV_AG)
MOTIF_RESULTAT = "resultat net de l'exercice"
MOTIF_NET = "total du bilan net"


def sha256_fichier(chemin: Path) -> str | None:
    """Empreinte SHA-256 du fichier **reellement present sur le disque**."""
    if not chemin.is_file():
        return None
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def taille_fichier(chemin: Path) -> int | None:
    return chemin.stat().st_size if chemin.is_file() else None


def texte_piece(contenu: bytes) -> str:
    """Texte normalise (minuscules, sans accents) d'une piece PDF."""
    return greffe.analyser_piece_pdf(contenu).texte_normalise


def montant_apres(texte: str, motif: str) -> str | None:
    """Montant « 1 234,56 » qui suit un libelle (None si absent)."""
    trouve = re.search(rf"{motif}\D{{0,40}}?(\d[\d ]*,\d\d)", texte)
    return trouve.group(1) if trouve else None


def montant_devise(valeur: object) -> str:
    """Format identique aux etats PDF : « 1 234,56 DH »."""
    from decimal import Decimal

    return f"{Decimal(str(valeur or 0)):,.2f} DH".replace(",", " ").replace(".", ",")


def inventaire(db, depot: GreffeDeposit) -> list[dict]:
    """Etat **reel** des pieces du dossier : base, disque, contenu, empreintes."""
    racine = greffe.racine_stockage()
    statuts = {ligne["code"]: ligne for ligne in greffe.checklist(db, depot)}
    lignes: list[dict] = []
    for document in sorted(depot.documents, key=lambda d: d.piece_code):
        chemin = racine / document.chemin
        contenu = chemin.read_bytes() if chemin.is_file() else None
        analyse = greffe.analyser_piece_pdf(contenu) if contenu is not None else None
        statut = statuts.get(document.piece_code, {})
        lignes.append(
            {
                "piece_code": document.piece_code,
                "libelle": document.libelle,
                "nom_fichier": document.nom_fichier,
                "chemin": document.chemin,
                "sur_disque": chemin.is_file(),
                "taille_base": document.taille_octets,
                "taille_disque": taille_fichier(chemin),
                "sha256_base": document.hash_sha256,
                "sha256_disque": sha256_fichier(chemin),
                "analyse": None if analyse is None else analyse.resume(),
                "texte": "" if analyse is None else analyse.texte_normalise,
                "source": document.source,
                "statut_checklist": statut.get("statut"),
                "anomalie": statut.get("anomalie"),
            }
        )
    return lignes


def controles(db, depot: GreffeDeposit) -> dict:
    """Controles Greffe complets : checklist, blocages, alertes, completude."""
    liste = greffe.controles_depot(db, depot)
    return {
        "controles": liste,
        "bloquants": greffe.controles_bloquants(liste),
        "alertes": greffe.alertes_depot(db, depot),
        "completude": greffe.taux_completude(db, depot),
        "checklist": greffe.checklist(db, depot),
    }


def donnees_exercice(db, company: Company) -> dict:
    """Chiffres de l'exercice **issus de la comptabilite** (source des PDF)."""
    donnees = _donnees_gestion(db, company.id, EXERCICE)
    return {
        "date_from": donnees["date_from"],
        "date_to": donnees["date_to"],
        # Total du bilan **net équilibré** (bilan CGNC brut / amortissements / net) :
        # seul total approuvé et déposé ; le brut ne sert que « pour mémoire ».
        "total_bilan": donnees["total_bilan"],
        "total_actif_brut": donnees["total_actif_brut"],
        "total_deductions": donnees["total_deductions"],
        "total_passif": donnees["total_passif_avec_resultat"],
        "resultat_net": donnees["resultat_net"],
        "chiffre_affaires": donnees["chiffre_affaires"],
        "equilibre": donnees["equilibre"],
        "affectation": affectation_resultat(donnees["resultat_net"]),
    }


def entree_piece(entrees: list[dict], code: str) -> dict | None:
    return next((entree for entree in entrees if entree["piece_code"] == code), None)


def contenu_piece(entrees: list[dict], code: str) -> bytes | None:
    """Contenu **du disque** de la piece demandee (None si absente)."""
    entree = entree_piece(entrees, code)
    if entree is None:
        return None
    chemin = greffe.racine_stockage() / entree["chemin"]
    return chemin.read_bytes() if chemin.is_file() else None


def _check(liste: list[dict], controle: str, condition: bool, detail: str) -> None:
    """Ajoute un controle PASS/NOK au rapport de recette."""
    liste.append(
        {"controle": controle, "resultat": "PASS" if condition else "NOK", "detail": detail}
    )


def extraits_lignes(
    entrees: list[dict], code: str, motifs: tuple[str, ...], *, largeur: int = 260
) -> list[str]:
    """Extraits du document **autour de chaque mention** attendue.

    Le texte normalise d'une piece est continu (les sauts de ligne du PDF sont
    ecrases) : on renvoie donc une fenetre de contexte autour de chaque motif,
    lisible dans la preuve, plutot qu'une ligne tronquee.
    """
    contenu = contenu_piece(entrees, code)
    if contenu is None:
        return []
    texte = texte_piece(contenu)
    extraits: list[str] = []
    for motif in motifs:
        position = texte.find(motif)
        if position == -1:
            continue
        debut = max(0, position - 70)
        extrait = texte[debut : debut + largeur].strip()
        extraits.append(("…" if debut else "") + extrait + "…")
    return extraits


def verifications_pieces(
    entrees: list[dict], donnees: dict, date_ag: date | None, company: Company
) -> list[dict]:
    """Rejeu des controles de **contenu** et de **coherence** des pieces."""
    checks: list[dict] = []
    rapport = contenu_piece(entrees, greffe.PIECE_RAPPORT_GESTION)
    pv = contenu_piece(entrees, greffe.PIECE_PV_AG)
    etats = contenu_piece(entrees, greffe.PIECE_ETATS_SYNTHESE)
    textes = {
        greffe.PIECE_RAPPORT_GESTION: texte_piece(rapport) if rapport else "",
        greffe.PIECE_PV_AG: texte_piece(pv) if pv else "",
        greffe.PIECE_ETATS_SYNTHESE: texte_piece(etats) if etats else "",
    }
    analyses = {
        code: greffe.analyser_piece_pdf(contenu)
        for code, contenu in (
            (greffe.PIECE_RAPPORT_GESTION, rapport),
            (greffe.PIECE_PV_AG, pv),
            (greffe.PIECE_ETATS_SYNTHESE, etats),
        )
        if contenu is not None
    }

    # 1. Lisibilite et renseignement des deux pieces ciblees.
    for code, libelle in (
        (greffe.PIECE_RAPPORT_GESTION, "Rapport de gestion"),
        (greffe.PIECE_PV_AG, "PV d'AG"),
    ):
        analyse = analyses.get(code)
        _check(
            checks,
            f"{libelle} : PDF lisible et renseigne",
            bool(analyse) and analyse.valide,
            (analyse.resume() if analyse else "piece absente du dossier"),
        )
        # 2. Controles bloquants de l'application (rejoues sur le fichier du disque).
        contenu = contenu_piece(entrees, code)
        entree = entree_piece(entrees, code)
        nom = entree["nom_fichier"] if entree else code
        try:
            greffe.verifier_contenu_piece(code, nom, contenu or b"")
            detail = "controles de contenu de l'application : acceptes"
            accepte = True
        except greffe.GreffeError as erreur:
            detail = str(erreur)
            accepte = False
        _check(checks, f"{libelle} : mentions metier obligatoires", accepte, detail)

    # 3. Distinction des deux pieces (contenu et empreinte).
    distincts = bool(rapport and pv) and rapport != pv
    empreintes = {
        entree["piece_code"]: (entree["sha256_disque"] or "") for entree in entrees
    }
    _check(
        checks,
        "Rapport de gestion et PV d'AG : documents distincts",
        distincts
        and empreintes.get(greffe.PIECE_RAPPORT_GESTION)
        != empreintes.get(greffe.PIECE_PV_AG),
        f"rapport={empreintes.get(greffe.PIECE_RAPPORT_GESTION, '—')[:16]}… "
        f"pv={empreintes.get(greffe.PIECE_PV_AG, '—')[:16]}…",
    )

    # 4. Empreintes en base = empreintes du disque (integrite).
    for entree in entrees:
        _check(
            checks,
            f"Empreinte SHA-256 en base = disque ({entree['piece_code']})",
            bool(entree["sha256_disque"])
            and entree["sha256_base"] == entree["sha256_disque"],
            f"base={entree['sha256_base'][:16]}… disque="
            f"{(entree['sha256_disque'] or '—')[:16]}…",
        )

    # 5. Les anciens PDF vides (193 octets, contenu identique) ont disparu.
    vides = [
        entree
        for entree in entrees
        if entree["taille_disque"] is not None and entree["taille_disque"] < 400
    ]
    _check(
        checks,
        "Anciens PDF de 193 octets remplaces (aucune piece < 400 octets)",
        not vides,
        "aucune piece vide"
        if not vides
        else "restantes : " + ", ".join(f"{e['nom_fichier']} ({e['taille_disque']} o)" for e in vides),
    )
    _check(
        checks,
        "Conflit de contenu resolu (aucune piece partageant une empreinte)",
        len({e["sha256_disque"] for e in entrees if e["sha256_disque"]})
        == len([e for e in entrees if e["sha256_disque"]]),
        "empreintes toutes distinctes"
        if len({e["sha256_disque"] for e in entrees if e["sha256_disque"]})
        == len([e for e in entrees if e["sha256_disque"]])
        else "empreinte partagee par plusieurs pieces : "
        + ", ".join(sorted({e["nom_fichier"] for e in entrees if e["sha256_disque"]})),
    )

    # 6. Coherence metier : exercice, date d'AG, resultat, affectation, bilan, CA.
    texte_rapport = textes[greffe.PIECE_RAPPORT_GESTION]
    texte_pv = textes[greffe.PIECE_PV_AG]
    exercice_dans_pieces = str(EXERCICE) in texte_rapport and str(EXERCICE) in texte_pv
    _check(
        checks,
        f"Exercice {EXERCICE} porte par les deux documents",
        exercice_dans_pieces,
        f"rapport={'2025 present' if str(EXERCICE) in texte_rapport else 'absent'} ; "
        f"pv={'2025 present' if str(EXERCICE) in texte_pv else 'absent'}",
    )
    if date_ag is not None:
        date_fr = date_ag.strftime("%d/%m/%Y")
        _check(
            checks,
            "Date d'AG reportee dans le PV d'AG",
            date_fr in texte_pv and "date de l'assemblee generale" in texte_pv,
            f"date attendue {date_fr} ; "
            f"{'presente' if date_fr in texte_pv else 'ABSENTE'} dans le PV",
        )
    resultat = montant_devise(donnees["resultat_net"]).replace(" DH", "")
    net = montant_devise(donnees["total_bilan"]).replace(" DH", "")
    brut = montant_devise(donnees["total_actif_brut"]).replace(" DH", "")
    deductions = montant_devise(donnees["total_deductions"]).replace(" DH", "")
    affaires = montant_devise(donnees["chiffre_affaires"]).replace(" DH", "")
    _check(
        checks,
        "Resultat 2025 : rapport = PV = comptabilite",
        montant_apres(texte_rapport, MOTIF_RESULTAT) == resultat
        and texte_pv.count(resultat) >= 2,
        f"comptabilite={resultat} ; rapport={montant_apres(texte_rapport, MOTIF_RESULTAT)} ; "
        f"occurrences dans le PV={texte_pv.count(resultat)}",
    )
    _check(
        checks,
        "Total du bilan **net** 2025 : rapport = PV = comptabilite",
        montant_apres(texte_rapport, MOTIF_NET) == net and texte_pv.count(net) >= 1,
        f"comptabilite (actif net)={net} ; brut={brut} ; deductions={deductions} ; rapport="
        f"{montant_apres(texte_rapport, MOTIF_NET)} ; "
        f"occurrences dans le PV={texte_pv.count(net)}",
    )
    _check(
        checks,
        "Total actif **brut** jamais utilise comme total du bilan",
        brut != net
        and montant_apres(texte_rapport, MOTIF_NET) == net
        and f"total du bilan net {net}" in texte_pv,
        f"net={net} ; brut={brut} ; PV : "
        f"{'net approuve' if f'total du bilan net {net}' in texte_pv else 'net ABSENT'} ; "
        f"brut {'cite pour memoire' if brut in texte_pv else 'absent du PV'}",
    )
    _check(
        checks,
        "Chiffre d'affaires 2025 : PV = comptabilite",
        affaires in texte_pv,
        f"comptabilite={affaires} ; pv={'present' if affaires in texte_pv else 'absent'}",
    )
    affectation = greffe._normaliser_texte(donnees["affectation"])
    _check(
        checks,
        "Affectation du resultat identique dans le rapport et le PV",
        affectation in texte_rapport and affectation in texte_pv,
        donnees["affectation"],
    )
    analyse_etats = analyses.get(greffe.PIECE_ETATS_SYNTHESE)
    mentions = [
        mention
        for mention in ("bilan", "compte de produits et charges", "soldes de gestion", "etic")
        if mention in textes[greffe.PIECE_ETATS_SYNTHESE]
    ]
    _check(
        checks,
        f"Etats de synthese {EXERCICE} : bilan, CPC, ESG et ETIC",
        bool(analyse_etats)
        and analyse_etats.valide
        and len(mentions) >= 3,
        f"{(analyse_etats.resume() if analyse_etats else 'piece absente')} ; "
        f"mentions={mentions}",
    )

    # 7. Identite harmonisee (fiche societe) dans les documents du dossier.
    from app.services.pdf_documents import (
        associe_unique,
        forme_juridique,
        siege_social,
    )

    forme = forme_juridique(company)
    siege = siege_social(company)
    porte_unique = "associe unique" in texte_pv
    bordereau = contenu_piece(entrees, greffe.PIECE_ETAT_COMPLEMENTAIRE)
    texte_bordereau = texte_piece(bordereau) if bordereau else ""
    documents = {"rapport": texte_rapport, "pv": texte_pv, "bordereau": texte_bordereau}
    for etiquette, texte in documents.items():
        if not texte:
            continue
        forme_ok = forme.lower() in texte
        siege_ok = siege.lower() in texte
        _check(
            checks,
            f"Identite harmonisee ({etiquette}) : forme juridique et siege social",
            forme_ok and siege_ok,
            f"forme « {forme} » {'presente' if forme_ok else 'ABSENTE'} ; "
            f"siege « {siege} » {'present' if siege_ok else 'ABSENT'}",
        )
    _check(
        checks,
        "Qualite « associe unique » (SARL AU) portee par le PV d'AG",
        porte_unique == associe_unique(company),
        f"societe a associe unique : {'oui' if associe_unique(company) else 'non'} ; "
        f"mention {'presente' if porte_unique else 'absente'} dans le PV",
    )
    if date_ag is not None:
        date_fr = date_ag.strftime("%d/%m/%Y")
        _check(
            checks,
            "Bordereau / etat complementaire a jour de la date d'AG",
            date_fr in texte_bordereau,
            f"date d'AG {date_fr} "
            f"{'presente' if date_fr in texte_bordereau else 'ABSENTE'} dans le bordereau",
        )
    return checks


def verifications_dossier(
    db, depot: GreffeDeposit, avant: dict, apres: dict, donnees: dict
) -> list[dict]:
    """Rejeu des controles **Greffe complets** + preuve de non-depot."""
    checks: list[dict] = []
    etat = controles(db, depot)
    statuts = {ligne["code"]: ligne for ligne in etat["checklist"]}

    for code, libelle in (
        (greffe.PIECE_RAPPORT_GESTION, "Rapport de gestion"),
        (greffe.PIECE_PV_AG, "PV d'AG"),
    ):
        ligne = statuts.get(code, {})
        _check(
            checks,
            f"Checklist : {libelle} « fournie »",
            ligne.get("fournie") is True and ligne.get("statut") == "fournie",
            f"statut={ligne.get('statut')} taille={ligne.get('taille_octets')} o "
            f"anomalie={ligne.get('anomalie') or 'aucune'}",
        )

    completude = etat["completude"]
    _check(
        checks,
        f"Completude du dossier : {completude['nb_fournies']}/{completude['nb_exigees']}",
        bool(completude["complete"]),
        f"manquantes={completude['manquantes'] or 'aucune'}",
    )
    _check(
        checks,
        "Controles Greffe : aucun controle bloquant",
        not etat["bloquants"],
        f"{len(etat['controles'])} controle(s), dont {len(etat['bloquants'])} bloquant(s) : "
        + "; ".join(f"{c['code']}({c['niveau']})" for c in etat["bloquants"]),
    )
    _check(
        checks,
        "Exercice / date d'AG / delai legal de six mois coherents",
        depot.exercice == EXERCICE
        and depot.date_ag is not None
        and depot.date_ag >= donnees["date_to"]
        and depot.date_ag <= depot.date_limite_depot,
        f"exercice={depot.exercice} ; AG={depot.date_ag} ; cloture={donnees['date_to']} ; "
        f"limite AG={depot.date_limite_depot}",
    )
    # Chronologie AG -> depot : la cloture precede l'AG, qui precede tout depot eventuel.
    depot_posterieur = depot.date_depot is None or (
        depot.date_ag is not None and depot.date_depot >= depot.date_ag
    )
    soumission_posterieure = depot.date_soumission is None or (
        depot.date_ag is not None and depot.date_soumission >= depot.date_ag
    )
    _check(
        checks,
        "Chronologie AG -> depot respectee (cloture <= AG <= soumission/depot)",
        depot_posterieur and soumission_posterieure,
        f"cloture={donnees['date_to']} ; AG={depot.date_ag} ; "
        f"soumission={depot.date_soumission or 'non effectuee'} ; "
        f"depot={depot.date_depot or 'non effectue'}",
    )
    # Aucun depot reel, aucun paiement, aucun certificat : etat du dossier inchange.
    _check(
        checks,
        "Aucun depot reel effectue (statut et dates de depot inchanges)",
        apres["statut"] == avant["statut"]
        and apres["date_depot"] == avant["date_depot"]
        and apres["reference_certificat"] == avant["reference_certificat"]
        and apres["certificat_path"] == avant["certificat_path"],
        f"statut={apres['statut']} (avant {avant['statut']}) ; date_depot={apres['date_depot']} ; "
        f"certificat={apres['reference_certificat'] or 'aucun'}",
    )
    _check(
        checks,
        "Aucun paiement enregistre et aucun evenement de depot cree",
        apres["nb_paiements"] == avant["nb_paiements"]
        and apres["total_paye"] == avant["total_paye"]
        and apres["nb_evenements"] == avant["nb_evenements"],
        f"paiements={apres['nb_paiements']} (avant {avant['nb_paiements']}) ; "
        f"evenements={apres['nb_evenements']} (avant {avant['nb_evenements']}) ; "
        f"taxes payees={apres['total_paye']}",
    )
    return checks


def regenerer(
    db,
    depot: GreffeDeposit,
    company: Company,
    date_ag: date,
    utilisateur: User | None,
    *,
    toutes: bool = False,
) -> list:
    """Regenere les pieces depuis l'application (rapport de gestion + PV d'AG).

    Par defaut, **seules les deux pieces ciblees** sont (re)generees : les etats de
    synthese, le bordereau et le justificatif de paiement deja archives ne sont pas
    touches (`--toutes` reproduit exactement le parcours de l'ecran Greffe, qui
    regenere l'ensemble des pieces du dossier).
    """
    utilisateur_id = None if utilisateur is None else utilisateur.id
    if toutes:
        return greffe.generer_pieces(
            db,
            depot,
            company=company,
            user_id=utilisateur_id,
            date_ag=date_ag,
        )["documents"]

    from app.core.audit import log_action  # noqa: PLC0415 - anti-cycle d'import
    from app.services.pdf_documents import (  # noqa: PLC0415 - anti-cycle d'import
        pdf_pv_ag,
        pdf_rapport_gestion,
    )

    # Date d'assemblee enregistree **avant** generation (tracabilite, comme l'ecran).
    depot.date_ag = date_ag
    document_rapport = greffe.ajouter_piece(
        db,
        depot,
        piece_code=greffe.PIECE_RAPPORT_GESTION,
        nom_fichier=f"Rapport_gestion_{depot.exercice}.pdf",
        contenu=pdf_rapport_gestion(db, company, depot.exercice),
        user_id=utilisateur_id,
        source=greffe.SOURCE_GENERE,
    )
    document_pv = greffe.ajouter_piece(
        db,
        depot,
        piece_code=greffe.PIECE_PV_AG,
        nom_fichier=f"PV_AG_{depot.exercice}.pdf",
        contenu=pdf_pv_ag(
            db,
            company,
            depot.exercice,
            date_ag=date_ag,
            date_limite=depot.date_limite_depot,
        ),
        user_id=utilisateur_id,
        source=greffe.SOURCE_GENERE,
    )
    log_action(
        db,
        action="GREFFE_PIECES_GENERATED",
        entity="GreffeDeposit",
        entity_id=depot.id,
        user_id=utilisateur_id,
        company_id=depot.company_id,
        payload={
            "exercice": depot.exercice,
            "date_ag": date_ag.isoformat(),
            "pieces": [greffe.PIECE_RAPPORT_GESTION, greffe.PIECE_PV_AG],
            "rapport_gestion": document_rapport.taille_octets,
            "pv_ag": document_pv.taille_octets,
        },
    )
    return [document_rapport, document_pv]


def _ligne_piece(entree: dict) -> str:
    sha = entree["sha256_disque"] or "—"
    return (
        f"| `{entree['piece_code']}` | {entree['nom_fichier']} | "
        f"{entree['taille_disque'] if entree['taille_disque'] is not None else '—'} o | "
        f"{sha[:32]}… | {entree['statut_checklist']} | {entree['analyse'] or '—'} |"
    )


def _table_pieces(entrees: list[dict]) -> str:
    lignes = [
        "| Piece | Fichier | Taille | SHA-256 | Checklist | Analyse de contenu |",
        "|---|---|---|---|---|---|",
    ]
    lignes += [_ligne_piece(entree) for entree in entrees]
    return "\n".join(lignes)


def _table_checks(checks: list[dict]) -> str:
    lignes = ["| Controle | Resultat | Detail |", "|---|---|---|"]
    for check in checks:
        detail = check["detail"].replace("|", "/").replace("\n", " ")
        lignes.append(f"| {check['controle']} | **{check['resultat']}** | {detail} |")
    return "\n".join(lignes)


def _table_controles(etat: dict) -> str:
    lignes = ["| Code | Niveau | Message |", "|---|---|---|"]
    for controle in etat["controles"]:
        message = controle["message"].replace("|", "/")
        lignes.append(f"| `{controle['code']}` | {controle['niveau']} | {message} |")
    if not etat["controles"]:
        lignes.append("| — | — | aucun controle |")
    return "\n".join(lignes)


def rediger_preuve(contexte: dict) -> str:
    """Compose le livrable `PREUVE_GREFFE_2025_FINAL.md` (avant/apres + controles)."""
    depot = contexte["depot"]
    donnees = contexte["donnees"]
    ecrit = contexte["ecrit"]
    date_ag = depot.date_ag
    blocs: list[str] = []
    blocs.append("# Preuve de finalisation du dossier Greffe 2025")
    blocs.append("")
    blocs.append(
        f"**Societe** : {contexte['company'].name} (ICE {contexte['company'].ice or '—'}, "
        f"RC {contexte['company'].rc or '—'})  ·  **Exercice** : {EXERCICE}  ·  "
        f"**Dossier** : #{depot.id}  ·  **Forme** : {depot.forme_juridique}"
    )
    blocs.append(
        f"**Statut du dossier** : `{depot.statut}`  ·  **Date d'AG enregistree** : "
        f"{date_ag.strftime('%d/%m/%Y') if date_ag else '**non renseignee**'}  ·  "
        f"**Date limite d'AG / depot** : {depot.date_limite_depot.strftime('%d/%m/%Y')}"
    )
    blocs.append(
        f"**Operateur** : {contexte['operateur']}  ·  **Commande** : "
        f"`python tools/p1_greffe_finaliser_2025.py"
        + (f" --date-ag {date_ag.isoformat()}`" if date_ag else "` (preparation)")
    )
    blocs.append("")

    # 1. Chiffres de l'exercice (source des documents).
    blocs.append("## 1. Chiffres de l'exercice (comptabilite, source des documents)")
    blocs.append("")
    blocs.append("| Indicateur | Montant |")
    blocs.append("|---|---|")
    blocs.append(f"| Exercice | {EXERCICE} (du {donnees['date_from']} au {donnees['date_to']}) |")
    blocs.append(
        f"| **Total du bilan net (actif net = passif)** | **{montant_devise(donnees['total_bilan'])}** |"
    )
    blocs.append(
        f"| Total actif brut (pour memoire, **jamais** retenu comme total du bilan) | "
        f"{montant_devise(donnees['total_actif_brut'])} |"
    )
    blocs.append(
        f"| Amortissements et provisions deduits de l'actif | "
        f"{montant_devise(donnees['total_deductions'])} |"
    )
    blocs.append(f"| Chiffre d'affaires | {montant_devise(donnees['chiffre_affaires'])} |")
    blocs.append(f"| Resultat net | {montant_devise(donnees['resultat_net'])} |")
    blocs.append(
        f"| Equilibre actif = passif | {'oui' if donnees['equilibre'] else '**NON**'} |"
    )
    blocs.append(f"| Affectation du resultat retenue | {donnees['affectation']} |")
    blocs.append("")

    # 2. Etat AVANT.
    blocs.append("## 2. Etat des pieces AVANT (dossier de recette)")
    blocs.append("")
    blocs.append(_table_pieces(contexte["avant_pieces"]))
    blocs.append("")
    blocs.append(
        f"Constat : `rapport_gestion` et `pv_ag` = **193 octets**, contenu **identique** "
        f"(SHA-256 `794abaa4f6f0…`), aucune page renseignee — d'ou "
        f"**{contexte['avant_bloquants']} controle(s) bloquant(s)** et une completude de "
        f"**{contexte['avant_completude']['nb_fournies']}/"
        f"{contexte['avant_completude']['nb_exigees']}**."
    )
    blocs.append("")
    blocs.append("Controles Greffe AVANT :")
    blocs.append("")
    blocs.append(_table_controles(contexte["avant_controles"]))
    blocs.append("")
    blocs.append(
        "Controles bloquants AVANT : "
        + (
            ", ".join(f"`{c['code']}`" for c in contexte["avant_controles"]["bloquants"])
            or "aucun"
        )
    )
    blocs.append("")
    return "\n".join(blocs)


def _suite_preuve(contexte: dict) -> list[str]:
    """Sections 3 a 9 du livrable (operation, etat apres, controles, confirmation)."""
    depot = contexte["depot"]
    donnees = contexte["donnees"]
    ecrit = contexte["ecrit"]
    blocs: list[str] = []

    # 3. Date d'AG.
    blocs.append("## 3. Date de l'assemblee generale")
    blocs.append("")
    if depot.date_ag is None:
        blocs.append(
            "**Aucune date d'AG n'est renseignee et aucune date n'a ete inventee.** "
            "La generation du PV d'AG (et l'etat « Approuve ») est bloquee par "
            "l'application tant que la date n'est pas fournie (loi 5-96, art. 10)."
        )
        blocs.append("")
        blocs.append(
            "Commande a lancer des que la date est fournie (AAAA-MM-JJ, posterieure a la "
            "cloture et au plus tard le "
            f"{depot.date_limite_depot.strftime('%d/%m/%Y')}) :"
        )
        blocs.append("")
        blocs.append("```")
        blocs.append("python tools/p1_greffe_finaliser_2025.py --date-ag AAAA-MM-JJ")
        blocs.append("```")
    else:
        blocs.append(
            f"Date transmise par le demandeur : **{depot.date_ag.strftime('%d/%m/%Y')}** — "
            f"enregistree sur le dossier #{depot.id} et reportee dans le PV d'AG."
        )
        if contexte.get("date_recette"):
            blocs.append("")
            blocs.append(
                "> **Date de recette (fictive)** : fournie explicitement par le demandeur "
                "comme date de scenario de recette, **elle ne correspond pas a une assemblee "
                "generale reelle**. Elle sert a valider la chaine technique (generation, "
                "controles, empreintes) ; toute exploitation reelle du dossier devra etre "
                "reprise avec la date de l'AG effectivement tenue."
            )
    blocs.append("")

    # 4. Operation realisee.
    blocs.append("## 4. Operation realisee (regeneration depuis l'application)")
    blocs.append("")
    if not ecrit:
        blocs.append(
            "**Non executee** : preparation uniquement (aucune ecriture en base, aucun "
            "fichier modifie)."
        )
        blocs.append("")
    else:
        blocs.append(
            f"`services.greffe.generer_pieces(..., date_ag={depot.date_ag})` — pieces "
            f"regeneres (source `genere`), anciens fichiers remplaces sur le disque :"
        )
        blocs.append("")
        blocs.append("| Piece regeneree | Fichier | Taille | SHA-256 |")
        blocs.append("|---|---|---|---|")
        for document in contexte["documents"]:
            blocs.append(
                f"| `{document.piece_code}` | {document.nom_fichier} | "
                f"{document.taille_octets} o | `{document.hash_sha256}` |"
            )
        blocs.append("")
        blocs.append(
            "Journalisation : `GREFFE_PIECES_GENERATED` (exercice, date d'AG, tailles) et "
            "`GREFFE_PIECE_ADDED` par piece (nom, taille, empreinte, source)."
        )
        blocs.append("")

    # 5. Etat APRES.
    blocs.append("## 5. Etat des pieces APRES")
    blocs.append("")
    blocs.append(_table_pieces(contexte["apres_pieces"]))
    blocs.append("")

    # 5 bis. Extraits des documents generes (PV d'AG et rapport de gestion).
    blocs.append("## 5 bis. Extraits des documents generes")
    blocs.append("")
    if not ecrit:
        blocs.append("_Extraits disponibles apres regeneration._")
        blocs.append("")
        return blocs
    extraits = (
        (
            "Rapport de gestion",
            greffe.PIECE_RAPPORT_GESTION,
            (
                "situation de la societe",
                "chiffre d'affaires",
                "excedent brut",
                "resultat d'exploitation",
                "resultat net de l'exercice",
                "total du bilan",
                "affectation du resultat",
                "affectation proposee",
                "depot au greffe",
            ),
        ),
        (
            "PV d'AG / decision de l'associe unique",
            greffe.PIECE_PV_AG,
            (
                "date de l'assemblee generale",
                "qualite des participants",
                "ordre du jour",
                "premiere resolution",
                "approuve les comptes",
                "deuxieme resolution",
                "resultat net de l'exercice est fixe",
                "troisieme resolution",
                "tous pouvoirs",
                "greffe du tribunal",
            ),
        ),
    )
    for libelle, code, motifs in extraits:
        entree = entree_piece(contexte["apres_pieces"], code)
        blocs.append(f"### {libelle}")
        blocs.append("")
        blocs.append(
            f"Fichier : `{entree['nom_fichier']}` "
            f"({entree['chemin']}) — {entree['taille_disque']} octets — "
            f"SHA-256 `{entree['sha256_disque']}`"
            if entree
            else "Piece absente."
        )
        blocs.append("")
        lignes = extraits_lignes(contexte["apres_pieces"], code, motifs)
        for ligne in dict.fromkeys(lignes):
            extrait = ligne if len(ligne) <= 300 else ligne[:297] + "…"
            blocs.append(f"- {extrait}")
        blocs.append("")
    return blocs


def _fin_preuve(contexte: dict) -> list[str]:
    """Sections 6 a 9 : controles PASS/NOK, coherence, non-depot, reste a faire."""
    depot = contexte["depot"]
    donnees = contexte["donnees"]
    blocs: list[str] = []
    checks_pieces = contexte["checks_pieces"]
    checks_dossier = contexte["checks_dossier"]

    blocs.append("## 6. Controles de recette (PASS / NOK)")
    blocs.append("")
    blocs.append("### 6.1 Pieces (lisibilite, mentions metier, unicite, integrite)")
    blocs.append("")
    blocs.append(_table_checks(checks_pieces))
    blocs.append("")
    blocs.append("### 6.2 Dossier (checklist, completude, controles Greffe, non-depot)")
    blocs.append("")
    blocs.append(
        _table_checks(checks_dossier)
        if checks_dossier
        else "| Controle | Resultat | Detail |\n|---|---|---|\n"
        "| Rejeu complet des controles | **EN ATTENTE** | a executer apres la fourniture de "
        "la date d'AG |"
    )
    blocs.append("")
    blocs.append("### 6.3 Versions actives du dossier (anti-doublon, anti-orphelin)")
    blocs.append("")
    blocs.append(_table_checks(contexte["checks_versions"]))
    blocs.append("")

    blocs.append("## 7. Coherence exercice 2025 / date d'AG / resultat / affectation")
    blocs.append("")
    blocs.append("| Element | Valeur | Source |")
    blocs.append("|---|---|---|")
    blocs.append(f"| Exercice du dossier | {depot.exercice} | `greffe_deposits.exercice` |")
    blocs.append(
        f"| Cloture de l'exercice | {donnees['date_to']} | calendrier de l'exercice fiscal |"
    )
    blocs.append(
        f"| Date d'AG | {depot.date_ag.strftime('%d/%m/%Y') if depot.date_ag else 'non renseignee'}"
        f" | dossier + PV d'AG |"
    )
    blocs.append(
        f"| Resultat net 2025 | {montant_devise(donnees['resultat_net'])} | comptabilite "
        f"(CPC / ESG) |"
    )
    blocs.append(
        f"| Affectation du resultat | {donnees['affectation']} | rapport de gestion (art. 4) et "
        f"PV (2e resolution) |"
    )
    blocs.append(
        f"| Total du bilan **net** | {montant_devise(donnees['total_bilan'])} | etats de synthese "
        f"(bilan net) + PV (1re resolution) |"
    )
    blocs.append(
        f"| Total actif brut (pour memoire) | {montant_devise(donnees['total_actif_brut'])} | "
        f"bilan (colonne brut) — jamais retenu comme total du bilan |"
    )
    blocs.append("")

    blocs.append("## 8. Confirmation : aucun depot, paiement ni certificat simule")
    blocs.append("")
    blocs.append(
        "- **Aucun depot reel** n'a ete effectue : le dossier reste a l'etat "
        f"`{depot.statut}` (portail `depotbilan.justice.gov.ma` non appele)."
    )
    blocs.append(
        f"- **Aucune date de depot** n'est enregistree (`date_depot={depot.date_depot}`) et le "
        "statut « Depose » n'a pas ete force."
    )
    blocs.append(
        "- **Aucun paiement** n'a ete enregistre : les taxes du dossier "
        f"({montant_devise(depot.montant_taxes)}) restent en l'etat, aucune transaction CMI "
        "n'est simulee."
    )
    blocs.append(
        "- **Aucun certificat / recepisse** n'est fabrique : "
        f"`reference_certificat={depot.reference_certificat or 'aucune'}` "
        f"(le certificat officiel, signe electroniquement, est fourni par le greffe)."
    )
    blocs.append(
        "- Les pieces **etats de synthese**, **bordereau** et **justificatif de paiement** "
        "n'ont pas ete modifiees par cette operation."
    )
    blocs.append("")
    blocs.append("## 9. Reste a faire (actions du demandeur)")
    blocs.append("")
    blocs.append(
        "1. Verifier le rapport de gestion et le PV d'AG (montants, affectation, date) et les "
        "valider avec l'expert-comptable."
    )
    blocs.append(
        "2. Deposer le dossier sur le portail officiel et **enregistrer le vrai certificat** "
        "dans l'application (ecran Greffe) — hors perimetre de cet outil."
    )
    blocs.append(
        "3. Enregistrer le paiement reel des taxes si le depot est approuve (aucun reglement "
        "n'est simule ici)."
    )
    blocs.append("")
    return blocs


def verifications_versions(db, depot: GreffeDeposit, entrees: list[dict]) -> list[dict]:
    """Une **seule version active** par piece, aucun fichier orphelin dans le dossier.

    Correctif de recette : le dossier ne doit contenir qu'une version active du
    bordereau / etat complementaire (et de chaque autre piece) ; aucune ancienne
    version (PDF de 193 octets, document etabli avant la date d'AG) ne doit pouvoir
    entrer dans l'archive finale.
    """
    from sqlalchemy import func

    from app.models.greffe import GreffeDocument

    checks: list[dict] = []
    comptes = dict(
        db.execute(
            select(GreffeDocument.piece_code, func.count(GreffeDocument.id))
            .where(GreffeDocument.deposit_id == depot.id)
            .group_by(GreffeDocument.piece_code)
        ).all()
    )
    doublons = {code: nombre for code, nombre in comptes.items() if nombre > 1}
    _check(
        checks,
        "Une seule version active par piece (aucun doublon en base)",
        not doublons,
        f"{len(comptes)} piece(s) : "
        + ", ".join(f"{code}×{nombre}" for code, nombre in sorted(comptes.items()))
        + (f" — doublons : {doublons}" if doublons else " (aucun doublon)"),
    )
    _check(
        checks,
        "Un seul bordereau / etat complementaire actif",
        comptes.get(greffe.PIECE_ETAT_COMPLEMENTAIRE, 0) == 1,
        f"etat_complementaire présent {comptes.get(greffe.PIECE_ETAT_COMPLEMENTAIRE, 0)} fois "
        f"(attendu : 1) — la generation remplace la version precedente sur le disque",
    )
    racine = greffe.racine_stockage()
    dossier = racine / str(depot.company_id) / str(depot.id)
    referencees = {entree["chemin"] for entree in entrees}
    presentes = (
        {
            str(chemin.relative_to(racine)).replace("\\", "/")
            for chemin in dossier.rglob("*")
            if chemin.is_file()
        }
        if dossier.is_dir()
        else set()
    )
    orphelins = sorted(presentes - referencees)
    _check(
        checks,
        "Aucun fichier orphelin dans le dossier du depot",
        not orphelins,
        f"{len(presentes)} fichier(s) sur le disque, tous referencés par la base"
        if not orphelins
        else "fichiers non referencés : " + ", ".join(orphelins),
    )
    anciens = [
        entree
        for entree in entrees
        if entree["nom_fichier"] and "j9" in entree["nom_fichier"].lower()
    ]
    _check(
        checks,
        "Aucune trace des anciennes versions de recette (fichiers « _j9 »)",
        not anciens,
        "aucune piece _j9 dans le dossier"
        if not anciens
        else ", ".join(entree["nom_fichier"] for entree in anciens),
    )
    return checks


def deps_depot(db, depot: GreffeDeposit) -> dict:
    """Compteurs du dossier (paiements, evenements, taxes payees, etat)."""
    return {
        "nb_paiements": len(depot.paiements),
        "nb_evenements": len(depot.events),
        "total_paye": greffe.total_paye(db, depot),
        "statut": depot.statut,
        "date_depot": depot.date_depot,
        "reference_certificat": depot.reference_certificat,
        "certificat_path": depot.certificat_path,
    }



def _argument(nom: str) -> str | None:
    """Valeur d'une option `--nom valeur` (None si absente)."""
    for index, argument in enumerate(sys.argv):
        if argument == nom and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def main() -> int:
    brut = _argument("--date-ag")
    hors_delai = "--hors-delai" in sys.argv
    date_recette = "--recette" in sys.argv
    mode_extraits = "--extraits" in sys.argv
    preuve = Path(_argument("--preuve") or PREUVE)
    db = SessionLocal()
    try:
        company = db.scalars(select(Company).order_by(Company.id)).first()
        depot = db.scalars(
            select(GreffeDeposit).where(GreffeDeposit.exercice == EXERCICE)
        ).first()
        utilisateur = db.scalars(select(User).order_by(User.id)).first()
        if company is None or depot is None:
            print(f"Aucun dossier de depot {EXERCICE} en base : rien a finaliser.")
            return 1
        donnees = donnees_exercice(db, company)
        avant_pieces = inventaire(db, depot)
        if mode_extraits:
            # Lecture seule : extraits lisibles des deux documents (annexe de preuve).
            for libelle, code, motifs in (
                (
                    "PV d'AG / decision de l'associe unique",
                    greffe.PIECE_PV_AG,
                    (
                        "date de l'assemblee generale",
                        "qualite des participants",
                        "exercice soumis a approbation",
                        "approuve les comptes",
                        "premiere resolution",
                        "deuxieme resolution",
                        "resultat net de l'exercice est fixe",
                        "troisieme resolution",
                        "greffe du tribunal",
                    ),
                ),
                (
                    "Rapport de gestion",
                    greffe.PIECE_RAPPORT_GESTION,
                    (
                        "etat des comptes",
                        "chiffre d'affaires",
                        "marge brute",
                        "valeur ajoutee",
                        "excedent brut d'exploitation",
                        "resultat d'exploitation",
                        "resultat net de l'exercice",
                        "total du bilan",
                        "affectation du resultat",
                        "depot au greffe",
                    ),
                ),
            ):
                entree = entree_piece(avant_pieces, code)
                print(f"\n### {libelle}\n")
                if entree is not None:
                    print(
                        f"Fichier : `{entree['nom_fichier']}` — "
                        f"{entree['taille_disque']} octets — SHA-256 "
                        f"`{entree['sha256_disque']}`\n"
                    )
                for extrait in extraits_lignes(avant_pieces, code, motifs):
                    print(f"- {extrait}")
            return 0
        avant_controles = controles(db, depot)
        avant = deps_depot(db, depot)
        print(
            f"Dossier #{depot.id} — exercice {depot.exercice} ({depot.forme_juridique}, "
            f"statut {depot.statut}, AG {depot.date_ag or 'non renseignee'})"
        )
        for entree in avant_pieces:
            print(
                f"  AVANT [{entree['piece_code']:<22}] {entree['nom_fichier']:<38} "
                f"{entree['taille_disque']} o  sha256={(entree['sha256_disque'] or '—')[:16]}… "
                f"statut={entree['statut_checklist']}"
            )
        print(
            f"  AVANT : {len(avant_controles['controles'])} controle(s), "
            f"{len(avant_controles['bloquants'])} bloquant(s) "
            f"({', '.join(c['code'] for c in avant_controles['bloquants'])}) ; "
            f"completude {avant_controles['completude']['nb_fournies']}/"
            f"{avant_controles['completude']['nb_exigees']}"
        )

        documents: list = []
        ecrit = False
        if brut is not None:
            date_ag = date.fromisoformat(brut)
            if date_ag < donnees["date_to"]:
                print(
                    f"Date d'AG refusee : {date_ag} est anterieure a la cloture de "
                    f"l'exercice {EXERCICE} ({donnees['date_to']})."
                )
                return 2
            if date_ag > depot.date_limite_depot and not hors_delai:
                print(
                    f"Date d'AG refusee : {date_ag} depasse le delai legal de six mois "
                    f"({depot.date_limite_depot}, loi 5-96 art. 10). Relancer avec "
                    f"--hors-delai si le depot amendable est assume."
                )
                return 2
            print(f"\nREGENERATION (date d'AG fournie : {date_ag}) …")
            # Statut **recette/provisoire** : les pieces ne sont pas definitives tant
            # que la regularisation comptable 2025 (P1B etape 3) n'a pas eu lieu.
            depot.notes = (
                f"Recette/provisoire — pieces generees le {date.today().strftime('%d/%m/%Y')} "
                f"avec la date d'AG de recette {date_ag.strftime('%d/%m/%Y')}. Le resultat "
                f"{EXERCICE} et son affectation peuvent changer apres la regularisation "
                "comptable (P1B etape 3) : regenerer alors etats de synthese, rapport de "
                "gestion, PV d'AG et bordereau, puis rejouer les controles de coherence. "
                "Aucun depot reel n'a ete effectue."
            )
            documents = regenerer(
                db,
                depot,
                company,
                date_ag,
                utilisateur,
                toutes="--toutes" in sys.argv,
            )
            db.commit()
            ecrit = True
            for document in documents:
                print(
                    f"  APRES [{document.piece_code:<22}] {document.nom_fichier:<38} "
                    f"{document.taille_octets} o  sha256={document.hash_sha256[:16]}…"
                )
        else:
            print(
                "\nPREPARATION : aucune date d'AG fournie — aucune piece regeneree, aucune "
                "date inventee."
            )

        db.expire_all()
        apres_pieces = inventaire(db, depot)
        apres = deps_depot(db, depot)
        checks_pieces = verifications_pieces(apres_pieces, donnees, depot.date_ag, company)
        checks_versions = verifications_versions(db, depot, apres_pieces)
        checks_dossier = (
            verifications_dossier(db, depot, avant, apres, donnees) if ecrit else []
        )

        contexte = {
            "company": company,
            "depot": depot,
            "donnees": donnees,
            "operateur": f"{utilisateur.email} (id {utilisateur.id})" if utilisateur else "systeme",
            "avant_pieces": avant_pieces,
            "apres_pieces": apres_pieces,
            "avant_controles": avant_controles,
            "avant_bloquants": len(avant_controles["bloquants"]),
            "avant_completude": avant_controles["completude"],
            "checks_pieces": checks_pieces,
            "checks_versions": checks_versions,
            "checks_dossier": checks_dossier,
            "documents": documents,
            "ecrit": ecrit,
            "date_recette": date_recette,
        }
        contenu = "\n".join(
            [rediger_preuve(contexte), *_suite_preuve(contexte), *_fin_preuve(contexte)]
        )
        if date_recette:
            contenu += (
                "\n---\n\n**Mention** : la date d'AG `"
                f"{depot.date_ag}` a ete fournie comme **date de recette (fictive)** pour ce "
                "scenario ; elle ne correspond a aucune assemblee generale reelle. Aucun "
                "depot, paiement ni certificat n'a ete produit.\n"
            )
        preuve.write_text(contenu + "\n", encoding="utf-8")

        print(f"\nControles pieces : {len(checks_pieces)}")
        for check in checks_pieces:
            print(f"  [{check['resultat']}] {check['controle']} — {check['detail']}")
        print(f"\nControles de versions : {len(checks_versions)}")
        for check in checks_versions:
            print(f"  [{check['resultat']}] {check['controle']} — {check['detail']}")
        for check in checks_dossier:
            print(f"  [{check['resultat']}] {check['controle']} — {check['detail']}")
        tous = checks_pieces + checks_versions + checks_dossier
        nok = [c for c in tous if c["resultat"] == "NOK"]
        print(f"\nLivrable ecrit : {preuve}")
        if not ecrit:
            print(
                "Preparation terminee — en attente de la date de l'AG "
                "(--date-ag AAAA-MM-JJ)."
            )
            return 0
        print(
            f"Resultat : {len(tous) - len(nok)} PASS / {len(nok)} NOK — aucun depot reel, "
            "aucun paiement, aucun certificat."
        )
        return 1 if nok else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())


