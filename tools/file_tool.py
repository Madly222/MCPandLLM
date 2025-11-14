# tools/file_tool.py
import re
from pathlib import Path
from typing import Optional, List
from agent.memory import memory
from .utils import BASE_FILES_DIR

# Для Word/PDF
from docx import Document
import PyPDF2

STOP_WORDS = {"открой", "покажи", "прочитай", "можешь", "файл", "текст"}

def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Ошибка при чтении файла: {e}"

def read_docx(path: Path) -> str:
    try:
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        return f"Ошибка при чтении Word файла: {e}"

def read_pdf(path: Path) -> str:
    try:
        text = ""
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Ошибка при чтении PDF файла: {e}"

def read_file(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return read_text_file(path)
    elif path.suffix.lower() == ".docx":
        return read_docx(path)
    elif path.suffix.lower() == ".pdf":
        return read_pdf(path)
    else:
        return f"Формат файла {path.suffix} не поддерживается."

def try_handle_file_command(text: str, user_id: str) -> Optional[str]:
    match = re.search(r"(прочитай|открой|покажи)\s*(.+)", text, re.I)
    if not match:
        return None

    raw = match.group(2).strip().lower()
    # убираем расширения и стоп-слова
    for ext in [".txt", ".pdf", ".docx"]:
        raw = raw.replace(ext, "")
    keywords = [kw for kw in raw.split() if kw not in STOP_WORDS]

    matched_files: List[Path] = [
        f for f in BASE_FILES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in (".txt", ".pdf", ".docx")
        and all(kw in f.stem.lower() for kw in keywords)
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