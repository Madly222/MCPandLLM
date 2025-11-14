import logging
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from agent.agent import agent_process

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Поднимаемся на уровень выше (корень проекта)
BASE_DIR = Path(__file__).resolve().parent.parent
web_dir = BASE_DIR / "web"

if web_dir.exists():
    app.mount("/web", StaticFiles(directory=web_dir), name="web")
else:
    logger.warning(f"Папка web не найдена: {web_dir}")

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
        response = await agent_process(prompt, user_id)
        return {"response": response}
    except Exception as e:
        logger.exception(f"Ошибка обработки запроса user_id={user_id}")
        return {"response": f"Ошибка при обработке запроса: {e}"}
