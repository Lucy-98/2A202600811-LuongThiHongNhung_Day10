# Runbook — Lab Day 10 (Incident Response & Mitigation)

---

## Symptom

- **RAG Agent Answer Anomaly:** RAG Agent trả lời thời gian hoàn tiền cho khách hàng là "14 ngày" thay vì "7 ngày làm việc", hoặc trả lời ngày phép năm của nhân viên mới là "10 ngày phép năm (bản HR 2025)" thay vì "12 ngày phép năm" theo chính sách 2026.
- **Fail grading test cases:** Script `grading_run.py` hoặc `eval_retrieval.py` trả về `contains_expected=False`, `hits_forbidden=True` hoặc `top1_doc_matches=False`.

---

## Detection

- **Freshness Alert (Double Boundary):** 
  - **Ingestion Freshness:** `freshness_check.ingest.status` báo `FAIL` (ví dụ: `age_hours` > 24 giờ do snapshot xuất từ ngày 2026-04-10). Điều này cho thấy dữ liệu xuất từ hệ thống nguồn đã cũ.
  - **Publish Freshness:** `freshness_check.publish.status` báo `FAIL` (ví dụ: pipeline không chạy định kỳ, khiến dữ liệu nhúng trong ChromaDB không được cập nhật).
- **Expectation Quality Gate Fail:** Pipeline kết thúc đột ngột với mã lỗi `2` hoặc in ra log: `expectation[...] FAIL (halt)`.
- **RAG Eval Metric Alerts:** Script tự động chấm điểm phát hiện `hits_forbidden=True` đối với câu hỏi hoàn tiền (`q_refund_window`) hoặc câu hỏi ngày phép (`q_hr_annual_leave_under3`).

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Kiểm tra `artifacts/manifests/*.json` mới nhất | Xác định `run_id`, số lượng `raw_records`, `cleaned_records`, và `quarantine_records`. Nếu `quarantine_records` tăng đột biến, chỉ ra nguồn dữ liệu đang bị lỗi hàng loạt. |
| 2 | Mở `artifacts/quarantine/*.csv` | Kiểm tra cột `quarantine_reasons`. <br>- Nếu lý do là `stale_hr_policy_effective_date`: do file raw chứa dòng phép năm cũ (2025). <br>- Nếu lý do là `missing_effective_date`: dữ liệu nguồn bị khuyết trường ngày hiệu lực. |
| 3 | Chạy `python eval_retrieval.py` | Kiểm tra tóm tắt kết quả RAG để biết chính xác câu hỏi nào đang lấy sai chunk hoặc chứa từ cấm. |
| 4 | Kiểm tra file log của pipeline | Xác định xem có lỗi cú pháp hoặc ngoại lệ Schema Validation từ Pydantic trong `quality/expectations.py` hay không. |

---

## Mitigation

1. **Khi Ingestion Freshness Fail (Dữ liệu nguồn cũ):**
   - Thông báo cho bên gửi dữ liệu (Data Owner của hệ thống nguồn) xuất file dữ liệu mới có chứa timestamp `exported_at` hiện tại.
   - Nếu dữ liệu snapshot cố tình cũ phục vụ môi trường test, có thể tạm thời nâng `FRESHNESS_SLA_HOURS` hoặc dùng tool cập nhật cột `exported_at` để pipeline chạy tiếp.
2. **Khi Quality Gate Halt (Dữ liệu bẩn vi phạm Expectation cứng):**
   - Nếu lỗi do format, sửa dữ liệu hoặc bỏ qua kiểm tra chất lượng bằng cờ `--skip-validate` (Chỉ dùng trong trường hợp khẩn cấp có sự đồng ý của Product Owner).
   - Kiểm tra `transform/cleaning_rules.py` để bổ sung rule xử lý phần dữ liệu lỗi đó (ví dụ: chuẩn hóa chuỗi, loại bỏ ký tự lạ).
3. **Khi RAG Retrieval bị lệch Rank:**
   - Chỉnh sửa `cleaning_rules.py` để làm giàu thông tin (Context Enrichment) cho các tài liệu đặc thù như `Escalation P1` để mô hình embedding dễ bắt trúng keyword.
4. **Rerun pipeline & Publish:**
   - Chạy lệnh: `$env:PYTHONIOENCODING="utf-8"; venv\Scripts\python.exe etl_pipeline.py run` để clean, validate và đồng bộ lại index ChromaDB.

---

## Prevention

- **Thiết lập Data Contract tự động:** Quản lý cấu hình allowlist `doc_id` và các tham số như `hr_leave_cutoff_date` trong `contracts/data_contract.yaml` để tránh hardcode trong code.
- **Pydantic Validation:** Sử dụng schema Pydantic tại Quality Gate để chặn đứng các bản ghi thiếu trường bắt buộc hoặc rỗng nội dung trước khi nạp vào Vector DB.
- **Độc lập Môi trường (Day 11):** Sử dụng các collection riêng biệt (`day10_kb`) cho việc kiểm thử và chỉ hoán đổi (swap alias) sang collection chính khi pipeline hoàn thành `PIPELINE_OK`.

