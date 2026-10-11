"""Tests de l'assembleur de liasse fiscale EDI (P2.1 — etape 2).

Verifie le modele `liasse_tables` / `liasse_cells`, la lecture du **contrat des XSD
officiels** (tableaux, `codeEdi`, entete du modele), le **referentiel de codification**
(`rubrique` <-> `codeEdi`), l'alimentation depuis la **balance definitive**, les
**immobilisations (J2)**, les **stocks (J3)**, les **frais de personnel / DTS (J6)**,
l'**EFI assiste par tableau** et la **persistance** (registre `tax_declarations`).

Les codes utilises dans les jeux de test sont des **codes legaux du schema**
comptable simplifie : ils servent de **placeholders** — la semantique
`codeEdi` <-> rubrique reste du ressort du referentiel valide par
l'expert-comptable (ambiguite **A22**, annexe DGI non fournie).
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import get_or_create_fiscal_year
from app.models import AuditLog
from app.services import liasse_edi
from app.services.accounting import create_entry, get_journal

pytestmark = pytest.mark.usefixtures("ctx")

ANNEE = 2026
MODELE = liasse_edi.MODELE_COMPTABLE_SIMPLIFIE
# Codes legaux du modele « comptable simplifie » utilises comme placeholders de test.
CODE_PASSIF = "4562"
CODE_ACTIF = "17929"
CODE_IMMO = "10061"
CODE_PERSONNEL = "14068"
CODE_EXTRA = "15005"


def _ecriture(db, ctx, lignes: list[dict], *, jour: date, label: str, journal: str = "OD"):
    """Passe une ecriture validee (journaux standards du dossier)."""
    exercice = get_or_create_fiscal_year(db, ctx["company"], jour.year)
    ecriture = create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=exercice,
        journal=get_journal(db, ctx["company"].id, journal),
        entry_date=jour,
        label=label,
        lines=lignes,
        validate=True,
    )
    db.commit()
    return ecriture


def _socle(db, ctx):
    """Exercice type : capital 100 000, vente 120 000 TTC, achat 40 000, IS 10 000."""
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "5141", "debit": "100000", "label": "Banque"},
            {"account_number": "1111", "credit": "100000", "label": "Capital social"},
        ],
        jour=date(ANNEE, 1, 5),
        label="Constitution du capital",
    )
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "3421", "debit": "120000", "label": "Client"},
            {"account_number": "7111", "credit": "100000", "label": "Ventes"},
            {"account_number": "4455", "credit": "20000", "label": "TVA collectée"},
        ],
        jour=date(ANNEE, 2, 10),
        label="Facture de vente",
        journal="VE",
    )
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6111", "debit": "40000", "label": "Achats"},
            {"account_number": "4411", "credit": "40000", "label": "Fournisseur"},
        ],
        jour=date(ANNEE, 3, 5),
        label="Facture d'achat",
        journal="AC",
    )
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6701", "debit": "10000", "label": "IS"},
            {"account_number": "4411", "credit": "10000", "label": "État"},
        ],
        jour=date(ANNEE, 12, 31),
        label="Impôt sur les bénéfices",
    )


def _cloturer(db, ctx, annee: int = ANNEE):
    """Cloture l'exercice (condition du depot IS / liasse, P1.6)."""
    exercice = get_or_create_fiscal_year(db, ctx["company"], annee)
    exercice.status = "closed"
    db.commit()
    return exercice


def _ligne(tableau_id: int, code_edi: str, rubrique: str, **extra) -> dict:
    """Ligne de referentiel de codification (jeu de test)."""
    return {
        "modele": extra.pop("modele", MODELE),
        "tableau_id": tableau_id,
        "tableau_libelle": extra.pop("tableau_libelle", None),
        "code_edi": code_edi,
        "rubrique": rubrique,
        "libelle": extra.pop("libelle", None),
        "numero_ligne": extra.pop("numero_ligne", None),
        "extra_field": extra.pop("extra_field", None),
        "origine": extra.pop("origine", "référentiel de test (J7 étape 2)"),
    }


def _codification_reference() -> list[dict]:
    """Referentiel de test : balance, actif/passif, immobilisations, personnel."""
    return [
        _ligne(61, CODE_PASSIF, "solde:1111", tableau_libelle="Passif", libelle="Capital"),
        _ligne(61, CODE_EXTRA, "solde:4411", extra_field="70", numero_ligne=2),
        _ligne(7, CODE_ACTIF, "solde:3421", tableau_libelle="Actif", libelle="Clients"),
        _ligne(23, CODE_IMMO, "immo:brut", tableau_libelle="Immobilisations", numero_ligne=1),
        _ligne(36, CODE_PERSONNEL, "personnel:brut_imposable", tableau_libelle="Personnel"),
    ]


# ---------------------------------------------------------------------------
# Contrat des schemas officiels (XSD) et referentiel de codification
# ---------------------------------------------------------------------------
def test_contrat_modele_simplifie_lu_dans_le_xsd():
    """Le contrat (tableaux, codes, entete) est lu dans le XSD officiel."""
    contrat = liasse_edi.contrat_modele("comptable simplifié")
    assert contrat["racine"] == "Liasse"
    assert contrat["modele_id"] == 7  # modele id fixe par le schema Simpl-IS
    assert len(contrat["tableaux"]) == 24
    assert 61 in contrat["tableaux"] and 7 in contrat["tableaux"]
    assert len(contrat["codes"]) == 1328
    assert {CODE_PASSIF, CODE_ACTIF, CODE_IMMO, CODE_PERSONNEL, CODE_EXTRA} <= (
        contrat["codes_ensemble"]
    )
    assert contrat["type_valeur"] == "xs:string"
    assert contrat["type_numero_ligne"] == "xs:int"
    assert len(contrat["extra_fields"]) == 11
    assert Path(contrat["fichier"]).is_file()


def test_contrat_modele_aliases_et_modele_inconnu():
    """Les noms usuels sont acceptes ; un modele inconnu est refuse."""
    assert liasse_edi.resoudre_modele("liasse_modele_normal") == liasse_edi.MODELE_NORMAL
    assert liasse_edi.resoudre_modele(" SIMPLIFIÉ ") == MODELE
    assert (
        liasse_edi.resoudre_modele("établissements de crédit")
        == liasse_edi.MODELE_ETABLISSEMENTS_CREDIT
    )
    with pytest.raises(liasse_edi.LiasseError):
        liasse_edi.contrat_modele("modele-inexistant")


def test_xsds_disponibles_dans_le_projet():
    """Les quatre schemas officiels sont installes dans le projet."""
    modeles = liasse_edi.xsds_disponibles()
    assert len(modeles) == 4
    assert set(modeles) == set(liasse_edi.MODELES_LIASSE)
    assert liasse_edi.xsds_disponibles(xsd_dir=Path("/dossier/inexistant")) == []


def test_referentiel_livre_est_documente_et_conforme():
    """Le referentiel versionne part de la seule correspondance documentee (CC EDI)."""
    lignes = liasse_edi.charger_codification()
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["modele"] == liasse_edi.MODELE_NORMAL
    assert (ligne["tableau_id"], ligne["code_edi"]) == (1, "13400")
    assert liasse_edi.rubrique_documentee(ligne["rubrique"]) is True
    contrat = liasse_edi.contrat_modele(liasse_edi.MODELE_NORMAL)
    assert "13400" in contrat["codes_ensemble"]
    assert 1 in contrat["tableaux"]
    # Aucune ligne pour le modele PME : l'annexe DGI n'est pas fournie (A22).
    assert liasse_edi.charger_codification(modele=MODELE) == []


def test_charger_codification_refuse_un_referentiel_invalide(tmp_path):
    """Colonnes manquantes, montants vides ou tableau non numerique sont refuses."""
    sans_colonnes = tmp_path / "sans_colonnes.csv"
    sans_colonnes.write_text("modele,tableau_id\nx,1\n", encoding="utf-8")
    with pytest.raises(liasse_edi.LiasseError):
        liasse_edi.charger_codification(chemin=sans_colonnes)

    code_vide = tmp_path / "code_vide.csv"
    code_vide.write_text(
        ",".join(liasse_edi.COLONNES_CODIFICATION) + f"\n{MODELE},61,Passif,,solde:1111\n",
        encoding="utf-8",
    )
    with pytest.raises(liasse_edi.LiasseError):
        liasse_edi.charger_codification(chemin=code_vide)

    tableau_invalide = tmp_path / "tableau_invalide.csv"
    with tableau_invalide.open("w", encoding="utf-8", newline="") as flux:
        writer = csv.writer(flux, lineterminator="\r\n")
        writer.writerow(liasse_edi.COLONNES_CODIFICATION)
        writer.writerow([MODELE, "soixante", "Passif", CODE_PASSIF, "solde:1111", "", "", "", ""])
    with pytest.raises(liasse_edi.LiasseError):
        liasse_edi.charger_codification(chemin=tableau_invalide)

    fichier_absent = tmp_path / "absent.csv"
    with pytest.raises(liasse_edi.LiasseError):
        liasse_edi.charger_codification(chemin=fichier_absent)


# ---------------------------------------------------------------------------
# Rubriques alimentees par l'application
# ---------------------------------------------------------------------------
def test_rubriques_liasse_balance_et_resultat_fiscal(db, ctx):
    """Soldes, cumuls et resultat fiscal sont mobilisables par le referentiel."""
    _socle(db, ctx)
    valeurs = liasse_edi.rubriques_liasse(db, ctx["company"], ANNEE)
    rubriques = valeurs["rubriques"]
    # Convention de la balance generale : solde = debit - credit
    assert rubriques["solde:1111"]["valeur"] == Decimal("-100000.00")
    assert rubriques["solde:1111"]["libelle"] == "Capital social"
    assert rubriques["solde:3421"]["valeur"] == Decimal("120000.00")
    assert rubriques["racine:44"]["valeur"] == Decimal("-70000.00")
    assert rubriques["classe:6"]["valeur"] == Decimal("50000.00")
    assert rubriques["classe:7"]["valeur"] == Decimal("-100000.00")
    # Resultat fiscal de l'etape 1 (J7) : charges 50 000 (6111 40 000 + IS 10 000),
    # resultat comptable 50 000, retraite hors IS -> 60 000, aucune reintegration ici
    assert rubriques["resultat_avant_impot"]["valeur"] == Decimal("60000.00")
    assert rubriques["resultat_fiscal"]["valeur"] == Decimal("60000.00")
    assert rubriques["is_theorique"]["valeur"] == Decimal("12000.00")
    assert rubriques["impot_du"]["valeur"] == Decimal("12000.00")
    assert rubriques["immo:brut"]["valeur"] == Decimal("0.00")
    assert rubriques["stock:valeur"]["valeur"] == Decimal("0.00")
    assert "balance 2026" in rubriques["solde:3421"]["source"]


def test_rubriques_liasse_signale_les_sources_indisponibles(db, ctx):
    """Sans bulletin de paie, la source DTS est signalee et non fatale."""
    _socle(db, ctx)
    valeurs = liasse_edi.rubriques_liasse(db, ctx["company"], ANNEE)
    sources = {item["source"] for item in valeurs["indisponibles"]}
    assert "personnel / DTS (J6)" in sources
    assert not any(cle.startswith("personnel:") for cle in valeurs["rubriques"])


# ---------------------------------------------------------------------------
# Assembleur
# ---------------------------------------------------------------------------
def test_construire_liasse_alimente_depuis_la_balance(db, ctx):
    """Les cellules du referentiel sont remplies par la balance definitive."""
    _socle(db, ctx)
    liasse = liasse_edi.construire_liasse(
        db, ctx["company"], ANNEE, codification=_codification_reference()
    )
    assert liasse["modele"] == MODELE
    assert liasse["modele_id"] == 7
    assert liasse["racine"] == "Liasse"
    assert liasse["entete"]["identifiantFiscal"] == ctx["company"].fiscal_id
    assert liasse["entete"]["exerciceFiscalDu"] == "2026-01-01"
    assert liasse["entete"]["exerciceFiscalAu"] == "2026-12-31"
    assert liasse["nb_tableaux"] == 4
    assert liasse["nb_cellules"] == 4
    tableau_passif = next(t for t in liasse["tableaux"] if t["tableau_id"] == 61)
    assert tableau_passif["libelle"] == "Passif"
    capital = next(c for c in tableau_passif["cellules"] if c["code_edi"] == CODE_PASSIF)
    assert capital["valeur"] == "-100000.00"
    assert capital["valeur_numerique"] == Decimal("-100000.00")
    assert capital["libelle"] == "Capital"
    assert "balance 2026 — solde du compte 1111" in capital["source"]
    assert capital["source"].endswith("référentiel de test (J7 étape 2)")
    # Aucune cellule hors schema et aucun ecart : la liasse est exploitable
    assert liasse["cellules_hors_schema"] == []
    assert liasse["cellules_rubrique_inconnue"] == []
    assert liasse["total_numerique"] == Decimal("-30000.00")


def test_numero_ligne_et_extra_field_conserves(db, ctx):
    """`numeroLigne` et `extraField` du referentiel sont reportes tels quels."""
    _socle(db, ctx)
    liasse = liasse_edi.construire_liasse(
        db, ctx["company"], ANNEE, codification=_codification_reference()
    )
    tableau_passif = next(t for t in liasse["tableaux"] if t["tableau_id"] == 61)
    ligne = next(c for c in tableau_passif["cellules"] if c["code_edi"] == CODE_EXTRA)
    assert ligne["numero_ligne"] == 2
    assert ligne["extra_field"] == "70"
    assert ligne["valeur_numerique"] == Decimal("-50000.00")
    # Les `extraField` du schema sont lus dans le XSD
    contrat = liasse_edi.contrat_modele(MODELE)
    assert ligne["extra_field"] in contrat["extra_fields"]


def test_cellule_sans_valeur_est_signalee_mais_non_bloquante(db, ctx):
    """Une rubrique du catalogue dont la source est absente reste a completer."""
    _socle(db, ctx)
    liasse = liasse_edi.construire_liasse(
        db, ctx["company"], ANNEE, codification=_codification_reference()
    )
    assert liasse["cellules_sans_valeur"] == [
        {"tableau_id": 36, "code_edi": CODE_PERSONNEL, "rubrique": "personnel:brut_imposable"}
    ]
    code_controles = {
        controle["code"]: controle
        for controle in liasse_edi.controles_liasse(db, ctx["company"], ANNEE, liasse)
    }
    assert code_controles["liasse.rubrique_sans_valeur"]["niveau"] == "avertissement"
    assert code_controles["liasse.recap"]["niveau"] == "information"
    assert "1328 codes" in code_controles["liasse.recap"]["message"]


def _liasse(db, ctx, **extra) -> dict:
    """Liasse de test construite avec le referentiel de reference."""
    return liasse_edi.construire_liasse(
        db,
        ctx["company"],
        ANNEE,
        codification=extra.pop("codification", _codification_reference()),
        **extra,
    )


def _controles(db, ctx, liasse) -> dict:
    """Controles de la liasse, indexes par code."""
    return {
        controle["code"]: controle
        for controle in liasse_edi.controles_liasse(db, ctx["company"], ANNEE, liasse)
    }


def test_code_hors_schema_est_bloquant(db, ctx):
    """Un `codeEdi` absent de l'enumeration du XSD interdit le depot."""
    _socle(db, ctx)
    liasse = _liasse(
        db, ctx, codification=_codification_reference() + [_ligne(61, "999999", "solde:1111")]
    )
    assert [item["code_edi"] for item in liasse["cellules_hors_schema"]] == ["999999"]
    assert "absent de l'énumération" in liasse["cellules_hors_schema"][0]["motif"]
    controles = _controles(db, ctx, liasse)
    assert controles["liasse.code_hors_schema"]["niveau"] == "bloquant"
    assert "999999" in controles["liasse.code_hors_schema"]["message"]


def test_tableau_hors_schema_est_bloquant(db, ctx):
    """Un `tableau/id` absent de l'enumeration du XSD interdit le depot."""
    _socle(db, ctx)
    liasse = _liasse(
        db,
        ctx,
        codification=[
            _ligne(999, CODE_PASSIF, "solde:1111", tableau_libelle="Tableau inconnu")
        ],
    )
    assert liasse["cellules_hors_schema"] == [
        {
            "tableau_id": 999,
            "code_edi": None,
            "motif": "tableau absent de l'énumération du schéma",
        }
    ]
    assert _controles(db, ctx, liasse)["liasse.code_hors_schema"]["niveau"] == "bloquant"


def test_rubrique_inconnue_est_bloquante(db, ctx):
    """Une rubrique hors catalogue (faute de frappe) n'est jamais devinee."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx, codification=[_ligne(61, CODE_PASSIF, "sold:1111")])
    assert liasse["nb_cellules"] == 0
    assert liasse["cellules_rubrique_inconnue"] == [
        {"tableau_id": 61, "code_edi": CODE_PASSIF, "rubrique": "sold:1111"}
    ]
    controles = _controles(db, ctx, liasse)
    assert controles["liasse.rubrique_inconnue"]["niveau"] == "bloquant"
    assert controles["liasse.codification_absente"]["niveau"] == "avertissement"
    assert "A22" in controles["liasse.codification_absente"]["message"]


def test_signe_inverse_et_reconciliation_balance(db, ctx):
    """`-solde:<compte>` inverse le signe et reste rapproche de la balance."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx, codification=[_ligne(61, CODE_EXTRA, "-solde:4455")])
    cellule = liasse["tableaux"][0]["cellules"][0]
    assert cellule["valeur"] == "20000.00"
    assert cellule["valeur_numerique"] == Decimal("20000.00")
    reconciliation = liasse_edi.reconciliation_liasse_balance(
        db, ctx["company"].id, ANNEE, liasse
    )
    assert reconciliation["nb_rapprochements"] == 1
    assert reconciliation["conforme"] is True


def test_schema_absent_bloque_le_edi_mais_pas_l_efi(db, ctx, tmp_path):
    """Sans XSD, les valeurs restent produites et l'EFI assiste reste utilisable."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx, xsd_dir=tmp_path)
    assert liasse["contrat"] is None
    assert liasse["modele_id"] is None
    assert liasse["nb_cellules"] == 4  # aucune valeur perdue
    controles = _controles(db, ctx, liasse)
    assert controles["liasse.schema_absent"]["niveau"] == "bloquant"
    assert "EFI" in controles["liasse.schema_absent"]["message"]
    assert len(liasse_edi.etat_de_saisie_efi_liasse(liasse)) == 4


def test_controles_exercice_non_clos_puis_cloture(db, ctx):
    """P1.6 : le depot de la liasse exige un exercice clos."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx)
    controles = _controles(db, ctx, liasse)
    assert controles["fiscal.exercice_non_clos"]["niveau"] == "bloquant"
    assert liasse_edi.controles_bloquants(list(controles.values()))
    _cloturer(db, ctx)
    controles = _controles(db, ctx, liasse)
    assert "fiscal.exercice_non_clos" not in controles
    assert liasse_edi.controles_bloquants(list(controles.values())) == []


def test_reconciliation_liasse_balance_detecte_un_ecart(db, ctx):
    """Une valeur fige e hors balance est detectee (Σ liasses ≠ balance)."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx)
    reconciliation = liasse_edi.reconciliation_liasse_balance(
        db, ctx["company"].id, ANNEE, liasse
    )
    assert reconciliation["nb_rapprochements"] == 3
    assert reconciliation["conforme"] is True
    assert reconciliation["ecarts"] == []

    cellule_capital = next(
        cellule
        for tableau in liasse["tableaux"]
        for cellule in tableau["cellules"]
        if cellule["rubrique"] == "solde:1111"
    )
    cellule_capital["valeur_numerique"] = Decimal("1234.00")
    reconciliation = liasse_edi.reconciliation_liasse_balance(
        db, ctx["company"].id, ANNEE, liasse
    )
    assert reconciliation["conforme"] is False
    assert reconciliation["ecarts"][0]["compte"] == "1111"
    controle = _controles(db, ctx, liasse)["liasse.reconciliation_balance"]
    assert controle["niveau"] == "bloquant"
    assert "1111" in controle["message"]


# ---------------------------------------------------------------------------
# EFI assiste par tableau
# ---------------------------------------------------------------------------
def test_etat_de_saisie_efi_par_tableau_et_csv(db, ctx):
    """L'EFI presente une feuille par tableau, avec `codeEdi` et valeur."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx)
    feuilles = liasse_edi.etat_de_saisie_efi_liasse(liasse)
    assert [feuille["tableau_id"] for feuille in feuilles] == [7, 23, 36, 61]
    passif = next(f for f in feuilles if f["tableau_id"] == 61)
    assert passif["onglet"] == "Tableau 61"
    assert passif["nb_lignes"] == 2
    assert passif["nb_a_completer"] == 0
    assert passif["lignes"][0]["etat"] == "valeur"
    assert passif["lignes"][0]["libelle"] == "Capital"
    personnel = next(f for f in feuilles if f["tableau_id"] == 36)
    assert personnel["nb_a_completer"] == 1
    assert personnel["lignes"][0]["valeur"] is None
    assert personnel["lignes"][0]["etat"] == "a_completer"

    csv_bytes = liasse_edi.efi_liasse_csv(liasse)
    assert csv_bytes.startswith(b"\xef\xbb\xbf")  # BOM : lisible par Excel
    texte = csv_bytes.decode("utf-8-sig")
    lignes = texte.splitlines()
    assert lignes[0].startswith("modele;tableau_id;tableau_libelle;code_edi")
    assert any(CODE_PERSONNEL in ligne and "a_completer" in ligne for ligne in lignes)
    assert any(f"{CODE_PASSIF};Capital;-100000.00" in ligne for ligne in lignes)


# ---------------------------------------------------------------------------
# Persistance : liasse_tables / liasse_cells + registre des declarations
# ---------------------------------------------------------------------------
def test_enregistrer_liasse_persiste_cellules_et_registre(db, ctx):
    """Les tableaux, cellules et la declaration LIASSE sont enregistres."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx)
    declaration = liasse_edi.enregistrer_liasse(
        db, ctx["company"], liasse, user_id=ctx["user"].id
    )
    db.commit()
    assert declaration.type == "LIASSE"
    assert declaration.periode == "2026"
    assert declaration.regime == MODELE
    assert declaration.statut == "brouillon"
    assert declaration.mode_depot == "EFI"
    assert declaration.nb_lignes == 4
    assert declaration.montant == Decimal("12000.00")  # impôt dû (étape 1)
    assert "4 cellule(s)" in (declaration.notes or "")

    relue = liasse_edi.liasse_enregistree(db, ctx["company"].id, ANNEE)
    assert relue["declaration"].id == declaration.id
    assert relue["nb_tableaux"] == 4
    assert relue["nb_cellules"] == 4
    assert [tableau["tableau_id"] for tableau in relue["tableaux"]] == [7, 23, 36, 61]
    tableau_passif = next(t for t in relue["tableaux"] if t["tableau_id"] == 61)
    assert tableau_passif["cellules"][0]["code_edi"] == CODE_PASSIF
    assert tableau_passif["cellules"][0]["valeur"] == "-100000.00"

    # Idempotence : rejouer la construction ne duplique rien
    liasse_edi.enregistrer_liasse(db, ctx["company"], liasse)
    db.commit()
    relue = liasse_edi.liasse_enregistree(db, ctx["company"].id, ANNEE)
    assert (relue["nb_tableaux"], relue["nb_cellules"]) == (4, 4)

    # Trace d'audit du module (LIASSE_RECORDED)
    journal = (
        db.execute(select(AuditLog).where(AuditLog.action == "LIASSE_RECORDED"))
        .scalars()
        .all()
    )
    assert len(journal) == 2
    assert journal[-1].entity == "TaxDeclaration"


def test_liasse_enregistree_absente_et_declaration_figee(db, ctx):
    """Une declaration déposée est figée ; sans dépôt, la lecture est vide."""
    assert liasse_edi.liasse_enregistree(db, ctx["company"].id, ANNEE)["declaration"] is None
    _socle(db, ctx)
    liasse = _liasse(db, ctx)
    declaration = liasse_edi.enregistrer_liasse(db, ctx["company"], liasse)
    declaration.statut = "soumise"
    db.commit()
    with pytest.raises(liasse_edi.LiasseError):
        liasse_edi.enregistrer_liasse(db, ctx["company"], liasse)


def test_exercice_absent_refuse_la_liasse(db, ctx):
    """Un exercice inconnu ne peut pas porter de liasse."""
    with pytest.raises(Exception):
        liasse_edi.construire_liasse(db, ctx["company"], 2019)


def test_referentiel_et_schemas_du_projet():
    """Les chemins par defaut pointent sur les referentiels installes."""
    assert settings.liasse_racine.is_dir()
    assert settings.liasse_codification.is_file()
    assert settings.liasse_codification.name == "codification_liasse.csv"


# ---------------------------------------------------------------------------
# Fichier XML EDI : structure du schema officiel et validation XSD reelle
# ---------------------------------------------------------------------------
def test_build_liasse_xml_structure_et_validation_xsd(db, ctx):
    """Le fichier suit la structure `Liasse` du schema et **passe le XSD**."""
    _socle(db, ctx)
    liasse = _liasse(db, ctx)
    xml = liasse_edi.build_liasse_xml(liasse)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<Liasse>" in xml
    assert "  <modele>\n    <id>7</id>\n  </modele>" in xml
    assert "<identifiantFiscal>1234567</identifiantFiscal>" in xml
    assert "<exerciceFiscalDu>2026-01-01</exerciceFiscalDu>" in xml
    assert "<exerciceFiscalAu>2026-12-31</exerciceFiscalAu>" in xml
    for balise in (
        "<groupeValeursTableau>",
        "<ValeursTableau>",
        "<tableau>\n        <id>61</id>",
        "<groupeValeurs>",
        "<ValeurCellule>",
        "<cellule>",
        f"<codeEdi>{CODE_PASSIF}</codeEdi>",
        "<valeur>-100000.00</valeur>",
        "<numeroLigne>2</numeroLigne>",
        "<extraFieldvaleurs>",
    ):
        assert balise in xml, balise
    assert "<valeur/>" not in xml
    assert xml.rstrip().endswith("</Liasse>")

    validation = liasse_edi.valider_xsd(xml, modele=MODELE)
    assert validation["valide"] is True, validation["message"]
    assert validation["erreurs"] == []
    assert validation["schema"].endswith("liasse_modele_comptable simplifié.xsd")
    assert liasse_edi.controle_taille(xml) == len(xml.encode("utf-8"))


def test_build_liasse_xml_omet_les_tableaux_sans_cellule(db, ctx):
    """Le schéma exige une cellule par tableau : les tableaux vides sont omis."""
    _socle(db, ctx)
    xml = liasse_edi.build_liasse_xml(_liasse(db, ctx))
    assert "<id>61</id>" in xml and "<id>7</id>" in xml
    assert "<id>36</id>" not in xml  # tableau « Personnel » sans valeur disponible
    assert liasse_edi.valider_xsd(xml, modele=MODELE)["valide"] is True


def test_build_liasse_xml_refuse_sans_cellule_ou_sans_schema(db, ctx, tmp_path):
    """Un document vide est refuse ; sans XSD, l'identifiant du modele est inconnu."""
    _socle(db, ctx)
    sans_cellule = _liasse(
        db, ctx, codification=[_ligne(36, CODE_PERSONNEL, "personnel:brut_imposable")]
    )
    with pytest.raises(liasse_edi.LiasseError) as erreur:
        liasse_edi.build_liasse_xml(sans_cellule)
    assert "au moins un tableau" in str(erreur.value)

    sans_schema = _liasse(db, ctx, xsd_dir=tmp_path)
    with pytest.raises(liasse_edi.LiasseError) as erreur:
        liasse_edi.build_liasse_xml(sans_schema)
    assert "XSD" in str(erreur.value)


def test_valider_xsd_refuse_les_ecarts_au_schema(db, ctx):
    """Code hors schéma, id de modèle invalide, XML illisible : refus explicites."""
    _socle(db, ctx)
    xml = liasse_edi.build_liasse_xml(_liasse(db, ctx))

    code_inconnu = xml.replace(CODE_PASSIF, "999999")
    validation = liasse_edi.valider_xsd(code_inconnu, modele=MODELE)
    assert validation["valide"] is False
    assert validation["erreurs"]
    assert "999999" in validation["message"]

    modele_invalide = xml.replace("    <id>7</id>", "    <id>9</id>")
    assert liasse_edi.valider_xsd(modele_invalide, modele=MODELE)["valide"] is False

    illisible = liasse_edi.valider_xsd("<Liasse>", modele=MODELE)
    assert illisible["valide"] is False
    assert "illisible" in illisible["message"]


def test_valider_xsd_schema_absent_ne_declare_pas_conforme(db, ctx, tmp_path):
    """Sans schéma, la validation est impossible : jamais « conforme »."""
    _socle(db, ctx)
    validation = liasse_edi.valider_xsd("<Liasse/>", modele=MODELE, xsd_dir=tmp_path)
    assert validation["valide"] is None
    assert "introuvable" in validation["message"]
    assert "conforme" in validation["message"]


def test_produire_liasse_xml_refuse_tant_qu_un_bloquant_subsiste(db, ctx):
    """Exercice ouvert : fichier refusé ; après clôture : produit et validé."""
    _socle(db, ctx)
    with pytest.raises(liasse_edi.LiasseError) as erreur:
        liasse_edi.produire_liasse_xml(
            db,
            ctx["company"],
            ANNEE,
            modele=MODELE,
            codification=_codification_reference(),
        )
    assert "fiscal.exercice_non_clos" in str(erreur.value)

    _cloturer(db, ctx)
    production = liasse_edi.produire_liasse_xml(
        db, ctx["company"], ANNEE, modele=MODELE, codification=_codification_reference()
    )
    assert production["validation"]["valide"] is True
    assert production["nom_fichier"] == "LIASSE_1234567_2026.xml"
    assert production["taille"] == len(production["xml"].encode("utf-8"))
    assert production["bloquants"] == []


def test_enregistrer_liasse_avec_fichier_hash_et_validation(db, ctx):
    """Le registre conserve le fichier produit (nom, taille, SHA-256, validation)."""
    _socle(db, ctx)
    _cloturer(db, ctx)
    production = liasse_edi.produire_liasse_xml(
        db, ctx["company"], ANNEE, modele=MODELE, codification=_codification_reference()
    )
    declaration = liasse_edi.enregistrer_liasse(
        db,
        ctx["company"],
        production["liasse"],
        mode_depot="EDI",
        xml=production["xml"],
        validation=production["validation"],
        user_id=ctx["user"].id,
    )
    db.commit()
    assert declaration.mode_depot == "EDI"
    assert declaration.fichier_nom == "LIASSE_1234567_2026.xml"
    assert declaration.fichier_taille == production["taille"]
    assert len(declaration.fichier_hash or "") == 64  # empreinte SHA-256
    assert "conforme au schéma XSD" in (declaration.notes or "")
    assert declaration.montant == Decimal("12000.00")


def test_soumettre_declaration_depot_rejet_puis_figeage(db, ctx):
    """Dépôt, rejet motivé, puis déclaration figée (aucun nouveau dépôt)."""
    _socle(db, ctx)
    declaration = liasse_edi.enregistrer_liasse(
        db, ctx["company"], _liasse(db, ctx), user_id=ctx["user"].id
    )
    depot = liasse_edi.soumettre_declaration(
        db, declaration, jour=date(2026, 4, 1), user_id=ctx["user"].id
    )
    assert depot.statut == "soumise"
    assert depot.soumise_le == date(2026, 4, 1)
    depot = liasse_edi.soumettre_declaration(
        db, declaration, motif_rejet="tableau 61 incohérent", user_id=ctx["user"].id
    )
    db.commit()
    assert depot.statut == "rejetee"
    assert depot.motif_rejet == "tableau 61 incohérent"
    with pytest.raises(liasse_edi.LiasseError):
        liasse_edi.soumettre_declaration(db, declaration, accuse_le=date(2026, 5, 1))


def test_soumettre_declaration_accuse_de_reception_accepte(db, ctx):
    """L'accusé de réception de la DGI rend la déclaration acceptée."""
    _socle(db, ctx)
    declaration = liasse_edi.enregistrer_liasse(db, ctx["company"], _liasse(db, ctx))
    liasse_edi.soumettre_declaration(db, declaration, jour=date(2026, 4, 1))
    liasse_edi.soumettre_declaration(db, declaration, accuse_le=date(2026, 4, 9))
    db.commit()
    assert declaration.statut == "acceptee"
    assert declaration.accuse_le == date(2026, 4, 9)
    assert declaration.soumise_le == date(2026, 4, 1)
    journal = (
        db.execute(select(AuditLog).where(AuditLog.action == "LIASSE_SUBMITTED"))
        .scalars()
        .all()
    )
    assert len(journal) == 2


def test_dossier_liasse_et_registre(db, ctx):
    """Le dossier de liasse agrege calcul fiscal, liasse, EFI et registre."""
    _socle(db, ctx)
    liasse_edi.enregistrer_liasse(db, ctx["company"], _liasse(db, ctx))
    db.commit()
    dossier = liasse_edi.dossier_liasse(
        db, ctx["company"], ANNEE, modele=MODELE, codification=_codification_reference()
    )
    assert set(dossier) >= {
        "annee",
        "modele",
        "liasse",
        "controles",
        "bloquants",
        "fiscal",
        "efi",
        "declarations",
        "declaration",
        "reconciliation",
    }
    assert dossier["fiscal"]["calcul"]["is_theorique"] == Decimal("12000.00")
    assert dossier["reconciliation"]["conforme"] is True
    assert [declaration.periode for declaration in dossier["declarations"]] == ["2026"]
    assert dossier["declaration"].regime == MODELE
    assert [feuille["tableau_id"] for feuille in dossier["efi"]] == [7, 23, 36, 61]