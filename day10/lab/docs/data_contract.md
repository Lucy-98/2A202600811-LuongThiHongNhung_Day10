# Data contract — Lab Day 10

> Xem chi tiết tại cấu hình [data_contract.yaml](file:///c:/Users/81908/OneDrive/M%C3%A1y%20t%C3%ADnh/2A202600811-LuongThiHongNhung_Day10/day10/lab/contracts/data_contract.yaml)

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `policy_refund_v4` | Batch CSV Export | Dữ liệu chứa thông tin cũ "14 ngày" chưa cập nhật | Alert nếu có chunk chứa "14 ngày làm việc" sau khi clean |
| `sla_p1_2026` | Batch CSV Export | Thiếu cột thông tin hoặc ngày hiệu lực không hợp lệ | Alert nếu không tìm thấy dữ liệu SLA P1 |
| `it_helpdesk_faq` | Batch CSV Export | Chunk bị trống nội dung | Quarantine đếm số lượng dòng trống |
| `hr_leave_policy` | Batch CSV Export | Chứa phiên bản cũ 2025 (phép năm cũ 10 ngày) | Lọc và quarantine các dòng có ngày hiệu lực trước 2026-01-01 |
| `access_control_sop` | Batch CSV Export | Tài liệu chưa được đăng ký trong hệ thống (Baseline quarantine) | Báo lỗi unknown_doc_id nếu chưa update allowlist |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | ID duy nhất sinh ra ổn định từ hash SHA-256 của nội dung chunk |
| `doc_id` | string | Có | Tên nguồn tài liệu, nằm trong allowlist đã được khai báo |
| `chunk_text` | string | Có | Nội dung văn bản, bắt buộc dài ít nhất 8 ký tự |
| `effective_date` | date | Có | Ngày hiệu lực của tài liệu dưới định dạng ISO YYYY-MM-DD |
| `exported_at` | datetime | Có | Thời điểm dữ liệu được export từ hệ thống nguồn |

---

## 3. Quy tắc quarantine vs drop

- **Quarantine:** Bản ghi bị flag và chuyển vào file CSV riêng ở thư mục `artifacts/quarantine/` trong các trường hợp:
  - `doc_id` không nằm trong allowlist của pipeline (unknown doc ID).
  - Thiếu ngày hiệu lực (`missing_effective_date`) hoặc sai định dạng ngày (`invalid_effective_date_format`).
  - Tài liệu HR lỗi thời (`stale_hr_policy_effective_date`).
  - Bản ghi trùng lặp nội dung (`duplicate_chunk_text`).
- **Drop:** Các dòng hoàn toàn trống, không có text (`missing_chunk_text`) hoặc lỗi encoding nghiêm trọng sẽ bị drop thẳng khỏi luồng xử lý và ghi nhận số lượng trong log file.
- **Merge Back:** Dữ liệu trong quarantine sẽ được đội ngũ kỹ thuật rà soát định kỳ. Sau khi chuẩn hoá tay hoặc cập nhật cấu hình allowlist, dữ liệu sẽ được re-ingest.

---

## 4. Phiên bản & canonical

- **Source of truth cho policy refund:** Tài liệu gốc `data/docs/policy_refund_v4.txt` quy định thời hạn hoàn tiền chính xác là 7 ngày làm việc. Pipeline có nhiệm vụ tự động sửa bất kỳ chunk nào bị xuất sai thành 14 ngày về đúng 7 ngày và gắn nhãn `[cleaned: stale_refund_window]`.
- **Source of truth cho HR Policy:** Tài liệu gốc `data/docs/hr_leave_policy.txt` quy định ngày phép năm của nhân viên dưới 3 năm kinh nghiệm là 12 ngày (hiệu lực từ 2026-01-01). Bất kỳ bản ghi nào có hiệu lực trước thời điểm này (chứa phép năm cũ 10 ngày) đều bị cách ly.
