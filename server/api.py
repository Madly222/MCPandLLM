import os
import logging
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from agent.agent import agent_process

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
static_dir = BASE_DIR / "static"
templates_dir = BASE_DIR / "templates"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    logger.warning(f"Статическая папка не найдена: {static_dir}")

templates = Jinja2Templates(directory=templates_dir if templates_dir.exists() else ".")

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

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