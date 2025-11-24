import sys
import logging
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from vector_store import vector_store  # ✅ Используем глобальный
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
        start += (max_words - overlap_words)  # Шаг с учётом overlap

    return chunks


def index_file(filepath: Path, user_id: str = None) -> dict:
    """
    Индексация файла в общий индекс.
    Если user_id передан → можно использовать для фильтров (но не сохраняем в Document)
    """
    if not filepath.exists():
        return {"success": False, "message": "Файл не найден"}

    try:
        # Чтение содержимого
        if filepath.suffix.lower() in ['.xlsx', '.xls']:
            content = read_excel(filepath.name)
            if isinstance(content, list):
                content = "\n".join(str(row) for row in content)
        else:
            content = read_file(filepath)

        if not content or str(content).startswith(("Ошибка", "Файл")):
            return {"success": False, "message": "Ошибка чтения"}

        content = str(content)
        chunks = chunk_text_with_overlap(content, max_words=500, overlap_words=50)

        for idx, chunk in enumerate(chunks):
            result = vector_store.add_document(
                content=chunk,
                filename=filepath.name,
                filetype=filepath.suffix.lstrip('.'),
                user_id="shared",  # Все файлы идут в общий индекс
                metadata={
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "source_path": str(filepath)
                }
            )
            if not result.get("success"):
                logger.warning(f"Ошибка индексации чанка {idx} из {filepath.name}")

        logger.info(f"✅ {filepath.name}: {len(chunks)} чанков")
        return {"success": True, "chunks": len(chunks)}

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

    logger.info(f"\n{'=' * 50}")
    logger.info(f"✅ Успешно: {success} | ❌ Ошибки: {errors}")
    logger.info(f"📊 Статистика: {vector_store.get_stats()}")
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

    # Полная переиндексация
    reindex_all(user_id)

    vector_store.disconnect()