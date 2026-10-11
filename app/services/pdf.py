"""Rendu PDF des documents comptables (etats, pieces, bordereaux).

**Moteur retenu : ReportLab** (pur Python, aucune dependance systeme).

Le moteur **WeasyPrint** (HTML/CSS -> PDF, qui aurait permis de reutiliser les
gabarits Jinja2) a ete **ecarte apres le POC du 22/09/2026** : son import echoue
sur un poste Windows sans runtime GTK
(``OSError: cannot load library 'libgobject-2.0-0'``), ce qui interdirait
l'empaquetage autonome de l'application. Voir `tools/poc_pdf.py` (mesures).

**Contrainte normative** : les pieces destinees au depot au greffe doivent etre
des PDF de **10 Mo maximum** (portail `depotbilan.justice.gov.ma`, guide du
Ministere de la Justice, novembre 2025) -> `controle_taille_pdf()`.

L'interface est volontairement stable (`Document` -> `rendre_pdf` -> `bytes`) :
un autre moteur pourra etre branche sans modifier les modules appelants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

TAILLE_MAX_GREFFE = 10 * 1024 * 1024  # 10 Mo : limite du portail greffe

# Caracteres typographiques -> equivalents Latin-1 (polices standard ReportLab).
REMPLACEMENTS_LATIN1: dict[str, str] = {
    "\u2014": "-",  # tiret cadratin
    "\u2013": "-",  # tiret demi-cadratin
    "\u2018": "'",
    "\u2019": "'",  # apostrophe courbe
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u202f": " ",  # espace insecable etroite
    "\u00a0": " ",  # espace insecable
    "\u2022": "-",  # puce
    "\u2264": "<=",
    "\u2265": ">=",
    "\u20ac": "EUR",
}


def texte_pdf(valeur: object) -> str:
    """Normalise un texte destine au PDF (polices standard en Latin-1).

    Les tirets longs, apostrophes courbes et espaces insecables sont remplaces
    par leurs equivalents, et tout caractere non encodable devient « ? » : un
    libelle saisi par l'utilisateur ne doit **jamais** faire echouer la
    generation d'un etat comptable.
    """
    texte = "" if valeur is None else str(valeur)
    for source, cible in REMPLACEMENTS_LATIN1.items():
        texte = texte.replace(source, cible)
    return texte.encode("latin-1", "replace").decode("latin-1").replace("\ufffd", "?")


class PdfError(RuntimeError):
    """Erreur de rendu PDF (moteur indisponible, document invalide)."""


class MoteurIndisponible(PdfError):
    """Le moteur de rendu n'est pas installe dans l'environnement."""


@dataclass
class Colonne:
    """Colonne d'un tableau PDF."""

    titre: str
    largeur: float | None = None  # en mm ; None = repartition automatique
    alignement: str = "left"  # left | right | center


@dataclass
class Tableau:
    """Tableau du document (soldes, mouvements, lignes de facture...)."""

    colonnes: list[Colonne]
    lignes: list[list[str]]
    titre: str | None = None
    total: list[str] | None = None  # ligne de totaux mise en evidence


@dataclass
class Document:
    """Document PDF generique (entete d'identification + tableaux)."""

    titre: str
    sous_titre: str | None = None
    entete: list[str] = field(default_factory=list)  # ex. société, IF, ICE, exercice
    tableaux: list[Tableau] = field(default_factory=list)
    pied: str | None = None
    filigrane: str | None = None  # ex. « BROUILLON »


def moteur_disponible() -> str:
    """Retourne le nom du moteur de rendu utilisable (leve si aucun)."""
    try:
        import reportlab  # noqa: F401, PLC0415
    except ImportError as exc:  # pragma: no cover - depend de l'environnement
        raise MoteurIndisponible(
            "Aucun moteur PDF installe : pip install reportlab"
        ) from exc
    return f"reportlab {reportlab.Version}"


def controle_taille_pdf(pdf: bytes, limite: int = TAILLE_MAX_GREFFE) -> int:
    """Retourne la taille du PDF et refuse un fichier au-dela de la limite.

    La limite par defaut (10 Mo) est celle du portail de depot au greffe
    (`depotbilan.justice.gov.ma`, guide de novembre 2025).
    """
    taille = len(pdf)
    if taille > limite:
        raise PdfError(
            f"PDF de {taille} octets : la limite du depot au greffe est de "
            f"{limite} octets (10 Mo). Reduisez les images ou scindez le document."
        )
    return taille


def rendre_pdf(document: Document, taille_max: int | None = TAILLE_MAX_GREFFE) -> bytes:
    """Rend le document en PDF (ReportLab) et retourne les octets.

    `taille_max` : limite de taille verifiee apres rendu (defaut 10 Mo, limite du
    depot au greffe). Passer `None` pour ne pas controler la taille.
    """
    moteur_disponible()  # leve MoteurIndisponible si le moteur est absent
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    feuille = getSampleStyleSheet()
    style_titre = ParagraphStyle(
        "titre", parent=feuille["Title"], fontSize=15, spaceAfter=4
    )
    style_secondaire = ParagraphStyle(
        "secondaire", parent=feuille["Normal"], fontSize=9.5,
        textColor=colors.HexColor("#555555"),
    )
    style_cellule = ParagraphStyle("cellule", parent=feuille["Normal"], fontSize=8)
    gris = colors.HexColor("#777777")

    flux: list = [Paragraph(texte_pdf(document.titre), style_titre)]
    if document.sous_titre:
        flux.append(Paragraph(texte_pdf(document.sous_titre), style_secondaire))
    for ligne in document.entete:
        flux.append(Paragraph(texte_pdf(ligne), style_secondaire))
    if document.entete or document.sous_titre:
        flux.append(Spacer(1, 3 * mm))

    for numero, tableau in enumerate(document.tableaux):
        if tableau.titre:
            flux.append(Paragraph(f"<b>{texte_pdf(tableau.titre)}</b>", style_secondaire))
            flux.append(Spacer(1, 1.5 * mm))
        donnees = [
            [
                Paragraph(f"<b>{texte_pdf(colonne.titre)}</b>", style_cellule)
                for colonne in tableau.colonnes
            ]
        ]
        for ligne in tableau.lignes:
            donnees.append([Paragraph(texte_pdf(cellule), style_cellule) for cellule in ligne])
        if tableau.total:
            donnees.append(
                [
                    Paragraph(f"<b>{texte_pdf(cellule)}</b>", style_cellule)
                    for cellule in tableau.total
                ]
            )

        largeurs = [
            colonne.largeur * mm if colonne.largeur else None for colonne in tableau.colonnes
        ]
        col_widths = None if all(largeur is None for largeur in largeurs) else largeurs
        table = Table(donnees, colWidths=col_widths, repeatRows=1, hAlign="LEFT")

        style: list = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAAAAA")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for index, colonne in enumerate(tableau.colonnes):
            if colonne.alignement in ("right", "center"):
                style.append(("ALIGN", (index, 0), (index, -1), colonne.alignement.upper()))
        if tableau.total:
            style.extend(
                [
                    ("LINEABOVE", (0, -1), (-1, -1), 0.7, colors.black),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F7F7F7")),
                ]
            )
        table.setStyle(TableStyle(style))
        flux.append(table)
        if numero < len(document.tableaux) - 1:
            flux.append(Spacer(1, 4 * mm))

    def decorer(canvas, doc):  # noqa: ANN001
        """Filigrane (brouillon) et pied de page sur chaque page."""
        canvas.saveState()
        if document.filigrane:
            canvas.setFont("Helvetica-Bold", 42)
            canvas.setFillColor(colors.HexColor("#E4E4E4"))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, texte_pdf(document.filigrane))
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(gris)
        if document.pied:
            canvas.drawString(15 * mm, 10 * mm, texte_pdf(document.pied))
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"page {doc.page}")
        canvas.restoreState()

    tampon = BytesIO()
    gabarit = SimpleDocTemplate(
        tampon,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title=document.titre,
        onFirstPage=decorer,
        onLaterPages=decorer,
    )
    gabarit.build(flux)
    pdf = tampon.getvalue()
    if taille_max:
        controle_taille_pdf(pdf, taille_max)
    return pdf

