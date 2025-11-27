import logging
import re
from typing import List, Dict, Optional

from vector_store import vector_store
from tools.utils import BASE_FILES_DIR, read_file
from tools.excel_tool import read_excel

logger = logging.getLogger(__name__)

KEYWORD_STOP_WORDS = {
    'найди', 'поиск', 'покажи', 'открой', 'файл', 'файлы', 'документ',
    'таблица', 'таблицы', 'все', 'всех', 'данные', 'информация',
    'search', 'find', 'show', 'file', 'files', 'document', 'table',
    'сколько', 'список', 'сводка', 'summary', 'все', 'полный'
}

FULL_CONTEXT_PATTERNS = [
    r'(сводк|summary|обзор|итог|весь|все\s+данные|полн|целиком)',
    r'(список\s+всех|все\s+проект|все\s+материал|все\s+товар)',
    r'(сколько\s+всего|общ\w+\s+колич|total|count\s+all)',
    r'(анализ|статистик|отчёт|report)',
]


def needs_full_context(query: str) -> bool:
    query_lower = query.lower()
    for pattern in FULL_CONTEXT_PATTERNS:
        if re.search(pattern, query_lower):
            return True
    return False


def extract_filename_pattern(query: str) -> str:
    if not query:
        return ""
    tokens = re.findall(r'\b[A-Za-zА-Яа-я0-9_-]{3,}\b', query)
    tokens = [t for t in tokens if t.lower() not in KEYWORD_STOP_WORDS]
    if not tokens:
        return ""
    tokens.sort(key=lambda s: (-len(s), s))
    return tokens[0]


def keyword_search_in_files(query: str, top_n: int = 5, context_chars: int = 300) -> List[Dict]:
    hits = []
    query_lower = (query or "").lower().strip()
    if not query_lower:
        return hits

    for filepath in BASE_FILES_DIR.iterdir():
        if not filepath.is_file():
            continue

        try:
            suffix = filepath.suffix.lower()
            is_table = suffix in {'.xlsx', '.xls', '.csv'}

            if is_table:
                content = read_excel(filepath.name)
            else:
                content = read_file(filepath)

            if not content or content.startswith(("Ошибка", "Error", "Файл")):
                continue

            content_lower = content.lower()
            pos = content_lower.find(query_lower)

            if pos != -1:
                start = max(0, pos - context_chars)
                end = min(len(content), pos + len(query) + context_chars)
                snippet = content[start:end].replace("\n", " ").strip()

                prefix = "..." if start > 0 else ""
                suffix_text = "..." if end < len(content) else ""

                hits.append({
                    "filename": filepath.name,
                    "filetype": suffix.lstrip('.'),
                    "content": f"{prefix}{snippet}{suffix_text}",
                    "is_table": is_table,
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "score": 1.0,
                    "match_type": "keyword"
                })

                if len(hits) >= top_n:
                    return hits

        except Exception as e:
            logger.error(f"Ошибка keyword поиска в {filepath.name}: {e}")

    return hits


def filename_search(query: str, user_id: str = "default", limit: int = 20) -> List[Dict]:
    pattern = extract_filename_pattern(query)
    if not pattern:
        return []

    if not vector_store.is_connected():
        return []

    try:
        results = vector_store.search_by_filename(pattern, user_id, limit=limit) or []
        for r in results:
            r["match_type"] = "filename"
        return results
    except Exception as e:
        logger.error(f"Ошибка поиска по имени: {e}")
        return []


def semantic_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:
    if not vector_store.is_connected():
        return []

    try:
        results = vector_store.search_documents(query, user_id, limit=limit) or []
        for r in results:
            r["match_type"] = "semantic"
        return results
    except Exception as e:
        logger.error(f"Ошибка семантического поиска: {e}")
        return []


def full_document_search(query: str, user_id: str = "default", limit: int = 5) -> List[Dict]:
    if not vector_store.is_connected():
        return []

    try:
        results = vector_store.search_full_documents(query, user_id, limit=limit) or []
        for r in results:
            r["match_type"] = "full_document"
        return results
    except Exception as e:
        logger.error(f"Ошибка поиска полных документов: {e}")
        return []


def smart_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:
    results = []
    seen = set()

    if not vector_store.is_connected():
        return keyword_search_in_files(query, top_n=limit)

    pattern = extract_filename_pattern(query)
    if pattern:
        name_hits = filename_search(query, user_id, limit=limit * 2)
        for doc in name_hits:
            key = doc.get("filename")
            if key and key not in seen:
                results.append(doc)
                seen.add(key)

    semantic_results = semantic_search(query, user_id, limit=limit)
    for doc in semantic_results:
        key = doc.get("filename")
        if key and key not in seen:
            results.append(doc)
            seen.add(key)

    if len(results) < 3:
        keyword_results = keyword_search_in_files(query, top_n=limit)
        for doc in keyword_results:
            key = doc.get("filename")
            if key and key not in seen:
                results.append(doc)
                seen.add(key)

    priority = {"filename": 0, "semantic": 1, "keyword": 2}
    results.sort(key=lambda x: (priority.get(x.get("match_type", "keyword"), 3), -float(x.get("score", 0))))

    return results[:limit]


def get_full_document_content(filename: str, user_id: str = "default") -> Optional[Dict]:
    if not vector_store.is_connected():
        return None

    doc = vector_store.get_full_document(filename, user_id)
    if doc:
        return doc

    filepath = BASE_FILES_DIR / filename
    if filepath.exists():
        suffix = filepath.suffix.lower()
        is_table = suffix in {'.xlsx', '.xls', '.csv'}

        if is_table:
            content = read_excel(filepath.name)
        else:
            content = read_file(filepath)

        return {
            "content": content,
            "filename": filename,
            "is_table": is_table,
        }

    return None


def get_rag_context(query: str, user_id: str = "default", top_n: int = 10,
                    max_context_chars: int = 30000) -> str:
    use_full = needs_full_context(query)

    if use_full:
        results = full_document_search(query, user_id, limit=min(top_n, 5))
        if not results:
            results = smart_search(query, user_id, limit=top_n)
    else:
        results = smart_search(query, user_id, limit=top_n)

    if not results:
        return ""

    parts = ["# КОНТЕКСТ ИЗ ДОКУМЕНТОВ\n"]
    total_chars = 0

    for i, doc in enumerate(results, 1):
        if total_chars >= max_context_chars:
            parts.append(f"\n... контекст обрезан ({len(results) - i + 1} документов не показано)")
            break

        doc_type = "ТАБЛИЦА" if doc.get("is_table") else "ДОКУМЕНТ"
        filename = doc.get("filename", "unknown")

        if use_full and doc.get("match_type") == "full_document":
            content = doc.get("content", "")
            remaining = max_context_chars - total_chars
            if len(content) > remaining:
                content = content[:remaining] + "\n...[документ обрезан]"
        else:
            content = doc.get("content", "")
            chunk_info = ""
            total_chunks = doc.get("total_chunks", 1) or 1
            if total_chunks > 1:
                chunk_info = f" (часть {doc.get('chunk_index', 0) + 1}/{total_chunks})"
            filename = f"{filename}{chunk_info}"

        summary = doc.get("summary", "")
        structure = doc.get("structure", "")

        header_parts = [f"## [{doc_type}] {filename}"]
        if summary:
            header_parts.append(f"**Summary:** {summary}")
        if structure and doc.get("is_table"):
            header_parts.append(f"**Structure:** {structure}")

        header = "\n".join(header_parts)
        doc_block = f"\n{header}\n\n{content}\n"

        parts.append(doc_block)
        total_chars += len(doc_block)

    return "\n".join(parts)


def get_rag_context_for_summary(query: str, user_id: str = "default",
                                  filenames: Optional[List[str]] = None,
                                  max_chars: int = 50000) -> str:
    parts = ["# ПОЛНЫЙ КОНТЕКСТ ДЛЯ АНАЛИЗА\n"]
    total_chars = 0

    if filenames:
        for fname in filenames:
            if total_chars >= max_chars:
                break
            doc = get_full_document_content(fname, user_id)
            if doc:
                content = doc.get("content", "")
                remaining = max_chars - total_chars
                if len(content) > remaining:
                    content = content[:remaining] + "\n...[обрезано]"

                doc_type = "ТАБЛИЦА" if doc.get("is_table") else "ДОКУМЕНТ"
                parts.append(f"\n## [{doc_type}] {fname}\n\n{content}\n")
                total_chars += len(content)
    else:
        results = full_document_search(query, user_id, limit=10)
        for doc in results:
            if total_chars >= max_chars:
                break
            content = doc.get("content", "")
            remaining = max_chars - total_chars
            if len(content) > remaining:
                content = content[:remaining] + "\n...[обрезано]"

            doc_type = "ТАБЛИЦА" if doc.get("is_table") else "ДОКУМЕНТ"
            fname = doc.get("filename", "unknown")
            parts.append(f"\n## [{doc_type}] {fname}\n\n{content}\n")
            total_chars += len(content)

    return "\n".join(parts)


def list_available_documents(user_id: str = "default") -> str:
    if not vector_store.is_connected():
        files = [f.name for f in BASE_FILES_DIR.iterdir() if f.is_file()]
        if not files:
            return "Нет доступных документов."
        return "Доступные файлы:\n" + "\n".join(f"- {f}" for f in files)

    docs = vector_store.get_all_full_documents(user_id)
    if not docs:
        return "Нет проиндексированных документов."

    lines = ["# Доступные документы\n"]
    for doc in docs:
        icon = "📊" if doc.get("is_table") else "📄"
        name = doc.get("filename", "unknown")
        summary = doc.get("summary", "")[:100]
        row_info = f", {doc.get('row_count', 0)} строк" if doc.get("is_table") else ""
        char_info = f", {doc.get('char_count', 0)} символов"

        lines.append(f"{icon} **{name}**{row_info}{char_info}")
        if summary:
            lines.append(f"   {summary}")

    return "\n".join(lines)


def search_documents(query: str, user_id: str = "default", top_n: int = 5) -> str:
    results = smart_search(query, user_id, limit=top_n)
    if not results:
        return "Ничего не найдено."

    lines = ["**Результаты поиска:**\n"]
    for i, doc in enumerate(results, 1):
        content_preview = (doc.get("content") or "")[:400]
        if len(doc.get("content", "")) > 400:
            content_preview += "..."

        icon = "📊" if doc.get("is_table") else "📄"
        chunk_info = ""
        total_chunks = doc.get("total_chunks", 1) or 1
        if total_chunks > 1:
            chunk_info = f" [часть {doc.get('chunk_index', 0) + 1}/{total_chunks}]"

        lines.append(f"{icon} **{i}. {doc['filename']}**{chunk_info}")
        lines.append(f"{content_preview}\n")

    return "\n".join(lines)

def perform_search(query: str, user_id: str = "default", top_n: int = 5) -> str:
    return search_documents(query, user_id, top_n)

def get_raw_results(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    return smart_search(query, user_id, limit=top_n)

def hybrid_search(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    return smart_search(query, user_id, limit=top_n)