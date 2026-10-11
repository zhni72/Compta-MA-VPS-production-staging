"""Services metier : comptabilite, facturation, tiers, TVA, etats.

Regle d'architecture : toute la logique metier vit ici (jamais dans les routeurs
ni dans les modeles), ce qui garantit la meme comportement en mono et
multi-utilisateurs.
"""

from app.services.accounting import (
    AccountingError,
    ComplianceError,
    EntryImmutableError,
    EntryNotBalancedError,
    FiscalYearClosedError,
    NotFoundError,
)

__all__ = [
    "AccountingError",
    "ComplianceError",
    "EntryImmutableError",
    "EntryNotBalancedError",
    "FiscalYearClosedError",
    "NotFoundError",
]