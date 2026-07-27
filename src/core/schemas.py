from pydantic import BaseModel, Field, field_validator
from typing import List, Optional


class InvoiceItem(BaseModel):
    name: str = Field(default="Unknown Product", description="Product name")
    price: float = Field(..., description="Unit price before tax")
    qty: int = Field(1, description="Quantity")
    is_reduced_vat: Optional[bool] = Field(
        None,
        description="None = chưa rõ diện thuế -> validator áp mặc định 10%; True nếu thuộc diện giảm 8%",
    )

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
    # confidence: None = chưa đo (thành thật) thay vì 1.0 giả. Chỉ set khi có tín hiệu thật.
    confidence: Optional[float] = Field(None, description="Confidence 0.0–1.0; None nếu chưa đo")
    sources: Optional[List[str]] = Field(None, description="List of URLs or document IDs referenced")

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class QuoteExtraction(BaseModel):
    """
    Kết quả trích xuất yêu cầu báo giá vận tải từ câu tiếng Việt tự do.

    Đây là MỘT TRONG HAI việc duy nhất LLM làm trong luồng báo giá (P1):
    ngôn ngữ tự nhiên -> struct này. Mọi tính toán sau đó là code thuần
    (n8n đọc Sheet -> /tools/quote). Schema này được đưa vào guided_json
    nên các field đều Optional — model KHÔNG được đoán bừa trường thiếu;
    trường bắt buộc nào thiếu thì chat.py hỏi lại người dùng.
    """
    origin: Optional[str] = Field(None, description="Điểm lấy hàng, ví dụ 'Hữu Nghị'")
    destination: Optional[str] = Field(None, description="Điểm giao, ví dụ 'Hải Phòng'")
    vehicle_type: Optional[str] = Field(
        None, description="Loại xe: '1.5T' | '3T' | '5T' | 'dau_keo'"
    )
    cargo_type: Optional[str] = Field(None, description="Loại hàng, ví dụ 'Hàng lạnh'")
    pickup_date: Optional[str] = Field(None, description="Ngày lấy hàng YYYY-MM-DD nếu nêu")
    customer_name: Optional[str] = Field(None, description="Tên khách/công ty nếu nêu")
    customer_email: Optional[str] = Field(None, description="Email khách nếu nêu")


# Các trường BẮT BUỘC để tính được báo giá — thiếu thì hỏi lại, không đoán.
QUOTE_REQUIRED_FIELDS = {
    "origin": "điểm lấy hàng",
    "destination": "điểm giao hàng",
    "vehicle_type": "loại xe (1.5T / 3T / 5T / đầu kéo)",
}


class ProductExtraction(BaseModel):
    # Tất cả Optional: OCR tự do thường thiếu trường -> tránh ValidationError làm rớt cả kết quả.
    sku: Optional[str] = Field(None, description="Extracted SKU")
    category: Optional[str] = Field(None, description="Product category (None nếu OCR không đọc được)")
    base_price: Optional[float] = Field(None, description="Base price before tax (None nếu chưa đọc được)")

    @field_validator("base_price")
    @classmethod
    def base_price_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("base_price must be >= 0")
        return v