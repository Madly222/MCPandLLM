# tools/file_tool.py
import re
from pathlib import Path
from typing import Optional, List
from agent.memory import memory
from .utils import BASE_FILES_DIR, read_file

STOP_WORDS = {"открой", "покажи", "прочитай", "можешь", "excel", "файл", "таблица", "таблицу", "лист"}

def try_handle_file_command(text: str, user_id: str) -> Optional[str]:
    """
    Search non-excel files by keywords and return content or selection prompt.
    """
    match = re.search(r"(прочитай|открой|покажи)\s*(.+)", text, re.I)
    if not match:
        return None

    raw = match.group(2).strip().lower()
    keywords = [kw for kw in raw.split() if kw and kw not in STOP_WORDS]

    matched_files: List[Path] = [
        f for f in BASE_FILES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() not in (".xlsx", ".xls")
        and all(kw in f.name.lower() for kw in keywords)
    ]

    if not matched_files:
        return f"Файл с ключевыми словами '{match.group(2)}' не найден."
    elif len(matched_files) == 1:
        return read_file(matched_files[0])
    else:
        memory.set_user_files(user_id, matched_files)
        state = memory.get_state(user_id) or {}
        state["awaiting_file_choice"] = True
        memory.set_state(user_id, state)
        return "Найдено несколько файлов: " + ", ".join(f"{i + 1}) {f.name}" for i, f in enumerate(matched_files))


def select_file(user_id: str, choice: str) -> str:
    matched_files = memory.get_user_files(user_id)
    if not matched_files:
        return "Сначала выполните команду поиска файла."

    try:
        idx = int(choice.strip()) - 1
        if idx < 0 or idx >= len(matched_files):
            return "Некорректный выбор файла. Введите номер из списка."
        selected = matched_files[idx]
        memory.clear_user_files(user_id)
        state = memory.get_state(user_id) or {}
        state["awaiting_file_choice"] = False
        memory.set_state(user_id, state)
        return read_file(selected)
    except ValueError:
        return "Введите номер файла (число)."
    except Exception as e:
        return f"Ошибка при выборе файла: {e}"
