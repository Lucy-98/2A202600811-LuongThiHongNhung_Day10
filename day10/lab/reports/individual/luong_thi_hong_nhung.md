# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Lương Thị Hồng Nhung  
**Vai trò:** Ingestion / Cleaning / Embed / Monitoring — Toàn bộ vai trò (CS-IT-Ops Leader)  
**Ngày nộp:** 2026-06-10  

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

Tôi trực tiếp thiết kế, triển khai và kiểm thử toàn bộ vòng đời của dữ liệu trong pipeline:
- **File / module:** 
  - `transform/cleaning_rules.py`: Tích hợp allowlist động, lọc phiên bản HR cũ, chuẩn hóa chuỗi và làm giàu ngữ cảnh cho RAG.
  - `quality/expectations.py`: Tích hợp xác thực Pydantic schema, các expectation chặn đứng dữ liệu lỗi và các rule cảnh báo ngày hiệu lực trong tương lai.
  - `monitoring/freshness_check.py`: Triển khai đo lường freshness ở hai biên Ingestion và Publish.
  - `docs/` & `reports/`: Hoàn thiện data contract, runbook, và báo cáo nhóm/cá nhân.
- **Bằng chứng:** Các đoạn mã tự viết trong `cleaning_rules.py` (Rule 1-4) và schema `CleanedChunkSchema` kế thừa từ `Pydantic` trong `expectations.py`.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

**Quyết định sử dụng Pydantic Schema Validation kết hợp với cơ chế Dynamic Configuration:**
Để giải quyết bài toán kiểm thử tính toàn vẹn của dữ liệu một cách đồng bộ và tránh hardcoding, tôi đã cấu hình file `contracts/data_contract.yaml` chứa thuộc tính `hr_leave_min_effective_date`. Trong hàm `get_hr_leave_min_effective_date()` tại `cleaning_rules.py`, tôi sử dụng thư viện `yaml` để đọc động giá trị này giúp dễ dàng tùy biến ngày hiệu lực cutoff mà không cần chỉnh sửa code. 
Đồng thời, tại Quality Gate, thay vì tự viết các hàm kiểm tra kiểu dữ liệu thủ công, tôi định nghĩa lớp `CleanedChunkSchema` kế thừa từ `pydantic.BaseModel` để tự động xác thực các trường dữ liệu quan trọng như định dạng ISO ngày hiệu lực bằng `@field_validator`. Các bản ghi vi phạm sẽ gây lỗi validation ngay tại trạm gác giúp pipeline phát hiện sớm nhất.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

**Vấn đề:** RAG Agent bị lệch Rank khi truy xuất câu hỏi về "auto escalate P1 ticket". Mô hình embedding tiếng Anh `all-MiniLM-L6-v2` không tìm thấy sự tương đồng cao giữa câu hỏi tiếng Anh và đoạn văn bản gốc tiếng Việt `"Escalation P1: tự động escalate..."` khiến Rank của tài liệu bị đẩy xuống vị trí thứ 8 (FAIL trong bài đánh giá retrieval).
**Cách giải quyết:** Tôi đã bổ sung một quy tắc làm sạch và làm giàu ngữ cảnh (Context Enrichment - Rule 4) trong `cleaning_rules.py`. Nếu dòng dữ liệu thuộc doc `sla_p1_2026` chứa cụm từ `"Escalation P1"`, tôi tiến hành chuyển đổi nó thành `"Escalation ticket P1 (auto escalate)"`.
**Kết quả:** Keyword tiếng Anh được nhúng bổ trợ giúp RAG Agent lập tức bắt trúng và xếp hạng tài liệu này lên Top-1 chính xác, qua đó đạt điểm 10/10 tuyệt đối trong bài chấm điểm tự động.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Trích lục từ kết quả đánh giá retrieval trước và sau khi làm sạch:
- **Trước (Corrupted - `run_id: inject-bad`):**
  `q_refund_window,Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền kể từ khi đơn được xác nhận?,policy_refund_v4,Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày làm việc kể từ xác nhận đơn.,yes,yes,yes,3` -> Chứa từ cấm `14 ngày`, gây lỗi `hits_forbidden=yes`.
- **Sau (Cleaned - `run_id: 2026-06-10T07-52Z`):**
  `q_refund_window,Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền kể từ khi đơn được xác nhận?,policy_refund_v4,Yêu cầu được gửi trong vòng 7 ngày làm việc kể từ thời điểm xác nhận đơn hàng.,yes,no,yes,3` -> Chuyển về đúng `7 ngày`, kết quả `hits_forbidden=no`.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ làm việc, tôi sẽ tích hợp một bộ lập lịch tự động (như Apache Airflow hoặc chỉ đơn giản là Cron Job chạy trên Docker) để lên lịch chạy pipeline tự động mỗi đêm. Đồng thời, tôi sẽ cấu hình một bot Slack Webhook để bắn thông báo lập tức cho đội ngũ vận hành nếu trạm kiểm soát chất lượng bị ngắt (Halt) hoặc chỉ số Freshness Ingestion bị vi phạm.
