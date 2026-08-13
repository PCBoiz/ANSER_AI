# Hoàng Phát — kết quả soát sổ trên dữ liệu ngày 11/08/2026

**Gửi:** Công ty TNHH Thương mại Dịch vụ Đầu tư Hoàng Phát (MST 0109527605)
**Dữ liệu đã đọc:** 4 file .xlsx xuất từ MISA ngày 13/08/2026
**Kỳ:** 01/01/2026 → 11/08/2026 (223 ngày), kho HÀNG HÓA

| File | Dòng đọc được | Cảnh báo khi đọc |
|---|---|---|
| Tổng hợp tồn kho (đến 11/08) | 121/121 | không |
| Danh sách hàng hóa, dịch vụ | 161/161 | không |
| Danh sách khách hàng | 104/104 | không |
| Danh sách nhà cung cấp | 42/42 | không |

Toàn bộ số liệu dưới đây **đối chiếu tay được** từ ô gốc trong file. Chỗ nào
chúng tôi chưa chắc, chúng tôi nói rõ là chưa chắc.

---

## 1. Có chứng từ bị sửa sau khi đã xuất báo cáo

Đây là phát hiện quan trọng nhất, và nó **chỉ nhìn ra được khi so hai bản xuất**
— không bản báo cáo đơn lẻ nào cho thấy điều này.

Hai bản cùng bắt đầu từ **01/01/2026**:

| Mã hàng | Bản đến 24/07 | Bản đến 11/08 | Chênh |
|---|---|---|---|
| VT00059 | xuất **4.508** → tồn **−21** | xuất **4.400** → tồn **+87** | **−108** |
| VT00039 | xuất **306** → tồn 0 | xuất **414** → tồn **−108** | **+108** |
| VT00023 | xuất **1.816** | xuất **1.800** | **−16** |

**Vì sao đây chắc chắn là sửa chứ không phải phát sinh mới:** hai bản có cùng
ngày bắt đầu, bản sau kéo dài thêm 18 ngày. Số xuất luỹ kế của một kỳ dài hơn
chỉ có thể **tăng lên hoặc giữ nguyên**. Giảm xuống là chuyện thời gian không
cho phép — nghĩa là một chứng từ nằm trong quãng đã báo cáo đã bị sửa, xoá, hoặc
huỷ ghi sổ.

**Điều đáng chú ý hơn:** VT00059 giảm đúng 108 lít, VT00039 tăng đúng 108 lít, ở
cùng cột xuất. Nhiều khả năng một phiếu xuất bị **sửa mã hàng** để dập lỗi âm
kho ở VT00059 — và lỗi mọc lại nguyên vẹn ở VT00039, mã nhận, vốn cũng không đủ
hàng. Lỗi được **dời chỗ**, không được xử lý.

> Chúng tôi nêu chênh lệch số liệu, **không quy trách nhiệm cho ai**. Sổ chi tiết
> của ba mã này sẽ cho biết chính xác chứng từ nào.

**Việc nên làm:** khoá sổ theo tháng. Chốt xong thì không sửa được chứng từ của
kỳ đã báo cáo nữa — đây là cách duy nhất chặn tận gốc, vì hiện tại báo cáo thuế
đã nộp và sổ sinh ra nó không còn khớp nhau.

---

## 2. Hai mã đang âm kho — một trong hai làm lãi gộp cao hơn thực tế

### VT00039 — 108 lít xuất mà giá vốn ghi 0

```
đầu kỳ 18  +  nhập 288  −  xuất 414  =  −108 lít
giá trị cuối kỳ: 0 đồng
```

Sổ ghi **giá trị bằng 0** cho phần xuất vượt. Nguy hiểm hơn hẳn trường hợp ghi
số âm, vì báo cáo lãi lỗ trông vẫn hoàn toàn bình thường — chỉ có lãi gộp cao
lên đúng bằng phần giá vốn bị bỏ.

Đơn giá nhập bình quân trong kỳ: **51.819 đ/lít**
→ **108 × 51.819 = 5.596.500 đ giá vốn chưa được ghi nhận.**

### VT00042 — xuất đúng gấp đôi số có

```
đầu kỳ 16  +  nhập 0  −  xuất 32  =  −16 lít
giá trị cuối kỳ: −1.023.583 đ
```

Xuất **32 trên tồn 16** — đúng gấp đôi, và giá trị âm bằng đúng số âm của giá
trị đầu kỳ. Đây là dấu hiệu điển hình của **một phiếu xuất bị nhập hai lần**.

**Cần kiểm:** sổ chi tiết ba mã VT00039, VT00042, VT00023 trong kỳ.

---

## 3. Dầu nhớt đang được giảm còn 8% — cả 161 mã đều chưa gắn cờ

Cột **"Giảm 2% thuế suất thuế GTGT"** trong danh mục hàng hóa đang để
**"Chưa xác định" cho toàn bộ 161/161 mã**.

**Vì sao điều này đáng tiền:**

Nghị định **174/2025/NĐ-CP** (theo Nghị quyết 204/2025/QH15) đã **bỏ** "sản phẩm
dầu mỏ tinh chế" khỏi danh mục KHÔNG được giảm thuế — trong đó ghi rõ **dầu mỡ
bôi trơn**. Hiệu lực **01/7/2025 → 31/12/2026**, tức phủ trọn kỳ đang xét.

Nhiều năm trước nhóm này chịu 10%, nên đây là thay đổi rất dễ bỏ sót vì nó đi
ngược thói quen.

Bảng tra của chúng tôi chạy trên 161 mã:

| Kết luận | Số mã |
|---|---|
| Thuộc diện giảm còn **8%** | 157 |
| Giữ **10%** — "Bia 333" (hàng khuyến mại, chịu thuế TTĐB) | 1 |
| Cần kế toán tự xác nhận | 2 |
| Không phải hàng hoá (Chi phí mua hàng) | 1 |

**Hai câu hỏi cần Hoàng Phát trả lời:**

1. Hoá đơn bán dầu nhớt từ 01/7/2025 đến nay đang ghi thuế suất **8% hay 10%**?
2. Nếu đang ghi 10%: bên mua — phần lớn là các công ty xây dựng lớn có bộ phận
   kế toán riêng — có quyền yêu cầu điều chỉnh hoá đơn.

Cờ chưa gắn nghĩa là phần mềm **không tự áp thuế suất**, thuế suất do người nhập
chọn tay trên từng hoá đơn. Gắn cờ cho cả danh mục thì phần mềm tự áp và tự chặn.

> Đây là **đề xuất kèm căn cứ**, không phải kết luận thay kế toán. Người chịu
> trách nhiệm về thuế suất trên hoá đơn vẫn là kế toán của doanh nghiệp.

---

## 4. Bức tranh tiền — chỗ này mới là rủi ro lớn nhất

| | Số tiền | Quy ra ngày giá vốn |
|---|---|---|
| Khách đang nợ mình | **3.962.266.920 đ** | **113 ngày** |
| Hàng nằm trong kho | 2.874.073.721 đ | 82 ngày |
| Mình đang nợ nhà cung cấp | 1.410.141.691 đ | 40 ngày |
| **Vốn lưu động bị kẹt** | **5.426.198.950 đ** | **154 ngày** |

*(Giá vốn bán ra: 7.833.688.922 đ trong 223 ngày = 35.128.650 đ/ngày)*

**Tiền nằm ở khách nhiều hơn nằm ở kho.** Với một công ty 4–5 người, đây là rủi
ro lớn hơn hẳn chuyện tồn kho.

### Tập trung khách hàng

| Khách | Số dư | Tỷ lệ |
|---|---|---|
| CÔNG TY CỔ PHẦN 479 HOÀ BÌNH | 1.129.540.864 đ | **29%** |
| CÔNG TY CỔ PHẦN CÔNG TRÌNH NGẦM FECON | 1.034.878.826 đ | 26% |
| CÔNG TY CỔ PHẦN XÂY DỰNG QUỐC GIA | 448.754.802 đ | 11% |
| **Ba khách lớn nhất** | **2.613.174.492 đ** | **66%** |

Một khách chậm trả là cả công ty đứng hình. Nhóm này nên theo dõi riêng hằng
tuần, có hạn mức công nợ và điều kiện thanh toán riêng — chứ không gộp chung vào
danh sách 104 khách.

### Tám khách có số dư phải thu ÂM — tổng ~78,9 triệu

| Mã | Khách | Số dư |
|---|---|---|
| KH00029 | CÔNG TY CP THƯƠNG MẠI VÀ DỊCH VỤ… | −31.206.600 |
| KH00021 | CÔNG TY TNHH TM & DV PHƯƠNG… | −28.962.041 |
| KH00094 | CÔNG TY TNHH BIGTOWN VIỆT NAM | −4.955.580 |
| KH00062 | CÙ ĐỨC ANH | −4.152.000 |
| KH00055 | NGUYỄN TRƯƠNG THANH | −3.048.000 |
| KH00065 | NGUYỄN VĂN TUẤN | −2.784.000 |
| KH00066 | NGUYỄN HẢI QUÂN | −2.544.000 |
| KH00053 | TRẦN ĐÌNH QUÂN | −1.296.000 |

Phải thu âm nghĩa là khách đã trả nhiều hơn số nợ ghi nhận: **tiền về rồi mà hoá
đơn chưa xuất**, hoặc một khoản mua hàng của chính đối tác đó bị ghi vào tài
khoản phải thu.

**KH00021 đáng chú ý riêng:** đối tác này nằm trong **cả hai** danh sách — vừa là
khách hàng vừa là nhà cung cấp. Số dư phải thu −28,9 triệu trong khi số dư phải
trả bằng 0. Gần như chắc chắn nghiệp vụ **mua hàng bị ghi vào tài khoản phải
thu**. Cần tách lại theo đúng vai trò rồi mới đối chiếu.

### Ba nhà cung cấp có số dư phải trả âm — tiền của mình đang nằm ở họ

NCC00037 Toàn Cầu ALIZ (−756.000) · NCC00026 Chi nhánh Mắt Bão (−458.000) ·
NCC00003 HATEK (−3.000). Đối chiếu để trừ vào đơn sau.

### Mã số thuế — danh mục sạch

Mã số thuế 10 số có chữ số cuối là **số kiểm tra** tính từ 9 chữ số đầu, nên gõ
sai một chữ số là phát hiện được ngay mà không cần tra cứu.

- **114 mã kiểm được — 0 mã sai.** Danh mục đối tác của Hoàng Phát sạch ở khoản
  này, không phải doanh nghiệp nào cũng vậy.
- 5 mã dạng **chi nhánh 13 số** (Đăng kiểm 29-06V, Mắt Bão, PVI Đông Đô, Golden
  Gate, Thái Minh Hải Phòng) — hợp lệ.
- 5 khách dùng **số định danh cá nhân 12 số** (3 hộ kinh doanh, 2 cá nhân) — đúng
  theo Thông tư 86/2024/TT-BTC, áp dụng từ 01/7/2025. Không có số kiểm tra nên
  không đối chiếu được, nhưng đúng khuôn.
- 27 khách lẻ chưa có mã số thuế — bình thường với khách cá nhân.

---

## 5. Tồn kho: 29 mã không xuất một đơn vị nào trong 222 ngày

Tổng giá trị nhóm này khoảng **160 triệu**. Ba mã nặng nhất:

| Mã | Giá trị tồn |
|---|---|
| VT00009 | 45.408.459 đ |
| VT00092 | 21.024.000 đ |
| VT00019 | 21.010.369 đ |

Ngoài ra **VT00013** tồn đủ bán **~8,3 năm** theo nhịp bán hiện tại (96,8 triệu).

Đây không phải lỗi sổ sách — là vốn đang nằm im. Cân nhắc xả hàng hoặc trả lại
nhà cung cấp.

---

## 6. Chúng tôi CHƯA kiểm được gì

Nói ra để không ai đọc báo cáo này rồi tưởng đã kiểm hết:

| Chưa làm được | Cần thêm gì |
|---|---|
| **Tuổi nợ** (30/60/90 ngày), nợ quá hạn | Sổ chi tiết công nợ phải thu, có ngày hoá đơn |
| Kho **KHUYẾN MẠI** — mã KM00034 âm 115,2 lít ở bản 24/07 | Bản xuất tồn kho kho KM đến 11/08 |
| Chứng từ cụ thể của 3 mã bị sửa | Sổ chi tiết VT00039, VT00042, VT00023 |
| Thuế suất thực tế đang ghi trên hoá đơn | Vài hoá đơn bán ra sau 01/7/2025 |
| Lãi gộp thật | Doanh thu theo mã hàng (hiện chỉ có giá vốn) |

---

## Bốn việc nên làm, theo thứ tự

1. **Kiểm 3 mã bị sửa hồi tố** (VT00039, VT00042, VT00023) — và kiểm cả mã nhận,
   đừng chỉ kiểm mã báo lỗi.
2. **Xác minh thuế suất dầu nhớt** đang ghi trên hoá đơn từ 01/7/2025 → gắn cờ
   cho cả danh mục.
3. **Khoá sổ theo tháng** để chặn sửa hồi tố.
4. **Tách riêng 3 khách lớn** (66% phải thu) ra theo dõi hằng tuần, đặt hạn mức.

---

*Báo cáo do ANSER sinh tự động từ 4 file MISA, mọi con số truy được về ô gốc.
Phần thuế suất là đề xuất kèm căn cứ pháp lý, cần kế toán xác nhận trước khi áp
dụng.*
