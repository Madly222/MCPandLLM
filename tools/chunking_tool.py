from pathlib import Path
from typing import List
from vector_store import vector_store, WeaviateStore
from tools.utils import BASE_FILES_DIR
from tools.file_tool import read_file
from tools.excel_tool import read_excel

# создаём глобальный объект для индексации
store = WeaviateStore()
if not store.is_connected():
    store.connect()

CHUNK_SIZE = 500  # символы или приблизительные токены
OVERLAP = 50

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> List[str]:
    """Разбивает текст на чанки с заданным overlap."""
    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunks.append(text[start:end].strip())
        start += chunk_size - overlap
    return chunks

def index_file(filepath: Path, user_id: str = None):
    """Индексация файла в Weaviate."""
    if not filepath.exists() or not filepath.is_file():
        print(f"❌ Файл не найден: {filepath}")
        return

    ext = filepath.suffix.lower()
    if ext in [".txt", ".pdf", ".docx"]:
        content = read_file(filepath)
    elif ext in [".xlsx", ".xls"]:
        rows = read_excel(filepath.name)
        content = "\n".join(rows) if isinstance(rows, list) else str(rows)
    else:
        print(f"❌ Формат файла не поддерживается: {filepath}")
        return

    if not content or not isinstance(content, str) or content.startswith("Ошибка"):
        print(f"❌ Ошибка чтения файла: {filepath.name}")
        return

    chunks = chunk_text(content)
    for idx, chunk in enumerate(chunks):
        metadata = {
            "chunk_index": idx,
            "source_path": str(filepath)
        }
        store.add_document(
            content=chunk,
            filename=filepath.name,
            filetype=ext.lstrip("."),
            user_id=user_id,
            metadata=metadata
        )

    print(f"✅ Файл '{filepath.name}' проиндексирован ({len(chunks)} чанков).")

def index_all_files(user_id: str = None):
    """Индексация всех файлов в BASE_FILES_DIR."""
    for f in BASE_FILES_DIR.iterdir():
        if f.is_file():
            index_file(f, user_id=user_id)

def reindex_all_files(user_id: str = None):
    """Полная переиндексация: очищает все данные пользователя и индексирует все файлы заново."""
    if user_id:
        store.clear_user_data(user_id)
        print(f"🧹 Старые данные пользователя {user_id} удалены.")
    else:
        print("⚠️ user_id не указан, старые данные не удаляются.")

    print("🔄 Начинаем переиндексацию всех файлов...")
    index_all_files(user_id=user_id)
    print("✅ Переиндексация завершена.")

def read_file_content(filepath: Path) -> str:
    """Универсальное чтение файла с нормализацией контента в строку."""
    ext = filepath.suffix.lower()
    if ext in [".txt", ".pdf", ".docx"]:
        content = read_file(filepath)
    elif ext in [".xlsx", ".xls"]:
        rows = read_excel(filepath.name)
        content = "\n".join(rows) if isinstance(rows, list) else str(rows)
    else:
        print(f"❌ Формат файла не поддерживается: {filepath}")
        return ""
    return content