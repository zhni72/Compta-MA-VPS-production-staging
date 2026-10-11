"""Controle des identifiants legaux des tiers (ICE, identifiant fiscal).

Ces controles repondent a l'exigence de l'Annexe 1 EDI de la DGI pour le releve
des deductions : chaque ligne doit porter l'IF et l'ICE du fournisseur
(ICE = 15 chiffres). Ils portent sur le FORMAT uniquement : l'absence d'ICE
n'est pas bloquante a la creation (tiers non assujetti, particulier, import),
mais elle est signalee par l'export EDI.
"""

from __future__ import annotations

from app.services.accounting import ComplianceError

ICE_LENGTH = 15
# L'identifiant fiscal marocain (IF) comporte **7 ou 8 chiffres** et doit etre
# utilise **tel quel** : ni ajout, ni suppression de zero (« 1084612 » reste
# « 1084612 » ; un IF a 8 chiffres reste a 8 chiffres).
# L'ancienne regle de complement a 8 chiffres (zfill) etait ERRONEE : elle
# produisait un identifiant different de celui attribue par la DGI
# (« 1086826 » devenait « 01086826 »), avec un risque de declaration rattachee
# a un mauvais contribuable. Elle a ete supprimee.
FISCAL_ID_LENGTHS = (7, 8)


def clean_identifier(value: str | None) -> str | None:
    """Retire les separateurs de saisie (« 108 6826 », « 108-6826 »).

    Les lettres ne sont PAS supprimees : un identifiant non numerique doit etre
    refuse, jamais transforme en silence (defaut constate dans les scripts qui
    ecrasent l'IF du fournisseur).
    """
    if value is None:
        return None
    nettoye = str(value).strip()
    for separateur in (" ", "\u00a0", "-", ".", "/", "\t"):
        nettoye = nettoye.replace(separateur, "")
    return nettoye or None


def validate_ice(ice: str | None, *, required: bool = False) -> str | None:
    """Valide l'ICE : 15 chiffres (obligatoire sur les factures B2B)."""
    nettoye = clean_identifier(ice)
    if nettoye is None:
        if required:
            raise ComplianceError("ICE obligatoire : 15 chiffres attendus")
        return None
    if not nettoye.isdigit() or len(nettoye) != ICE_LENGTH:
        raise ComplianceError(
            f"ICE invalide : {ICE_LENGTH} chiffres attendus, « {ice} » fourni"
        )
    return nettoye


def normalize_fiscal_id(fiscal_id: str | None) -> str | None:
    """Verifie l'IF et le retourne **tel quel** (7 ou 8 chiffres).

    Regle marocaine : l'identifiant fiscal comporte **7 ou 8 chiffres** et
    s'utilise sans transformation (« 1084612 » reste « 1084612 », « 1086826 »
    reste « 1086826 » ; un IF a 8 chiffres reste a 8 chiffres).

    Seuls les separateurs de saisie sont retires (« 108 6826 » -> « 1086826 »).
    Toute autre longueur (6, 9 chiffres...) ou tout caractere non numerique est
    refuse : un identifiant invalide n'est jamais corrige en silence.
    """
    nettoye = clean_identifier(fiscal_id)
    if nettoye is None:
        return None
    if not nettoye.isdigit() or len(nettoye) not in FISCAL_ID_LENGTHS:
        raise ComplianceError(
            "Identifiant fiscal (IF) invalide : 7 ou 8 chiffres attendus, "
            f"« {fiscal_id} » fourni"
        )
    return nettoye


def validate_fiscal_id(fiscal_id: str | None, *, required: bool = False) -> str | None:
    """Valide l'IF (7 ou 8 chiffres) sans le transformer."""
    nettoye = normalize_fiscal_id(fiscal_id)
    if nettoye is None and required:
        raise ComplianceError("Identifiant fiscal (IF) obligatoire")
    return nettoye


def validate_party_identifiers(
    *,
    kind: str,
    is_individual: bool,
    ice: str | None,
    fiscal_id: str | None,
) -> tuple[str | None, str | None]:
    """Valide et normalise les identifiants d'un tiers.

    Retourne (ICE normalise, IF normalise). Les formats incoherents levent une
    ComplianceError (traduite en HTTP 422 par l'API et par l'interface).
    """
    if is_individual:
        # Un particulier n'a ni ICE ni identifiant fiscal : on n'impose rien,
        # mais un ICE fourni reste controle dans son format.
        return validate_ice(ice), validate_fiscal_id(fiscal_id)
    return validate_ice(ice), validate_fiscal_id(fiscal_id)