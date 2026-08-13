# Hoàng Phát — dữ liệu cần xin

> **Sửa 13/08/2026.** Bản trước xin dữ liệu cho cả mảng vận tải. Chú Hoàng Phát
> nói rõ: *"hiện tại công ty chú là chuyên bán dầu, chưa phải là công ty về vận
> tải"*. Bốn trong sáu mục cũ không dùng đến — đã chuyển xuống phụ lục, không
> xoá, để dành cho lúc công ty mở mảng vận tải.
>
> Bản này xếp theo **thứ tự công ty phân phối dầu nhớt thật sự cần**.

## Đã nhận và đã dùng

| Ngày | File | Đã ra kết quả gì |
|---|---|---|
| 30/07 | Tổng hợp tồn kho, 2 kho, đến 24/07 | 119 + 38 dòng đọc sạch; phát hiện tồn âm |
| 13/08 | Tổng hợp tồn kho, kho HH, đến 11/08 | 121 dòng; phát hiện **chứng từ bị sửa hồi tố** |
| 13/08 | Danh sách hàng hóa, dịch vụ | 161 mã; **157 mã đang để sai diện thuế GTGT** |
| 13/08 | Danh sách khách hàng | 104 khách; phải thu **3,96 tỷ**, 3 khách giữ **66%** |
| 13/08 | Danh sách nhà cung cấp | 42 NCC; 3 số dư ngược dấu |

> **Về danh sách khách hàng:** lúc trao đổi có nói "không có cũng không sao".
> Thực tế nó ra **nhiều phát hiện đáng tiền nhất** trong cả bốn file — riêng con
> số 3,96 tỷ phải thu và mức tập trung 66% chỉ nhìn ra được từ file đó.

---

## Còn cần xin — theo thứ tự đáng tiền

| # | Thứ cần xin | Số lượng | Mở khoá được gì | Không có thì sao |
|---|---|---|---|---|
| **A** | **Sổ chi tiết công nợ phải thu** | 1 file | **Tuổi nợ 30/60/90 ngày, nợ quá hạn** | Chỉ biết tổng, không biết ai nợ lâu |
| **B** | Sổ chi tiết 3 mã: VT00039, VT00042, VT00023 | 3 mã | Chứng từ nào bị sửa | Chỉ biết CÓ sửa, không biết chỗ nào |
| **C** | Tổng hợp tồn kho **kho KHUYẾN MẠI** đến 11/08 | 1 file | Kiểm lại KM00034 âm 115,2 lít | Lỗi treo từ 24/07 chưa rõ đã xử lý chưa |
| **D** | 3–5 hoá đơn bán ra sau 01/7/2025 | 3–5 tờ | Biết đang xuất 8% hay 10% | Không biết có phải điều chỉnh hoá đơn không |
| **E** | Bảng tổng hợp N-X-T các kỳ trước | càng nhiều càng tốt | So nhiều kỳ, bắt sửa hồi tố sớm | Chỉ so được 2 kỳ đang có |
| F | Giá vốn từng mặt hàng (mục 4) | toàn bộ SKU | Báo cáo lãi lỗ đáng tin | Báo cáo dừng ở "độ tin cậy thấp" |
| G | Tài liệu nội bộ (mục 5) | 10–30 file | Hỏi đáp theo quy định của chính công ty | Trả lời chung chung |

**Ba thứ chặn nhiều việc nhất: A, B, C.** Xin được ba thứ đó là đủ cho vòng này.

---

## 1. Bốn thứ cần cho vòng này (A–D ở bảng trên)

### A. Sổ chi tiết công nợ phải thu

MISA: *Báo cáo → Bán hàng → Sổ chi tiết công nợ phải thu* → **Xuất khẩu → Excel**.

Cần có cột **ngày hoá đơn** hoặc **ngày phát sinh**. Danh sách khách hàng đang
có chỉ cho **số dư** — một con số duy nhất cho mỗi khách, không kèm ngày. Từ đó
tính được mức độ tập trung và số dư ngược dấu, nhưng **không tính được nợ quá
hạn bao lâu**, mà với 3,96 tỷ phải thu thì đó mới là câu hỏi quan trọng nhất.

### B. Sổ chi tiết ba mã hàng

MISA: *Báo cáo → Kho → Sổ chi tiết vật tư hàng hoá*, lọc theo mã, kỳ 01/01/2026
đến nay. Ba mã: **VT00039**, **VT00042**, **VT00023**.

Lý do: so hai bản xuất tồn kho cho thấy số xuất luỹ kế của ba mã này **giảm
xuống** giữa hai lần xuất, dù kỳ sau dài hơn. Sổ chi tiết cho biết chứng từ nào.

### C. Tổng hợp tồn kho — kho KHUYẾN MẠI

Cùng đường xuất như kho hàng hoá, chọn **KHO KHUYẾN MẠI**, kỳ 01/01/2026 đến
11/08/2026. Bản 24/07 cho thấy KM00034 âm 115,2 lít (đúng 6 thùng 19,2L) — chưa
biết đã xử lý chưa.

### D. Vài hoá đơn bán ra sau 01/7/2025

Chỉ cần 3–5 tờ, che tên khách cũng được. Cần nhìn đúng **một ô: thuế suất**.

Lý do: Nghị định 174/2025/NĐ-CP đưa dầu mỡ bôi trơn vào diện giảm còn **8%** từ
01/7/2025, khác với nhiều năm trước. Danh mục hàng hoá đang để "Chưa xác định"
cho cả 161 mã nên phần mềm không tự áp — thuế suất do người nhập chọn tay từng
hoá đơn.

---

## 2. Bảng tổng hợp Nhập – Xuất – Tồn (.xlsx)


**Đã dùng được ngay** — đường nạp file vừa hoàn thành, không cần lập trình thêm.

### Xin thế nào
Trong MISA: *Báo cáo → Kho → Tổng hợp Nhập Xuất Tồn* → **Xuất khẩu → Excel**.

> **Xin bản .xlsx, đừng lấy bản in ra PDF.** Hai file đang có là PDF in từ Excel.
> Đọc Excel thì chính xác tuyệt đối; đọc ảnh bảng số tiền thì có lúc nhầm 5 thành
> 6 ở đúng cột giá vốn, mà loại sai đó không ai phát hiện được.

### Bảng phải có các cột
```
Mã hàng | Tên hàng | ĐVT | Đầu kỳ         | Nhập kho       | Xuất kho       | Cuối kỳ
                          SL | Giá trị     SL | Giá trị     SL | Giá trị     SL | Giá trị
```
Có thêm cột "Đơn giá BQ" thì **càng tốt** — hệ thống dùng nó để tự kiểm chéo và
phát hiện lỗi lệch cột lúc đọc.

### Xin bao nhiêu kỳ
Càng nhiều càng tốt, tối thiểu **2 kỳ liên tiếp**. Một kỳ chỉ soi được lỗi trong
kỳ đó; nhiều kỳ mới thấy được giá nhập trôi dần và hàng nằm chết.

### Dùng ở đâu
Dashboard → Kho → tab **Kiểm sổ từ Excel**. Ra ngay: tồn âm, hàng chết, giá nhập
nhảy vọt, hàng không ghi nhận giá trị, dấu hiệu hai phương pháp tính giá vốn
chạy song song.

---

## 3. Danh mục nền — **ĐÃ NHẬN 13/08/2026**


Để nạp dữ liệu vào ANSER thay vì gõ tay từng dòng.

| File | Cột cần có |
|---|---|
| Danh mục hàng hoá | Mã, Tên, ĐVT, Nhóm hàng, Giá bán, **Giá vốn**, Tồn hiện tại |
| Danh mục khách hàng | Tên, MST, Địa chỉ, Điện thoại, Email, Công nợ hiện tại |
| Danh mục nhà cung cấp | Tên, MST, Địa chỉ, Điện thoại |
| Danh sách kho | Tên kho, Địa chỉ |

Xuất từ MISA: *Danh mục → \<loại\> → Xuất khẩu → Excel*.

---

## 4. Giá vốn từng mặt hàng


Đây là thứ chặn báo cáo lãi lỗ. Hiện tại cột giá vốn trong ANSER **rỗng hoàn
toàn**, nên mọi báo cáo lãi đều ở mức "độ tin cậy thấp".

### Vì sao không tự suy ra được
Vì `null` (chưa biết) và `0` (không tốn đồng nào) là hai chuyện khác hẳn. Nếu
coi phần chưa biết là 0 thì lãi gộp nhảy lên 100% doanh thu — một con số sai mà
nghe cực kỳ xuôi tai, và không ai phát hiện tới lúc quyết toán. Hệ thống cố ý
**không đoán**: nó loại phần chưa biết ra khỏi phép tính lãi và báo rõ còn bao
nhiêu phần trăm chưa có.

### Ba đường nạp, dùng đường nào cũng được
1. **Từ bảng N-X-T ở mục 1** — `Giá trị xuất kho ÷ Số lượng xuất` chính là giá
   vốn bình quân. **Đã làm xong**: sau khi kiểm sổ, bấm *Lấy giá vốn từ file
   này* → xem trước → ghi. Mặc định chỉ điền ô đang trống.
2. **Nhập tay khi tạo phiếu nhập kho** — **đã làm xong**: form nhập kho có ô
   "Đơn giá nhập", giá vốn tự bồi dần theo bình quân gia quyền mỗi lần nhập hàng.
   Form sản phẩm cũng có ô giá vốn.
3. **Nạp hàng loạt từ file danh mục có sẵn cột giá vốn** — *chưa làm*. Hiện phải
   sửa từng mặt hàng một.

### ⚠ MÃ HÀNG PHẢI KHỚP — điều kiện quan trọng nhất của đường 1

Chạy thử trên dữ liệu thật (03/08/2026) cho ra **0/2 khớp**: mã trong file
(`VT00059`) không trùng mã nào trong ANSER. Đường nạp giá vốn khớp theo **mã
hàng** trước, chỉ lùi về **tên hàng** khi mã không thấy, và tên trùng nhau giữa
hai mặt hàng thì bỏ hẳn chứ không đoán bừa — gán nhầm giá vốn tạo ra một con số
trông hoàn toàn bình thường, còn tệ hơn để trống.

Nên cần hỏi khách thêm một trong hai:

- **Nạp danh mục hàng từ MISA vào ANSER trước** (mục 8), để mã hai bên là một.
  Đây là cách sạch nhất và nên làm ngay từ đầu.
- Hoặc xin **bảng đối chiếu mã**: `mã MISA | mã ANSER | tên hàng`.

Nếu tên hàng hai bên viết giống hệt nhau thì đường lùi theo tên vẫn cứu được,
nhưng đừng trông vào đó: chỉ cần khác một chữ viết tắt hay một khoảng trắng là
trượt, và nhiều mặt hàng dầu nhớt trùng tên nhau chỉ khác dung tích.

### Xin thêm nếu có
Bảng giá nhập của **2–3 kỳ gần nhất**, để thấy giá nhập trôi theo thời gian.
Giá vốn hôm nay gán cho đơn bán sáu tháng trước là sai — đã xử lý bằng cách chụp
lại giá vốn ngay lúc bán, nhưng chỉ áp dụng được cho đơn từ nay về sau.

---

## 5. Tài liệu nội bộ (hỏi đáp nội bộ)


| Loại | Ví dụ | Ưu tiên |
|---|---|---|
| Bảng giá cước | Bảng giá theo tuyến, theo loại xe | **cao** |
| Hợp đồng mẫu | Hợp đồng vận chuyển, hợp đồng phân phối | cao |
| Quy định nội bộ | Quy trình giao nhận, quy định bồi thường hàng hỏng | trung bình |
| Catalog sản phẩm | Thông số dầu nhớt, hạn dùng, quy cách đóng gói | trung bình |
| Chính sách công nợ | Hạn mức, điều kiện | trung bình |

### Hai thứ phải hỏi kèm mỗi tài liệu
1. **Bản này còn hiệu lực không, từ ngày nào?** Bảng giá cũ nằm lẫn với bảng giá
   mới là nguồn sai nguy hiểm nhất — hệ thống sẽ trả lời tự tin bằng giá năm ngoái.
2. **Tài liệu này ai được xem?** Có thứ nhân viên giao nhận không nên đọc được
   (giá vốn, biên lợi nhuận, điều khoản riêng với từng khách).

Định dạng: `.docx` / `.pdf` bản mềm. Bản scan cũng nhận được nhưng kém chính xác hơn.

---

## Việc cần nói rõ với khách về bảo mật


Ba mục 1, 5, 8 chứa **giá vốn từng mặt hàng** — thứ nhạy cảm nhất của một nhà
phân phối, vì từ đó suy ra được biên lợi nhuận với từng khách.

Cần nói trước, đừng để họ tự phát hiện:
- File tải lên **không được lưu lại** ở máy chủ AI — đọc trong bộ nhớ rồi thả.
- Dữ liệu nằm trong cơ sở dữ liệu của ANSER, không gửi sang dịch vụ AI bên ngoài.
- Khi cần chạy trên GPU thuê, phần tính toán tài chính vẫn chạy bằng code thuần
  ở máy mình, không đi qua model.

---

## Ba câu hỏi cần trả lời trước khi rời buổi làm việc


1. **Giá vốn đang được tính theo phương pháp nào — FIFO hay bình quân gia quyền?**
   Hai bản PDF hiện có mang dấu hiệu của cả hai. Cần biết chắc, vì kiểm sổ dựa
   vào giả định này.

2. **Hoá đơn bán dầu nhớt từ 01/7/2025 đến nay đang ghi thuế suất 8% hay 10%?**
   Nghị định 174/2025 đưa dầu mỡ bôi trơn vào diện giảm còn 8% từ ngày đó, khác
   với nhiều năm trước. Danh mục 161 mã đang để "Chưa xác định" nên phần mềm
   không tự áp — mỗi hoá đơn chọn tay một kiểu được. Đây là câu đáng tiền nhất
   trong ba câu.

3. **Số liệu tồn kho trong MISA có khớp với đếm kho thật không, lần kiểm kê gần
   nhất là khi nào?** Nếu sổ đã lệch thực tế từ lâu thì kiểm sổ chỉ soi được
   mâu thuẫn trong sổ, không soi được mất mát thật.
---

# Phụ lục — dành cho khi công ty mở mảng vận tải

> **Chưa cần đến.** Bốn mục dưới đây là dữ liệu cho công thức báo giá cước và
> chọn nhà xe. Công ty hiện chuyên bán dầu nhớt nên chưa dùng tới. Giữ lại
> nguyên văn để khỏi phải viết lại nếu sau này có nhu cầu.
>
> Phần mềm đã có sẵn engine cho hai việc này, nhưng **chưa hiệu chỉnh trên số
> thật của ai** — nên chưa dùng được cho khách, kể cả khi có dữ liệu.

### PL-1. Báo giá vận tải đã chốt — 15–20 dòng


Đây là thứ mở khoá **công thức giá**: từ giá nhà xe báo → ra giá mình báo khách.

### Lấy file mẫu
```bash
python offline_training/calibrate.py template --what quotes --out bao_gia.csv
```

### Cột (đúng tên này)
| Cột | Nghĩa | Bắt buộc |
|---|---|---|
| `quote_id` | Mã báo giá | không |
| `date` | Ngày báo giá (YYYY-MM-DD) | nên có |
| `route` | Tuyến, ví dụ `Hà Nội → Đà Nẵng` | nên có |
| `vehicle_type` | `xe tải 5 tấn`, `container 20ft`... | nên có |
| `carrier_cost` | **Giá NHÀ XE báo cho mình hôm đó** | **bắt buộc** |
| `fuel_price` | **Giá dầu ngày hôm đó** | bắt buộc nếu muốn hiệu chỉnh nhiên liệu |
| `actual_price` | **Giá MÌNH BÁO khách và đã CHỐT** | **bắt buộc** |
| `surcharges` | `bốc xếp:500000;lưu ca:300000` | không |
| `note` | Ghi chú | không |

### Hai điều kiện dễ bị bỏ qua
1. **Chỉ lấy báo giá ĐÃ CHỐT.** Báo giá khách từ chối phản ánh mức mình *muốn*
   lấy, không phải mức thị trường chấp nhận — trộn vào sẽ đẩy công thức lên cao.
2. **`fuel_price` phải TRẢI ĐỀU nhiều mức khác nhau.** 20 dòng cùng một mức giá
   dầu thì không tách nổi "biên cố định" khỏi "phần điều chỉnh theo dầu" — hệ
   thống sẽ cảnh báo và bỏ qua phần nhiên liệu. Cần chênh lệch **ít nhất 3%**
   giữa mức cao nhất và thấp nhất.

### Chạy
```bash
python offline_training/calibrate.py pricing --csv bao_gia.csv
```
Ngưỡng đạt: **MAPE ≤ 5%**. Đạt thì có công thức dùng được. Không đạt cũng có
giá trị — nó nói thẳng rằng giá đang đặt theo cảm tính từng ca, không theo quy
tắc nào, và đó là một phát hiện đáng tiền.

---

### PL-2. Danh sách nhà xe


```bash
python offline_training/calibrate.py template --what carriers --out nha_xe.csv
```

| Cột | Nghĩa |
|---|---|
| `carrier_id` | Mã tự đặt, ví dụ `NX01` |
| `name` | Tên nhà xe |
| `vehicle_types` | Nhiều loại ngăn bằng `\|`: `xe tải 5 tấn\|xe tải 8 tấn` |
| `depot_lat`, `depot_lon` | Toạ độ bãi xe (mở Google Maps, chuột phải → toạ độ) |
| `discount_pct` | % ưu đãi đang có |
| `credit_days` | Số ngày cho nợ |
| `years_partner` | Số năm hợp tác |
| `on_time_rate` | Tỷ lệ đúng hẹn, `0.94` = 94% |

`on_time_rate` **ước lượng cũng được** — biết "thằng này hay trễ" là đã có
thông tin, còn hơn để trống. Nhưng phải nói rõ là ước lượng.

---

### PL-3. Lịch sử chọn nhà xe — 30–50 ca


Đây là thứ dạy hệ thống **thứ tự ưu tiên thật** của công ty. Hỏi miệng thì ai
cũng nói "ưu tiên giá"; số liệu thường nói khác.

```bash
python offline_training/calibrate.py template --what choices --out chon_xe.csv
```

| Cột | Nghĩa |
|---|---|
| `case_id` | Mã ca — **nhiều dòng cùng `case_id` = các lựa chọn của cùng một chuyến** |
| `origin`, `destination` | Điểm đi / điểm đến |
| `vehicle_type` | Loại xe cần |
| `origin_lat`, `origin_lon` | Toạ độ điểm lấy hàng |
| `carrier_id` | Khớp với file nhà xe ở mục 3 |
| `offer_price` | Giá nhà xe đó báo cho ca này |
| `chosen` | `1` cho nhà xe được chọn, `0` cho các nhà xe còn lại |
| `note` | Vì sao chọn — **rất có giá trị** |

### Điều kiện quan trọng nhất
**Mỗi ca phải có ít nhất 2 nhà xe cùng báo giá.** Ca chỉ có một lựa chọn thì
không dạy được gì — "chọn đúng" là hiển nhiên khi chỉ có một cửa. Hệ thống đếm
riêng số ca có nhiều lựa chọn (`top1_accuracy_informative_pct`) chính vì lý do
này; nếu toàn ca một lựa chọn, độ chính xác sẽ hiện 100% mà vô nghĩa.

### Xin cả những ca chọn "sai"
Ca mà công ty chọn nhà xe **đắt hơn** đặc biệt quý — nó cho biết cái gì đủ quan
trọng để đánh đổi lấy tiền (gần bãi? cho nợ lâu? xe đời mới?). Ghi lý do vào cột
`note`.

### Chạy (cần cả file ở mục 3)
```bash
python offline_training/calibrate.py carriers --carriers nha_xe.csv --choices chon_xe.csv
```

---

### PL-4. Hoá đơn giấy của nhà xe — 30–50 ảnh


Dành cho thứ **chỉ tồn tại dưới dạng ảnh**. Hoá đơn nhà xe thường là giấy viết
tay hoặc in kim, không có bản mềm.

### Xin thế nào
Chụp bằng điện thoại, để nguyên — **đừng chọn ảnh đẹp**.

### Phải có cả hoá đơn xấu
Đây là điểm quan trọng nhất của mục này. Cần đủ các kiểu:
- chụp nghiêng, thiếu sáng, có bóng tay
- giấy nhàu, mờ, in kim bị nhoè
- viết tay
- có dấu đỏ đè lên số tiền
- ảnh chụp màn hình Zalo (nhà xe gửi qua Zalo rất phổ biến)

Chỉ đưa hoá đơn chụp đẹp thì hệ thống sẽ đạt điểm cao lúc thử và hỏng lúc dùng
thật. Số liệu trên hoá đơn xấu mới là số liệu đáng tin.

### Kèm theo
Với **10–15 tờ**, ghi tay ra một file Excel số tiền đúng của từng tờ (tổng tiền,
ngày, tên nhà xe, tuyến). Đây là thước đo — không có nó thì không biết hệ thống
đọc đúng hay sai.

---

