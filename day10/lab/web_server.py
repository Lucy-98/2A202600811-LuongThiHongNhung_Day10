#!/usr/bin/env python3
"""
Web Server for Data Pipeline & Observability Testing (Lab Day 10)
Hosts a premium frontend dashboard to interactively test semantic search,
upload raw files to run the ETL pipeline, review metrics, and audit quarantined records.

Run command:
  python web_server.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent

# Check dependencies
try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    print("Error: Missing packages. Run: venv\\Scripts\\python.exe -m pip install chromadb sentence-transformers", file=sys.stderr)
    sys.exit(1)

# Helper to find latest files
def get_latest_file(directory: Path, glob_pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = list(directory.glob(glob_pattern))
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime)

class DashboardAPI:
    @staticmethod
    def get_stats() -> dict:
        # Load latest manifest
        manifest_dir = ROOT / "artifacts" / "manifests"
        latest_manifest = get_latest_file(manifest_dir, "manifest_*.json")
        manifest_data = {}
        if latest_manifest:
            try:
                manifest_data = json.loads(latest_manifest.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        # Calculate freshness
        freshness_status = "N/A"
        ingest_age = "N/A"
        publish_age = "N/A"
        
        if manifest_data:
            from monitoring.freshness_check import parse_iso
            now = datetime.now(timezone.utc)
            
            ts_ingest = manifest_data.get("latest_exported_at")
            dt_ingest = parse_iso(str(ts_ingest)) if ts_ingest else None
            if dt_ingest:
                ingest_age = f"{round((now - dt_ingest).total_seconds() / 3600.0, 1)} giờ"
            
            ts_publish = manifest_data.get("run_timestamp")
            dt_publish = parse_iso(str(ts_publish)) if ts_publish else None
            if dt_publish:
                publish_age = f"{round((now - dt_publish).total_seconds() / 3600.0, 2)} giờ"
                
            # Quick check freshness status
            sla_hours = 24.0
            from monitoring.freshness_check import check_manifest_freshness
            status, _ = check_manifest_freshness(latest_manifest, sla_hours=sla_hours, now=now)
            freshness_status = status

        return {
            "manifest": manifest_data,
            "freshness": {
                "status": freshness_status,
                "ingest_age": ingest_age,
                "publish_age": publish_age,
                "sla_hours": 24.0
            }
        }

    @staticmethod
    def query_chroma(query_text: str, top_k: int = 5) -> dict:
        db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
        collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
        model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

        try:
            client = chromadb.PersistentClient(path=db_path)
            emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
            col = client.get_collection(name=collection_name, embedding_function=emb)
            
            res = col.query(query_texts=[query_text], n_results=top_k)
            
            documents = (res.get("documents") or [[]])[0]
            metadatas = (res.get("metadatas") or [[]])[0]
            ids = (res.get("ids") or [[]])[0]
            distances = (res.get("distances") or [[]])[0]
            
            results = []
            for i in range(len(documents)):
                results.append({
                    "id": ids[i],
                    "text": documents[i],
                    "metadata": metadatas[i],
                    "distance": round(distances[i], 4) if i < len(distances) else 0.0
                })
            return {"status": "success", "results": results}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_quarantine() -> list:
        quar_dir = ROOT / "artifacts" / "quarantine"
        latest_quar = get_latest_file(quar_dir, "quarantine_*.csv")
        records = []
        if latest_quar:
            try:
                with latest_quar.open(encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for i, row in enumerate(reader):
                        if i >= 50: # Limit 50 rows
                            break
                        records.append(dict(row))
            except Exception:
                pass
        return records

    @staticmethod
    def run_grading() -> list:
        # Load grading questions
        qpath = ROOT / "data" / "grading_questions.json"
        if not qpath.is_file():
            return []
        
        try:
            qs = json.loads(qpath.read_text(encoding="utf-8"))
        except Exception:
            return []

        db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
        collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
        model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

        results = []
        try:
            client = chromadb.PersistentClient(path=db_path)
            emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
            col = client.get_collection(name=collection_name, embedding_function=emb)

            for q in qs:
                text = q["question"]
                res = col.query(query_texts=[text], n_results=5)
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                blob = " ".join(docs).lower()
                
                must_any = [x.lower() for x in q.get("must_contain_any", [])]
                forbidden = [x.lower() for x in q.get("must_not_contain", [])]
                
                ok_any = any(m in blob for m in must_any) if must_any else True
                bad_forb = any(m in blob for m in forbidden) if forbidden else False
                top_doc = (metas[0] or {}).get("doc_id", "") if metas else ""
                want_top1 = (q.get("expect_top1_doc_id") or "").strip()
                
                top1_ok = True
                if want_top1:
                    top1_ok = top_doc == want_top1
                
                results.append({
                    "id": q.get("id"),
                    "question": text,
                    "top1_doc_id": top_doc,
                    "top1_preview": docs[0][:120] + "..." if docs else "No docs retrieved",
                    "contains_expected": ok_any,
                    "hits_forbidden": bad_forb,
                    "top1_doc_matches": top1_ok if want_top1 else None,
                    "criteria": q.get("grading_criteria", [])
                })
        except Exception as e:
            print(f"Grading error: {e}")
        return results

class HTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Suppress request logs to keep terminal clean
        return

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/upload":
            # Read content-length to get body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.wfile if content_length == 0 else self.rfile.read(content_length)
            
            # Read metadata headers
            no_refund_fix = self.headers.get("X-No-Refund-Fix", "false").lower() == "true"
            skip_validate = self.headers.get("X-Skip-Validate", "false").lower() == "true"
            
            # Save CSV file content to raw upload target
            upload_dir = ROOT / "data" / "raw"
            upload_dir.mkdir(parents=True, exist_ok=True)
            temp_file = upload_dir / "temp_upload.csv"
            
            try:
                temp_file.write_bytes(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Failed to save uploaded file: {e}"}).encode("utf-8"))
                return

            # Run etl_pipeline command in subprocess
            python_exe = sys.executable
            cmd = [python_exe, "etl_pipeline.py", "run", "--raw", str(temp_file)]
            if no_refund_fix:
                cmd.append("--no-refund-fix")
            if skip_validate:
                cmd.append("--skip-validate")
                
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            # Execute pipeline run
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env
            )
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            
            res_payload = {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0
            }
            self.wfile.write(json.dumps(res_payload, ensure_ascii=False).encode("utf-8"))
            return

        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Serve API endpoints
        if path == "/api/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = DashboardAPI.get_stats()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/query":
            q = query_params.get("q", [""])[0]
            top_k = int(query_params.get("top_k", [5])[0])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = DashboardAPI.query_chroma(q, top_k)
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/quarantine":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = DashboardAPI.get_quarantine()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/run-grading":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = DashboardAPI.run_grading()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        # Serve index html dashboard
        elif path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.get_html_content().encode("utf-8"))
            return

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def get_html_content(self) -> str:
        return """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Day 10 Pipeline Observability & Test UI</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #0b0f19;
            --bg-card: rgba(17, 24, 39, 0.7);
            --bg-accent: #1e1b4b;
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --color-indigo: #6366f1;
            --color-emerald: #10b981;
            --color-rose: #f43f5e;
            --color-amber: #f59e0b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-main);
            color: var(--text-primary);
            font-family: 'Outfit', sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(16, 185, 129, 0.1) 0%, transparent 40%);
        }

        header {
            border-bottom: 1px solid var(--border-color);
            background: rgba(11, 15, 25, 0.8);
            backdrop-filter: blur(12px);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .header-container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 1.25rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-weight: 700;
            font-size: 1.35rem;
            letter-spacing: -0.025em;
            background: linear-gradient(135deg, #a5b4fc 0%, var(--color-indigo) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .nav-tabs {
            display: flex;
            gap: 0.5rem;
            background: rgba(255, 255, 255, 0.03);
            padding: 0.25rem;
            border-radius: 10px;
            border: 1px solid var(--border-color);
        }

        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-secondary);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }

        .tab-btn:hover {
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.05);
        }

        .tab-btn.active {
            color: #fff;
            background: var(--color-indigo);
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
        }

        main {
            max-width: 1200px;
            width: 100%;
            margin: 2rem auto;
            padding: 0 2rem;
            flex: 1;
        }

        .tab-content {
            display: none;
            animation: fadeIn 0.3s ease-out;
        }

        .tab-content.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Dashboard Overview cards */
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .card {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
            transition: transform 0.25s ease, border-color 0.25s ease;
        }

        .card:hover {
            border-color: rgba(99, 102, 241, 0.3);
            transform: translateY(-2px);
        }

        .card-title {
            font-size: 0.875rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            margin-bottom: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .card-value {
            font-size: 2.25rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.5rem;
        }

        .card-value.emerald { color: var(--color-emerald); }
        .card-value.indigo { color: var(--color-indigo); }
        .card-value.rose { color: var(--color-rose); }
        .card-value.amber { color: var(--color-amber); }

        .card-desc {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        .badge {
            display: inline-block;
            padding: 0.25rem 0.6rem;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 9999px;
            text-transform: uppercase;
        }

        .badge.pass { background: rgba(16, 185, 129, 0.15); color: var(--color-emerald); }
        .badge.fail { background: rgba(244, 63, 94, 0.15); color: var(--color-rose); }
        .badge.warn { background: rgba(245, 158, 11, 0.15); color: var(--color-amber); }

        /* File Upload Playground Style */
        .playground-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }

        @media (max-width: 900px) {
            .playground-container {
                grid-template-columns: 1fr;
            }
        }

        .upload-zone {
            border: 2px dashed rgba(99, 102, 241, 0.3);
            background: rgba(99, 102, 241, 0.03);
            border-radius: 16px;
            padding: 2.5rem 1.5rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.25s ease;
            position: relative;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 1rem;
        }

        .upload-zone:hover, .upload-zone.dragover {
            border-color: var(--color-indigo);
            background: rgba(99, 102, 241, 0.08);
            box-shadow: 0 0 20px rgba(99, 102, 241, 0.15);
        }

        .upload-icon {
            color: var(--color-indigo);
            opacity: 0.8;
            transition: transform 0.25s;
        }

        .upload-zone:hover .upload-icon {
            transform: translateY(-4px);
        }

        .options-panel {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            cursor: pointer;
            font-size: 0.95rem;
            user-select: none;
        }

        .checkbox-group input {
            width: 18px;
            height: 18px;
            accent-color: var(--color-indigo);
            cursor: pointer;
        }

        /* Terminal Console */
        .terminal {
            background: #05070c;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.85rem;
            color: #d1d5db;
            line-height: 1.5;
            height: 350px;
            overflow-y: auto;
            white-space: pre-wrap;
            box-shadow: inset 0 2px 10px rgba(0,0,0,0.8);
            margin-top: 1.5rem;
            grid-column: span 2;
        }

        .terminal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: var(--text-secondary);
            font-size: 0.75rem;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            padding-bottom: 0.5rem;
            margin-bottom: 0.75rem;
            font-family: sans-serif;
        }

        /* Search / Query Section */
        .query-box {
            display: flex;
            gap: 0.75rem;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 0.75rem;
            border-radius: 12px;
            margin-bottom: 2rem;
        }

        .query-box input {
            flex: 1;
            background: transparent;
            border: none;
            color: #fff;
            font-family: inherit;
            font-size: 1.05rem;
            padding: 0.5rem 0.75rem;
            outline: none;
        }

        .query-box button {
            background: var(--color-indigo);
            color: white;
            border: none;
            padding: 0.75rem 1.75rem;
            border-radius: 8px;
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }

        .query-box button:hover {
            background: #4f46e5;
        }

        .select-k {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: #fff;
            padding: 0.5rem;
            border-radius: 8px;
            font-family: inherit;
            outline: none;
            cursor: pointer;
        }

        /* Search Results style */
        .search-results {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .result-item {
            background: rgba(17, 24, 39, 0.5);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            transition: all 0.2s ease;
        }

        .result-item:hover {
            background: rgba(255, 255, 255, 0.02);
            border-color: rgba(255, 255, 255, 0.15);
        }

        .result-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
            font-size: 0.85rem;
        }

        .result-meta {
            display: flex;
            gap: 1rem;
            color: var(--text-secondary);
        }

        .result-doc-id {
            color: #a5b4fc;
            font-weight: 600;
        }

        .result-distance {
            color: var(--color-amber);
            font-weight: 500;
        }

        .result-text {
            line-height: 1.6;
            font-size: 0.95rem;
        }

        /* Grading test cases table */
        .table-container {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
            margin-bottom: 2rem;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9rem;
        }

        th {
            background: rgba(255, 255, 255, 0.02);
            padding: 1rem 1.25rem;
            font-weight: 600;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border-color);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }

        td {
            padding: 1.1rem 1.25rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }

        tr:last-child td {
            border-bottom: none;
        }

        .question-col {
            font-weight: 500;
            max-width: 400px;
        }

        .preview-col {
            color: var(--text-secondary);
            font-size: 0.85rem;
            max-width: 300px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        /* Grading Control header */
        .action-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }

        .btn-primary {
            background: var(--color-indigo);
            color: white;
            border: none;
            padding: 0.6rem 1.5rem;
            border-radius: 8px;
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .btn-primary:hover {
            background: #4f46e5;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
        }

        /* Quarantine audit reasons styles */
        .quar-reason {
            color: var(--color-rose);
            font-weight: 600;
            background: rgba(244, 63, 94, 0.1);
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            font-size: 0.8rem;
            display: inline-block;
        }
        
        /* Footer */
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
            font-size: 0.85rem;
            border-top: 1px solid var(--border-color);
            margin-top: 4rem;
        }

        /* Pulse loading effect */
        .pulse-loader {
            display: inline-block;
            width: 12px;
            height: 12px;
            background-color: var(--color-indigo);
            border-radius: 50%;
            animation: pulse 1.2s infinite ease-in-out;
        }

        @keyframes pulse {
            0% { transform: scale(0.8); opacity: 0.5; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.8); opacity: 0.5; }
        }
    </style>
</head>
<body>

    <header>
        <div class="header-container">
            <div class="logo">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                CS-IT-Ops Observability Dashboard
            </div>
            <div class="nav-tabs">
                <button class="tab-btn active" onclick="switchTab('dashboard')">Dashboard</button>
                <button class="tab-btn" onclick="switchTab('pipeline')">Run Pipeline</button>
                <button class="tab-btn" onclick="switchTab('query')">Semantic Search</button>
                <button class="tab-btn" onclick="switchTab('grading')">Grading Suite</button>
                <button class="tab-btn" onclick="switchTab('quarantine')">Quarantine Audit</button>
            </div>
        </div>
    </header>

    <main>
        <!-- 1. DASHBOARD OVERVIEW -->
        <section id="dashboard" class="tab-content active">
            <div class="dashboard-grid">
                <div class="card">
                    <div class="card-title">
                        <span>Pipeline Status</span>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
                    </div>
                    <div class="card-value emerald" id="val-pipeline-status">Loading...</div>
                    <div class="card-desc" id="val-run-id">Run ID: ...</div>
                </div>

                <div class="card">
                    <div class="card-title">
                        <span>Records Volume</span>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
                    </div>
                    <div class="card-value indigo" id="val-records">0 / 0</div>
                    <div class="card-desc" id="val-quarantine">Quarantine: 0</div>
                </div>

                <div class="card">
                    <div class="card-title">
                        <span>Ingest Freshness</span>
                        <span id="badge-ingest-fresh" class="badge">N/A</span>
                    </div>
                    <div class="card-value amber" id="val-ingest-age">...</div>
                    <div class="card-desc">Thời gian từ lúc export ở nguồn</div>
                </div>

                <div class="card">
                    <div class="card-title">
                        <span>Publish Freshness</span>
                        <span id="badge-pub-fresh" class="badge">N/A</span>
                    </div>
                    <div class="card-value emerald" id="val-publish-age">...</div>
                    <div class="card-desc">Thời gian từ lúc nạp ChromaDB</div>
                </div>
            </div>

            <div class="table-container" style="padding: 1.5rem;">
                <h3 style="margin-bottom: 1rem; color: #fff;">Thông tin cấu hình Data Contract</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; font-size: 0.9rem;">
                    <div>
                        <div style="color: var(--text-secondary); margin-bottom: 0.25rem;">Dataset</div>
                        <div style="font-weight: 600;" id="contract-dataset">kb_chunk_export</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); margin-bottom: 0.25rem;">Owner Team</div>
                        <div style="font-weight: 600;" id="contract-owner">CS-IT-Ops</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); margin-bottom: 0.25rem;">Chroma Collection</div>
                        <div style="font-weight: 600;" id="contract-collection">day10_kb</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); margin-bottom: 0.25rem;">HR Cutoff Date</div>
                        <div style="font-weight: 600; color: var(--color-indigo);" id="contract-cutoff">2026-01-01</div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 2. RUN PIPELINE (PLAYGROUND) -->
        <section id="pipeline" class="tab-content">
            <div class="playground-container">
                <div class="upload-zone" id="drop-zone" onclick="document.getElementById('file-input').click()">
                    <svg class="upload-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    <div style="font-weight: 500; font-size: 1.05rem;">Kéo & Thả file CSV dữ liệu thô vào đây</div>
                    <div style="color: var(--text-secondary); font-size: 0.85rem;">hoặc click để chọn file từ máy tính</div>
                    <input type="file" id="file-input" accept=".csv" style="display:none;" onchange="handleFileSelected(event)">
                    <div id="file-name-label" style="font-weight: 600; color: var(--color-indigo); margin-top: 0.5rem; display:none;"></div>
                </div>

                <div class="options-panel">
                    <h3 style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem; color: #fff;">Tùy chọn thực thi</h3>
                    
                    <label class="checkbox-group">
                        <input type="checkbox" id="opt-no-refund">
                        <span>Bỏ qua sửa lỗi hoàn tiền (--no-refund-fix)</span>
                    </label>

                    <label class="checkbox-group">
                        <input type="checkbox" id="opt-skip-validate">
                        <span>Bỏ qua kiểm định chất lượng (--skip-validate)</span>
                    </label>

                    <div style="flex:1; display:flex; align-items:flex-end;">
                        <button class="btn-primary" id="run-pipeline-btn" onclick="startETLPipeline()" style="width:100%; justify-content:center; padding: 0.85rem;" disabled>
                            Chạy ETL Pipeline
                        </button>
                    </div>
                </div>

                <div class="terminal">
                    <div class="terminal-header">
                        <span>CONSOLE PIPELINE LOGS</span>
                        <span id="terminal-status">READY</span>
                    </div>
                    <div id="terminal-output" style="max-height: 290px; overflow-y:auto; font-size: 0.85rem;">Mời bạn chèn tệp dữ liệu CSV thô bên trên và nhấn "Chạy ETL Pipeline" để quan sát trực tiếp luồng chạy.</div>
                </div>
            </div>
        </section>

        <!-- 3. SEMANTIC SEARCH TEST -->
        <section id="query" class="tab-content">
            <div class="query-box">
                <input type="text" id="query-input" placeholder="Nhập câu hỏi để tìm kiếm ngữ cảnh (ví dụ: hoàn tiền bao nhiêu ngày?)..." onkeydown="if(event.key==='Enter') executeQuery()">
                <select id="query-topk" class="select-k">
                    <option value="1">Top 1</option>
                    <option value="3" selected>Top 3</option>
                    <option value="5">Top 5</option>
                </select>
                <button onclick="executeQuery()">Tìm kiếm</button>
            </div>

            <div class="search-results" id="search-results-list">
                <div style="color: var(--text-secondary); text-align: center; padding: 2rem;">Nhập câu hỏi và nhấn Tìm kiếm để test RAG retrieval.</div>
            </div>
        </section>

        <!-- 4. GRADING SUITE -->
        <section id="grading" class="tab-content">
            <div class="action-bar">
                <h2 style="font-size: 1.25rem; font-weight: 600;">Danh sách 10 câu hỏi kiểm tra grading (Chấm tự động)</h2>
                <button class="btn-primary" onclick="runGradingSuite()">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
                    Chạy Test Grading
                </button>
            </div>

            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Câu hỏi</th>
                            <th>Top 1 Doc ID</th>
                            <th>Preview Context</th>
                            <th>Expected?</th>
                            <th>No Forbidden?</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="grading-tbody">
                        <tr>
                            <td colspan="7" style="text-align: center; color: var(--text-secondary); padding: 2rem;">
                                Nhấn nút "Chạy Test Grading" để chấm điểm tự động.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <!-- 5. QUARANTINE AUDIT -->
        <section id="quarantine" class="tab-content">
            <div class="action-bar">
                <h2 style="font-size: 1.25rem; font-weight: 600;">Dữ liệu bị cô lập trong Quarantine (Tối đa 50 dòng mới nhất)</h2>
                <button class="btn-primary" onclick="loadQuarantine()">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
                    Tải lại danh sách
                </button>
            </div>

            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Doc ID</th>
                            <th>Lý do Quarantine</th>
                            <th>Nội dung Chunk (Raw)</th>
                            <th>Ngày hiệu lực</th>
                        </tr>
                    </thead>
                    <tbody id="quarantine-tbody">
                        <tr>
                            <td colspan="4" style="text-align: center; color: var(--text-secondary); padding: 2rem;">Loading...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    </main>

    <footer>
        CS-IT-Ops Team &bull; Lab Day 10 Data Observability &bull; AI in Action
    </footer>

    <script>
        let selectedFile = null;

        // Switch nav tabs
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');

            if (tabId === 'quarantine') {
                loadQuarantine();
            }
        }

        // Drag & drop logic
        const dropZone = document.getElementById('drop-zone');
        
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                dropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                dropZone.classList.remove('dragover');
            }, false);
        });

        dropZone.addEventListener('drop', e => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length > 0 && files[0].name.endsWith('.csv')) {
                setFile(files[0]);
            }
        });

        function handleFileSelected(e) {
            const files = e.target.files;
            if (files.length > 0) {
                setFile(files[0]);
            }
        }

        function setFile(file) {
            selectedFile = file;
            const label = document.getElementById('file-name-label');
            label.innerText = `Đã chọn: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
            label.style.display = 'block';
            document.getElementById('run-pipeline-btn').disabled = false;
        }

        // Start ETL Pipeline run
        async function startETLPipeline() {
            if (!selectedFile) return;

            const noRefundFix = document.getElementById('opt-no-refund').checked;
            const skipValidate = document.getElementById('opt-skip-validate').checked;
            const terminal = document.getElementById('terminal-output');
            const terminalStatus = document.getElementById('terminal-status');
            const runBtn = document.getElementById('run-pipeline-btn');

            runBtn.disabled = true;
            terminalStatus.innerText = 'RUNNING';
            terminalStatus.style.color = 'var(--color-indigo)';
            terminal.innerHTML = 'Đang đọc tệp và gửi dữ liệu lên server...\\n';

            const reader = new FileReader();
            reader.onload = async function(e) {
                const csvData = e.target.result;
                terminal.innerHTML += 'Đang chạy ETL Pipeline (Injest -> Clean -> Validate -> Embed)...\\n';
                
                try {
                    const response = await fetch('/api/upload', {
                        method: 'POST',
                        body: csvData,
                        headers: {
                            'Content-Type': 'text/csv',
                            'X-No-Refund-Fix': noRefundFix ? 'true' : 'false',
                            'X-Skip-Validate': skipValidate ? 'true' : 'false'
                        }
                    });
                    
                    const data = await response.json();
                    
                    // Format terminal console output logs
                    let logHtml = data.stdout || '';
                    if (data.stderr) {
                        logHtml += '\\n\\n--- ERRORS/STDERR ---\\n' + data.stderr;
                    }
                    
                    // Highlights keywords in console log
                    logHtml = logHtml
                        .replace(/(OK)/g, '<span style="color:var(--color-emerald); font-weight:600;">$1</span>')
                        .replace(/(FAIL|ERROR|PIPELINE_HALT)/g, '<span style="color:var(--color-rose); font-weight:600;">$1</span>')
                        .replace(/(WARN)/g, '<span style="color:var(--color-amber); font-weight:600;">$1</span>');

                    terminal.innerHTML = logHtml;
                    terminal.scrollTop = terminal.scrollHeight;
                    
                    if (data.success) {
                        terminalStatus.innerText = 'SUCCESS';
                        terminalStatus.style.color = 'var(--color-emerald)';
                    } else {
                        terminalStatus.innerText = 'HALTED / FAIL';
                        terminalStatus.style.color = 'var(--color-rose)';
                    }
                    
                    // Refresh dashboard data
                    loadStats();
                } catch (err) {
                    terminal.innerHTML += `\\n[ERROR] Lỗi gọi API: ${err}`;
                    terminalStatus.innerText = 'API ERROR';
                    terminalStatus.style.color = 'var(--color-rose)';
                } finally {
                    runBtn.disabled = false;
                }
            };
            
            reader.readAsArrayBuffer(selectedFile);
        }

        // Load stats for Dashboard
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const data = await response.json();
                
                const m = data.manifest;
                if (m.run_id) {
                    document.getElementById('val-pipeline-status').innerText = m.skipped_validate ? 'WARNING' : 'PIPELINE_OK';
                    document.getElementById('val-pipeline-status').className = m.skipped_validate ? 'card-value amber' : 'card-value emerald';
                    document.getElementById('val-run-id').innerText = `Run ID: ${m.run_id}`;
                    document.getElementById('val-records').innerText = `${m.cleaned_records} / ${m.raw_records}`;
                    document.getElementById('val-quarantine').innerText = `Quarantine: ${m.quarantine_records}`;
                    
                    document.getElementById('contract-dataset').innerText = m.dataset || 'kb_chunk_export';
                    document.getElementById('contract-collection').innerText = m.chroma_collection || 'day10_kb';
                }
                
                const f = data.freshness;
                document.getElementById('val-ingest-age').innerText = f.ingest_age;
                document.getElementById('badge-ingest-fresh').innerText = f.status === 'FAIL' && f.ingest_age !== 'N/A' ? 'FAIL' : 'PASS';
                document.getElementById('badge-ingest-fresh').className = `badge ${f.status === 'FAIL' ? 'fail' : 'pass'}`;
                
                document.getElementById('val-publish-age').innerText = f.publish_age;
                document.getElementById('badge-pub-fresh').innerText = 'PASS';
                document.getElementById('badge-pub-fresh').className = 'badge pass';
            } catch (err) {
                console.error("Error loading stats:", err);
            }
        }

        // Execute semantic search query
        async function executeQuery() {
            const query = document.getElementById('query-input').value.trim();
            const top_k = document.getElementById('query-topk').value;
            if (!query) return;

            const list = document.getElementById('search-results-list');
            list.innerHTML = '<div style="text-align:center; padding: 2rem;"><span class="pulse-loader"></span></div>';

            try {
                const response = await fetch(`/api/query?q=${encodeURIComponent(query)}&top_k=${top_k}`);
                const data = await response.json();

                if (data.status === 'success') {
                    if (data.results.length === 0) {
                        list.innerHTML = '<div style="color: var(--text-secondary); text-align: center; padding: 2rem;">Không tìm thấy dữ liệu tương đồng.</div>';
                        return;
                    }
                    list.innerHTML = data.results.map(r => `
                        <div class="result-item">
                            <div class="result-header">
                                <div class="result-meta">
                                    <span class="result-doc-id">${r.metadata.doc_id || 'N/A'}</span>
                                    <span>ID: ${r.id}</span>
                                    <span>Date: ${r.metadata.effective_date || 'N/A'}</span>
                                </div>
                                <div class="result-distance">Score: ${r.distance}</div>
                            </div>
                            <div class="result-text">${r.text}</div>
                        </div>
                    `).join('');
                } else {
                    list.innerHTML = `<div style="color: var(--color-rose); text-align: center; padding: 2rem;">Lỗi: ${data.message}</div>`;
                }
            } catch (err) {
                list.innerHTML = `<div style="color: var(--color-rose); text-align: center; padding: 2rem;">Lỗi kết nối API: ${err}</div>`;
            }
        }

        // Run grading suite check
        async function runGradingSuite() {
            const tbody = document.getElementById('grading-tbody');
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 2rem;"><span class="pulse-loader"></span><br><br>Đang chạy RAG retrieval chấm điểm...</td></tr>';

            try {
                const response = await fetch('/api/run-grading');
                const data = await response.json();

                if (data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-secondary); padding: 2rem;">Không tải được câu hỏi kiểm tra.</td></tr>';
                    return;
                }

                tbody.innerHTML = data.map(q => {
                    const statusClass = (q.contains_expected && !q.hits_forbidden && (q.top1_doc_matches !== false)) ? 'pass' : 'fail';
                    const statusText = statusClass === 'pass' ? 'PASS' : 'FAIL';
                    
                    return `
                        <tr>
                            <td style="font-family: monospace; font-weight: 600;">${q.id}</td>
                            <td class="question-col">${q.question}</td>
                            <td style="font-family: monospace; color:#a5b4fc;">${q.top1_doc_id || 'None'}</td>
                            <td class="preview-col" title="${q.top1_preview}">${q.top1_preview}</td>
                            <td><span class="badge ${q.contains_expected ? 'pass' : 'fail'}">${q.contains_expected ? 'YES' : 'NO'}</span></td>
                            <td><span class="badge ${!q.hits_forbidden ? 'pass' : 'fail'}">${!q.hits_forbidden ? 'YES' : 'NO'}</span></td>
                            <td><span class="badge ${statusClass}">${statusText}</span></td>
                        </tr>
                    `;
                }).join('');
            } catch (err) {
                tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--color-rose); padding: 2rem;">Lỗi kết nối API: ${err}</td></tr>`;
            }
        }

        // Load quarantine logs
        async function loadQuarantine() {
            const tbody = document.getElementById('quarantine-tbody');
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;"><span class="pulse-loader"></span></td></tr>';

            try {
                const response = await fetch('/api/quarantine');
                const data = await response.json();

                if (data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-secondary); padding: 2rem;">Quarantine rỗng. Mọi bản ghi đều sạch!</td></tr>';
                    return;
                }

                tbody.innerHTML = data.map(r => `
                    <tr>
                        <td style="font-family: monospace; color: #a5b4fc; font-weight: 600;">${r.doc_id || 'N/A'}</td>
                        <td><span class="quar-reason">${r.reason || 'N/A'}</span></td>
                        <td style="font-size: 0.85rem; line-height: 1.4; max-width: 500px;">${r.chunk_text || ''}</td>
                        <td style="font-family: monospace;">${r.effective_date || r.effective_date_raw || 'N/A'}</td>
                    </tr>
                `).join('');
            } catch (err) {
                tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--color-rose); padding: 2rem;">Lỗi kết nối API: ${err}</td></tr>`;
            }
        }

        // Auto initialization
        window.addEventListener('DOMContentLoaded', () => {
            loadStats();
        });
    </script>
</body>
</html>
"""

def run_server(port: int = 8000) -> None:
    server_address = ("", port)
    httpd = HTTPServer(server_address, HTTPRequestHandler)
    print(f"============================================================")
    print(f"   Dashboard Testing UI is running on: http://localhost:{port}")
    print(f"   Press Ctrl+C to terminate.")
    print(f"============================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server...")
        httpd.server_close()

if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_server(port)
