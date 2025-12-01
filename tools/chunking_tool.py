import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from vector_store import vector_store
from tools.utils import read_file
from tools.excel_tool import read_excel_structured

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))

CHUNK_MAX_CHARS = 3000
CHUNK_OVERLAP_CHARS = 300


def get_role_files_dir(role: str) -> Path:
    return STORAGE_DIR / role


def chunk_text_semantic(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> List[Dict]:
    if len(text) <= max_chars:
        return [{"content": text, "index": 0, "total": 1}]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2

        if current_len + para_len > max_chars and current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunks.append(chunk_text)

            overlap_text = []
            overlap_len = 0
            for p in reversed(current_chunk):
                if overlap_len + len(p) > overlap:
                    break
                overlap_text.insert(0, p)
                overlap_len += len(p)

            current_chunk = overlap_text
            current_len = overlap_len

        current_chunk.append(para)
        current_len += para_len

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return [
        {"content": c, "index": i, "total": len(chunks)}
        for i, c in enumerate(chunks)
    ]


def generate_text_summary(content: str, filename: str) -> str:
    lines = content.split("\n")[:20]
    preview = "\n".join(lines)
    if len(preview) > 500:
        preview = preview[:500] + "..."

    word_count = len(content.split())
    return f"Файл: {filename}. ~{word_count} слов. Начало: {preview}"


def generate_text_structure(content: str) -> str:
    headers = []
    for line in content.split("\n")[:100]:
        stripped = line.strip()
        if stripped.startswith("#"):
            headers.append(stripped)
        elif stripped.isupper() and len(stripped) > 3 and len(stripped) < 100:
            headers.append(stripped)

    return str({"headers": headers[:20], "char_count": len(content)})


def is_error_response(content: str) -> bool:
    if not content:
        return True
    return content.strip().startswith(("Ошибка", "File error", "Error", "Файл"))


def index_excel_file(filepath: Path, role: str) -> Dict:
    result = read_excel_structured(filepath, role=role)

    if "error" in result:
        return {"success": False, "message": result["error"]}

    content = result["content"]
    summary = result["summary"]
    structure = result["structure"]
    total_rows = result["total_rows"]
    columns = ", ".join(list(set(result["all_columns"]))[:20])

    doc_hash = vector_store._hash_content(content)

    full_result = vector_store.add_full_document(
        content=content,
        filename=filepath.name,
        filetype=filepath.suffix[1:],
        user_id=role,
        metadata={
            "is_table": True,
            "summary": summary,
            "structure": structure,
            "row_count": total_rows,
            "columns": columns,
        }
    )

    if full_result.get("skipped"):
        return {"success": True, "chunks": 0, "skipped": True}

    vector_store._delete_chunks(filepath.name, role)

    if len(content) <= CHUNK_MAX_CHARS:
        chunk_result = vector_store.add_document(
            content=content,
            filename=filepath.name,
            filetype=filepath.suffix[1:],
            user_id=role,
            metadata={
                "chunk_index": 0,
                "total_chunks": 1,
                "source_path": str(filepath),
                "is_table": True,
                "summary": summary,
                "structure": structure,
                "row_count": total_rows,
                "columns": columns,
                "doc_hash": doc_hash,
            }
        )
        return {"success": chunk_result.get("success", False), "chunks": 1}

    chunks = chunk_text_semantic(content)
    success_chunks = 0

    for chunk_data in chunks:
        chunk_meta = {
            "chunk_index": chunk_data["index"],
            "total_chunks": chunk_data["total"],
            "source_path": str(filepath),
            "is_table": True,
            "summary": summary,
            "structure": structure,
            "row_count": total_rows,
            "columns": columns,
            "doc_hash": doc_hash,
        }

        if chunk_data["index"] == 0:
            chunk_content = f"[SUMMARY: {summary}]\n\n{chunk_data['content']}"
        else:
            chunk_content = chunk_data["content"]

        result = vector_store.add_document(
            content=chunk_content,
            filename=filepath.name,
            filetype=filepath.suffix[1:],
            user_id=role,
            metadata=chunk_meta
        )

        if result.get("success"):
            success_chunks += 1

    logger.info(f"Таблица {filepath.name}: {success_chunks}/{len(chunks)} чанков, {total_rows} строк")
    return {"success": True, "chunks": success_chunks}


def index_text_file(filepath: Path, role: str) -> Dict:
    content = read_file(filepath)

    if is_error_response(content):
        return {"success": False, "message": content}

    summary = generate_text_summary(content, filepath.name)
    structure = generate_text_structure(content)
    doc_hash = vector_store._hash_content(content)

    full_result = vector_store.add_full_document(
        content=content,
        filename=filepath.name,
        filetype=filepath.suffix[1:],
        user_id=role,
        metadata={
            "is_table": False,
            "summary": summary,
            "structure": structure,
        }
    )

    if full_result.get("skipped"):
        return {"success": True, "chunks": 0, "skipped": True}

    vector_store._delete_chunks(filepath.name, role)

    if len(content) <= CHUNK_MAX_CHARS:
        result = vector_store.add_document(
            content=content,
            filename=filepath.name,
            filetype=filepath.suffix[1:],
            user_id=role,
            metadata={
                "chunk_index": 0,
                "total_chunks": 1,
                "source_path": str(filepath),
                "is_table": False,
                "summary": summary,
                "structure": structure,
                "doc_hash": doc_hash,
            }
        )
        return {"success": result.get("success", False), "chunks": 1}

    chunks = chunk_text_semantic(content)
    success_chunks = 0

    for chunk_data in chunks:
        chunk_meta = {
            "chunk_index": chunk_data["index"],
            "total_chunks": chunk_data["total"],
            "source_path": str(filepath),
            "is_table": False,
            "summary": summary,
            "structure": structure,
            "doc_hash": doc_hash,
        }

        if chunk_data["index"] == 0:
            chunk_content = f"[SUMMARY: {summary}]\n\n{chunk_data['content']}"
        else:
            chunk_content = chunk_data["content"]

        result = vector_store.add_document(
            content=chunk_content,
            filename=filepath.name,
            filetype=filepath.suffix[1:],
            user_id=role,
            metadata=chunk_meta
        )

        if result.get("success"):
            success_chunks += 1

    logger.info(f"Документ {filepath.name}: {success_chunks}/{len(chunks)} чанков")
    return {"success": True, "chunks": success_chunks}


def index_file(filepath: Path, role: str = "default") -> Dict:
    if not filepath.exists():
        return {"success": False, "message": "Файл не найден"}

    suffix = filepath.suffix.lower()

    if suffix in (".xlsx", ".xls", ".csv"):
        return index_excel_file(filepath, role)
    else:
        return index_text_file(filepath, role)


def index_all_files(role: str = "default"):
    if not vector_store.is_connected():
        if not vector_store.connect():
            logger.error("Не удалось подключиться к Weaviate")
            return

    role_dir = get_role_files_dir(role)
    if not role_dir.exists():
        logger.warning(f"Папка роли не найдена: {role_dir}")
        return

    supported = {".txt", ".pdf", ".docx", ".xlsx", ".xls", ".md", ".csv", ".log"}

    files = [
        f for f in role_dir.iterdir()
        if f.is_file() and f.suffix.lower() in supported
    ]

    if not files:
        logger.warning(f"Нет файлов для индексации в {role_dir}")
        return

    success = 0
    skipped = 0
    errors = 0

    for f in files:
        result = index_file(f, role)
        if result.get("skipped"):
            skipped += 1
        elif result.get("success"):
            success += 1
        else:
            errors += 1

    stats = vector_store.get_stats()

    logger.info("=" * 60)
    logger.info(f"[{role}] Новых: {success} | Пропущено: {skipped} | Ошибки: {errors}")
    logger.info(f"Статистика: {stats}")
    logger.info("=" * 60)


def reindex_all(role: str = "default"):
    logger.info(f"Очистка старых данных для роли {role}...")
    vector_store.clear_user_data(role)

    logger.info("Переиндексация...")
    index_all_files(role)

    logger.info("Готово")


if __name__ == "__main__":
    if not vector_store.connect():
        print("Не удалось подключиться")
        sys.exit(1)

    role = sys.argv[1] if len(sys.argv) > 1 else "default"
    reindex_all(role)
    vector_store.disconnect()