from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file
from tools.excel_tool import read_excel
from tools.utils import BASE_FILES_DIR
from tools.search_tool import perform_search
from vector_store import vector_store
from pathlib import Path
import re
import logging
from tools.multi_file_tool import process_multiple_files

logger = logging.getLogger(__name__)


async def route_message(messages: list, user_id: str):
    last_user_msg = messages[-1]["content"]
    state = memory.get_state(user_id) or {}

    if state.get("awaiting_file_choice"):
        if state.get("awaiting_excel_choice"):
            from tools.excel_tool import select_excel_file
            chosen_text = select_excel_file(user_id, last_user_msg)
            state["awaiting_file_choice"] = False
            state["awaiting_excel_choice"] = False
            memory.set_state(user_id, state)
            return chosen_text, messages
        else:
            chosen_text = select_file(user_id, last_user_msg)
            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return chosen_text, messages

    if re.search(r"(найди|поиск|найди в файлах|search)\s+\w", last_user_msg, re.I):
        query = re.sub(r"(найди|поиск|найди в файлах|search)\s*", "", last_user_msg, flags=re.I).strip()
        if query:
            result = perform_search(query, user_id)
            return result, messages

    if re.search(r"(запомни|сохрани факт|добавь в память)", last_user_msg, re.I):
        fact = re.sub(r"(запомни|сохрани факт|добавь в память)\s*", "", last_user_msg, flags=re.I).strip()
        if fact and vector_store.is_connected():
            result = vector_store.add_memory(fact, "general", user_id)
            return result.get("message", "Ошибка"), messages

    if re.search(r"(сводка|сводку|обзор|summary).*(файл|документ|всех)", last_user_msg, re.I):
        result = await process_multiple_files(last_user_msg, user_id, top_n=20)
        return result, messages

    if re.search(r"(сравни|сравнение|compare)", last_user_msg, re.I):
        result = await process_multiple_files(last_user_msg, user_id, top_n=10)
        return result, messages

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
            return f"Excel файл не найден.", messages

        elif len(matched_files) == 1:
            content = read_excel(matched_files[0].name)
            return content, messages

        else:
            memory.set_user_files(user_id, matched_files)
            state["awaiting_file_choice"] = True
            state["awaiting_excel_choice"] = True
            memory.set_state(user_id, state)
            return "Найдено несколько Excel файлов: " + ", ".join(
                f"{i + 1}) {f.name}" for i, f in enumerate(matched_files)
            ), messages

    file_result = try_handle_file_command(last_user_msg, user_id)
    if file_result:
        return file_result, messages

    return None, messages