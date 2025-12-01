import os
import re
from pathlib import Path
from typing import Optional, List
from agent.memory import memory
from .utils import read_file
from .excel_tool import read_excel

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))

STOP_WORDS = {"открой", "покажи", "прочитай", "можешь", "файл", "текст"}


def get_role_files_dir(role: str) -> Path:
    return STORAGE_DIR / role


def _read_file_by_type(filepath: Path, role: str) -> str:
    suffix = filepath.suffix.lower()
    if suffix in {'.xlsx', '.xls', '.csv'}:
        return read_excel(filepath, role=role)
    else:
        return read_file(filepath)


def try_handle_file_command(text: str, role: str) -> Optional[str]:
    match = re.search(r"(прочитай|открой|покажи)\s*(.+)", text, re.I)
    if not match:
        return None

    role_dir = get_role_files_dir(role)
    if not role_dir.exists():
        return f"Папка для роли '{role}' не найдена."

    raw = match.group(2).strip().lower()
    for ext in [".txt", ".pdf", ".docx", ".xlsx", ".xls"]:
        raw = raw.replace(ext, "")
    keywords = [kw for kw in raw.split() if kw not in STOP_WORDS]

    matched_files: List[Path] = [
        f for f in role_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".txt", ".pdf", ".docx", ".xlsx", ".xls")
        and all(kw in f.stem.lower() for kw in keywords)
    ]

    if not matched_files:
        all_files = [f.name for f in role_dir.iterdir() if f.is_file()][:10]
        if all_files:
            files_list = "\n".join(f"- {f}" for f in all_files)
            return f"Файл с ключевыми словами '{match.group(2)}' не найден.\n\nДоступные файлы:\n{files_list}"
        return f"Файл с ключевыми словами '{match.group(2)}' не найден."
    elif len(matched_files) == 1:
        return _read_file_by_type(matched_files[0], role)
    else:
        memory.set_user_files(role, matched_files)
        state = memory.get_state(role) or {}
        state["awaiting_file_choice"] = True
        memory.set_state(role, state)
        return "Найдено несколько файлов: " + ", ".join(
            f"{i + 1}) {f.name}" for i, f in enumerate(matched_files)
        )


def select_file(role: str, choice: str) -> str:
    matched_files = memory.get_user_files(role)
    if not matched_files:
        return "Сначала выполните команду поиска файла."

    try:
        idx = int(choice.strip()) - 1
        if idx < 0 or idx >= len(matched_files):
            return "Некорректный выбор файла. Введите номер из списка."
        selected = matched_files[idx]
        memory.clear_user_files(role)
        state = memory.get_state(role) or {}
        state["awaiting_file_choice"] = False
        memory.set_state(role, state)
        return _read_file_by_type(selected, role)
    except ValueError:
        return "Введите номер файла (число)."
    except Exception as e:
        return f"Ошибка при выборе файла: {e}"