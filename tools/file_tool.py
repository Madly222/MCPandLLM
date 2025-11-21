# agent/router.py
from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file, read_file
from tools.excel_tool import read_excel, select_excel_file
from tools.utils import BASE_FILES_DIR
from vector_store import vector_store
import re
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


async def route_message(messages: list, user_id: str):
    last_user_msg = messages[-1]["content"]
    state = memory.get_state(user_id) or {}

    # --- проверка ожидаемого выбора файла ---
    if state.get("awaiting_file_choice"):
        if state.get("awaiting_excel_choice"):
            chosen_text = select_excel_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text})

            selected_file = _get_selected_file(user_id, last_user_msg)
            if selected_file:
                _index_file_to_vector_store(selected_file, user_id)

            state["awaiting_file_choice"] = False
            state["awaiting_excel_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages
        else:
            chosen_text = select_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text})

            selected_file = _get_selected_file(user_id, last_user_msg)
            if selected_file:
                _index_file_to_vector_store(selected_file, user_id)

            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages

    # --- команда семантического поиска ---
    if re.search(r"(найди|поиск|найди в файлах|search)", last_user_msg, re.I):
        query = re.sub(r"(найди|поиск|найди в файлах|search)\s*", "", last_user_msg, flags=re.I).strip()
        if query:
            result = _perform_search(query, user_id)
            messages.append({"role": "assistant", "content": result})
            return messages[-1]["content"], messages

    # --- команда добавления в память ---
    if re.search(r"(запомни|сохрани факт|добавь в память)", last_user_msg, re.I):
        fact = re.sub(r"(запомни|сохрани факт|добавь в память)\s*", "", last_user_msg, flags=re.I).strip()
        if fact:
            result = _add_to_memory(fact, user_id)
            messages.append({"role": "assistant", "content": result})
            return messages[-1]["content"], messages

    # --- проверка команды открытия Excel файла ---
    if any(ext in last_user_msg.lower() for ext in ["excel", ".xlsx", ".xls"]):
        text = last_user_msg.lower()
        text = re.sub(r"(открой|прочитай|покажи|excel)", "", text)
        for ext in [".xlsx", ".xls"]:
            text = text.replace(ext, "")
        keywords_list = [kw.strip() for kw in text.split() if kw.strip()]

        matched_files = [
            f for f in BASE_FILES_DIR.iterdir()
            if f.suffix.lower() in [".xlsx", ".xls"]
               and all(kw in f.stem.lower() for kw in keywords_list)
        ]

        if not matched_files:
            messages.append({"role": "assistant", "content": f"Excel файл с ключевыми словами '{last_user_msg}' не найден."})
            return messages[-1]["content"], messages
        elif len(matched_files) == 1:
            content = read_excel(matched_files[0].name)
            messages.append({"role": "assistant", "content": content})

            _index_file_to_vector_store(matched_files[0], user_id, content)

            return messages[-1]["content"], messages
        else:
            memory.set_user_files(user_id, matched_files)
            state["awaiting_file_choice"] = True
            state["awaiting_excel_choice"] = True
            memory.set_state(user_id, state)
            messages.append({"role": "assistant",
                             "content": "Найдено несколько Excel файлов: " +
                                        ", ".join(f"{i + 1}) {f.name}" for i, f in enumerate(matched_files))})
            return messages[-1]["content"], messages

    # --- проверка команды открытия обычного файла ---
    file_result = try_handle_file_command(last_user_msg, user_id)
    if file_result:
        messages.append({"role": "assistant", "content": file_result})

        if not file_result.startswith("Найдено несколько"):
            _auto_index_last_file(user_id, file_result)

        return messages[-1]["content"], messages

    # --- LLM обработает сам ---
    return None, messages


# === Вспомогательные функции ===

def brute_force_search_files(query: str, user_id: str, max_results: int = 5):
    """Ищем точную подстроку query в исходных файлах (регистронезависимо)."""
    q = query.lower()
    hits = []
    for f in BASE_FILES_DIR.iterdir():
        if not f.is_file():
            continue
        try:
            text = read_file(f)
            if not text or text.startswith("Ошибка"):
                continue
            if q in text.lower():
                start = text.lower().index(q)
                begin = max(0, start - 120)
                end = min(len(text), start + len(q) + 120)
                snippet = text[begin:end].strip().replace("\n", " ")
                hits.append({
                    "content": snippet,
                    "filename": f.name,
                    "filetype": f.suffix.lstrip("."),
                    "score": 1.0
                })
                if len(hits) >= max_results:
                    break
        except Exception:
            continue
    return hits


def _perform_search(query: str, user_id: str) -> str:
    """Выполнение семантического поиска + фоллбек"""
    if not vector_store.is_connected():
        return "❌ Векторная БД не подключена. Поиск недоступен."

    logger.info("Поиск в Weaviate: '%s' for user %s", query, user_id)
    results = vector_store.search_documents(query, user_id, limit=5)

    # Если семантика вернула пусто — пробуем brute-force по исходным файлам
    if not results:
        logger.info("Weaviate вернул 0 результатов — пытаемся прямой поиск по файлам")
        fb = brute_force_search_files(query, user_id, max_results=5)
        if fb:
            results = fb

    if not results:
        return "❌ Ничего не найдено в ваших документах"

    result_lines = ["🔍 **Результаты поиска:**\n"]
    for i, doc in enumerate(results, 1):
        content_preview = doc["content"][:300]
        if len(doc["content"]) > 300:
            content_preview += "..."
        result_lines.append(
            f"📄 **{i}. {doc.get('filename','(unnamed)')}** ({doc.get('filetype','')})\n"
            f"{content_preview}\n"
        )

    return "\n".join(result_lines)


def _add_to_memory(fact: str, user_id: str) -> str:
    if not vector_store.is_connected():
        return "❌ Векторная БД не подключена. Память недоступна."

    result = vector_store.add_memory(fact, "general", user_id)

    if result["success"]:
        return result["message"]
    else:
        return f"❌ Ошибка: {result['message']}"


def _index_file_to_vector_store(filepath: Path, user_id: str, content: str = None):
    if not vector_store.is_connected():
        return

    try:
        if content is None:
            content = read_file(filepath)

        if content and not content.startswith("Ошибка"):
            result = vector_store.add_document(
                content=content,
                filename=filepath.name,
                filetype=filepath.suffix.lstrip('.'),
                user_id=user_id,
                metadata={"source_path": str(filepath)}
            )

            if result["success"]:
                logger.info(f"✅ {filepath.name} проиндексирован")
    except Exception as e:
        logger.error(f"Ошибка индексации {filepath.name}: {e}")


def _get_selected_file(user_id: str, choice: str) -> Path:
    try:
        matched_files = memory.get_user_files(user_id)
        idx = int(choice.strip()) - 1
        if 0 <= idx < len(matched_files):
            return matched_files[idx]
    except Exception:
        pass
    return None


def _auto_index_last_file(user_id: str, content: str):
    matched_files = memory.get_user_files(user_id)
    if matched_files and len(matched_files) == 1:
        _index_file_to_vector_store(matched_files[0], user_id, content)