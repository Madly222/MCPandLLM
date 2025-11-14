from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file
from tools.excel_tool import read_excel, write_excel, select_excel_file
from tools.utils import BASE_FILES_DIR

async def route_message(messages: list, user_id: str):
    last_user_msg = messages[-1]["content"]
    state = memory.get_state(user_id)

    # --- проверка ожидаемого выбора файла ---
    if state.get("awaiting_file_choice"):
        # Сначала проверяем, ожидается ли выбор Excel файла
        if state.get("awaiting_excel_choice"):
            chosen_text = select_excel_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text[:4000]})
            return messages[-1]["content"], messages
        else:
            # Иначе это обычный файл
            chosen_text = select_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text[:4000]})
            return messages[-1]["content"], messages

    # --- проверка команды открытия Excel файла ---
    if any(ext in last_user_msg.lower() for ext in ["excel", ".xlsx", ".xls"]):
        keywords = last_user_msg.lower().replace("excel", "").strip()
        matched_files = [f for f in BASE_FILES_DIR.iterdir()
                         if f.suffix.lower() in [".xlsx", ".xls"] and all(kw in f.name.lower() for kw in keywords.split())]

        if not matched_files:
            messages.append({"role": "assistant", "content": f"Excel файл с ключевыми словами '{last_user_msg}' не найден."})
            return messages[-1]["content"], messages
        elif len(matched_files) == 1:
            messages.append({"role": "assistant", "content": read_excel(matched_files[0].name)[:4000]})
            return messages[-1]["content"], messages
        else:
            memory.set_user_files(user_id, matched_files)
            memory.set_state(user_id, {"awaiting_excel_choice": True})
            messages.append({"role": "assistant",
                             "content": "Найдено несколько Excel файлов: " +
                                        ", ".join(f"{i + 1}) {f.name}" for i, f in enumerate(matched_files))})
            return messages[-1]["content"], messages

    # --- проверка команды открытия обычного файла ---
    file_result = try_handle_file_command(last_user_msg, user_id)
    if file_result:
        messages.append({"role": "assistant", "content": file_result[:4000]})
        return messages[-1]["content"], messages

    # --- LLM обработает сам ---
    return None, messages

