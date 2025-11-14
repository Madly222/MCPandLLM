from typing import Dict, List
from pathlib import Path

class Memory:
    def __init__(self):
        self.history: Dict[str, list] = {}
        self.user_files: Dict[str, List[Path]] = {}
        self.state: Dict[str, dict] = {}  # для get_state/set_state

    # --- история ---
    def get_history(self, user_id: str):
        return self.history.get(user_id, [])

    def set_history(self, user_id: str, messages: list):
        self.history[user_id] = messages

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