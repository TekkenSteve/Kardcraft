# Simple Ragix Web UI for manual testing
# - Upload file to MinIO
# - Index via RagixClient
# - Query via RagixClient

import os
import uuid
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse

from kardcraft.ragix import RagixClient
from kardcraft.services.minio_client import MinIOClient
from dotenv import load_dotenv


app = FastAPI(title="Ragix Web UI (Test)")


class AppState:
    def __init__(self) -> None:
        self.ragix: Optional[RagixClient] = None
        self.ragix_mode: str = "default"
        self.minio: Optional[MinIOClient] = None
        self.bucket: str = os.getenv("RAGIX_UI_BUCKET", "ragix-tests")
        self.uploads: Dict[str, Dict[str, Any]] = {}
        self.indexed: Dict[str, Dict[str, Any]] = {}


STATE = AppState()


@app.on_event("startup")
async def startup() -> None:
    # Load .env.llm from repo root if present (for local testing)
    repo_root = Path(__file__).resolve().parents[5]
    env_path = repo_root / ".env.llm"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)

    # Initialize Ragix client (default mode)
    STATE.ragix = RagixClient()
    await STATE.ragix.initialize()

    # Initialize MinIO client
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    STATE.minio = MinIOClient(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )
    await STATE.minio.connect()

    # Ensure bucket exists
    if STATE.minio.client is not None:
        if not STATE.minio.client.bucket_exists(STATE.bucket):
            STATE.minio.client.make_bucket(STATE.bucket)


def _parse_file_ids(raw: str) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p]


def _get_lightrag_debug(session_id: str) -> str:
    if STATE.ragix is None or not session_id:
        return ""

    try:
        return "LightRAG server mode: local workspace debug is not available."
    except Exception as e:
        return f"debug_error: {e}"


def _get_lightrag_session_dir(session_id: str) -> Path:
    raise RuntimeError(
        "Local LightRAG workspace paths are not available in server mode."
    )


def _set_lightrag_cosine_threshold(session_id: str, cosine_threshold: float) -> None:
    raise RuntimeError("cosine_threshold is not supported in server mode.")


def _render_page(message: str = "", result: str = "") -> str:
    uploads_list = "\n".join(
        [
            f"<li><code>{fid}</code> - {info['filename']} ({info['object_name']})</li>"
            for fid, info in STATE.uploads.items()
        ]
    )
    indexed_list = "\n".join(
        [
            f"<li><code>{fid}</code> → <code>{info['doc_id']}</code></li>"
            for fid, info in STATE.indexed.items()
        ]
    )

    return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Ragix Web UI (Test)</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; max-width: 960px; }}
      input, textarea {{ width: 100%; padding: 8px; margin: 6px 0; }}
      button {{ padding: 8px 12px; }}
      .box {{ border: 1px solid #ddd; padding: 12px; margin: 12px 0; }}
      .muted {{ color: #666; font-size: 12px; }}
      ul {{ padding-left: 20px; }}
      code {{ background: #f3f3f3; padding: 2px 4px; }}
    </style>
  </head>
  <body>
    <h1>Ragix Web UI (Test)</h1>
    <div class="muted">Bucket: {STATE.bucket}</div>

    <div class="box">
      <h3>Upload to MinIO</h3>
      <form action="/upload" method="post" enctype="multipart/form-data">
        <label>Session ID</label>
        <input name="session_id" placeholder="test-session" />
        <label>File</label>
        <input type="file" name="file" />
        <button type="submit">Upload</button>
      </form>
    </div>

    <div class="box">
      <h3>Index (by file_ids)</h3>
      <form action="/index" method="post">
        <label>Session ID (workspace)</label>
        <input name="session_id" placeholder="test-session" />
        <label>Ragix Mode</label>
        <select name="ragix_mode">
          <option value="default" {"selected" if STATE.ragix_mode == "default" else ""}>default (full)</option>
          <option value="light" {"selected" if STATE.ragix_mode == "light" else ""}>light (docling + text)</option>
          <option value="no_mm" {"selected" if STATE.ragix_mode == "no_mm" else ""}>no_mm (disable multimodal)</option>
        </select>
        <label>File IDs (comma or newline separated)</label>
        <textarea name="file_ids" rows="3" placeholder="{list(STATE.uploads.keys())[:3]}"></textarea>
        <label>Parser Override (optional, e.g. mineru_api)</label>
        <input name="parser_override" placeholder="leave blank for smart parser" />
        <label>Parse Method Override (optional, e.g. auto)</label>
        <input name="parse_method_override" placeholder="leave blank for default" />
        <label>MinerU API URL (optional)</label>
        <input name="mineru_api_url" placeholder="http://localhost:30001" />
        <label>MinerU Cloud API Base URL (optional)</label>
        <input name="mineru_cloud_api_url" placeholder="https://mineru.net/api/v4" />
        <label>MinerU Cloud API Token (optional, no Bearer)</label>
        <input name="mineru_cloud_api_token" placeholder="token only" />
        <label>MinerU Cloud Model Version (optional, e.g. vlm)</label>
        <input name="mineru_cloud_model" placeholder="vlm" />
        <label>MinerU Cloud is_ocr (optional)</label>
        <input name="mineru_cloud_is_ocr" placeholder="true/false" />
        <label>MinerU Cloud enable_formula (optional)</label>
        <input name="mineru_cloud_enable_formula" placeholder="true/false" />
        <label>MinerU Cloud enable_table (optional)</label>
        <input name="mineru_cloud_enable_table" placeholder="true/false" />
        <label>MinerU Cloud language (optional, e.g. ch)</label>
        <input name="mineru_cloud_language" placeholder="ch" />
        <label>MinerU Cloud page_ranges (optional, e.g. 1-3,5)</label>
        <input name="mineru_cloud_page_ranges" placeholder="1-3,5" />
        <label>MinerU Cloud data_id (optional)</label>
        <input name="mineru_cloud_data_id" placeholder="my-data-id" />
        <button type="submit">Index</button>
      </form>
    </div>

    <div class="box">
      <h3>Query</h3>
      <form action="/query" method="post">
        <label>Session ID</label>
        <input name="session_id" placeholder="test-session" />
        <label>User ID (optional, only if you want Ragix to try file_ids path)</label>
        <input name="user_id" placeholder="user-1" />
        <label>File IDs (comma or newline separated)</label>
        <textarea name="file_ids" rows="2"></textarea>
        <label>Query Mode</label>
        <select name="mode">
          <option value="naive">naive</option>
          <option value="local">local</option>
          <option value="global">global</option>
          <option value="hybrid">hybrid</option>
          <option value="mix" selected>mix</option>
        </select>
        <label>Question</label>
        <textarea name="question" rows="4"></textarea>
        <button type="submit">Query</button>
      </form>
    </div>

    <div class="box">
      <h3>Reset Session</h3>
      <form action="/reset" method="post">
        <label>Session ID</label>
        <input name="session_id" placeholder="test-session" />
        <button type="submit">Reset</button>
      </form>
    </div>

    <div class="box">
      <h3>Uploaded Files</h3>
      <ul>{uploads_list}</ul>
      <h3>Indexed Files</h3>
      <ul>{indexed_list}</ul>
    </div>

    <div class="box">
      <h3>Status</h3>
      <div>{message}</div>
      <pre>{result}</pre>
    </div>
  </body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _render_page()


@app.post("/upload", response_class=HTMLResponse)
async def upload(
    session_id: str = Form("test-session"),
    file: UploadFile = File(...),
) -> str:
    if STATE.minio is None:
        return _render_page("MinIO client not initialized")

    content = await file.read()
    file_id = uuid.uuid4().hex
    object_name = f"{session_id}/{file_id}_{file.filename}"

    ok = await STATE.minio.put_file(
        STATE.bucket,
        object_name,
        content,
        content_type=file.content_type or "application/octet-stream",
    )

    if ok:
        STATE.uploads[file_id] = {
            "filename": file.filename,
            "content_type": file.content_type,
            "object_name": object_name,
            "session_id": session_id,
        }
        return _render_page(f"Uploaded file_id={file_id}")

    return _render_page("Upload failed")


@app.post("/index", response_class=HTMLResponse)
async def index_files(
    file_ids: str = Form(""),
    ragix_mode: str = Form("default"),
    session_id: str = Form(""),
    parser_override: str = Form(""),
    parse_method_override: str = Form(""),
    mineru_api_url: str = Form(""),
    mineru_cloud_api_url: str = Form(""),
    mineru_cloud_api_token: str = Form(""),
    mineru_cloud_model: str = Form(""),
    mineru_cloud_is_ocr: str = Form(""),
    mineru_cloud_enable_formula: str = Form(""),
    mineru_cloud_enable_table: str = Form(""),
    mineru_cloud_language: str = Form(""),
    mineru_cloud_page_ranges: str = Form(""),
    mineru_cloud_data_id: str = Form(""),
) -> str:
    if STATE.minio is None or STATE.ragix is None:
        return _render_page("MinIO or Ragix client not initialized")

    if ragix_mode not in {"default", "light", "no_mm"}:
        ragix_mode = "default"

    if ragix_mode != STATE.ragix_mode:
        STATE.ragix = RagixClient()
        await STATE.ragix.initialize()
        STATE.ragix_mode = ragix_mode

    ids = _parse_file_ids(file_ids)
    if not ids:
        ids = list(STATE.uploads.keys())
    if not ids:
        return _render_page("No file_ids provided")

    results = []
    for fid in ids:
        info = STATE.uploads.get(fid)
        if not info:
            results.append({"file_id": fid, "error": "Unknown file_id"})
            continue

        data = await STATE.minio.get_file(STATE.bucket, info["object_name"])
        if data is None:
            results.append({"file_id": fid, "error": "File not found in MinIO"})
            continue

        suffix = Path(info["filename"]).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            parser_params = {}
            if mineru_api_url.strip():
                parser_params["server_url"] = mineru_api_url.strip()
            if mineru_cloud_api_url.strip():
                parser_params["api_base_url"] = mineru_cloud_api_url.strip()
            if mineru_cloud_api_token.strip():
                parser_params["api_token"] = mineru_cloud_api_token.strip()
            if mineru_cloud_model.strip():
                parser_params["model_version"] = mineru_cloud_model.strip()
            if mineru_cloud_is_ocr.strip():
                parser_params["is_ocr"] = mineru_cloud_is_ocr.strip().lower() in {"1", "true", "yes", "on"}
            if mineru_cloud_enable_formula.strip():
                parser_params["enable_formula"] = mineru_cloud_enable_formula.strip().lower() in {"1", "true", "yes", "on"}
            if mineru_cloud_enable_table.strip():
                parser_params["enable_table"] = mineru_cloud_enable_table.strip().lower() in {"1", "true", "yes", "on"}
            if mineru_cloud_language.strip():
                parser_params["language"] = mineru_cloud_language.strip()
            if mineru_cloud_page_ranges.strip():
                parser_params["page_ranges"] = mineru_cloud_page_ranges.strip()
            if mineru_cloud_data_id.strip():
                parser_params["data_id"] = mineru_cloud_data_id.strip()

            doc_id = await STATE.ragix.add_local_document(
                tmp_path,
                session_id=session_id or None,
                parser_override=parser_override.strip() or None,
                parse_method_override=parse_method_override.strip() or None,
                parser_params=parser_params or None,
            )
            STATE.indexed[fid] = {"doc_id": doc_id, "file_path": tmp_path}
            results.append({"file_id": fid, "doc_id": doc_id})
        except Exception as e:
            results.append({"file_id": fid, "error": str(e)})

    debug = _get_lightrag_debug(session_id)
    result_text = json.dumps(results, ensure_ascii=False, indent=2)
    if debug:
        result_text = f"{result_text}\n\nLightRAG Debug\n{debug}"
    return _render_page("Index complete", result_text)


@app.post("/query", response_class=HTMLResponse)
async def query(
    session_id: str = Form(""),
    user_id: str = Form(""),
    file_ids: str = Form(""),
    mode: str = Form("mix"),
    question: str = Form(""),
) -> str:
    if STATE.ragix is None:
        return _render_page("Ragix client not initialized")

    ids = _parse_file_ids(file_ids)
    if not question.strip():
        return _render_page("Question is required")


    try:
        answer = await STATE.ragix.query(
            question,
            session_id=session_id or None,
            file_ids=ids or None,
            user_id=user_id or None,
            mode=mode,
        )
        result = {
            "text": getattr(answer, "text", str(answer)),
            "citations": [
                {"text": ref.text, "metadata": ref.metadata, "score": ref.score}
                for ref in getattr(answer, "citations", [])
            ],
        }
        debug = _get_lightrag_debug(session_id)
        result_text = json.dumps(result, ensure_ascii=False, indent=2)
        if debug:
            result_text = f"{result_text}\n\nLightRAG Debug\n{debug}"
        return _render_page("Query complete", result_text)
    except Exception as e:
        return _render_page("Query failed", str(e))


@app.post("/reset", response_class=HTMLResponse)
async def reset_session(session_id: str = Form("")) -> str:
    if STATE.ragix is None:
        return _render_page("Ragix client not initialized")

    if not session_id:
        return _render_page("Session ID is required")

    try:
        await STATE.ragix.delete_session(session_id)
        # Also delete local workspace directory if exists
        ws_dir = _get_lightrag_session_dir(session_id)
        if ws_dir.exists():
            import shutil
            shutil.rmtree(ws_dir, ignore_errors=True)
        return _render_page(f"Session {session_id} reset")
    except Exception as e:
        return _render_page("Reset failed", str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "kardcraft.ragix.tests.web_ui:app",
        host="0.0.0.0",
        port=int(os.getenv("RAGIX_UI_PORT", "8050")),
        reload=False,
    )
