import os
from pathlib import Path
from PyPDF2 import PdfReader
import requests
from dotenv import load_dotenv

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


def check_openrouter_balance():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print("❌ OPENAI_API_KEY не найден в .env")
        return

    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"}
        )

        if response.status_code == 200:
            data = response.json().get("data", {})
            print("💰 OpenRouter Balance:")
            print(f"   • Usage: ${data.get('usage', 0):.2f}")
            print(f"   • Limit: ${data.get('limit', 0):.2f}")
            print(f"   • Remaining: ${data.get('limit', 0) - data.get('usage', 0):.2f}")
            print(f"   • Free tier: {data.get('is_free_tier', False)}")

            rate_limit = data.get('rate_limit', {})
            if rate_limit:
                print(f"   • Rate limit: {rate_limit.get('requests')} req / {rate_limit.get('interval')}")
        else:
            print(f"❌ Ошибка: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"❌ Ошибка проверки баланса: {e}")


if __name__ == "__main__":
    check_openrouter_balance()