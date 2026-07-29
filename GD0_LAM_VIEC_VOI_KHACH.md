# Giai đoạn 0 — Buổi làm việc với khách

> Việc này **chặn mọi giai đoạn khác** trong [ROADMAP.md](ROADMAP.md), dù nó không
> có một dòng code nào. Lý do: `fuel_sensitivity = 0.35` và bộ trọng số chọn nhà xe
> hiện tại là **giả định đọc từ bản ghi phỏng vấn**, chưa một con số thật nào chạy
> qua. Fine-tune giỏi mấy cũng không cứu được một công thức giá sai — model chỉ học
> cách gọi tool thật thuần thục để trả về một con số sai.
>
> Sai ở tuần 1: mất một buổi. Sai phát hiện ở tuần 10: mất toàn bộ dữ liệu đo, toàn
> bộ lần fine-tune, và niềm tin của khách.

**Cổng ra:** chạy 15-20 báo giá lịch sử qua engine, sai lệch tuyệt đối trung bình **< 5%**.

---

## 1. Chuẩn bị trước khi đi

Sinh sẵn ba file mẫu, gửi khách trước 2-3 ngày để họ có thời gian tra sổ:

```bash
python -m offline_training.calibrate template --what quotes   --out bao_gia_lich_su.csv
python -m offline_training.calibrate template --what carriers --out nha_xe.csv
python -m offline_training.calibrate template --what choices  --out lua_chon.csv
```

Mang theo: laptop chạy được lệnh trên, và bản in mục 5 (câu hỏi về tồn kho).

---

## 2. Dữ liệu cần xin — theo thứ tự ưu tiên

| # | Thứ cần | Vì sao | Không có thì sao |
|---|---|---|---|
| 1 | **15-20 báo giá đã chốt**, kèm giá nhà xe và giá dầu ngày đó | Nguồn duy nhất kiểm chứng được công thức giá | Không qua được cổng GĐ 0, mọi thứ sau đó xây trên cát |
| 2 | **10-15 lần chọn nhà xe**, kèm các bên đã chào giá lúc đó | Hiệu chỉnh trọng số | Giữ trọng số mặc định, chấp nhận rủi ro gợi ý sai |
| 3 | File `.xlsx` **TỔNG HỢP TỒN KHO** (đã có) | Giá vốn cho báo cáo lãi lỗ | Báo cáo phải tự thú "chỉ 62% doanh thu có giá vốn" |
| 4 | 30-50 ảnh **hoá đơn nhà xe** | Dữ liệu đo cho VLM (GĐ 3b) | Không biết VLM có đủ dùng không, phải đoán |
| 5 | Bảng giá nhà xe hiện hành | Đầu vào thật cho `compute_quote` | Phải nhập tay từng lần |

**Điểm dễ hỏng nhất:** cột `fuel_price`. Nếu tất cả báo giá đều cùng một mức giá dầu
thì **không thể** ước lượng `fuel_sensitivity` — mọi giá trị 0..1 cho kết quả y hệt.
Nói rõ với khách: cần báo giá **trải đều nhiều thời điểm giá dầu khác nhau**, tối
thiểu chênh 3% giữa mức thấp nhất và cao nhất. Engine sẽ từ chối hiệu chỉnh và nói
thẳng nếu dữ liệu không đủ điều kiện.

---

## 3. Câu hỏi về công thức giá

Hỏi theo thứ tự này. Mỗi câu tương ứng một tham số trong `PricingRule`.

**3.1. Biên lợi nhuận** → `base_margin_pct`
- Anh cộng thêm bao nhiêu phần trăm lên giá nhà xe báo? Con số đó cố định hay tuỳ khách?
- Có khách nào được giá riêng không? Dựa vào đâu — sản lượng, thâm niên, hay quan hệ?
- Có mức lãi tối thiểu tuyệt đối không? *(Ví dụ: "chuyến nào cũng phải lời ít nhất 500k, dưới đó không nhận")* → `min_margin_amount`

**3.2. Nhiên liệu** → `fuel_sensitivity`, `fuel_baseline_price`
- Dầu tăng 10% thì anh tăng giá báo bao nhiêu phần trăm? *(Đây là câu quan trọng nhất. Nếu khách trả lời "tăng 10%" thì `fuel_sensitivity = 1.0`, khác hẳn giả định 0,35 của chúng ta.)*
- Anh nhìn giá dầu ở đâu, cập nhật lúc nào? Giá bán lẻ Petrolimex hay giá nhà xe báo?
- Bảng giá nhà xe hiện tại chốt lúc dầu bao nhiêu? → `fuel_baseline_price`
- Nhà xe tự tăng giá khi dầu lên, hay anh phải tự cộng vào?

*Câu cuối quyết định cả kiến trúc:* nếu nhà xe **đã** tính dầu vào giá báo, thì
`fuel_adjustment` của chúng ta đang **tính hai lần**.

**3.3. Phụ phí** → `Surcharge`
- Ngoài cước có những khoản nào hay cộng thêm? (bốc xếp, chờ, hàng lạnh, quá tải, lưu bãi…)
- Khoản nào tính cố định, khoản nào tính theo % cước?
- Khoản nào ghi rõ trên báo giá gửi khách, khoản nào gộp vào giá chung?

**3.4. Làm tròn**
- Anh chốt giá theo bậc nghìn hay bậc chục nghìn? *(Engine đang làm tròn 1.000đ.)*

---

## 4. Câu hỏi về chọn nhà xe

Đừng hỏi "anh cho điểm mỗi tiêu chí mấy phần trăm" — không ai trả lời được thật.
Hỏi bằng **tình huống**:

- Hai nhà xe cùng chạy được tuyến này, bên A rẻ hơn 500 nghìn nhưng bên B cho nợ 30 ngày còn bên A đòi trả ngay. Anh gọi bên nào?
- Nếu bên rẻ hơn từng trễ hàng một lần trong 10 chuyến, anh còn dùng không?
- Bãi xe gần điểm lấy hàng có quan trọng không? Gần hơn 20km thì anh chịu trả thêm bao nhiêu?
- Có nhà xe nào **luôn** gọi đầu tiên bất kể giá không? Vì sao?
- Có nhà xe nào anh **không bao giờ** dùng dù rẻ? Vì sao? → đây là **ràng buộc cứng**, không phải trừ điểm

Ghi lại nguyên văn câu trả lời vào cột `note` của `lua_chon.csv`. Khi engine chọn
sai, chính ghi chú đó giải thích vì sao.

---

## 5. Câu hỏi từ dữ liệu tồn kho đã có

Đã chạy engine trên hai file `.xlsx`. Ba câu dưới đây quyết định mỗi phát hiện là
lỗi thật hay chuyện bình thường:

**5.1.** `VT00059` (Diesel CI4/SL 15W40 200L) tồn cuối kỳ **âm 21 lít**: 87 + 4.400 − 4.508.
Kho `KM00034` cũng âm 115,2 lít.
→ *Thiếu phiếu nhập chưa vào sổ, hay sai quy đổi phuy 200L sang lít?*

**5.2.** Kho khuyến mại có **9.196 đơn vị nhập, 8.568 tồn, giá trị bằng 0 tuyệt đối**.
→ *Đây có phải hàng ENEOS tài trợ không?*
- **Nếu tài trợ:** giá trị 0 là hợp lệ, không cần sửa.
- **Nếu công ty tự mua để khuyến mại:** chi phí đang **bỏ ngoài sổ**, lãi gộp đang cao hơn thực tế.

**5.3.** Sổ đang dùng **hai phương pháp giá vốn song song** — `VT00015/00022` theo bình
quân, `VT00013/00025` theo FIFO. VAS 02 buộc nhất quán.
→ *Kế toán có biết không? Có phải do đổi phần mềm hay đổi người làm giữa kỳ?*

**Thêm, dạng cơ hội chứ không phải lỗi:**
- `VT00013` tồn đủ bán **7,6 năm** (96,9 triệu đọng). `VT00009` không xuất đơn vị nào trong 204 ngày (45,4 triệu). → *Có định xả không?*
- `VT00025` giá nhập **+31,7%** mà 7 tháng chỉ bán 105 lít. → *Giá bán đã tăng theo chưa?*
- `VT00002` giá vốn hàng còn tồn cao hơn hàng đã bán **12%**. → *Bán hết chỗ này ở giá hiện tại thì biên kỳ sau hẹp lại — có biết không?*

---

## 6. Câu hỏi cho VLM (chuẩn bị GĐ 3b)

- Hoá đơn nhà xe gửi bằng gì — ảnh chụp Zalo, PDF, hay giấy?
- Mỗi tháng khoảng bao nhiêu tờ? Ai nhập vào sổ, mất bao lâu?
- Trên tờ hoá đơn, những ô nào **bắt buộc** phải đúng? *(số tiền, biển số xe, tuyến, ngày…)*
- Nhập sai một tờ thì phát hiện lúc nào, sửa thế nào?
- **Xin 30-50 tờ thật**, gồm cả những tờ xấu: mờ, chụp nghiêng, viết tay, có dấu đè.

*Tờ xấu quan trọng hơn tờ đẹp.* Đo trên toàn hoá đơn đẹp rồi kết luận "đạt 95%" là
tự lừa mình — thực tế chạy sẽ toàn tờ xấu.

---

## 7. Sau buổi làm việc — chạy gì

```bash
# Công thức giá (thay số theo câu trả lời mục 3)
python -m offline_training.calibrate pricing \
    --csv bao_gia_lich_su.csv \
    --margin 10 --fuel-sens 0.35 --fuel-baseline 25000 \
    --json ket_qua.json

# Trọng số chọn nhà xe
python -m offline_training.calibrate carriers \
    --carriers nha_xe.csv --choices lua_chon.csv
```

---

## 8. Đọc kết quả — bốn cái bẫy

**8.1. "ĐẠT" chưa chắc là đúng.**
Công cụ báo `⛔ ĐẠT GIẢ` khi quy tắc hiện tại lọt cổng < 5% nhưng bộ hiệu chỉnh còn
tốt hơn rõ rệt. Quan sát thật khi chạy thử: biên giả định 10% (thật là 13,5%) vẫn cho
sai lệch 4,62% → "ĐẠT", trong khi hiệu chỉnh kéo xuống 1,68%. **Lọt cổng không có
nghĩa là tham số đúng.**

**8.2. Trung bình che mất thảm hoạ.**
Luôn đọc cột `p90` và `max`, không chỉ trung bình. Sai lệch trung bình 4% có thể là
19 chuyến lệch 1% và 1 chuyến lệch 60%. Xem danh sách **5 ca lệch nhất** — mỗi ca là
một câu hỏi cho khách: *"chuyến này vì sao anh báo giá đó?"* Thường câu trả lời là
"phá giá giành khách mới" hoặc "khách ruột nên bớt" — đó là **quy tắc chưa được khai
báo**, không phải công thức sai.

**8.3. Hệ số dầu có thể không ước lượng được.**
Nếu thấy cảnh báo `KHÔNG ước lượng được fuel_sensitivity`, đừng dùng con số engine
đưa ra. Quay lại xin thêm báo giá ở các mức giá dầu khác nhau.

**8.4. Trọng số có thể là học thuộc.**
So `Trong mẫu` với `Kiểm chéo bỏ-một`. Chênh nhau ≥ 15 điểm nghĩa là bộ trọng số
đang thuộc lòng 15 ca đã cho chứ không nắm được quy tắc. Lúc đó **đừng dùng** —
quay lại hỏi khách trực tiếp về thứ tự ưu tiên.

---

## 9. Quyết định sau GĐ 0

| Kết quả | Làm gì tiếp |
|---|---|
| Sai lệch < 5% và không "ĐẠT GIẢ" | Chốt tham số, mở khoá GĐ 1 và GĐ 2 |
| Sai lệch < 5% nhưng "ĐẠT GIẢ" | Dùng bộ hiệu chỉnh, chạy lại, rồi mới mở khoá |
| Sai lệch 5-15% | Xem 5 ca lệch nhất — gần như chắc chắn có quy tắc chưa khai báo. Bổ sung rồi chạy lại |
| Sai lệch > 15% | **Dừng.** Công thức đang sai về bản chất, không phải sai tham số. Ngồi lại với khách dựng lại công thức từ đầu |
