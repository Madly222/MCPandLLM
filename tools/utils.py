import os
from pathlib import Path
from dotenv import load_dotenv
from PyPDF2 import PdfReader

load_dotenv()
BASE_FILES_DIR = Path(os.getenv("FILES_DIR", Path.cwd()))
if not BASE_FILES_DIR.exists():
    raise RuntimeError(f"Папка с файлами не найдена: {BASE_FILES_DIR}")

def read_file(filepath: Path) -> str:
    if not filepath.exists():
        return f"Файл {filepath} не найден."
    try:
        if filepath.suffix.lower() in [".txt", ".md", ".csv", ".log"]:
            return filepath.read_text(encoding="utf-8")
        elif filepath.suffix.lower() == ".pdf":
            reader = PdfReader(filepath)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        else:
            return f"Тип файла {filepath.suffix} не поддерживается."
    except Exception as e:
        return f"Ошибка при чтении файла {filepath}: {e}"