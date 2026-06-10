# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** CS-IT-Ops  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Lương Thị Hồng Nhung | Ingestion / Raw Owner | luonghongnhung@company.internal |
| Lương Thị Hồng Nhung | Cleaning & Quality Owner | luonghongnhung@company.internal |
| Lương Thị Hồng Nhung | Embed & Idempotency Owner | luonghongnhung@company.internal |
| Lương Thị Hồng Nhung | Monitoring / Docs Owner | luonghongnhung@company.internal |

**Ngày nộp:** 2026-06-10  
**Repo:** `2A202600811-LuongThiHongNhung_Day10`  
**Độ dài:** ~800 từ

---

## 1. Pipeline tổng quan (150–200 từ)

Hệ thống Data Pipeline của nhóm CS-IT-Ops được xây dựng nhằm chuẩn hóa, kiểm định và nạp dữ liệu tri thức chính sách từ tệp thô `data/raw/policy_export_dirty.csv` vào cơ sở dữ liệu vector Chroma DB phục vụ cho các ứng dụng RAG. 

**Tóm tắt luồng xử lý:**
1. **Ingestion:** Đọc tệp dữ liệu thô định dạng CSV chứa các dòng văn bản chính sách kèm theo metadata hiệu lực (`effective_date`) và ngày xuất bản (`exported_at`).
2. **Transform (Cleaning):** Áp dụng allowlist của tài liệu, chuẩn hóa ngày tháng sang dạng ISO (`YYYY-MM-DD`), loại bỏ các tiền tố/hậu tố nhiễu chuỗi, lọc bỏ các dòng trùng lặp và các phiên bản tài liệu HR cũ (2025). Đồng thời, tự động sửa đổi lỗi chính sách hoàn tiền stale từ "14 ngày" về đúng "7 ngày làm việc".
3. **Quality Gate (Expectations):** Xác thực dữ liệu thông qua lớp Pydantic schema validation và 8 expectations nghiệp vụ khác để ngăn ngừa dữ liệu lỗi nạp vào DB.
4. **Embedding & Pruning:** Sử dụng mô hình `all-MiniLM-L6-v2` chuyển đổi văn bản sang vector, nạp idempotency (Natural Key Upsert) vào collection `day10_kb` và dọn dẹp các ID cũ không còn tồn tại (Index Pruning).
5. **Monitoring:** Đo lường độ tươi của dữ liệu trên cả biên Ingest và Publish.

**Lệnh chạy một dòng:**
```bash
$env:PYTHONIOENCODING="utf-8"; venv\Scripts\python.exe etl_pipeline.py run
```
Mỗi phiên chạy tạo ra một mã định danh duy nhất `run_id` được ghi nhận tự động dạng UTC Timestamp như `2026-06-10T07-52Z` trong manifest file và console log.

---

## 2. Cleaning & expectation (150–200 từ)

Nhóm đã kế thừa các quy tắc cơ bản và mở rộng thêm **4 quy tắc làm sạch mới** cùng **2 expectations bổ sung** nhằm nâng cao chất lượng dữ liệu tri thức.

### 2a. Bảng metric_impact

| Rule / Expectation mới | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ |
|-----------------------------------|------------------|-----------------------------|-------------------------------|
| **Rule 1:** Bỏ tiền tố `"Nội dung không rõ ràng: "` | 1 dòng bị nhiễu và rank retrieval thấp | Chuỗi được làm sạch hoàn toàn | [cleaning_rules.py](file:///c:/Users/81908/OneDrive/M%C3%A1y%20t%C3%ADnh/2A202600811-LuongThiHongNhung_Day10/day10/lab/transform/cleaning_rules.py#L151-L154) |
| **Rule 2:** Bỏ ký tự nhiễu `"!!!"` ở đầu/cuối | 1 dòng bị dính chuỗi gây lỗi phân tách từ | Đã làm sạch tiền tố và hậu tố | [cleaning_rules.py](file:///c:/Users/81908/OneDrive/M%C3%A1y%20t%C3%ADnh/2A202600811-LuongThiHongNhung_Day10/day10/lab/transform/cleaning_rules.py#L156-L160) |
| **Rule 3:** Sửa lỗi lặp từ `"làm việc làm việc"` | 1 dòng bị lặp từ kép | Gộp về từ đơn đúng nghĩa | [cleaning_rules.py](file:///c:/Users/81908/OneDrive/M%C3%A1y%20t%C3%ADnh/2A202600811-LuongThiHongNhung_Day10/day10/lab/transform/cleaning_rules.py#L162-L164) |
| **Rule 4:** Làm giàu ngữ cảnh cho SLA P1 | Rank retrieval = 8 (FAIL trong eval) | Rank retrieval = 1 (PASS 10/10) | [cleaning_rules.py](file:///c:/Users/81908/OneDrive/M%C3%A1y%20t%C3%ADnh/2A202600811-LuongThiHongNhung_Day10/day10/lab/transform/cleaning_rules.py#L166-L168) |
| **Expectation E7:** Không có ngày hiệu lực tương lai | Chưa có cảnh báo | Phát hiện dòng tương lai (warn) | [expectations.py](file:///c:/Users/81908/OneDrive/M%C3%A1y%20t%C3%ADnh/2A202600811-LuongThiHongNhung_Day10/day10/lab/quality/expectations.py#L142-L157) |
| **Expectation E8:** Min 4 unique doc types | Chưa có kiểm tra | Đảm bảo tính đa dạng của nguồn (halt) | [expectations.py](file:///c:/Users/81908/OneDrive/M%C3%A1y%20t%C3%ADnh/2A202600811-LuongThiHongNhung_Day10/day10/lab/quality/expectations.py#L159-L169) |

**Ví dụ 1 lần expectation fail và cách xử lý:**
Khi chạy thử nghiệm không có cờ `--skip-validate` trên tập dữ liệu bẩn chưa kích hoạt bộ lọc refund fix, hệ thống lập tức thông báo lỗi vi phạm tại expectation `refund_no_stale_14d_window` với thông tin: `expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1`. Pipeline lập tức thoát ra với mã lỗi `2`. Để xử lý, chúng tôi đã kích hoạt hàm sửa đổi thay thế chuỗi tại `cleaning_rules.py` chuyển đổi cụm từ "14 ngày làm việc" sang "7 ngày làm việc" để dữ liệu đạt tiêu chuẩn chất lượng.

---

## 3. Before / after ảnh hưởng retrieval hoặc agent (200–250 từ)

**Kịch bản inject corruption:**
Chúng tôi đã giả lập một kịch bản làm hỏng dữ liệu thông qua lệnh chạy:
```bash
$env:PYTHONIOENCODING="utf-8"; venv\Scripts\python.exe etl_pipeline.py run --no-refund-fix --skip-validate
```
Lệnh này ngăn cản việc sửa lỗi thời hạn hoàn tiền đồng thời bỏ qua Quality Gate, khiến dữ liệu hoàn tiền cũ (14 ngày làm việc) bị nhúng thẳng vào collection `day10_kb`.

**Kết quả định lượng:**
- **Trước khi sửa đổi (Khi inject dữ liệu lỗi):**
  Khi truy vấn câu hỏi `q_refund_window` ("Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền kể từ khi đơn được xác nhận?"), RAG Agent nhận được văn bản có nội dung: `"Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày làm việc..."` làm câu trả lời hàng đầu (`hits_forbidden: yes`), dẫn đến việc cung cấp thông tin sai lệch cho khách hàng.
- **Sau khi sửa đổi (Clean Run):**
  Sau khi chạy lại pipeline chuẩn để ghi đè và làm sạch dữ liệu, truy vấn trả về: `"Yêu cầu được gửi trong vòng 7 ngày làm việc kể từ thời điểm xác nhận đơn hàng."` (`hits_forbidden: no`). Trạm gác đã hoạt động chính xác và sửa đổi triệt để dữ liệu lỗi thời.

---

## 4. Freshness & monitoring (100–150 từ)

Chúng tôi thiết lập SLA độ tươi của dữ liệu là **24.0 giờ**.
- **Ingestion Freshness:** Đo lường độ trễ từ lúc dữ liệu được trích xuất ở hệ thống nguồn (`exported_at = 2026-04-10`) so với hiện tại. Kết quả trả về `FAIL` do dữ liệu thô mẫu đã cũ (cách thời điểm chạy hơn 1400 giờ). Đây là thông tin quan trọng báo hiệu cho đội ngũ Data Engineer cần cập nhật bản xuất dữ liệu mới từ nguồn.
- **Publish Freshness:** Đo lường thời gian chạy pipeline mới nhất. Kết quả trả về `PASS` (độ trễ = 0.0 giờ), xác nhận vector store vừa được cập nhật thành công.

---

## 5. Liên hệ Day 09 (50–100 từ)

Dữ liệu tri thức được lưu trữ độc lập tại collection `day10_kb` đóng vai trò làm nền tảng thông tin sạch cho RAG Agent đã phát triển tại Day 09. Nhóm đã thực hiện hoán đổi cấu hình trỏ từ collection tri thức cũ sang collection mới `day10_kb`. Việc này giúp RAG Agent ngay lập tức có thể trả lời các câu hỏi về hoàn tiền 7 ngày hoặc phép năm 12 ngày một cách chính xác mà không gặp lỗi phản hồi từ chính sách lỗi thời 2025.

---

## 6. Rủi ro còn lại & việc chưa làm

- **Tiếng Việt chưa tối ưu:** Việc sử dụng mô hình embedding hỗ trợ tiếng Anh khiến ta phải làm giàu dữ liệu bằng keyword tiếng Anh thủ công trong code.
- **Xử lý Quarantine thủ công:** Quy trình giải quyết các bản ghi trong quarantine để merge back lại luồng chính vẫn cần con người can thiệp thủ công qua các file CSV.
