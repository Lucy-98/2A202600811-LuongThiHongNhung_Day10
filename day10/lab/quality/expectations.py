import datetime
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field, field_validator


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str  # "warn" | "halt"
    detail: str


class CleanedChunkSchema(BaseModel):
    chunk_id: str = Field(..., min_length=1)
    doc_id: str = Field(..., min_length=1)
    chunk_text: str = Field(..., min_length=1)
    effective_date: str
    exported_at: str

    @field_validator('effective_date')
    @classmethod
    def check_date_iso(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v.strip()):
            raise ValueError("Must be in YYYY-MM-DD format")
        return v


def run_expectations(cleaned_rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    """
    Trả về (results, should_halt).

    should_halt = True nếu có bất kỳ expectation severity halt nào fail.
    """
    results: List[ExpectationResult] = []

    # E0: Pydantic Schema Validation (Distinction a & Bonus)
    pydantic_errors = []
    for idx, row in enumerate(cleaned_rows):
        try:
            CleanedChunkSchema(**row)
        except Exception as e:
            pydantic_errors.append((idx, str(e)))
    ok0 = len(pydantic_errors) == 0
    results.append(
        ExpectationResult(
            "pydantic_schema_validation",
            ok0,
            "halt",
            f"schema_violations={len(pydantic_errors)}, first_error={pydantic_errors[0] if pydantic_errors else ''}",
        )
    )

    # E1: có ít nhất 1 dòng sau clean
    ok = len(cleaned_rows) >= 1
    results.append(
        ExpectationResult(
            "min_one_row",
            ok,
            "halt",
            f"cleaned_rows={len(cleaned_rows)}",
        )
    )

    # E2: không doc_id rỗng
    bad_doc = [r for r in cleaned_rows if not (r.get("doc_id") or "").strip()]
    ok2 = len(bad_doc) == 0
    results.append(
        ExpectationResult(
            "no_empty_doc_id",
            ok2,
            "halt",
            f"empty_doc_id_count={len(bad_doc)}",
        )
    )

    # E3: policy refund không được chứa cửa sổ sai 14 ngày (sau khi đã fix)
    bad_refund = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "policy_refund_v4"
        and "14 ngày làm việc" in (r.get("chunk_text") or "")
    ]
    ok3 = len(bad_refund) == 0
    results.append(
        ExpectationResult(
            "refund_no_stale_14d_window",
            ok3,
            "halt",
            f"violations={len(bad_refund)}",
        )
    )

    # E4: chunk_text đủ dài
    short = [r for r in cleaned_rows if len((r.get("chunk_text") or "")) < 8]
    ok4 = len(short) == 0
    results.append(
        ExpectationResult(
            "chunk_min_length_8",
            ok4,
            "warn",
            f"short_chunks={len(short)}",
        )
    )

    # E5: effective_date đúng định dạng ISO sau clean (phát hiện parser lỏng)
    iso_bad = [
        r
        for r in cleaned_rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or "").strip())
    ]
    ok5 = len(iso_bad) == 0
    results.append(
        ExpectationResult(
            "effective_date_iso_yyyy_mm_dd",
            ok5,
            "halt",
            f"non_iso_rows={len(iso_bad)}",
        )
    )

    # E6: không còn marker phép năm cũ 10 ngày trên doc HR (conflict version sau clean)
    bad_hr_annual = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "hr_leave_policy"
        and "10 ngày phép năm" in (r.get("chunk_text") or "")
    ]
    ok6 = len(bad_hr_annual) == 0
    results.append(
        ExpectationResult(
            "hr_leave_no_stale_10d_annual",
            ok6,
            "halt",
            f"violations={len(bad_hr_annual)}",
        )
    )

    # E7: Ngày hiệu lực không ở tương lai (New Expectation 1)
    today_str = datetime.date.today().isoformat()
    future_dates = [
        r
        for r in cleaned_rows
        if (r.get("effective_date") or "") > today_str
    ]
    ok7 = len(future_dates) == 0
    results.append(
        ExpectationResult(
            "no_future_effective_date",
            ok7,
            "warn",
            f"future_date_count={len(future_dates)}",
        )
    )

    # E8: Phải có ít nhất 4 loại tài liệu nguồn unique được nạp (New Expectation 2)
    unique_docs = {r.get("doc_id") for r in cleaned_rows if r.get("doc_id")}
    ok8 = len(unique_docs) >= 4
    results.append(
        ExpectationResult(
            "min_four_unique_doc_types",
            ok8,
            "halt",
            f"unique_docs_found={len(unique_docs)} ({sorted(unique_docs)})",
        )
    )

    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
