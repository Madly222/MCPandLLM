# api.py
import os
import logging
import asyncio
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

from agent.agent import agent_process
from vector_store import vector_store
from tools.chunking_tool import index_file
from user.users import verify_user
from user.auth import create_access_token, decode_access_token
from fastapi.responses import RedirectResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



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

if web_dir.exists():
    app.mount("/web", StaticFiles(directory=web_dir), name="web")

PUBLIC_PATHS = {
    "/login",
    "/web/login.html",
    "/web/style.css",
    "/web/script.js",
    "/favicon.ico",
}

async def periodic_task():
    await asyncio.sleep(300)

    while True:
        try:
            load_storage_files()
            logger.info("load_storage_files выполнен")
        except Exception as e:
            logger.error(f"Ошибка periodic_task: {e}")
        await asyncio.sleep(300)

@asynccontextmanager
async def lifespan(app):
    if not vector_store.is_connected():
        if vector_store.connect():
            logger.info("Weaviate подключен")
        else:
            logger.warning("Не удалось подключиться к Weaviate")

    task = asyncio.create_task(periodic_task())

    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi.json"):
        return await call_next(request)

    token = request.cookies.get("token", "")

    if not token:
        return RedirectResponse(url="/web/login.html")

    try:
        data = decode_access_token(token)
        request.state.user = data["username"]
        request.state.role = data["role"]
    except HTTPException:
        return RedirectResponse(url="/web/login.html")

    return await call_next(request)


def load_storage_files():
    if not vector_store.is_connected():
        logger.warning("Weaviate не подключен.")
        return

    if not STORAGE_DIR.exists():
        logger.warning(f"Папка storage не найдена: {STORAGE_DIR}")
        return

    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx', '.xls', '.md', '.csv', '.log'}

    for role_folder in STORAGE_DIR.iterdir():
        if not role_folder.is_dir():
            continue

        role = role_folder.name

        try:
            existing_docs = vector_store.get_all_user_documents(role, limit=10000)
        except Exception as e:
            logger.error(f"Ошибка чтения документов Weaviate для роли {role}: {e}")
            continue

        existing_files = {doc["filename"] for doc in existing_docs}

        logger.info(f"[{role}] Уже загружено {len(existing_files)} файлов")

        for file_path in role_folder.iterdir():
            if not file_path.is_file():
                continue

            if file_path.suffix.lower() not in supported_extensions:
                continue

            if file_path.name in existing_files:
                continue

            try:
                result = index_file(file_path, role)
                if result.get("success"):
                    logger.info(f"[{role}] {file_path.name} загружен")
            except Exception as e:
                logger.error(f"[{role}] Ошибка загрузки {file_path.name}: {e}")

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

    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
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

    role = request.state.role
    username = request.state.user

    logger.info(f"Запрос от {username} (роль: {role}): {prompt}")

    try:
        response = await agent_process(prompt, role)
        return {"response": response}
    except Exception as e:
        logger.exception("Ошибка обработки")
        return {"response": f"Ошибка: {e}"}


@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    role = request.state.role
    username = request.state.user

    role_dir = STORAGE_DIR / role
    role_dir.mkdir(parents=True, exist_ok=True)

    file_path = role_dir / file.filename
    file_bytes = await file.read()

    try:
        file_path.write_bytes(file_bytes)

        result = index_file(file_path, role)
        if result.get("success"):
            logger.info(f"[{role}] Файл {file.filename} загружен пользователем {username}")
            return {"message": f"Файл {file.filename} загружен"}
        else:
            return {"message": f"Файл сохранён, но не проиндексирован: {result.get('message')}"}
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сохранения")


@app.get("/download/{filename:path}")
async def download_file(request: Request, filename: str):
    role = request.state.role

    file_path = DOWNLOADS_DIR / filename
    if not file_path.exists():
        file_path = STORAGE_DIR / role / filename
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
    role = request.state.role
    username = request.state.user
    files = []

    role_storage = STORAGE_DIR / role
    if role_storage.exists():
        for f in role_storage.iterdir():
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

    return {
        "files": files,
        "storage_dir": str(role_storage),
        "downloads_dir": str(DOWNLOADS_DIR),
        "user": username,
        "role": role
    }


@app.get("/debug/all-docs")
async def debug_all_docs(request: Request):
    role = request.state.role

    if not vector_store.is_connected():
        return {"error": "Weaviate не подключен"}

    from weaviate.classes.query import Filter

    collection = vector_store.client.collections.get("Document")
    response = collection.query.fetch_objects(
        limit=100,
        return_properties=["filename", "is_table"],
        filters=Filter.by_property("user_id").equal(role)
    )

    return {
        "role": role,
        "total": len(response.objects),
        "files": [obj.properties.get("filename") for obj in response.objects]
    }


@app.get("/debug/clear-docs")
async def clear_docs(request: Request):
    role = request.state.role

    if not vector_store.is_connected():
        return {"error": "Weaviate не подключен"}

    vector_store.clear_user_data(role)
    return {"message": f"Документы роли {role} удалены"}