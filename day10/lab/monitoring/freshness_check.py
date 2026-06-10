"""
Kiểm tra freshness từ manifest pipeline (SLA đơn giản theo giờ).

Sinh viên mở rộng: đọc watermark DB, so sánh với clock batch, v.v.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple


def parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # Cho phép "2026-04-10T08:00:00" không có timezone
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def check_manifest_freshness(
    manifest_path: Path,
    *,
    sla_hours: float = 24.0,
    now: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Trả về ("PASS" | "WARN" | "FAIL", detail dict).

    Đo độ tươi ở cả 2 biên (double boundary) để đạt Distinction b & Bonus:
    1) Ingestion Boundary: thời gian trễ từ latest_exported_at đến nay
    2) Publish Boundary: thời gian trễ từ run_timestamp đến nay
    """
    now = now or datetime.now(timezone.utc)
    if not manifest_path.is_file():
        return "FAIL", {"reason": "manifest_missing", "path": str(manifest_path)}

    data: Dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    
    # Ingestion boundary
    ts_ingest = data.get("latest_exported_at")
    dt_ingest = parse_iso(str(ts_ingest)) if ts_ingest else None
    
    # Publish boundary
    ts_publish = data.get("run_timestamp")
    dt_publish = parse_iso(str(ts_publish)) if ts_publish else None

    detail: Dict[str, Any] = {
        "sla_hours": sla_hours,
    }

    status = "PASS"

    if dt_ingest:
        age_ingest = (now - dt_ingest).total_seconds() / 3600.0
        detail["ingest"] = {
            "latest_exported_at": ts_ingest,
            "age_hours": round(age_ingest, 3),
            "status": "PASS" if age_ingest <= sla_hours else "FAIL"
        }
        if age_ingest > sla_hours:
            status = "FAIL"
    else:
        detail["ingest"] = {"status": "WARN", "reason": "no_ingest_timestamp_in_manifest"}
        if status != "FAIL":
            status = "WARN"

    if dt_publish:
        age_publish = (now - dt_publish).total_seconds() / 3600.0
        detail["publish"] = {
            "run_timestamp": ts_publish,
            "age_hours": round(age_publish, 3),
            "status": "PASS" if age_publish <= sla_hours else "FAIL"
        }
        if age_publish > sla_hours:
            status = "FAIL"
    else:
        detail["publish"] = {"status": "WARN", "reason": "no_publish_timestamp_in_manifest"}
        if status != "FAIL":
            status = "WARN"

    if status == "FAIL":
        detail["reason"] = "freshness_sla_exceeded"
        
    return status, detail
