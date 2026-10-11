"""Schemas Pydantic de l'API (entrees et sorties)."""

from app.schemas.account import AccountCreate, AccountRead
from app.schemas.asset import (
    AssetCessionRequest,
    AssetCreate,
    AssetDotationRequest,
    AssetRead,
    AssetRebutRequest,
)
from app.schemas.company import CompanyCreate, CompanyRead, FiscalYearCreate, FiscalYearRead
from app.schemas.greffe import (
    GreffeCertificatRequest,
    GreffeDepositCreate,
    GreffeDepositRead,
    GreffeDocumentRead,
    GreffeEtatRequest,
    GreffeEventRead,
    GreffePaymentCreate,
    GreffePaymentRead,
)
from app.schemas.entry import EntryCreate, EntryLineCreate, EntryRead, ReversalRequest
from app.schemas.invoice import (
    CancellationRequest,
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceRead,
    PaymentCreate,
)
from app.schemas.liasse import LiasseEnregistrementRequest, LiasseSoumissionRequest
from app.schemas.party import ThirdPartyCreate, ThirdPartyRead
from app.schemas.payroll import (
    DtsSoumissionRequest,
    EmployeeCreate,
    EmployeeRead,
    PayContractCreate,
    PayContractRead,
    PayrollPayRequest,
    PayrollPrepareRequest,
    PayrollRunRead,
    PayslipLineRead,
    PayslipRead,
    TaxDeclarationRead,
)
from app.schemas.stock import (
    StockCountCreate,
    StockItemCreate,
    StockItemRead,
    StockMovementCreate,
    StockProvisionCreate,
)
from app.schemas.user import Token, UserCreate, UserRead

__all__ = [
    "DtsSoumissionRequest",
    "LiasseEnregistrementRequest",
    "LiasseSoumissionRequest",
    "EmployeeCreate",
    "EmployeeRead",
    "PayContractCreate",
    "PayContractRead",
    "PayrollPayRequest",
    "PayrollPrepareRequest",
    "PayrollRunRead",
    "PayslipLineRead",
    "PayslipRead",
    "TaxDeclarationRead",
    "GreffeCertificatRequest",
    "GreffeDepositCreate",
    "GreffeDepositRead",
    "GreffeDocumentRead",
    "GreffeEtatRequest",
    "GreffeEventRead",
    "GreffePaymentCreate",
    "GreffePaymentRead",
    "AccountCreate",
    "AccountRead",
    "AssetCreate",
    "AssetRead",
    "AssetDotationRequest",
    "AssetCessionRequest",
    "AssetRebutRequest",
    "CompanyCreate",
    "CompanyRead",
    "FiscalYearCreate",
    "FiscalYearRead",
    "EntryCreate",
    "EntryLineCreate",
    "EntryRead",
    "ReversalRequest",
    "InvoiceCreate",
    "InvoiceLineCreate",
    "InvoiceRead",
    "PaymentCreate",
    "CancellationRequest",
    "ThirdPartyCreate",
    "ThirdPartyRead",
    "StockItemCreate",
    "StockItemRead",
    "StockMovementCreate",
    "StockCountCreate",
    "StockProvisionCreate",
    "Token",
    "UserCreate",
    "UserRead",
]