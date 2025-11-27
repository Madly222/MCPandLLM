import os
import asyncio
import logging
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

logger = logging.getLogger(__name__)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

DEFAULT_MODEL = "claude-3-haiku-20240307"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7

async def send_to_llm(messages: list, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:

    # Claude требует content как LIST, а не string
    claude_messages = []
    for msg in messages:
        claude_messages.append({
            "role": msg["role"],
            "content": [{"type": "text", "text": msg["content"]}]
        })

    loop = asyncio.get_event_loop()

    def blocking():
        return client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=max_tokens,
            temperature=DEFAULT_TEMPERATURE,
            messages=claude_messages
        )

    try:
        res = await loop.run_in_executor(None, blocking)

        output = "".join(block.text for block in res.content)

        return output

    except Exception as e:
        logger.error(f"❌ LLM error: {e}")
        raise