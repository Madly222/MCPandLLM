import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
BASE_FILES_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))

if not BASE_FILES_DIR.exists():
    BASE_FILES_DIR.mkdir(parents=True, exist_ok=True)

def read_file(filepath) -> str:
    if isinstance(filepath, str):
        filepath = Path(filepath)
        if not filepath.is_absolute():
            filepath = BASE_FILES_DIR / filepath

    if not filepath.exists():
        return f"Файл {filepath} не найден."

    suffix = filepath.suffix.lower()

    try:
        if suffix in {".txt", ".md", ".csv", ".log"}:
            return filepath.read_text(encoding="utf-8")

        if suffix == ".pdf":
            from PyPDF2 import PdfReader
            reader = PdfReader(filepath)
            pages = []
            for i, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"--- Страница {i} ---\n{text}")
            return "\n\n".join(pages)

        if suffix == ".docx":
            from docx import Document
            doc = Document(filepath)
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

        return f"Формат {suffix} не поддерживается."

    except Exception as e:
        return f"Ошибка чтения {filepath}: {e}"