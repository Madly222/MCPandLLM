# main.py
import os
import logging
import asyncio
import hashlib
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from agent.agent import agent_process
from vector_store import vector_store
from tools.upload_tool import save_and_index_file
from tools.chunking_tool import index_file
from user.users import verify_user
from user.auth import create_access_token, decode_access_token
from fastapi.responses import RedirectResponse

from tools.file_tool import read_file
from tools.excel_tool import read_excel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
web_dir = BASE_DIR / "web"

STORAGE_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", BASE_DIR / "downloads"))

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_USER_ID = "default"

if web_dir.exists():
    app.mount("/web", StaticFiles(directory=web_dir), name="web")

PUBLIC_PATHS = {
    "/login",
    "/web/login.html",
    "/web/style.css",
    "/web/script.js",
    "/favicon.ico",
}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Публичные пути
    if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi.json"):
        return await call_next(request)

    # Берём токен из куки
    token = request.cookies.get("token", "")

    if not token:
        # Редирект на login
        return RedirectResponse(url="/web/login.html")

    try:
        data = decode_access_token(token)
        request.state.user = data["username"]
        request.state.role = data["role"]
    except HTTPException:
        return RedirectResponse(url="/web/login.html")

    return await call_next(request)

def chunk_text_with_overlap(text: str, max_words: int = 500, overlap_words: int = 50):
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        start += (max_words - overlap_words)
    return chunks

def _compute_doc_hash(content: str) -> str:
    return hashlib.md5(content.encode('utf-8')).hexdigest()

# --- new indexing function for a single file and specific user_id ---
def index_file_for_user(file_path: Path, user_id: str) -> dict:
    """
    Index one file and mark it with user_id.
    - Adds/updates FullDocument (with doc_hash)
    - If full doc added/changed and it's text-like, creates chunks in Document.
    Returns dict with keys: success(bool), note(str), added_chunks(int)
    """
    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx', '.xls', '.md', '.csv', '.log'}
    if not file_path.exists() or not file_path.is_file():
        return {"success": False, "note": "file not found"}

    if file_path.suffix.lower() not in supported_extensions:
        return {"success": False, "note": "unsupported extension"}

    try:
        # Read content
        if file_path.suffix.lower() in ['.xlsx', '.xls']:
            raw = read_excel(str(file_path))
            if isinstance(raw, list):
                # join rows and cells into text
                content = "\n".join(" ".join(map(str, row)) for row in raw)
            else:
                content = str(raw)
            is_table = True
        else:
            content = read_file(file_path)
            if content is None:
                return {"success": False, "note": "read error"}
            content = str(content)
            is_table = False

        # normalize content
        content = content.strip()
        doc_hash = _compute_doc_hash(content)

        # Try to add full document (vector_store.add_full_document checks doc_hash and will skip if unchanged)
        meta = {
            "is_table": is_table,
            "source_path": str(file_path),
            "doc_hash": doc_hash,
            "row_count": 0,
            "columns": ""
        }
        full_result = vector_store.add_full_document(
            content=content,
            filename=file_path.name,
            filetype=file_path.suffix.lstrip('.'),
            user_id=user_id,
            metadata=meta
        )

        # If full_result indicates skipped (no changes) — we can safely return
        if full_result.get("success") and full_result.get("skipped"):
            return {"success": True, "note": "unchanged, skipped", "added_chunks": 0}

        # Otherwise: full doc added/updated — rebuild chunks for Document collection
        # First delete old chunks (safe even if none)
        try:
            # use internal method (exists in your vector_store)
            vector_store._delete_chunks(file_path.name, user_id)
        except Exception:
            # fallback: ignore deletion error but continue
            logger.debug(f"Could not delete previous chunks for {file_path.name} / {user_id}")

        added_chunks = 0
        # For tables, you may want to NOT chunk — here we skip chunking for tables
        if not is_table:
            chunks = chunk_text_with_overlap(content, max_words=500, overlap_words=50)
            for idx, chunk in enumerate(chunks):
                r = vector_store.add_document(
                    content=chunk,
                    filename=file_path.name,
                    filetype=file_path.suffix.lstrip('.'),
                    user_id=user_id,
                    metadata={
                        "chunk_index": idx,
                        "total_chunks": len(chunks),
                        "source_path": str(file_path),
                        "doc_hash": doc_hash
                    }
                )
                if r.get("success"):
                    added_chunks += 1
                else:
                    logger.warning(f"[{user_id}] Ошибка индексации чанка {idx} для {file_path.name}: {r}")
        else:
            # For tables we only added full document; optionally add a single Document entry that is the full table
            r = vector_store.add_document(
                content=content,
                filename=file_path.name,
                filetype=file_path.suffix.lstrip('.'),
                user_id=user_id,
                metadata={
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "source_path": str(file_path),
                    "is_table": True,
                    "doc_hash": doc_hash
                }
            )
            if r.get("success"):
                added_chunks = 1

        return {"success": True, "note": "indexed", "added_chunks": added_chunks}

    except Exception as e:
        logger.error(f"Ошибка при индексации файла {file_path}: {e}")
        return {"success": False, "note": str(e)}

# --- replacement load_storage_files() ---
def load_storage_files():
    """
    Walk every user folder inside STORAGE_DIR and index all files.
    Uses index_file_for_user() which deduplicates by doc_hash.
    """
    if not vector_store.is_connected():
        logger.warning("Weaviate не подключен.")
        return

    if not STORAGE_DIR.exists():
        logger.warning(f"Папка storage не найдена: {STORAGE_DIR}")
        return

    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx', '.xls', '.md', '.csv', '.log'}

    # Walk top-level entries inside storage: expect each to be a user folder
    for user_folder in sorted(STORAGE_DIR.iterdir()):
        if not user_folder.is_dir():
            # optionally, if there are files directly under storage/ (legacy), index them under DEFAULT_USER_ID
            if user_folder.is_file() and user_folder.suffix.lower() in supported_extensions:
                # treat as default user
                try:
                    res = index_file_for_user(user_folder, DEFAULT_USER_ID)
                    logger.info(f"[{DEFAULT_USER_ID}] {user_folder.name}: {res.get('note')}")
                except Exception as e:
                    logger.error(f"Ошибка загрузки {user_folder}: {e}")
            continue

        user_id = user_folder.name
        logger.info(f"Scanning folder for user: {user_id} -> {user_folder}")

        # iterate files inside user folder
        for file_path in sorted(user_folder.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in supported_extensions:
                logger.debug(f"Skipping unsupported file: {file_path}")
                continue

            try:
                res = index_file_for_user(file_path, user_id)
                if res.get("success"):
                    logger.info(f"[{user_id}] {file_path.name}: {res.get('note')} (+{res.get('added_chunks',0)} chunks)")
                else:
                    logger.warning(f"[{user_id}] {file_path.name}: failed => {res.get('note')}")
            except Exception as e:
                logger.error(f"[{user_id}] Ошибка загрузки {file_path.name}: {e}")

@app.on_event("startup")
async def startup():
    if not vector_store.is_connected():
        if vector_store.connect():
            logger.info("Weaviate подключен")
        else:
            logger.warning("Не удалось подключиться к Weaviate")
    load_storage_files()
    asyncio.create_task(periodic_task())

async def periodic_task():
    while True:
        try:
            load_storage_files()
            logger.info("load_storage_files выполнен")
        except Exception as e:
            logger.error(f"Ошибка periodic_task: {e}")
        await asyncio.sleep(300)

@app.post("/login")
async def login(data: dict):
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return JSONResponse({"success": False, "message": "Username and password required"}, status_code=400)

    ok, role = verify_user(username, password)
    if not ok:
        return JSONResponse({"success": False, "message": "Invalid credentials"}, status_code=401)

    token = create_access_token(username, role)
    response = JSONResponse({"success": True, "username": username, "role": role})

    # безопасная кука
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,  # недоступно JS, безопаснее
        samesite="lax",
        max_age=3600
    )
    return response

@app.get("/")
async def index(request: Request):
    index_file_path = web_dir / "index.html"
    if index_file_path.exists():
        return FileResponse(index_file_path)
    raise HTTPException(status_code=404, detail="index.html не найден")

@app.post("/query")
async def query(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return {"response": "Пустой запрос"}

    user_id = request.state.user  # Всегда из токена

    logger.info(f"Запрос от {user_id}: {prompt}")

    try:
        response = await agent_process(prompt, user_id)
        return {"response": response}
    except Exception as e:
        logger.exception("Ошибка обработки")
        return {"response": f"Ошибка: {e}"}

@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...), user_id: str = None):
    token_user = request.state.user
    if not user_id:
        form = await request.form()
        user_id = form.get("user_id") or token_user
    if user_id != token_user:
        raise HTTPException(status_code=403, detail="user_id does not match authenticated user")

    file_bytes = await file.read()
    success = save_and_index_file(file_bytes, file.filename, user_id=token_user)
    if success:
        return {"message": f"Файл {file.filename} загружен"}
    raise HTTPException(status_code=500, detail="Ошибка сохранения")

@app.get("/download/{filename:path}")
async def download_file(request: Request, filename: str):
    file_path = DOWNLOADS_DIR / filename
    if not file_path.exists():
        file_path = STORAGE_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Файл {filename} не найден")

    encoded_filename = quote(filename)
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )

@app.get("/files")
async def list_files(request: Request):
    token_user = request.state.user
    files = []

    if STORAGE_DIR.exists():
        for f in STORAGE_DIR.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "type": "storage",
                    "size": f.stat().st_size,
                    "download_url": f"/download/{f.name}"
                })

    if DOWNLOADS_DIR.exists():
        for f in DOWNLOADS_DIR.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "type": "edited",
                    "size": f.stat().st_size,
                    "download_url": f"/download/{f.name}"
                })

    return {"files": files, "storage_dir": str(STORAGE_DIR), "downloads_dir": str(DOWNLOADS_DIR), "user": token_user}

@app.get("/debug/all-docs")
async def debug_all_docs(user_id: str = DEFAULT_USER_ID):
    if not vector_store.is_connected():
        return {"error": "Weaviate не подключен"}

    from weaviate.classes.query import Filter

    collection = vector_store.client.collections.get("Document")
    response = collection.query.fetch_objects(
        limit=100,
        return_properties=["filename", "is_table"],
        filters=Filter.by_property("user_id").equal(user_id)
    )

    return {
        "user_id": user_id,
        "total": len(response.objects),
        "files": [obj.properties.get("filename") for obj in response.objects]
    }


@app.get("/debug/clear-docs")
async def clear_docs(user_id: str = DEFAULT_USER_ID):
    if not vector_store.is_connected():
        return {"error": "Weaviate не подключен"}

    vector_store.clear_user_data(user_id)
    return {"message": f"Документы {user_id} удалены"}