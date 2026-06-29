from pydantic import BaseModel, Field, field_validator
from typing import List, Optional


class InvoiceItem(BaseModel):
    name: str = Field(default="Unknown Product", description="Product name")
    price: float = Field(..., description="Unit price before tax")
    qty: int = Field(1, description="Quantity")
    is_reduced_vat: bool = Field(True, description="Whether item qualifies for reduced VAT (e.g., 8%)")

    @field_validator("price")
    @classmethod
    def price_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("price must be >= 0")
        return v

    @field_validator("qty")
    @classmethod
    def qty_at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError("qty must be >= 1")
        return v


class InvoicePayload(BaseModel):
    items: List[InvoiceItem] = Field(..., description="List of items in the invoice")
    total: float = Field(..., description="Stated total price on the invoice including tax")

    @field_validator("total")
    @classmethod
    def total_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("total must be > 0")
        return v


class RetailChatResponse(BaseModel):
    answer: str = Field(..., description="The main response text to the user")
    confidence: float = Field(1.0, description="Confidence score from 0.0 to 1.0")
    sources: Optional[List[str]] = Field(None, description="List of URLs or document IDs referenced")

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class ProductExtraction(BaseModel):
    sku: Optional[str] = Field(None, description="Extracted SKU")
    category: str = Field(..., description="Product category")
    base_price: float = Field(..., description="Base price before tax")

    @field_validator("base_price")
    @classmethod
    def base_price_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("base_price must be >= 0")
        return v
