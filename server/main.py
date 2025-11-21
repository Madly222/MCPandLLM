import uvicorn
from pathlib import Path
from dotenv import load_dotenv
from vector_store import vector_store  # ← Добавили импорт

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

if __name__ == "__main__":
    # ✅ Подключаемся к Weaviate перед запуском сервера
    if vector_store.connect():
        print("✅ Weaviate подключен и готов к работе")
    else:
        print("⚠️ Weaviate не подключен, но сервер запустится")

    uvicorn.run("server.api:app", host="0.0.0.0", port=8000, reload=True)