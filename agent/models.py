import os
from dotenv import load_dotenv
from openai import OpenAI
import asyncio

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

async def send_to_llm(messages):
    loop = asyncio.get_event_loop()
    def blocking_call():
        return client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
    res = await loop.run_in_executor(None, blocking_call)
    return res.choices[0].message.content