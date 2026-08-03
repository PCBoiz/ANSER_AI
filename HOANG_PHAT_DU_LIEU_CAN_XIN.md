



## Bảng tóm tắt 

| # | Thứ cần xin | Số lượng | Định dạng | Mở khoá được gì | Không có thì sao |
|---|---|---|---|---|---|
| 1 | Bảng tổng hợp Nhập–Xuất–Tồn | 1 file/kỳ | **.xlsx** | Kiểm sổ kho (đã chạy được) | Chỉ còn 2 bản PDF, phải gõ tay |
| 2 | Báo giá vận tải đã chốt | **15–20 dòng** | .csv/.xlsx | Công thức giá tự động | Phải hỏi khách "anh tính thế nào" và tin lời kể |
| 3 | Danh sách nhà xe | 5–15 dòng | .csv/.xlsx | Chọn nhà xe có trọng số | Không chạy được mục 4 |
| 4 | Lịch sử chọn nhà xe | **30–50 ca** | .csv/.xlsx | Trọng số ưu tiên thật | Dùng trọng số mặc định, có thể sai hẳn |
| 5 | Giá vốn từng mặt hàng | toàn bộ SKU | .xlsx hoặc nhập tay | Báo cáo lãi lỗ đáng tin | Báo cáo mãi ở "độ tin cậy thấp" |
| 6 | Hoá đơn giấy nhà xe | 30–50 ảnh | ảnh chụp | Đọc hoá đơn tự động (GĐ 3b) | Gõ tay từng tờ |
| 7 | Tài liệu nội bộ | 10–30 file | .docx/.pdf | Hỏi đáp nội bộ (GĐ 3a) | Model trả lời chung chung |
| 8 | Danh mục hàng + khách | toàn bộ | .xlsx | Nạp dữ liệu đầu vào ANSER | Nhập tay từng dòng, **và mục 5 không khớp được mã** |

**Ba thứ chặn nhiều việc nhất: mục 1, 2, 4.** Nếu chỉ xin được ba thứ, xin ba thứ đó.

**Xin mục 8 TRƯỚC mục 1.** Chạy thử trên dữ liệu thật cho ra 0/2 mã khớp — nạp
giá vốn từ bảng N-X-T chỉ chạy khi mã hàng hai bên là một. Nạp danh mục vào
trước thì mọi thứ sau đó khớp; làm ngược lại là phải đối chiếu tay từng dòng.

---

## 1. Bảng tổng hợp Nhập – Xuất – Tồn (.xlsx)

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

## 2. Báo giá vận tải đã chốt — **15–20 dòng**

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

## 3. Danh sách nhà xe

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

## 4. Lịch sử chọn nhà xe — **30–50 ca**

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

## 5. Giá vốn từng mặt hàng

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

## 6. Hoá đơn giấy của nhà xe — 30–50 ảnh (GĐ 3b)

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

## 7. Tài liệu nội bộ (GĐ 3a — hỏi đáp)

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

## 8. Danh mục nền

Để nạp dữ liệu vào ANSER thay vì gõ tay từng dòng.

| File | Cột cần có |
|---|---|
| Danh mục hàng hoá | Mã, Tên, ĐVT, Nhóm hàng, Giá bán, **Giá vốn**, Tồn hiện tại |
| Danh mục khách hàng | Tên, MST, Địa chỉ, Điện thoại, Email, Công nợ hiện tại |
| Danh mục nhà cung cấp | Tên, MST, Địa chỉ, Điện thoại |
| Danh sách kho | Tên kho, Địa chỉ |

Xuất từ MISA: *Danh mục → \<loại\> → Xuất khẩu → Excel*.

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

2. **Ai là người ra giá cuối cùng cho khách, và họ có làm theo bảng nào không?**
   Nếu mỗi ca một kiểu thì mục 2 sẽ không hiệu chuẩn ra công thức — nhưng biết
   được điều đó cũng là kết quả, và nó đổi hướng sản phẩm.

3. **Số liệu tồn kho trong MISA có khớp với đếm kho thật không, lần kiểm kê gần
   nhất là khi nào?** Nếu sổ đã lệch thực tế từ lâu thì kiểm sổ chỉ soi được
   mâu thuẫn trong sổ, không soi được mất mát thật.
