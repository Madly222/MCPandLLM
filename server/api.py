import os
import logging
import asyncio

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File

from agent.agent import agent_process
from vector_store import vector_store
from tools.upload_tool import save_and_index_file
from tools.chunking_tool import index_file

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


def load_storage_files():
    if not vector_store.is_connected():
        logger.warning("Weaviate не подключен.")
        return

    if not STORAGE_DIR.exists():
        logger.warning(f"Папка storage не найдена: {STORAGE_DIR}")
        return

    existing_docs = vector_store.get_all_user_documents(DEFAULT_USER_ID, limit=100)
    existing_files = {doc["filename"] for doc in existing_docs}

    if existing_files:
        logger.info(f"Уже загружено {len(existing_files)} файлов")
        return

    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx', '.xls', '.md', '.csv', '.log'}

    for file_path in STORAGE_DIR.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in supported_extensions:
            continue

        try:
            result = index_file(file_path, DEFAULT_USER_ID)
            if result.get("success"):
                logger.info(f"{file_path.name} загружен")
        except Exception as e:
            logger.error(f"Ошибка при загрузке {file_path.name}: {e}")


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

@app.get("/")
async def index():
    index_file_path = web_dir / "index.html"
    if index_file_path.exists():
        return FileResponse(index_file_path)
    else:
        raise HTTPException(status_code=404, detail="index.html не найден")


@app.post("/query")
async def query(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат JSON")

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return {"response": "Пустой запрос"}

    user_id = data.get("user_id", DEFAULT_USER_ID).strip()
    logger.info(f"Запрос от {user_id}: {prompt}")

    try:
        response = await agent_process(prompt, user_id)
        return {"response": response}
    except Exception as e:
        logger.exception(f"Ошибка обработки")
        return {"response": f"Ошибка: {e}"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = DEFAULT_USER_ID):
    try:
        file_bytes = await file.read()
        success = save_and_index_file(file_bytes, file.filename, user_id=user_id)
        if success:
            return {"message": f"Файл {file.filename} загружен"}
        else:
            raise HTTPException(status_code=500, detail="Ошибка сохранения")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{filename:path}")
async def download_file(filename: str):
    file_path = DOWNLOADS_DIR / filename

    if not file_path.exists():
        file_path = STORAGE_DIR / filename

    if not file_path.exists():
        logger.error(f"Файл не найден: {filename}")
        logger.error(f"Проверено: {DOWNLOADS_DIR / filename}, {STORAGE_DIR / filename}")
        raise HTTPException(status_code=404, detail=f"Файл {filename} не найден")

    logger.info(f"Скачивание: {file_path}")

    encoded_filename = quote(filename)

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@app.get("/files")
async def list_files():
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

    return {"files": files, "storage_dir": str(STORAGE_DIR), "downloads_dir": str(DOWNLOADS_DIR)}


@app.get("/debug/paths")
async def debug_paths():
    return {
        "base_dir": str(BASE_DIR),
        "storage_dir": str(STORAGE_DIR),
        "downloads_dir": str(DOWNLOADS_DIR),
        "storage_exists": STORAGE_DIR.exists(),
        "downloads_exists": DOWNLOADS_DIR.exists(),
        "storage_files": [f.name for f in STORAGE_DIR.iterdir()] if STORAGE_DIR.exists() else [],
        "downloads_files": [f.name for f in DOWNLOADS_DIR.iterdir()] if DOWNLOADS_DIR.exists() else [],
    }


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