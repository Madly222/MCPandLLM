# agent/router.py
from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file, read_file
from tools.excel_tool import read_excel, select_excel_file
from tools.utils import BASE_FILES_DIR
from tools.indexing_tool import index_file
from tools.search_tool import perform_search
from vector_store import vector_store
from pathlib import Path
import re
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
                index_file(selected_file, user_id)

            state["awaiting_file_choice"] = False
            state["awaiting_excel_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages

        else:
            chosen_text = select_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text})

            selected_file = _get_selected_file(user_id, last_user_msg)
            if selected_file:
                index_file(selected_file, user_id)

            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages

    # --- команда семантического поиска ---
    if re.search(r"(найди|поиск|найди в файлах|search)", last_user_msg, re.I):
        query = re.sub(r"(найди|поиск|найди в файлах|search)\s*", "", last_user_msg, flags=re.I).strip()
        if query:
            result = perform_search(query, user_id)
            messages.append({"role": "assistant", "content": result})
            return messages[-1]["content"], messages

    # --- команда добавления в память ---
    if re.search(r"(запомни|сохрани факт|добавь в память)", last_user_msg, re.I):
        fact = re.sub(r"(запомни|сохрани факт|добавь в память)\s*", "", last_user_msg, flags=re.I).strip()
        if fact:
            result = _add_to_memory(fact, user_id)
            messages.append({"role": "assistant", "content": result})
            return messages[-1]["content"], messages

    # --- открытие Excel файлов ---
    if any(ext in last_user_msg.lower() for ext in ["excel", ".xlsx", ".xls"]):
        keywords = re.sub(r"(открой|прочитай|покажи|excel)", "", last_user_msg.lower())
        for ext in [".xlsx", ".xls"]:
            keywords = keywords.replace(ext, "")
        keywords_list = [kw.strip() for kw in keywords.split() if kw.strip()]

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
            index_file(matched_files[0], user_id, content)
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

    # --- открытие обычных файлов ---
    file_result = try_handle_file_command(last_user_msg, user_id)
    if file_result:
        messages.append({"role": "assistant", "content": file_result})

        if not file_result.startswith("Найдено несколько"):
            matched_file = _get_selected_file(user_id, last_user_msg)
            if matched_file:
                index_file(matched_file, user_id, file_result)

        return messages[-1]["content"], messages

    # --- LLM обработает сам ---
    return None, messages


# === Вспомогательные функции ===

def _add_to_memory(fact: str, user_id: str) -> str:
    if not vector_store.is_connected():
        return "❌ Векторная БД не подключена. Память недоступна."
    result = vector_store.add_memory(fact, "general", user_id)
    return result["message"] if result["success"] else f"❌ Ошибка: {result['message']}"


def _get_selected_file(user_id: str, choice: str) -> Path:
    try:
        matched_files = memory.get_user_files(user_id)
        idx = int(choice.strip()) - 1
        if 0 <= idx < len(matched_files):
            return matched_files[idx]
    except Exception:
        pass
    return None