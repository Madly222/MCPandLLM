import re
import json
import logging
from pathlib import Path
from typing import Optional, Tuple, List

from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file
from tools.excel_tool import read_excel
from tools.utils import BASE_FILES_DIR
from tools.search_tool import perform_search, smart_search
from tools.edit_excel_tool import edit_excel, get_excel_preview
from tools.excel_nlu import parse_excel_command
from tools.multi_file_tool import process_multiple_files
from vector_store import vector_store

logger = logging.getLogger(__name__)

EDIT_TRIGGERS = [
    r"добавь строку",
    r"добавь колонку",
    r"удали строку",
    r"удали колонку",
    r"измени ячейку",
    r"поменяй ячейку",
    r"вставь строку",
    r"новая строка",
    r"новая колонка",
    r"отредактируй",
    r"редактируй",
    r"измени в файле",
    r"измени файл",
    r"обнови файл",
    r"удали.*работ",
    r"удали.*строк",
    r"добавь.*в файл",
    r"добавь.*в таблиц",
]


def _is_edit_command(text: str) -> bool:
    text_lower = text.lower()
    for trigger in EDIT_TRIGGERS:
        if re.search(trigger, text_lower):
            return True
    return False


def _extract_filename_from_text(text: str) -> Optional[str]:
    text_lower = text.lower()

    best_match = None
    best_match_len = 0

    for filepath in BASE_FILES_DIR.iterdir():
        if filepath.suffix.lower() in ['.xlsx', '.xls']:
            filename = filepath.name
            filename_lower = filename.lower()

            if filename_lower in text_lower:
                if len(filename) > best_match_len:
                    best_match = filename
                    best_match_len = len(filename)

            stem_lower = filepath.stem.lower()
            if stem_lower in text_lower:
                if len(filepath.stem) > best_match_len:
                    best_match = filename
                    best_match_len = len(filepath.stem)

    if best_match:
        logger.info(f"Найден файл по точному совпадению: {best_match}")
        return best_match

    xlsx_match = re.search(r'(\S+\.xlsx?)', text, re.I)
    if xlsx_match:
        potential_name = xlsx_match.group(1)
        found = _find_file_by_pattern(potential_name)
        if found:
            logger.info(f"Найден файл по паттерну: {found}")
            return found

    keywords = []
    for word in text.split():
        word_clean = re.sub(r'[^\w]', '', word.lower())
        if word_clean and len(word_clean) >= 3:
            if word_clean not in ['отредактируй', 'редактируй', 'измени', 'удали',
                                  'добавь', 'файл', 'таблицу', 'таблица', 'excel',
                                  'строку', 'строки', 'колонку', 'ячейку', 'работы',
                                  'все', 'выполненые', 'выполненные', 'невыполненные']:
                keywords.append(word_clean)

    if keywords:
        best_file = None
        best_score = 0

        for filepath in BASE_FILES_DIR.iterdir():
            if filepath.suffix.lower() in ['.xlsx', '.xls']:
                stem_lower = filepath.stem.lower()
                score = sum(1 for kw in keywords if kw in stem_lower)
                if score > best_score:
                    best_score = score
                    best_file = filepath.name

        if best_file:
            logger.info(f"Найден файл по ключевым словам ({best_score} совпадений): {best_file}")
            return best_file

    return None


def _find_file_by_pattern(pattern: str) -> Optional[str]:
    if not pattern:
        return None

    pattern_clean = pattern.lower().replace('.xlsx', '').replace('.xls', '')
    pattern_clean = re.sub(r'[^\w]', '', pattern_clean)

    best_match = None
    best_score = 0

    for filepath in BASE_FILES_DIR.iterdir():
        if filepath.suffix.lower() in ['.xlsx', '.xls']:
            stem_clean = re.sub(r'[^\w]', '', filepath.stem.lower())

            if pattern_clean == stem_clean:
                return filepath.name

            if pattern_clean in stem_clean:
                score = len(pattern_clean) / len(stem_clean)
                if score > best_score:
                    best_score = score
                    best_match = filepath.name

    return best_match


def _is_complex_edit_command(text: str) -> bool:
    complex_patterns = [
        r"удали.*все",
        r"удали.*выполнен",
        r"удали.*невыполнен",
        r"удали.*где",
        r"удали.*которые",
        r"измени.*все",
        r"замени.*все",
        r"пересчитай",
        r"обнови.*итог",
    ]

    text_lower = text.lower()
    for pattern in complex_patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def _get_edit_instruction(text: str, filename: str) -> str:
    text_clean = text.lower()
    text_clean = re.sub(r'отредактируй\s*', '', text_clean)
    text_clean = re.sub(r'редактируй\s*', '', text_clean)
    text_clean = re.sub(r'[^\s]+\.xlsx?', '', text_clean, flags=re.I)
    text_clean = text_clean.strip()
    return text_clean


async def route_message(messages: list, user_id: str):
    last_user_msg = messages[-1]["content"]
    state = memory.get_state(user_id) or {}

    logger.info(f"Router: обрабатываем '{last_user_msg[:50]}...'")

    if state.get("awaiting_file_choice"):
        if state.get("awaiting_excel_choice"):
            from tools.excel_tool import select_excel_file
            chosen_text = select_excel_file(user_id, last_user_msg)
            state["awaiting_file_choice"] = False
            state["awaiting_excel_choice"] = False
            memory.set_state(user_id, state)
            return chosen_text, messages
        else:
            chosen_text = select_file(user_id, last_user_msg)
            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return chosen_text, messages

    if state.get("awaiting_file_for_edit"):
        operations = state.get("pending_operations", [])
        filename = _find_file_by_pattern(last_user_msg)

        if filename:
            result = edit_excel(filename, operations)
            state["awaiting_file_for_edit"] = False
            state["pending_operations"] = None
            memory.set_state(user_id, state)

            if result.get("success"):
                return f"Готово! Скачать: {result['download_url']}", messages
            else:
                return f"Ошибка: {result.get('error')}", messages
        else:
            return "Файл не найден. Укажите точное имя файла.", messages

    if _is_edit_command(last_user_msg):
        logger.info("Router: обнаружена команда редактирования")
        filename = _extract_filename_from_text(last_user_msg)
        logger.info(f"Router: извлечённый файл = {filename}")

        if not filename:
            results = smart_search(last_user_msg, user_id, limit=5)
            excel_files = [r for r in results if r.get("is_table")]

            if len(excel_files) == 1:
                filename = excel_files[0]["filename"]
            elif len(excel_files) > 1:
                files_list = "\n".join([f"- {f['filename']}" for f in excel_files])
                return f"Найдено несколько файлов:\n{files_list}\n\nУкажите какой файл редактировать.", messages

        if not filename:
            all_excel = [f.name for f in BASE_FILES_DIR.iterdir()
                         if f.suffix.lower() in ['.xlsx', '.xls']]
            if all_excel:
                files_list = "\n".join([f"- {f}" for f in all_excel[:10]])
                return f"Не удалось определить файл. Доступные файлы:\n{files_list}", messages
            else:
                return "Excel файлы не найдены.", messages

        if _is_complex_edit_command(last_user_msg):
            instruction = _get_edit_instruction(last_user_msg, filename)
            file_content = read_excel(filename)

            context = f"""Файл: {filename}

Содержимое:
{file_content}

---
Инструкция пользователя: {instruction}

Проанализируй таблицу и сгенерируй JSON с операциями редактирования.
Формат ответа:
```json
{{
  "filename": "{filename}",
  "operations": [
    {{"action": "delete_row", "row": N}},
    ...
  ]
}}
```

Доступные операции:
- delete_row: удалить строку (row = номер строки)
- edit_cell: изменить ячейку (row, col, value)
- add_row: добавить строку (data = массив значений, after_row = после какой строки)
"""
            messages.append({"role": "user", "content": context})
            logger.info(f"Router: сложная команда, отправляем в LLM. Файл: {filename}")
            return None, messages

        _, operations = parse_excel_command(last_user_msg)

        if operations:
            result = edit_excel(filename, operations)

            if result.get("success"):
                ops_desc = ", ".join([op["action"] for op in operations])
                return f"Выполнено ({ops_desc})!\n\nСкачать: {result['download_url']}", messages
            else:
                return f"Ошибка: {result.get('error')}", messages
        else:
            file_content = read_excel(filename)
            instruction = _get_edit_instruction(last_user_msg, filename)

            context = f"""Файл: {filename}

Содержимое:
{file_content}

---
Инструкция: {instruction}

Сгенерируй JSON с операциями:
```json
{{
  "filename": "{filename}",
  "operations": [...]
}}
```
"""
            messages.append({"role": "user", "content": context})
            return None, messages

    if re.search(r"(найди|поиск|найди в файлах|search)\s+\w", last_user_msg, re.I):
        query = re.sub(r"(найди|поиск|найди в файлах|search)\s*", "", last_user_msg, flags=re.I).strip()
        if query:
            result = perform_search(query, user_id)
            return result, messages

    if re.search(r"(запомни|сохрани факт|добавь в память)", last_user_msg, re.I):
        fact = re.sub(r"(запомни|сохрани факт|добавь в память)\s*", "", last_user_msg, flags=re.I).strip()
        if fact and vector_store.is_connected():
            result = vector_store.add_memory(fact, "general", user_id)
            return result.get("message", "Ошибка"), messages

    if re.search(r"(сводка|сводку|обзор|summary).*(файл|документ|всех)", last_user_msg, re.I):
        result = await process_multiple_files(last_user_msg, user_id, top_n=20)
        return result, messages

    if re.search(r"(сравни|сравнение|compare)", last_user_msg, re.I):
        result = await process_multiple_files(last_user_msg, user_id, top_n=10)
        return result, messages

    edit_match = re.search(
        r'```json\s*(\{[\s\S]*?"operations"[\s\S]*?\})\s*```',
        last_user_msg,
        re.I
    )
    if edit_match:
        try:
            edit_data = json.loads(edit_match.group(1))
            filename = edit_data.get("filename")
            operations = edit_data.get("operations", [])

            if filename and operations:
                result = edit_excel(filename, operations)
                if result.get("success"):
                    return f"Файл отредактирован!\n\nСкачать: {result['download_url']}", messages
                else:
                    return f"Ошибка: {result.get('error')}", messages
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")

    if any(ext in last_user_msg.lower() for ext in [".xlsx", ".xls"]):
        filename = _extract_filename_from_text(last_user_msg)
        if filename:
            content = read_excel(filename)
            return content, messages

    file_result = try_handle_file_command(last_user_msg, user_id)
    if file_result:
        return file_result, messages

    return None, messages