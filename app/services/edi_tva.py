"""Export EDI du releve des deductions de TVA (téléservice Simpl-TVA / DGI).

Format produit conformement a l'annexe « Correspondance des balises RD »
(V4.0) du cahier des charges EDI du releve des deductions de la TVA :

    <DeclarationReleveDeduction>
      <identifiantFiscal>…</identifiantFiscal>
      <annee>…</annee>
      <periode>1..12 (mensuel) ou 1..4 (trimestriel)</periode>
      <regime>1 mensuel | 2 trimestriel | 3 cessation temporaire | 4 cession-cessation</regime>
      <releveDeductions>
        <rd>
          <ord>1</ord><num>…</num><des>…</des>
          <mht>0.00</mht><tva>0.00</tva><ttc>0.00</ttc>
          <refF><if>…</if><nom>…</nom><ice>…</ice></refF>
          <tx>20</tx><prorata>90</prorata>   (pourcentage ; balise optionnelle)
          <mp><id>1..7</id></mp><dpai>AAAA-MM-JJ</dpai><dfac>AAAA-MM-JJ</dfac>
        </rd>
      </releveDeductions>
    </DeclarationReleveDeduction>

Regles appliquees (issues du cahier des charges EDI) :
- un seul fichier XML par periode, de moins de 1 Mo ;
- decimaux avec le point comme separateur ;
- dates au format AAAA-MM-JJ ;
- les lignes a TVA nulle ne sont pas reprises dans le releve des deductions
  (elles le sont dans la declaration principale) ;
- un avoir vient en deduction negative ;
- periode rattachee en priorite a la DATE DE PAIEMENT : le modele officiel DGI
  (« ADC082F-15I », art. 112 du CGI) intitule la colonne du regime
  « REGIME(Encais-1) » et chaque ligne porte <dpai> et <dfac> ; en regime de
  l'encaissement la deduction s'exerce au paiement. La base peut etre basculee
  sur la date de facture (`base_periode=BASE_PERIODE_FACTURE`) ;
- identifiant fiscal (declarant et fournisseur) : **7 ou 8 chiffres, tel quel**
  (aucune transformation, cf. `services/identifiers.py`) ;
- prorata de deduction (CGI art. 106) applique a la TVA deductible lorsqu'il est
  fourni ; la balise <prorata> reste **optionnelle** et s'ecrit en
  **pourcentage** (exemple officiel : `<prorata>70</prorata>`) ;
- limite de lignes **parametrable** (`settings.max_rd_lines`, defaut 127).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rates_ma import money
from app.models import (
    INVOICE_STATUS_CANCELLED,
    INVOICE_STATUS_DRAFT,
    PAYMENT_METHOD_CODES,
    Company,
    Invoice,
    Payment,
    ThirdParty,
)
from app.services.accounting import AccountingError
from app.services.identifiers import ICE_LENGTH, ComplianceError, normalize_fiscal_id

MAX_XML_BYTES = 1_000_000  # limite de la DGI au controle de format (niveau 1)
# Limite de lignes du releve : le schema officiel de la DGI (modele EDI
# « ADC082F-15I ») declare <ord> et <mp><id> en xs:byte (maximum 127), alors que
# l'annexe « balises RD » V4.0 les declare en « Entier ». La limite reelle reste
# donc a confirmer aupres de la DGI : elle est PARAMETRABLE
# (`settings.max_rd_lines`, surchargeable par l'argument `max_lignes`) et le
# defaut conserve est prudent (127).
MAX_RD_LINES = 127
LEGAL_VAT_RATES = (Decimal("20"), Decimal("14"), Decimal("10"), Decimal("7"), Decimal("0"))
TX_UNITS = ("percent", "ratio")

# Base de rattachement de la periode du releve.
# Le modele officiel de la DGI (« ADC082F-15I », art. 112 du CGI) intitule la
# colonne du regime « REGIME(Encais-1) » et chaque ligne du relevé porte a la
# fois <dpai> (date de paiement) et <dfac> (date de facture) : en regime de
# l'encaissement, la deduction s'exerce lors du paiement, la periode du releve
# est donc celle des paiements. La base « facture » reste disponible pour les
# controles et les cas particuliers.
BASE_PERIODE_PAIEMENT = "paiement"
BASE_PERIODE_FACTURE = "facture"
BASES_PERIODE = (BASE_PERIODE_PAIEMENT, BASE_PERIODE_FACTURE)
BASE_PERIODE_DEFAUT = BASE_PERIODE_PAIEMENT


from app.models.activity import (
    REGIME_TVA_CESSATION_TEMPORAIRE,
    REGIME_TVA_CESSION_CESSATION,
)


# Regimes de declaration d'activite (annexe 1 RD V4.0 : regimes 3 et 4, periode 1).
REGIMES_ACTIVITE = (REGIME_TVA_CESSATION_TEMPORAIRE, REGIME_TVA_CESSION_CESSATION)


class EdiTvaError(AccountingError):
    """Erreur bloquante empechant la production du fichier EDI."""


@dataclass
class RdLigne:
    """Une ligne du releve des deductions (une facture d'achat)."""

    ordre: int
    num: str
    designation: str
    mht: Decimal
    tva: Decimal
    ttc: Decimal
    if_fournisseur: str | None
    nom_fournisseur: str
    ice_fournisseur: str | None
    taux: Decimal
    prorata: Decimal
    mode_id: int
    date_paiement: date | None
    date_facture: date
    facture_id: int
    anomalies: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ordre": self.ordre,
            "num": self.num,
            "designation": self.designation,
            "mht": str(self.mht),
            "tva": str(self.tva),
            "ttc": str(self.ttc),
            "if_fournisseur": self.if_fournisseur,
            "nom_fournisseur": self.nom_fournisseur,
            "ice_fournisseur": self.ice_fournisseur,
            "taux": str(self.taux),
            "prorata": str(self.prorata),
            "mode_id": self.mode_id,
            "date_paiement": self.date_paiement.isoformat() if self.date_paiement else None,
            "date_facture": self.date_facture.isoformat(),
            "facture_id": self.facture_id,
            "anomalies": list(self.anomalies),
        }


# ---------------------------------------------------------------------------
# Aides de format
# ---------------------------------------------------------------------------
def _esc(value: object) -> str:
    """Echappe une valeur XML et supprime les caracteres de controle interdits."""
    texte = "" if value is None else str(value)
    texte = "".join(
        caractere
        for caractere in texte
        if caractere in ("\t", "\n", "\r") or ord(caractere) >= 32
    )
    return (
        texte.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _dec(value: Decimal | int | float | str | None) -> str:
    """Decimal au format EDI : point separateur, 2 decimales (ex. 10570.25)."""
    return f"{money(value or 0):.2f}"


def _date_iso(jour: date | None) -> str:
    """Date au format AAAA-MM-JJ (exigence de l'annexe RD)."""
    return jour.isoformat() if jour else ""


def regime_code(company: Company) -> int:
    """1 = mensuel, 2 = trimestriel (balise <regime>)."""
    return 1 if company.vat_regime == "mensuel" else 2


def taux_edi(taux: Decimal, tx_unit: str = "percent") -> str:
    """Valeur de la balise <tx> : 20 (pourcent, defaut) ou 0.20 (ratio).

    L'annexe precise seulement « Taux de la taxe — Décimal » : le choix est donc
    parametrable et doit etre confirme contre le XSD officiel.
    """
    if tx_unit not in TX_UNITS:
        raise EdiTvaError(f"Unite de taux inconnue : {tx_unit!r} (attendu : {TX_UNITS})")
    montant = Decimal(str(taux))
    return f"{montant:.2f}" if tx_unit == "ratio" else f"{montant.quantize(Decimal('1'))}"


def validate_period(regime: int, periode: int) -> None:
    """Controle de coherence regime / periode (cahier des charges §4).

    L'annexe 1 « correspondance balise RD V4.0 » ajoute les declarations de
    **cessation temporaire d'activite** (regime **3**) et de **cession ou cessation**
    (regime **4**), qui portent la **periode 1** (P2.2 — meme fichier EDI que le
    releve periodique, transmis avec la declaration de sortie).
    """
    if regime == 1 and not 1 <= periode <= 12:
        raise EdiTvaError("Regime mensuel : la periode doit etre comprise entre 1 et 12")
    if regime == 2 and not 1 <= periode <= 4:
        raise EdiTvaError("Regime trimestriel : la periode doit etre comprise entre 1 et 4")
    if regime in REGIMES_ACTIVITE and periode != 1:
        raise EdiTvaError(
            f"Regime {regime} (cessation ou cession d'activite) : la periode doit "
            "etre 1 (annexe 1 RD V4.0)."
        )


def verifier_lignes(lignes: list[RdLigne], *, tolerance: Decimal = Decimal("0.02")) -> list[dict]:
    """Controles **bloquants** de coherence interne des lignes du releve.

    Deux invariants doivent etre verifies pour **chaque** ligne avant toute
    generation de fichier (defaut constate en recette J9 : `<mht>` au montant de
    la facture alors que `<tva>` etait limitee a la fraction reglee) :

    1. ``TTC = base HT + TVA`` (identite comptable de la ligne) ;
    2. coherence taux / base : ``TVA = base HT x taux / 100 x prorata`` a
       l'arrondi pres (tolerance de 2 centimes, cumul des arrondis commerciaux).
       Le controle n'est applique que si la ligne porte **un seul taux**
       (``taux > 0``) : une facture multi-taux est signalee separement (une ligne
       EDI par facture).

    Retourne la liste des anomalies bloquantes (vide si tout est coherent).
    """
    anomalies: list[dict] = []
    for ligne in lignes:
        reference = ligne.num or f"#{ligne.facture_id or '?'}"
        attendu = money(ligne.mht + ligne.tva)
        if money(ligne.ttc) != attendu:
            anomalies.append(
                {
                    "reference": reference,
                    "motif": (
                        f"Incoherence bloquante : TTC {ligne.ttc} <> base HT {ligne.mht} "
                        f"+ TVA {ligne.tva} (= {attendu})"
                    ),
                    "bloquant": True,
                }
            )
        if ligne.taux and ligne.taux > 0:
            prorata = Decimal(str(ligne.prorata or 1))
            tva_theorique = money(ligne.mht * ligne.taux / Decimal("100") * prorata)
            if abs(money(ligne.tva) - tva_theorique) > tolerance:
                anomalies.append(
                    {
                        "reference": reference,
                        "motif": (
                            f"Incoherence bloquante taux/base : TVA {ligne.tva} <> "
                            f"{ligne.mht} x {ligne.taux} % x prorata {prorata} "
                            f"(= {tva_theorique})"
                        ),
                        "bloquant": True,
                    }
                )
    return anomalies


def xml_filename(annee: int, periode: int, regime: int) -> str:
    """Nom du fichier XML a deposer sur le portail EDI."""
    if regime == REGIME_TVA_CESSATION_TEMPORAIRE:
        return f"ReleveDeductions_{annee}_CessationTemporaire_1.xml"
    if regime == REGIME_TVA_CESSION_CESSATION:
        return f"ReleveDeductions_{annee}_CessionCessation_1.xml"
    return f"ReleveDeductions_{annee}_{'M' if regime == 1 else 'T'}{periode}.xml"


def limite_lignes(max_lignes: int | None = None) -> int:
    """Limite de lignes du releve : argument > `settings.max_rd_lines` > 127.

    Les documents de la DGI ne fixent pas la meme limite (<ord> en xs:byte dans le
    schema du modele officiel, « Entier » dans l'annexe V4.0) : la limite est donc
    parametrable, avec un defaut prudent, pour ne pas bloquer un depot legitime.
    """
    if max_lignes is not None:
        return int(max_lignes)
    return int(getattr(settings, "max_rd_lines", MAX_RD_LINES))


def _prorata_edi(fraction: Decimal) -> str:
    """Valeur de la balise <prorata> : POURCENTAGE, comme l'exemple officiel DGI.

    L'exemple officiel du releve des deductions porte ``<prorata>70</prorata>`` et
    ``<prorata>80</prorata>`` (et non 0.70 / 0.80). En interne,
    `collect_rd_lines` manipule une FRACTION (0.90) qui sert au calcul de la TVA
    deductible : la conversion en pourcentage est faite ici.
    """
    pourcentage = Decimal(str(fraction)) * Decimal("100")
    if pourcentage == pourcentage.to_integral_value():
        return str(int(pourcentage))
    return f"{pourcentage.normalize():f}"


# ---------------------------------------------------------------------------
# Collecte des lignes depuis la comptabilite
# ---------------------------------------------------------------------------
def collect_rd_lines(
    db: Session,
    company: Company,
    date_from: date,
    date_to: date,
    *,
    include_zero_vat: bool = False,
    prorata: Decimal = Decimal("1"),
    base_periode: str = BASE_PERIODE_DEFAUT,
) -> dict:
    """Prepare les lignes du releve des deductions (factures d'achat validees).

    - `base_periode` : "paiement" (defaut, regime de l'encaissement : la periode
      est celle des reglements) ou "facture" (periode des factures) ;
    - `prorata` : fraction de TVA deductible (CGI art. 106). 1 = deduction
      integrale ; la valeur est appliquee a la balise <tva> des lignes ;
    - `include_zero_vat` : reprendre les lignes a TVA nulle (controle interne).

    Retourne {"lignes", "anomalies", "exclues", "totaux", "base_periode",
    "prorata"}.
    """
    if base_periode not in BASES_PERIODE:
        raise EdiTvaError(
            f"Base de periode inconnue : {base_periode!r} (attendu : {BASES_PERIODE})"
        )
    taux_prorata = Decimal(str(prorata))
    if not Decimal("0") < taux_prorata <= Decimal("1"):
        raise EdiTvaError(
            "Prorata de deduction invalide : attendu entre 0 (exclu) et 1 "
            f"(recu : {taux_prorata})"
        )

    conditions = [
        Invoice.company_id == company.id,
        Invoice.invoice_type == "achat",
        Invoice.status.notin_((INVOICE_STATUS_DRAFT, INVOICE_STATUS_CANCELLED)),
    ]
    if base_periode == BASE_PERIODE_PAIEMENT:
        # Deduction exercee au paiement : factures dont un reglement tombe dans
        # la periode declaree, meme si la facture est anterieure.
        factures_reglees = (
            select(Payment.invoice_id)
            .where(
                Payment.company_id == company.id,
                Payment.invoice_id.is_not(None),
                Payment.payment_date >= date_from,
                Payment.payment_date <= date_to,
            )
            .distinct()
        )
        conditions.append(
            or_(
                Invoice.id.in_(factures_reglees),
                # Un avoir n'est pas « regle » : il reste rattache a sa date
                # (il ne doit jamais disparaitre du releve des deductions).
                and_(
                    Invoice.is_credit_note.is_(True),
                    Invoice.invoice_date >= date_from,
                    Invoice.invoice_date <= date_to,
                ),
            )
        )
    else:
        conditions.extend(
            (Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
        )
    factures = db.execute(
        select(Invoice)
        .where(*conditions)
        .order_by(Invoice.invoice_date, Invoice.id)
    ).scalars().all()

    partenaires = {
        tiers.id: tiers
        for tiers in db.execute(
            select(ThirdParty).where(ThirdParty.company_id == company.id)
        ).scalars().all()
    }
    reglements: dict[int, list[Payment]] = {}
    for paiement in db.execute(
        select(Payment).where(Payment.company_id == company.id).order_by(Payment.payment_date)
    ).scalars().all():
        reglements.setdefault(paiement.invoice_id or 0, []).append(paiement)

    lignes: list[RdLigne] = []
    anomalies: list[dict] = []
    exclues: list[dict] = []

    def signaler(reference: str, motif: str, bloquant: bool = True) -> None:
        anomalies.append({"reference": reference, "motif": motif, "bloquant": bloquant})

    for facture in factures:
        tiers = partenaires.get(facture.partner_id)
        reference = facture.reference or f"facture #{facture.id}"
        signe = Decimal("-1") if facture.is_credit_note else Decimal("1")
        paiements = reglements.get(facture.id, [])

        taux_liste = sorted({ligne.vat_rate for ligne in facture.lines})
        taux = taux_liste[0] if len(taux_liste) == 1 else Decimal("0")
        if len(taux_liste) > 1:
            signaler(
                reference,
                "Plusieurs taux de TVA sur la meme facture : une seule ligne EDI "
                "par facture, taux de la premiere ligne retenu",
                bloquant=False,
            )
        if any(t not in LEGAL_VAT_RATES for t in taux_liste):
            signaler(reference, f"Taux de TVA hors bareme legal : {[str(t) for t in taux_liste]}")

        if tiers is None:
            signaler(reference, "Fournisseur introuvable dans le dossier")
            continue
        if not tiers.ice:
            signaler(
                reference,
                f"ICE du fournisseur {tiers.name} manquant (obligatoire dans le releve)",
            )
        elif not (tiers.ice.isdigit() and len(tiers.ice) == ICE_LENGTH):
            signaler(reference, f"ICE du fournisseur {tiers.name} invalide : « {tiers.ice} »")
        if not tiers.fiscal_id:
            signaler(reference, f"Identifiant fiscal (IF) du fournisseur {tiers.name} manquant")

        if not paiements:
            signaler(
                reference,
                "Aucun reglement enregistre : la date de paiement (balise <dpai>) sera vide",
                bloquant=False,
            )
        elif facture.remaining_amount > 0:
            signaler(
                reference,
                f"Facture partiellement reglee (reste {money(facture.remaining_amount)})",
                bloquant=False,
            )
        if not facture.number:
            signaler(reference, "Facture sans numero interne (document non valide ?)")

        mht = money(facture.total_ht * signe)
        # Base et TVA de la facture (signees) : elles servent aux controles
        # ci-dessous, puis au calcul de la **base eligible** de la periode.
        tva_facture = money(facture.total_vat * signe)
        tva = tva_facture
        mht_facture = mht
        if tva == 0 and not include_zero_vat:
            # TVA nulle (exonere) : hors relevé des déductions, mais tracée.
            exclues.append(
                {
                    "reference": reference,
                    "motif": "TVA nulle (exonere) : hors releve des deductions",
                    "mht": str(mht),
                }
            )
            continue
        if tva < 0:
            # Avoir fournisseur : il vient en deduction negative (jamais exclu).
            signaler(
                reference,
                "Avoir fournisseur : ligne reprise en deduction negative",
                bloquant=False,
            )

        if base_periode == BASE_PERIODE_PAIEMENT and not facture.is_credit_note:
            # Regime de l'encaissement : la deduction suit le reglement. La base
            # eligible et la TVA deductible sont **la meme fraction** du montant
            # de la facture :
            #
            #     base = HT x (cumul regle fin de periode - cumul regle avant)
            #     TVA  = TVA x (cumul regle fin de periode - cumul regle avant)
            #
            # Le calcul est fonde sur des **cumuls** plafonnes au TTC : les
            # montants se telescopent donc exactement sur la duree de vie de la
            # facture (aucune perte ni double emploi d'arrondi), et la ligne
            # reste coherente : TVA = base x taux / 100 et TTC = base + TVA.
            reglements_periode = [
                reglement
                for reglement in paiements
                if date_from <= reglement.payment_date <= date_to
            ]
            reglement_retenu = reglements_periode[-1] if reglements_periode else None
            du_ttc = money(abs(facture.total_ttc))
            if du_ttc == 0:
                signaler(
                    reference,
                    "Facture d'un montant TTC nul : base eligible indeterminable",
                )
                continue
            regle_avant = money(
                sum(
                    (
                        reglement.amount
                        for reglement in paiements
                        if reglement.payment_date < date_from
                    ),
                    Decimal("0"),
                )
            )
            regle_dans = money(
                sum(
                    (reglement.amount for reglement in reglements_periode),
                    Decimal("0"),
                )
            )
            cumul_avant = min(regle_avant, du_ttc)
            cumul_apres = min(regle_avant + regle_dans, du_ttc)
            # Meme fraction pour la base et pour la TVA (aucune divergence).
            mht = money(
                money(abs(mht_facture) * (cumul_apres / du_ttc))
                - money(abs(mht_facture) * (cumul_avant / du_ttc))
            )
            tva = money(
                money(abs(tva_facture) * (cumul_apres / du_ttc))
                - money(abs(tva_facture) * (cumul_avant / du_ttc))
            )
            if mht == 0 and tva == 0:
                # Tout a deja ete deduit (facture soldee avant la periode) :
                # aucune ligne ne doit etre emise (risque de double deduction).
                exclues.append(
                    {
                        "reference": reference,
                        "motif": (
                            "Aucun nouveau reglement deductible sur la periode "
                            f"(deja deduit a hauteur de {cumul_avant} / {du_ttc})"
                        ),
                        "mht": str(mht),
                    }
                )
                if regle_avant >= du_ttc and regle_dans > 0:
                    signaler(
                        reference,
                        f"Reglement excedentaire apres solde : {regle_dans} regle "
                        f"alors que la facture est deja soldee ({du_ttc})",
                        bloquant=False,
                    )
                continue
            if cumul_apres < du_ttc:
                signaler(
                    reference,
                    f"Facture partiellement reglee a la fin de la periode "
                    f"({cumul_apres} / {du_ttc}) : base et TVA deductibles limitees a la "
                    "fraction reglee",
                    bloquant=False,
                )
        else:
            reglement_retenu = paiements[-1] if paiements else None
        date_paiement = reglement_retenu.payment_date if reglement_retenu else None
        mode = (
            reglement_retenu.method if reglement_retenu else facture.payment_mode
        ) or "autre"

        # Prorata de deduction (CGI art. 106) : la **TVA deductible** est la
        # fraction deductee (la base HT reste la charge supportee, comme dans le
        # modele DGI) ; le TTC de la ligne reste l'identite base + TVA.
        tva = money(tva * taux_prorata)
        ttc = money(mht + tva)

        lignes.append(
            RdLigne(
                ordre=0,  # numerote apres tri
                num=facture.reference or facture.number or f"#{facture.id}",
                designation=facture.lines[0].designation if facture.lines else "Achat",
                mht=mht,
                tva=tva,
                ttc=ttc,
                if_fournisseur=tiers.fiscal_id,
                nom_fournisseur=tiers.name,
                ice_fournisseur=tiers.ice,
                taux=taux,
                prorata=prorata,
                mode_id=PAYMENT_METHOD_CODES.get(mode, 7),
                date_paiement=date_paiement,
                date_facture=facture.invoice_date,
                facture_id=facture.id,
            )
        )

    if taux_prorata != Decimal("1"):
        anomalies.append(
            {
                "reference": "prorata",
                "motif": (
                    f"Prorata de deduction {taux_prorata} applique a la TVA "
                    "deductible (CGI art. 106) : verifiez le calcul du prorata "
                    "de l'exercice et la regularisation eventuelle"
                ),
                "bloquant": False,
            }
        )

    # Doublons : meme numero de facture fournisseur pour le meme IF.
    vus: set[tuple[str, str | None]] = set()
    for ligne in lignes:
        cle = (ligne.num.strip().lower(), ligne.if_fournisseur)
        if cle in vus:
            signaler(
                ligne.num,
                "Doublon : facture deja presente dans le releve (meme n° et meme IF)",
            )
        vus.add(cle)

    if base_periode == BASE_PERIODE_PAIEMENT:
        lignes.sort(key=lambda l: (l.date_paiement or l.date_facture, l.num))
    else:
        lignes.sort(key=lambda l: (l.date_facture, l.num))
    for index, ligne in enumerate(lignes, start=1):
        ligne.ordre = index

    # Controles bloquants de coherence interne (HT + TVA = TTC, TVA = base x taux) :
    # remontes a l'ecran et refuses par `build_rd_xml` avant toute production XML.
    anomalies.extend(verifier_lignes(lignes))

    return {
        "lignes": lignes,
        "anomalies": anomalies,
        "exclues": exclues,
        "base_periode": base_periode,
        "prorata": taux_prorata,
        "totaux": {
            "nb_lignes": len(lignes),
            "mht": money(sum((l.mht for l in lignes), Decimal("0"))),
            "tva": money(sum((l.tva for l in lignes), Decimal("0"))),
            "ttc": money(sum((l.ttc for l in lignes), Decimal("0"))),
            "par_taux": {
                str(taux): {
                    "nb": len([l for l in lignes if l.taux == taux]),
                    "base": money(
                        sum((l.mht for l in lignes if l.taux == taux), Decimal("0"))
                    ),
                    "tva": money(
                        sum((l.tva for l in lignes if l.taux == taux), Decimal("0"))
                    ),
                }
                for taux in sorted({l.taux for l in lignes}, reverse=True)
            },
        },
    }


# ---------------------------------------------------------------------------
# Construction du fichier XML
# ---------------------------------------------------------------------------
def build_rd_xml(
    *,
    identifiant_fiscal: str,
    annee: int,
    periode: int,
    regime: int,
    lignes: list[RdLigne],
    tx_unit: str = "percent",
    declarant_nom: str | None = None,
    inclure_prorata: bool = False,
    max_lignes: int | None = None,
) -> str:
    """Construit le fichier XML du releve des deductions.

    Structure validee contre le schema XSD officiel de la DGI (modele EDI
    « ADC082F-15I », Article 112 du CGI) : l'ordre des balises est impose par
    `xs:sequence`.

    - `<prorata>` : **absente du XSD** mais documentee par l'annexe V4.0 et
      portee par l'exemple officiel **en pourcentage** (`<prorata>70</prorata>`).
      Elle reste donc **optionnelle** (`inclure_prorata`) ; par defaut le fichier
      suit le format du relevé réellement déposé (balise omise).
    - `max_lignes` : limite de lignes (balise `<ord>`), par defaut
      `settings.max_rd_lines` (127, defaut prudent).
    """
    try:
        identifiant_normalise = normalize_fiscal_id(identifiant_fiscal)
    except ComplianceError as exc:
        raise EdiTvaError(
            f"Identifiant fiscal du declarant invalide (7 ou 8 chiffres attendus) : {exc}"
        ) from exc
    if identifiant_normalise is None:
        raise EdiTvaError(
            "Identifiant fiscal du declarant absent : "
            "renseignez « IF » (7 ou 8 chiffres) dans la fiche societe"
        )
    validate_period(regime, periode)
    if not lignes:
        raise EdiTvaError(
            "Aucune ligne de TVA deductible sur la periode : "
            "fichier EDI vide refuse par la DGI (controle « fichier vide »)"
        )
    limite = limite_lignes(max_lignes)
    if len(lignes) > limite:
        raise EdiTvaError(
            f"{len(lignes)} lignes : au-dela de la limite de {limite} lignes par "
            "fichier (balise <ord>). Deposez le releve par periode plus courte ou "
            "ajustez la limite (settings.max_rd_lines / parametre max_lignes)."
        )

    # Controles bloquants AVANT toute ecriture du fichier : la base eligible, la
    # TVA et le TTC doivent etre coherents sur chaque ligne (audit J9 : `mht` au
    # montant de la facture alors que `tva` etait limitee a la fraction reglee).
    incoherences = verifier_lignes(lignes)
    if incoherences:
        details = " | ".join(
            f"{anomalie['reference']} : {anomalie['motif']}" for anomalie in incoherences[:5]
        )
        raise EdiTvaError(
            "Fichier EDI refuse : lignes incoherentes (base HT + TVA = TTC et "
            f"TVA = base x taux doivent etre respectes) -> {details}"
        )

    parties: list[str] = []
    parties.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    if declarant_nom:
        parties.append(f"<!-- Declarant : {_esc(declarant_nom)} -->")
    parties.append("<DeclarationReleveDeduction>")
    parties.append(
        f"  <identifiantFiscal>{_esc(identifiant_normalise)}</identifiantFiscal>"
    )
    parties.append(f"  <annee>{annee}</annee>")
    parties.append(f"  <periode>{periode}</periode>")
    parties.append(f"  <regime>{regime}</regime>")
    parties.append("  <releveDeductions>")

    for ligne in lignes:
        parties.append("    <rd>")
        parties.append(f"      <ord>{ligne.ordre}</ord>")
        parties.append(f"      <num>{_esc(ligne.num)}</num>")
        parties.append(f"      <des>{_esc(ligne.designation)}</des>")
        parties.append(f"      <mht>{_dec(ligne.mht)}</mht>")
        parties.append(f"      <tva>{_dec(ligne.tva)}</tva>")
        parties.append(f"      <ttc>{_dec(ligne.ttc)}</ttc>")
        parties.append("      <refF>")
        parties.append(f"        <if>{_esc(_if_edi(ligne.if_fournisseur))}</if>")
        parties.append(f"        <nom>{_esc(ligne.nom_fournisseur)}</nom>")
        parties.append(f"        <ice>{_esc(ligne.ice_fournisseur)}</ice>")
        parties.append("      </refF>")
        parties.append(f"      <tx>{taux_edi(ligne.taux, tx_unit)}</tx>")
        if inclure_prorata:
            # Pourcentage, comme l'exemple officiel DGI (<prorata>70</prorata>).
            parties.append(f"      <prorata>{_prorata_edi(ligne.prorata)}</prorata>")
        parties.append("      <mp>")
        parties.append(f"        <id>{ligne.mode_id}</id>")
        parties.append("      </mp>")
        parties.append(f"      <dpai>{_date_iso(ligne.date_paiement)}</dpai>")
        parties.append(f"      <dfac>{_date_iso(ligne.date_facture)}</dfac>")
        parties.append("    </rd>")

    parties.append("  </releveDeductions>")
    parties.append("</DeclarationReleveDeduction>")
    return "\n".join(parties)


def _if_edi(valeur: str | None) -> str:
    """IF du fournisseur au format DGI : **7 ou 8 chiffres, tel quel**.

    Aucune transformation n'est appliquee (la regle historique de complement a
    8 chiffres a ete supprimee) ; un identifiant atypique est laisse tel quel et
    signale par les controles du releve (IF manquant / invalide).
    """
    if valeur is None:
        return ""
    try:
        return normalize_fiscal_id(valeur) or ""
    except ComplianceError:
        return valeur


def controle_taille(xml: str) -> int:
    """Taille du fichier en octets ; leve une erreur au-dela de 1 Mo (DGI)."""
    taille = len(xml.encode("utf-8"))
    if taille > MAX_XML_BYTES:
        raise EdiTvaError(
            f"Fichier EDI trop volumineux : {taille} octets "
            f"(limite DGI {MAX_XML_BYTES} octets). Deposez par periode plus courte."
        )
    return taille