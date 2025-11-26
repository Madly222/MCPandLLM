import os
import asyncio
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# === НАСТРОЙКИ ===
DEFAULT_MODEL = "gpt-4o-mini"  # или доступная модель DeepSeek
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEEPSEEK_API_KEY = os.getenv("sk-f3d90f3a29924efb9953077b4578be45")
DEEPSEEK_BASE_URL = "https://api.deepsik.com/v1"  # пример, уточни актуальный URL

async def send_to_llm(messages: list, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Отправка запроса к LLM через DeepSeek HTTP API"""

    async with httpx.AsyncClient() as client:
        payload = {
            "model": DEFAULT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": DEFAULT_TEMPERATURE
        }
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        try:
            response = await client.post(f"{DEEPSEEK_BASE_URL}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            # В DeepSeek ответ может быть в data["choices"][0]["message"]["content"]
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"❌ Ошибка LLM: {e}")
            raise

# === Пример использования ===
async def main():
    messages = [{"role": "user", "content": "Привет, DeepSeek!"}]
    response = await send_to_llm(messages)
    print(response)

if __name__ == "__main__":
    asyncio.run(main())