import sys
import logging
from pathlib import Path
from typing import List, Any
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


def _table_summary_from_raw(raw: Any, max_preview_chars: int = 2000) -> dict:
    summary_parts = []
    preview = ""
    try:
        import pandas as pd
        if isinstance(raw, pd.DataFrame):
            df = raw
            rows = len(df)
            cols = list(df.columns.astype(str))[:10]
            summary_parts.append(f"DataFrame: rows={rows}, cols={len(df.columns)}")
            summary_parts.append(f"columns: {', '.join(cols)}")
            preview = df.head(20).to_csv(index=False)[:max_preview_chars]
            return {"summary": "\n".join(summary_parts), "preview": preview, "rows": rows, "cols": len(df.columns)}
    except Exception:
        pass
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            headers = list(first.keys())
            rows = len(raw)
            summary_parts.append(f"Table (list of dicts): rows={rows}, cols={len(headers)}")
            summary_parts.append(f"columns: {', '.join(headers[:10])}")
            lines = [", ".join(headers)]
            for r in raw[:20]:
                vals = [str(r.get(h, "")) for h in headers]
                lines.append(", ".join(vals))
            preview = "\n".join(lines)[:max_preview_chars]
            return {"summary": "\n".join(summary_parts), "preview": preview, "rows": rows, "cols": len(headers)}
    if isinstance(raw, dict):
        parts = []
        total_rows = 0
        for sheet, data in raw.items():
            if isinstance(data, list) and data:
                headers = list(data[0].keys()) if isinstance(data[0], dict) else []
                rows = len(data)
                total_rows += rows
                parts.append(f"{sheet}: rows={rows}, cols={len(headers)}")
            else:
                parts.append(f"{sheet}: type={type(data).__name__}")
        summary = "Sheets: " + "; ".join(parts)
        preview_lines = []
        for sheet, data in raw.items():
            preview_lines.append(f"=== {sheet} ===")
            if isinstance(data, list) and data:
                headers = list(data[0].keys()) if isinstance(data[0], dict) else []
                preview_lines.append(", ".join(headers))
                for r in data[:10]:
                    if isinstance(r, dict):
                        preview_lines.append(", ".join(str(r.get(h, "")) for h in headers))
                    else:
                        preview_lines.append(str(r)[:200])
            else:
                preview_lines.append(str(data)[:200])
            if len("\n".join(preview_lines)) > max_preview_chars:
                preview_lines.append("...[sheet truncated]")
                break
        preview = "\n".join(preview_lines)[:max_preview_chars]
        return {"summary": summary, "preview": preview, "rows": total_rows, "cols": None}
    try:
        txt = str(raw)
        return {"summary": f"Table-like object of type {type(raw).__name__}", "preview": txt[:max_preview_chars], "rows": None, "cols": None}
    except Exception:
        return {"summary": f"Unknown table type {type(raw).__name__}", "preview": "", "rows": None, "cols": None}


def _text_summary_from_raw(raw: Any, max_chars: int = 2000) -> dict:
    try:
        txt = raw if isinstance(raw, str) else str(raw)
    except Exception:
        txt = repr(raw)
    length = len(txt)
    words = len(txt.split())
    preview = txt[:max_chars]
    summary = f"Text document: chars={length}, words={words}"
    return {"summary": summary, "preview": preview}


def _generate_summary(raw: Any, suffix: str) -> dict:
    if suffix in (".xlsx", ".xls", ".csv"):
        return _table_summary_from_raw(raw)
    return _text_summary_from_raw(raw)


def index_file(filepath: Path, user_id: str = "default") -> dict:
    if not filepath.exists():
        return {"success": False, "message": "Файл не найден"}
    try:
        suffix = filepath.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            raw = read_excel(filepath.name)
        else:
            raw = read_file(filepath)
        if raw is None or is_error_response(str(raw)):
            logger.error(f"❌ Ошибка чтения {filepath.name}: {raw}")
            return {"success": False, "message": str(raw)}
        summary_obj = _generate_summary(raw, suffix)
        summary_content = summary_obj.get("summary", "") + "\n\nPREVIEW:\n" + (summary_obj.get("preview") or "")
        summary_meta = {
            "type": "summary",
            "source_path": str(filepath),
            "is_table": suffix in (".xlsx", ".xls", ".csv"),
            "rows": summary_obj.get("rows"),
            "cols": summary_obj.get("cols")
        }
        try:
            vec_res = vector_store.add_document(
                content=summary_content,
                filename=filepath.name,
                filetype=suffix.lstrip('.'),
                user_id=user_id,
                metadata=summary_meta
            )
            if not vec_res.get("success"):
                logger.warning(f"⚠️ Не удалось добавить summary для {filepath.name}: {vec_res.get('message')}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении summary в векторное хранилище для {filepath.name}: {e}")
        if suffix in (".xlsx", ".xls", ".csv"):
            content_for_index = summary_obj.get("preview") or str(raw)
            result = vector_store.add_document(
                content=content_for_index,
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
                logger.info(f"📊 {filepath.name}: таблица добавлена целиком")
                return {"success": True, "chunks": 1}
            return {"success": False, "message": result.get("message")}
        chunks = chunk_text_with_overlap(str(raw))
        success_chunks = 0
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks):
            result = vector_store.add_document(
                content=chunk,
                filename=filepath.name,
                filetype=suffix.lstrip('.'),
                user_id=user_id,
                metadata={
                    "chunk_index": idx,
                    "total_chunks": total_chunks,
                    "source_path": str(filepath),
                }
            )
            if result.get("success"):
                success_chunks += 1
            else:
                logger.warning(f"⚠️ Ошибка индексации чанка {idx} из {filepath.name}")
        logger.info(f"📄 {filepath.name}: {success_chunks}/{total_chunks} чанков")
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
    files = [f for f in BASE_FILES_DIR.iterdir() if f.is_file() and f.suffix.lower() in supported]
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