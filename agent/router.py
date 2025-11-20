from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file, read_file
from tools.excel_tool import read_excel, select_excel_file
from tools.utils import BASE_FILES_DIR
from vector_store import vector_store
import re
from pathlib import Path


async def route_message(messages: list, user_id: str):
    last_user_msg = messages[-1]["content"]
    state = memory.get_state(user_id) or {}

    # --- проверка ожидаемого выбора файла ---
    if state.get("awaiting_file_choice"):
        if state.get("awaiting_excel_choice"):
            # Выбор Excel файла
            chosen_text = select_excel_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text})

            # Автоматическая индексация в векторную БД
            selected_file = _get_selected_file(user_id, last_user_msg)
            if selected_file:
                _index_file_to_vector_store(selected_file, user_id)

            # Сброс состояния выбора файлов
            state["awaiting_file_choice"] = False
            state["awaiting_excel_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages
        else:
            # Выбор обычного файла
            chosen_text = select_file(user_id, last_user_msg)
            messages.append({"role": "assistant", "content": chosen_text})

            # Автоматическая индексация в векторную БД
            selected_file = _get_selected_file(user_id, last_user_msg)
            if selected_file:
                _index_file_to_vector_store(selected_file, user_id)

            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return messages[-1]["content"], messages

    # --- команда семантического поиска ---
    if re.search(r"(найди|поиск|найди в файлах|search)", last_user_msg, re.I):
        # Извлекаем поисковый запрос
        query = re.sub(r"(найди|поиск|найди в файлах|search)\s*", "", last_user_msg, flags=re.I).strip()
        if query:
            result = _perform_search(query, user_id)
            messages.append({"role": "assistant", "content": result})
            return messages[-1]["content"], messages

    # --- команда добавления в память ---
    if re.search(r"(запомни|сохрани факт|добавь в память)", last_user_msg, re.I):
        fact = re.sub(r"(запомни|сохрани факт|добавь в память)\s*", "", last_user_msg, flags=re.I).strip()
        if fact:
            result = _add_to_memory(fact, user_id)
            messages.append({"role": "assistant", "content": result})
            return messages[-1]["content"], messages

    # --- проверка команды открытия Excel файла ---
    if any(ext in last_user_msg.lower() for ext in ["excel", ".xlsx", ".xls"]):
        text = last_user_msg.lower()
        # удаляем служебные слова и расширения
        text = re.sub(r"(открой|прочитай|покажи|excel)", "", text)
        for ext in [".xlsx", ".xls"]:
            text = text.replace(ext, "")
        keywords_list = [kw.strip() for kw in text.split() if kw.strip()]

        matched_files = [
            f for f in BASE_FILES_DIR.iterdir()
            if f.suffix.lower() in [".xlsx", ".xls"]
               and all(kw in f.stem.lower() for kw in keywords_list)
        ]

        if not matched_files:
            messages.append(
                {"role": "assistant", "content": f"Excel файл с ключевыми словами '{last_user_msg}' не найден."})
            return messages[-1]["content"], messages
        elif len(matched_files) == 1:
            content = read_excel(matched_files[0].name)
            messages.append({"role": "assistant", "content": content})

            # Автоматическая индексация в векторную БД
            _index_file_to_vector_store(matched_files[0], user_id, content)

            return messages[-1]["content"], messages
        else:
            memory.set_user_files(user_id, matched_files)
            state["awaiting_file_choice"] = True
            state["awaiting_excel_choice"] = True
            memory.set_state(user_id, state)
            messages.append({"role": "assistant",
                             "content": "Найдено несколько Excel файлов: " +
                                        ", ".join(f"{i + 1}) {f.name}" for i, f in enumerate(matched_files))})
            return messages[-1]["content"], messages

    # --- проверка команды открытия обычного файла ---
    file_result = try_handle_file_command(last_user_msg, user_id)
    if file_result:
        messages.append({"role": "assistant", "content": file_result})

        # Попытка индексации (если файл был открыт)
        if not file_result.startswith("Найдено несколько"):
            _auto_index_last_file(user_id, file_result)

        return messages[-1]["content"], messages

    # --- LLM обработает сам ---
    return None, messages


# === Вспомогательные функции для работы с векторной БД ===

def _perform_search(query: str, user_id: str) -> str:
    """Выполнение семантического поиска"""
    if not vector_store.is_connected():
        return "❌ Векторная БД не подключена. Поиск недоступен."

    results = vector_store.search_documents(query, user_id, limit=5)

    if not results:
        return "❌ Ничего не найдено в ваших документах"

    result_lines = ["🔍 **Результаты поиска:**\n"]
    for i, doc in enumerate(results, 1):
        content_preview = doc["content"][:300]
        if len(doc["content"]) > 300:
            content_preview += "..."

        result_lines.append(
            f"📄 **{i}. {doc['filename']}** ({doc['filetype']})\n"
            f"{content_preview}\n"
        )

    return "\n".join(result_lines)


def _add_to_memory(fact: str, user_id: str) -> str:
    """Добавление факта в долговременную память"""
    if not vector_store.is_connected():
        return "❌ Векторная БД не подключена. Память недоступна."

    result = vector_store.add_memory(fact, "general", user_id)

    if result["success"]:
        return result["message"]
    else:
        return f"❌ Ошибка: {result['message']}"


def _index_file_to_vector_store(filepath: Path, user_id: str, content: str = None):
    """Индексация файла в векторную БД"""
    if not vector_store.is_connected():
        return

    try:
        if content is None:
            content = read_file(filepath)

        if content and not content.startswith("Ошибка"):
            result = vector_store.add_document(
                content=content,
                filename=filepath.name,
                filetype=filepath.suffix.lstrip('.'),
                user_id=user_id
            )

            if result["success"]:
                print(f"✅ {filepath.name} проиндексирован")
    except Exception as e:
        print(f"Ошибка индексации {filepath.name}: {e}")


def _get_selected_file(user_id: str, choice: str) -> Path:
    """Получение выбранного файла по номеру"""
    try:
        matched_files = memory.get_user_files(user_id)
        idx = int(choice.strip()) - 1
        if 0 <= idx < len(matched_files):
            return matched_files[idx]
    except:
        pass
    return None


def _auto_index_last_file(user_id: str, content: str):
    """Автоматическая индексация последнего открытого файла"""
    matched_files = memory.get_user_files(user_id)
    if matched_files and len(matched_files) == 1:
        _index_file_to_vector_store(matched_files[0], user_id, content)