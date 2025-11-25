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


# ---------------------- CHUNKING ----------------------

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


def read_content(filepath: Path) -> str:
    """Читает файл и всегда возвращает строку"""
    if filepath.suffix.lower() in ['.xlsx', '.xls', '.csv']:
        content = read_excel(str(filepath))  # ✅ используем полный путь
        if isinstance(content, list):
            return "\n".join(str(row) for row in content)
        return str(content)

    return str(read_file(filepath))

def is_table_file(filepath: Path) -> bool:
    return filepath.suffix.lower() in ['.xlsx', '.xls', '.csv']


# ---------------------- INDEXING ----------------------

def index_file(filepath: Path) -> dict:
    """Индексация одного файла без чанкования таблиц"""
    if not filepath.exists():
        return {"success": False, "message": "Файл не найден"}

    try:
        content = read_content(filepath)

        if not content or str(content).startswith(("Ошибка", "Файл")):
            return {"success": False, "message": "Ошибка чтения файла"}

        content = str(content)

        # -----------------------------------------------------
        # 1. Таблицы — НИКОГДА НЕ РАЗБИВАЕМ НА ЧАНКИ
        # -----------------------------------------------------
        if is_table_file(filepath):
            result = vector_store.add_document(
                content=content,
                filename=filepath.name,
                filetype=filepath.suffix.lstrip('.'),
                user_id = "default",
                metadata={
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "source_path": str(filepath),
                    "is_table": True
                }
            )
            logger.info(f"📊 {filepath.name}: 1 чанк (таблица без разбиения)")
            return {"success": True, "chunks": 1}

        # -----------------------------------------------------
        # 2. Обычные файлы — чанкование
        # -----------------------------------------------------
        chunks = chunk_text_with_overlap(content, max_words=500, overlap_words=50)

        for idx, chunk in enumerate(chunks):
            result = vector_store.add_document(
                content=chunk,
                filename=filepath.name,
                filetype=filepath.suffix.lstrip('.'),
                user_id="default",
                metadata={
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "source_path": str(filepath)
                }
            )

            if not result.get("success"):
                logger.warning(f"Ошибка индексации чанка {idx} из {filepath.name}")

        logger.info(f"📄 {filepath.name}: {len(chunks)} чанков")
        return {"success": True, "chunks": len(chunks)}

    except Exception as e:
        logger.error(f"❌ Ошибка индексации {filepath.name}: {e}")
        return {"success": False, "message": str(e)}


# ---------------------- INDEX ALL ----------------------

def index_all_files():
    """Массовая индексация всех файлов"""
    if not vector_store.is_connected():
        if not vector_store.connect():
            logger.error("❌ Не удалось подключиться к Weaviate")
            return

    supported = {'.txt', '.pdf', '.docx', '.xlsx', '.xls', '.md', '.csv', '.log'}

    all_files = [
        f for f in BASE_FILES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in supported
    ]

    if not all_files:
        logger.warning(f"⚠️ Файлы не найдены в {BASE_FILES_DIR}")
        return

    logger.info(f"📁 Найдено файлов: {len(all_files)}")

    ok, bad = 0, 0

    for filepath in all_files:
        result = index_file(filepath)
        if result.get("success"):
            ok += 1
        else:
            bad += 1

    logger.info(f"\n{'=' * 50}")
    logger.info(f"✅ Успешно: {ok} | ❌ Ошибки: {bad}")
    logger.info(f"📊 Статистика: {vector_store.get_stats()}")
    logger.info(f"{'=' * 50}\n")


# ---------------------- RECHUNK ALL ----------------------

def rechunk_all():
    """Удаляет ВСЕ старые чанки и создаёт новые"""
    logger.info("🧹 Удаление всех старых данных пользователя...")
    vector_store.clear_user_data()

    logger.info("♻️ Создание новых чанков...")
    index_all_files()

    logger.info("✅ Пересоздание чанков завершено")


# ---------------------- REINDEX SINGLE FILE ----------------------

def reindex_file(filename: str):
    """
    Полная переиндексация ОДНОГО файла:
    - удаляет только его старые документы
    - создаёт новые чанки
    """
    logger.info(f"🧹 Очистка старых данных файла: {filename}")

    # Удаляем только этот файл из коллекции Document
    collection = vector_store.client.collections.get("Document")

    from weaviate.classes.query import Filter
    collection.data.delete_many(
        where=Filter.by_property("filename").equal(filename)
    )

    filepath = BASE_FILES_DIR / filename

    if not filepath.exists():
        logger.error(f"❌ Файл {filename} не найден в BASE_FILES_DIR")
        return

    logger.info(f"🔄 Переиндексация файла: {filename}")
    index_file(filepath)

    logger.info(f"✅ Переиндексация файла {filename} завершена")


# ---------------------- MAIN ----------------------

if __name__ == "__main__":
    if not vector_store.connect():
        print("❌ Не удалось подключиться к Weaviate")
        sys.exit(1)

    file_name = sys.argv[1] if len(sys.argv) > 1 else None

    if file_name:
        reindex_file(file_name)
    else:
        rechunk_all()

    vector_store.disconnect()