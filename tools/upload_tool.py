# tools/upload_tool.py
from pathlib import Path
import logging
from vector_store.wv_store import WeaviateStore
from tools.chunking_tool import index_file
import os

logger = logging.getLogger(__name__)

# Папка для хранения файлов
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))

# Гарантируем существование папки
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Глобальный объект для индексации
store = WeaviateStore()
if not store.is_connected():
    store.connect()


def save_and_index_file(file_bytes: bytes, filename: str, user_id: str = "default") -> bool:
    """
    Сохраняет файл в STORAGE_DIR и индексирует его в Weaviate.
    Возвращает True, если успешно.
    """
    try:
        file_path = STORAGE_DIR / filename
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        # Индексация через chunking_tool
        index_file(file_path, user_id=user_id)
        logger.info(f"✅ Файл '{filename}' успешно сохранён и проиндексирован")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении или индексации файла '{filename}': {e}")
        return False
