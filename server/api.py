import os
import logging
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from agent.agent import agent_process
from vector_store import vector_store
from tools.file_tool import read_file
from fastapi import UploadFile, File
from tools.upload_tool import save_and_index_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
web_dir = BASE_DIR / "web"

# Папка с файлами для индексации берется из переменной окружения FILES_DIR
STORAGE_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))

if web_dir.exists():
    app.mount("/web", StaticFiles(directory=web_dir), name="web")
else:
    logger.warning(f"Папка web не найдена: {web_dir}")

def load_storage_files():
    if not vector_store.is_connected():
        logger.warning("Weaviate не подключен. Файлы из storage не будут загружены.")
        return

    if not STORAGE_DIR.exists():
        logger.warning(f"Папка storage не найдена: {STORAGE_DIR}")
        return

    for file_path in STORAGE_DIR.iterdir():
        if file_path.is_file():
            try:
                content = read_file(file_path)
                if content and not content.startswith("Ошибка"):
                    result = vector_store.add_document(
                        content=content,
                        filename=file_path.name,
                        filetype=file_path.suffix.lstrip('.'),
                        user_id="default"
                    )
                    if result["success"]:
                        logger.info(f"✅ {file_path.name} загружен в RAG")
            except Exception as e:
                logger.error(f"❌ Ошибка при загрузке {file_path.name}: {e}")


@app.on_event("startup")
async def startup():
    # ✅ Подключаемся к Weaviate
    if not vector_store.is_connected():
        if vector_store.connect():
            logger.info("✅ Weaviate подключен при старте сервера")
        else:
            logger.warning("⚠️ Не удалось подключиться к Weaviate")

    logger.info("Запуск автозагрузки файлов из storage...")

@app.get("/")
async def index():
    index_file = web_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
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

    user_id = data.get("user_id", "default").strip()
    logger.info(f"Получен запрос от user_id={user_id}: {prompt}")

    try:
        # При поиске используем общий индекс
        response = await agent_process(prompt, user_id)
        return {"response": response}
    except Exception as e:
        logger.exception(f"Ошибка обработки запроса user_id={user_id}")
        return {"response": f"Ошибка при обработке запроса: {e}"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = "default"):
    try:
        file_bytes = await file.read()
        success = save_and_index_file(file_bytes, file.filename, user_id=user_id)
        if success:
            return {"message": f"Файл {file.filename} успешно загружен и проиндексирован"}
        else:
            raise HTTPException(status_code=500, detail="Ошибка при сохранении или индексации файла")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке файла: {e}")