# tools/chunking_tool.py
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
    """Разбиение текста на чанки с overlap по словам"""
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += (max_words - overlap_words)

    return chunks


def is_error_response(content: str) -> bool:
    """Проверяет, является ли контент сообщением об ошибке"""
    if not content:
        return True
    error_prefixes = ("Ошибка", "Файл", "Error")
    return content.strip().startswith(error_prefixes)


def index_file(filepath: Path, user_id: str = "default") -> dict:
    """
    Индексация одного файла.
    Таблицы (Excel) — всегда 1 чанк.
    Остальные файлы — chunking с overlap.
    """
    if not filepath.exists():
        return {"success": False, "message": "Файл не найден"}

    try:
        suffix = filepath.suffix.lower()

        # =============================
        # Чтение содержимого
        # =============================
        if suffix in ['.xlsx', '.xls']:
            # read_excel теперь возвращает str напрямую
            content = read_excel(filepath.name)
        else:
            content = read_file(filepath)

        # Проверка на ошибки чтения
        if is_error_response(content):
            logger.error(f"❌ Ошибка чтения {filepath.name}: {content}")
            return {"success": False, "message": content}

        # =============================
        # Таблицы — всегда 1 чанк
        # =============================
        if suffix in ['.xlsx', '.xls']:
            result = vector_store.add_document(
                content=content,
                filename=filepath.name,
                filetype=suffix.lstrip('.'),
                user_id=user_id,
                metadata={
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "source_path": str(filepath),
                    "is_table": True
                }
            )

            if result.get("success"):
                logger.info(f"✅ {filepath.name}: таблица добавлена целиком (1 чанк)")
                return {"success": True, "chunks": 1}
            else:
                logger.error(f"❌ Ошибка индексации таблицы {filepath.name}: {result.get('message')}")
                return {"success": False, "message": result.get("message", "Ошибка добавления")}

        # =============================
        # Остальные файлы — chunking с overlap
        # =============================
        chunks = chunk_text_with_overlap(content, max_words=500, overlap_words=50)
        added_chunks = 0

        for idx, chunk in enumerate(chunks):
            result = vector_store.add_document(
                content=chunk,
                filename=filepath.name,
                filetype=suffix.lstrip('.'),
                user_id=user_id,
                metadata={
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "source_path": str(filepath)
                }
            )
            if result.get("success"):
                added_chunks += 1
            else:
                logger.warning(f"⚠️ Ошибка индексации чанка {idx} из {filepath.name}")

        logger.info(f"✅ {filepath.name}: {added_chunks}/{len(chunks)} чанков")
        return {"success": True, "chunks": added_chunks}

    except Exception as e:
        logger.error(f"❌ Ошибка индексации {filepath.name}: {e}")
        return {"success": False, "message": str(e)}


def index_all_files(user_id: str = "default"):
    """Массовая индексация всех файлов"""
    if not vector_store.is_connected():
        if not vector_store.connect():
            logger.error("❌ Не удалось подключиться к Weaviate")
            return

    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx', '.xls', '.md', '.csv', '.log'}
    all_files = [
        f for f in BASE_FILES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in supported_extensions
    ]

    if not all_files:
        logger.warning(f"⚠️ Файлы не найдены в {BASE_FILES_DIR}")
        return

    logger.info(f"📁 Найдено файлов: {len(all_files)}")

    success = 0
    errors = 0

    for filepath in all_files:
        result = index_file(filepath, user_id)
        if result.get("success"):
            success += 1
        else:
            errors += 1

    stats = vector_store.get_stats()
    stats_rounded = {k: round(v, 2) if isinstance(v, float) else v for k, v in stats.items()}

    logger.info(f"\n{'=' * 50}")
    logger.info(f"✅ Успешно: {success} | ❌ Ошибки: {errors}")
    logger.info(f"📊 Статистика: {stats_rounded}")
    logger.info(f"{'=' * 50}\n")


def reindex_all(user_id: str = "default"):
    """Полная переиндексация с очисткой"""
    logger.info("🧹 Очистка старых данных...")
    vector_store.clear_user_data(user_id)

    logger.info("🔄 Начинаем переиндексацию...")
    index_all_files(user_id)

    logger.info("✅ Переиндексация завершена")


if __name__ == "__main__":
    if not vector_store.connect():
        print("❌ Не удалось подключиться к Weaviate")
        sys.exit(1)

    user_id = sys.argv[1] if len(sys.argv) > 1 else "default"
    reindex_all(user_id)
    vector_store.disconnect()