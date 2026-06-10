# Quality report — Lab Day 10 (nhóm)

**run_id:** `2026-06-10T07-52Z`  
**Ngày:** 2026-06-10

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước (Corrupted / Injected)* | Sau (Clean Run) | Ghi chú |
|--------|------------------------------|-----------------|---------|
| raw_records | 247 | 247 | Dữ liệu nguồn vào không thay đổi. |
| cleaned_records | 34 | 34 | Số lượng bản ghi vượt qua bước kiểm duyệt. |
| quarantine_records | 213 | 213 | Số lượng bản ghi bị cô lập vào Quarantine. |
| Expectation halt? | Không (Do `--skip-validate`) | Không (Vượt qua tất cả kiểm thử chất lượng) | Nếu chạy `--no-refund-fix` mà không có `--skip-validate`, pipeline sẽ halt lập tức do vi phạm E3 (`refund_no_stale_14d_window`). |

*\* Trạng thái "Trước" tương ứng với lần chạy `run_id = inject-bad` (chạy với `--no-refund-fix --skip-validate` để cố tình nạp dữ liệu lỗi vào ChromaDB).*

---

## 2. Before / after retrieval (bắt buộc)

Dữ liệu so sánh chi tiết được ghi nhận giữa hai file:
- **Trước (Corrupted):** `artifacts/eval/after_inject_bad.csv`
- **Sau (Clean/Fixed):** `artifacts/eval/eval_after_fix.csv`

### **Câu hỏi then chốt:** refund window (`q_refund_window`)  
- **Trước (Corrupted):**
  - **top1_doc_id:** `policy_refund_v4`
  - **top1_preview:** `Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày làm việc kể từ xác nhận đơn.`
  - **contains_expected:** `yes`
  - **hits_forbidden:** `yes` (Chứa từ khóa cấm "14" ngày)
- **Sau (Clean/Fixed):**
  - **top1_doc_id:** `policy_refund_v4`
  - **top1_preview:** `Yêu cầu được gửi trong vòng 7 ngày làm việc kể từ thời điểm xác nhận đơn hàng.`
  - **contains_expected:** `yes`
  - **hits_forbidden:** `no` (Đã chuyển thành công về "7" ngày nhờ rule sửa lỗi hoàn tiền cũ)

---

### **Merit (khuyến nghị):** versioning HR — `q_leave_version` (`contains_expected`, `hits_forbidden`, cột `top1_doc_expected`)

- **Trước (Chưa lọc phiên bản 2025):** 
  - Tài liệu HR 2025 chứa thông tin "10 ngày phép năm" sẽ bị lẫn vào ChromaDB, gây nhiễu và trả về thông tin lỗi thời cho RAG Agent.
- **Sau (Đã áp dụng rule lọc HR 2025):**
  - Lọc bỏ dòng chứa "10 ngày phép năm (bản HR 2025)" nhờ so sánh hiệu lực date (`hr_leave_cutoff_date: 2026-01-01`) được lấy động từ `data_contract.yaml`.
  - Kết quả: `contains_expected: true` (chứa 12 ngày phép), `hits_forbidden: false` (không chứa 10 ngày phép), `top1_doc_expected: yes`.

---

## 3. Freshness & monitor

Kết quả check freshness cuối cùng:
- **Ingestion Freshness:** `FAIL` (Do snapshot `policy_export_dirty.csv` chứa cột `exported_at = 2026-04-10`, có độ trễ lớn hơn 24 giờ so với thời điểm chạy pipeline hiện tại). Đây là cảnh báo chính xác vì dữ liệu nguồn của hệ thống đã lâu không được cập nhật xuất mới.
- **Publish Freshness:** `PASS` (Do `run_timestamp` được ghi nhận tại thời điểm chạy pipeline hiện tại, thể hiện việc nạp dữ liệu vào vector store vừa diễn ra và hoàn toàn tươi mới).
- **Lý do chọn SLA:** Chọn `24.0 giờ` làm SLA tiêu chuẩn cho cả hai đầu biên vì các chính sách nội bộ thường được rà soát và đồng bộ hàng ngày để đảm bảo nhân viên và khách hàng luôn nhận được câu trả lời chính xác, tránh các chính sách cũ hết hiệu lực.

---

## 4. Corruption inject (Sprint 3)

- **Cách thức làm hỏng dữ liệu (Corruption Injection):**
  - Sử dụng cờ `--no-refund-fix --skip-validate` khi chạy pipeline. Lệnh này bỏ qua bước sửa đổi chuỗi từ "14 ngày làm việc" về "7 ngày làm việc", đồng thời bỏ qua các trạm kiểm soát chất lượng (Quality Gate Expectations).
  - Kết quả là chuỗi sai lệch "14 ngày" được nhúng trực tiếp vào ChromaDB.
- **Cách phát hiện:**
  - Nếu không chạy `--skip-validate`, trạm kiểm soát chất lượng `refund_no_stale_14d_window` sẽ bắt được lỗi này ngay lập tức nhờ kiểm tra xem có văn bản nào thuộc doc `policy_refund_v4` chứa từ khóa "14 ngày" hay không và thực hiện dừng (halt) pipeline để ngăn chặn dữ liệu bẩn lọt vào vector database.

---

## 5. Hạn chế & việc chưa làm

- **Đồng bộ hóa Real-time:** Hiện tại pipeline vẫn chạy theo cơ chế Batch ETL thủ công/định kỳ, chưa hỗ trợ phát hiện thay đổi real-time (Change Data Capture - CDC).
- **Mô hình Embedding Tiếng Việt:** Đang sử dụng mô hình embedding tiếng Anh `all-MiniLM-L6-v2` nên cần thực hiện thêm bước bổ trợ keyword (Context Enrichment) cho tiếng Việt trong file `cleaning_rules.py`. Trong tương lai nên nâng cấp lên mô hình đa ngôn ngữ hoặc mô hình tiếng Việt tối ưu hơn (như `sentence-transformers/LaBSE` hoặc các mô hình tương tự).
