from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file
from tools.excel_tool import read_excel, select_excel_file
from tools.utils import BASE_FILES_DIR
import re
from pathlib import Path

async def route_message(messages: list, user_id: str):
    last_user_msg = messages[-1]["content"]
    state = memory.get_state(user_id) or {}

    # --- проверка ожидаемого выбора файла ---
    if state.get("awaiting_file_choice"):
        if state.get("awaiting_excel_choice"):
            # Выбор Excel файла
            chosen_text = select_excel_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text})
            # Сброс состояния выбора файлов
            state["awaiting_file_choice"] = False
            state["awaiting_excel_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages
        else:
            # Выбор обычного файла
            chosen_text = select_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text})
            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages

    # --- проверка команды открытия Excel файла ---
    if any(ext in last_user_msg.lower() for ext in ["excel", ".xlsx", ".xls"]):
        text = last_user_msg.lower()
        # удаляем служебные слова и расширения
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
            messages.append({"role": "assistant", "content": read_excel(matched_files[0].name)})
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
        return messages[-1]["content"], messages

    # --- LLM обработает сам ---
    return None, messages