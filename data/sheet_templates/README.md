# Bộ Google Sheet mẫu — nhập liệu logistics cho pilot

**Quyết định 27/07/2026:** khách pilot nhập dữ liệu hãng xe/tuyến/giá **một lần
duy nhất** qua Google Sheet (khớp thói quen Excel/MISA), thay vì chờ UI bên Body.
Mỗi file CSV ở đây = một tab của Sheet. Tạo một Google Sheet mới → File → Import →
Upload từng CSV → mỗi CSV một tab, giữ đúng tên tab = tên file.

## Các tab

| Tab (file) | Nội dung | Ai nhập | Tần suất |
|---|---|---|---|
| `Carriers` | Hồ sơ hãng xe đối tác | Khách | 1 lần + khi có hãng mới |
| `Routes` | Tuyến đường hay chạy | Khách | 1 lần + khi có tuyến mới |
| `CarrierQuotes` | Giá nhà xe chào theo tuyến × loại xe | Khách | Khi nhà xe báo giá mới |
| `PricingRules` | ⚠️ Quy tắc biên — BÍ MẬT KINH DOANH | Chủ DN, KHÔNG chia sẻ sheet này rộng | Hiếm khi đổi |
| `FuelIndex` | Giá dầu theo ngày | Tự động (n8n) hoặc tay | Hàng ngày |

## Luồng dữ liệu

```
Sheet (khách nhập 1 lần)
  → n8n đọc (googleSheets node / Sheets API)
  → POST BRAIN_BASE_URL/tools/quote | /tools/carrier-selection   (tính thuần)
  → kết quả 'quote' đi email khách cuối; 'internal' chỉ báo về Zalo chủ DN
```

## Quy ước cột

- `vehicle_types` trong Carriers: danh sách cách nhau dấu `|` — ví dụ `1.5T|3T|5T`
- Toạ độ (`depot_lat/lon`): lấy từ Google Maps (chuột phải → What's here). Bỏ
  trống được — hệ thống tự loại tiêu chí khoảng cách và báo rõ trong kết quả.
- Tiền: số nguyên VND, không dấu chấm phẩy ngăn cách.
- `fuel_sensitivity` trong PricingRules: tỷ trọng nhiên liệu trong chi phí nhà
  xe (0–1). Xe tải đường dài thường 0.30–0.40.
- `fuel_baseline_price`: giá dầu tại thời điểm nhà xe chốt bảng giá — mốc để
  tính điều chỉnh khi giá dầu biến động.

## Lưu ý bảo mật (AGENTS.md R2)

Tab `PricingRules` chứa biên lợi nhuận. Chia sẻ Sheet cho nhân viên thì **ẩn/
bảo vệ tab này** (Data → Protect sheet). Nội dung tab không bao giờ xuất hiện
trong email/Zalo gửi khách cuối — engine đã tách sẵn `quote` vs `internal`.
