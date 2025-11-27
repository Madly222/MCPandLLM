import sys
import logging
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from vector_store import vector_store
from tools.utils import BASE_FILES_DIR
from tools.file_tool import read_file
from tools.excel_tool import read_excel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def chunk_text_with_overlap(text: str, max_words: int = 500, overlap_words: int = 50) -> List[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks = []
    start = 0

    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        start += max_words - overlap_words

    return chunks

def is_error_response(content: str) -> bool:
    if not content:
        return True
    error_prefixes = ("Ошибка", "File error", "Error")
    return content.strip().startswith(error_prefixes)

def index_file(filepath: Path, user_id: str = "default") -> dict:

    if not filepath.exists():
        return {"success": False, "message": "Файл не найден"}

    try:
        suffix = filepath.suffix.lower()

        # ==========================
        # Read file
        # ==========================
        if suffix in (".xlsx", ".xls"):
            content = read_excel(filepath.name)
        else:
            content = read_file(filepath)

        if is_error_response(content):
            logger.error(f"❌ Ошибка чтения {filepath.name}: {content}")
            return {"success": False, "message": content}

        if suffix in (".xlsx", ".xls", ".csv"):
            result = vector_store.add_document(
                content=content,
                filename=filepath.name,
                filetype=suffix[1:],
                user_id=user_id,
                metadata={
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "source_path": str(filepath),
                    "is_table": True
                }
            )

            if result.get("success"):
                logger.info(f"📊 {filepath.name}: таблица добавлена целиком")
                return {"success": True, "chunks": 1}

            return {"success": False, "message": result.get("message")}

        # ==========================
        # Normal text → chunking
        # ==========================
        chunks = chunk_text_with_overlap(content)
        success_chunks = 0

        for idx, chunk in enumerate(chunks):
            result = vector_store.add_document(
                content=chunk,
                filename=filepath.name,
                filetype=suffix[1:],
                user_id=user_id,
                metadata={
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "source_path": str(filepath),
                }
            )
            if result.get("success"):
                success_chunks += 1

        logger.info(f"📄 {filepath.name}: {success_chunks}/{len(chunks)} чанков")
        return {"success": True, "chunks": success_chunks}

    except Exception as e:
        logger.error(f"❌ Ошибка индексации {filepath.name}: {e}")
        return {"success": False, "message": str(e)}

def index_all_files(user_id: str = "default"):

    if not vector_store.is_connected():
        if not vector_store.connect():
            logger.error("❌ Не удалось подключиться к Weaviate")
            return

    supported = {".txt", ".pdf", ".docx", ".xlsx", ".xls", ".md", ".csv", ".log"}

    files = [
        f for f in BASE_FILES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in supported
    ]

    if not files:
        logger.warning("⚠️ Нет файлов для индексации")
        return

    success = 0
    errors = 0

    for f in files:
        result = index_file(f, user_id)
        if result.get("success"):
            success += 1
        else:
            errors += 1

    stats = vector_store.get_stats()

    logger.info("=" * 60)
    logger.info(f"✔ Успешно: {success} | ✘ Ошибки: {errors}")
    logger.info(f"📊 Статистика: {stats}")
    logger.info("=" * 60)


def reindex_all(user_id: str = "default"):
    logger.info("🧹 Очистка старых данных…")
    vector_store.clear_user_data(user_id)

    logger.info("🔄 Переиндексация…")
    index_all_files(user_id)

    logger.info("✔ Готово")


if __name__ == "__main__":
    if not vector_store.connect():
        print("❌ Не удалось подключиться")
        sys.exit(1)

    uid = sys.argv[1] if len(sys.argv) > 1 else "default"
    reindex_all(uid)
    vector_store.disconnect()