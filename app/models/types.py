"""Types de colonnes partages (montants en dirhams, taux, quantites)."""

from __future__ import annotations

from sqlalchemy import Numeric

# Montant en dirhams : 14 chiffres dont 2 decimales
Money = Numeric(14, 2, asdecimal=True)
# Taux (ex. 20.00 pour 20 %)
Rate = Numeric(5, 2, asdecimal=True)
# Quantite (3 decimales utiles pour les prestations)
Quantity = Numeric(14, 3, asdecimal=True)