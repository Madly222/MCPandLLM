from typing import Dict, List
from pathlib import Path

class Memory:
    def __init__(self):
        memory.clear_all_history()
        self.history: Dict[str, list] = {}
        self.user_files: Dict[str, List[Path]] = {}
        self.state: Dict[str, dict] = {}  # для get_state/set_state

        # Ограничение на количество сообщений в истории
        self.max_history_messages = 10

    # --- история ---
    def get_history(self, user_id: str):
        return self.history.get(user_id, [])

    def set_history(self, user_id: str, messages: list):
        # Защита: сохраняем только dict'ы с ролями user/assistant и полем content
        safe = []
        for m in messages or []:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and "content" in m:
                safe.append({"role": m["role"], "content": str(m["content"])})

        # Ограничиваем историю по длине
        if len(safe) > self.max_history_messages:
            safe = safe[-self.max_history_messages:]

        self.history[user_id] = safe

    def add_message(self, user_id: str, role: str, content: str):
        """Добавляет сообщение и автоматически ограничивает историю."""
        if user_id not in self.history:
            self.history[user_id] = []

        self.history[user_id].append({"role": role, "content": content})

        # Обрезаем лишнее
        if len(self.history[user_id]) > self.max_history_messages:
            self.history[user_id] = self.history[user_id][-self.max_history_messages:]

    def clear_history(self, user_id: str):
        """Полностью очищает историю пользователя."""
        if user_id in self.history:
            del self.history[user_id]

    def clear_all_history(self):
        """Полный сброс истории всех пользователей."""
        self.history.clear()

    # --- пользовательские файлы ---
    def set_user_files(self, user_id: str, files: List[Path]):
        self.user_files[user_id] = files

    def get_user_files(self, user_id: str) -> List[Path]:
        return self.user_files.get(user_id, [])

    def clear_user_files(self, user_id: str):
        if user_id in self.user_files:
            del self.user_files[user_id]

    # --- состояние пользователя ---
    def get_state(self, user_id: str):
        return self.state.get(user_id, {})

    def set_state(self, user_id: str, state: dict):
        self.state[user_id] = state

memory = Memory()