import os
import re
import json
import logging
from pathlib import Path
from typing import Optional, Tuple, List

from agent.memory import memory
from tools.file_tool import try_handle_file_command, select_file
from tools.excel_tool import read_excel, read_excel_for_edit
from tools.search_tool import perform_search, smart_search
from tools.edit_excel_tool import edit_excel, get_excel_preview
from tools.excel_nlu import parse_excel_command
from tools.multi_file_tool import process_multiple_files
from tools.file_reader_tool import (
    get_example_files, find_file, extract_content,
    read_multiple_files, ExtractedContent
)
from tools.file_generator_tool import (
    generate_file, parse_llm_json, build_from_json
)
from tools.template_analyzer import analyze_template, format_schema_for_llm
from tools.data_mapper import (
    map_columns, map_multiple_sources,
    extract_mapped_data, format_mapping_for_llm
)
from vector_store import vector_store

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))


def get_role_files_dir(role: str) -> Path:
    return STORAGE_DIR / role


EDIT_TRIGGERS = [
    r"добавь строку", r"добавь колонку", r"удали строку", r"удали колонку",
    r"измени ячейку", r"поменяй ячейку", r"вставь строку", r"новая строка",
    r"новая колонка", r"отредактируй", r"редактируй", r"измени в файле",
    r"измени файл", r"обнови файл", r"удали.*работ", r"удали.*строк",
    r"добавь.*в файл", r"добавь.*в таблиц",
]

GENERATE_TRIGGERS = [
    r"создай.*из.*файл", r"сделай.*из.*файл", r"объедини.*файл",
    r"собери.*из", r"сгенерируй.*из", r"создай.*объединив",
    r"сделай.*объединив", r"из файла.*и.*файла.*создай",
    r"из файла.*и.*файла.*сделай", r"по примеру.*создай",
    r"по шаблону.*создай", r"как в примере", r"как в examples",
    r"используя.*шаблон", r"создай.*excel", r"создай.*word",
    r"создай.*xlsx", r"создай.*docx", r"сделай.*отчёт.*из",
    r"сделай.*отчет.*из", r"создай.*отчёт.*из", r"создай.*отчет.*из",
    r"создай новый", r"сделай новый", r"новый файл из",
    r"по структуре", r"такой же как", r"аналогично",
]

TEMPLATE_KEYWORDS = [
    "по примеру", "по шаблону", "как в", "по структуре",
    "такой же как", "аналогично", "используя шаблон",
    "по образцу", "скопируй структуру"
]


def _is_edit_command(text: str) -> bool:
    text_lower = text.lower()
    for trigger in EDIT_TRIGGERS:
        if re.search(trigger, text_lower):
            return True
    return False


def _is_generate_command(text: str) -> bool:
    text_lower = text.lower()
    for trigger in GENERATE_TRIGGERS:
        if re.search(trigger, text_lower):
            return True
    return False


def _is_template_command(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in TEMPLATE_KEYWORDS)


def _extract_template_name(text: str, role: str) -> Optional[str]:
    patterns = [
        r'(?:по примеру|по шаблону|как в|по образцу|по структуре)\s+["\']?([^\s"\']+\.\w+)["\']?',
        r'(?:по примеру|по шаблону|как в|по образцу|по структуре)\s+["\']?([^\s"\']+)["\']?',
        r'(?:файл[а]?|шаблон[а]?)\s+["\']?([^\s"\']+\.\w+)["\']?',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            potential = match.group(1)
            if find_file(potential, role):
                return potential
            if find_file(potential + ".xlsx", role):
                return potential + ".xlsx"

    role_dir = STORAGE_DIR / role
    if role_dir.exists():
        for filepath in role_dir.iterdir():
            if filepath.is_file():
                name_lower = filepath.stem.lower()
                if name_lower in text.lower() or filepath.name.lower() in text.lower():
                    return filepath.name

    examples_dir = STORAGE_DIR / "examples"
    if examples_dir.exists():
        for filepath in examples_dir.iterdir():
            if filepath.is_file():
                name_lower = filepath.stem.lower()
                if name_lower in text.lower() or filepath.name.lower() in text.lower():
                    return filepath.name

    return None


def _extract_source_files(text: str, role: str, exclude: Optional[str] = None) -> List[str]:
    found_files = set()

    file_patterns = [
        r'из\s+(?:файлов?\s+)?["\']?([^\s"\']+\.(?:xlsx?|docx|pdf|pptx))["\']?',
        r'(?:файл[аы]?\s+)?["\']?([^\s"\']+\.(?:xlsx?|docx|pdf|pptx))["\']?',
        r'и\s+["\']?([^\s"\']+\.(?:xlsx?|docx|pdf|pptx))["\']?',
        r'данные\s+из\s+["\']?([^\s"\']+)["\']?',
    ]

    for pattern in file_patterns:
        matches = re.findall(pattern, text, re.I)
        for match in matches:
            if match and match != exclude:
                found_files.add(match)

    role_dir = STORAGE_DIR / role
    if role_dir.exists():
        for filepath in role_dir.iterdir():
            if filepath.is_file() and filepath.name != exclude:
                name_lower = filepath.stem.lower()
                if name_lower in text.lower() or filepath.name.lower() in text.lower():
                    if filepath.suffix.lower() in ['.xlsx', '.xls', '.docx', '.pdf', '.pptx']:
                        found_files.add(filepath.name)

    if exclude:
        found_files.discard(exclude)

    return list(found_files)


def _extract_output_params(text: str) -> Tuple[str, Optional[str]]:
    output_format = "xlsx"
    output_name = None

    text_lower = text.lower()

    if 'word' in text_lower or 'docx' in text_lower or 'документ' in text_lower:
        output_format = "docx"
    elif 'excel' in text_lower or 'xlsx' in text_lower or 'таблиц' in text_lower:
        output_format = "xlsx"

    name_match = re.search(
        r'(?:назови|сохрани как|имя файла|название)\s+["\']?([a-zA-Zа-яА-Я0-9_\-]+)["\']?',
        text, re.I
    )
    if name_match:
        output_name = name_match.group(1)

    return output_format, output_name


def _format_content_for_llm(content: ExtractedContent) -> str:
    parts = []

    if content.text:
        text_preview = content.text[:2000]
        if len(content.text) > 2000:
            text_preview += "\n... (текст обрезан)"
        parts.append(f"Текст:\n{text_preview}")

    for i, table in enumerate(content.tables):
        table_str = f"\nТаблица {i + 1}"
        if table.sheet_name:
            table_str += f" (лист: {table.sheet_name})"
        table_str += ":\n"

        if table.headers:
            table_str += "| " + " | ".join(str(h) for h in table.headers) + " |\n"
            table_str += "| " + " | ".join(["---"] * len(table.headers)) + " |\n"

        for row in table.rows[:50]:
            table_str += "| " + " | ".join(str(cell) for cell in row) + " |\n"

        if len(table.rows) > 50:
            table_str += f"... ещё {len(table.rows) - 50} строк\n"

        parts.append(table_str)

    return "\n".join(parts) if parts else "(пустой файл)"


def _extract_filename_from_text(text: str, role: str) -> Optional[str]:
    text_lower = text.lower()
    role_dir = get_role_files_dir(role)

    if not role_dir.exists():
        return None

    best_match = None
    best_match_len = 0

    for filepath in role_dir.iterdir():
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
        return best_match

    xlsx_match = re.search(r'(\S+\.xlsx?)', text, re.I)
    if xlsx_match:
        potential_name = xlsx_match.group(1)
        for filepath in role_dir.iterdir():
            if filepath.suffix.lower() in ['.xlsx', '.xls']:
                if potential_name.lower() in filepath.name.lower():
                    return filepath.name

    return None


def _is_complex_edit_command(text: str) -> bool:
    complex_patterns = [
        r"удали.*все", r"удали.*выполнен", r"удали.*невыполнен",
        r"удали.*где", r"удали.*которые", r"измени.*все",
        r"замени.*все", r"пересчитай", r"обнови.*итог",
    ]
    text_lower = text.lower()
    for pattern in complex_patterns:
        if re.search(pattern, text_lower):
            return True
    return False


async def route_message(messages: list, role: str):
    last_user_msg = messages[-1]["content"]
    state = memory.get_state(role) or {}

    logger.info(f"Router: '{last_user_msg[:50]}...'")

    if state.get("awaiting_file_choice"):
        if state.get("awaiting_excel_choice"):
            from tools.excel_tool import select_excel_file
            chosen_text = select_excel_file(role, last_user_msg)
            state["awaiting_file_choice"] = False
            state["awaiting_excel_choice"] = False
            memory.set_state(role, state)
            return chosen_text, messages
        else:
            chosen_text = select_file(role, last_user_msg)
            state["awaiting_file_choice"] = False
            memory.set_state(role, state)
            return chosen_text, messages

    if state.get("awaiting_file_for_edit"):
        operations = state.get("pending_operations", [])
        filename = _extract_filename_from_text(last_user_msg, role)

        if filename:
            result = edit_excel(filename, operations, role=role)
            state["awaiting_file_for_edit"] = False
            state["pending_operations"] = None
            memory.set_state(role, state)

            if result.get("success"):
                return f"Готово! Скачать: {result['download_url']}", messages
            else:
                return f"Ошибка: {result.get('error')}", messages
        else:
            return "Файл не найден. Укажите точное имя файла.", messages

    json_data = parse_llm_json(last_user_msg)
    if json_data and "sheets" in json_data:
        pending = state.get("pending_template_build", {})

        result = build_from_json(
            json_data,
            template_name=pending.get("template"),
            role=role
        )

        state["pending_template_build"] = None
        memory.set_state(role, state)

        if result.get("success"):
            response = f"✅ Файл создан: {result['filename']}\n"
            response += f"📊 Листов: {result.get('sheets_count', 0)}, "
            response += f"Строк: {result.get('rows_count', 0)}\n"
            response += f"🔗 Скачать: {result['download_url']}"
            return response, messages
        else:
            return f"❌ Ошибка создания файла: {result.get('error')}", messages

    if _is_template_command(last_user_msg) or _is_generate_command(last_user_msg):
        logger.info("Router: команда генерации по шаблону")

        if re.search(r'покажи\s+примеры|список\s+примеров|что\s+есть\s+в\s+examples|шаблоны|список шаблонов',
                     last_user_msg, re.I):
            examples = get_example_files()
            role_dir = STORAGE_DIR / role
            role_files = []
            if role_dir.exists():
                role_files = [
                    {"name": f.name, "type": f.suffix}
                    for f in role_dir.iterdir()
                    if f.suffix.lower() in ['.xlsx', '.xls', '.docx']
                ]

            response = "📁 Доступные файлы:\n\n"
            if examples:
                response += "**Шаблоны (examples):**\n"
                response += "\n".join([f"- {e['name']}" for e in examples])
                response += "\n\n"
            if role_files:
                response += "**Ваши файлы:**\n"
                response += "\n".join([f"- {f['name']}" for f in role_files])

            return response, messages

        template_name = _extract_template_name(last_user_msg, role)
        source_files = _extract_source_files(last_user_msg, role, exclude=template_name)
        output_format, output_name = _extract_output_params(last_user_msg)

        if not output_name:
            output_name = "generated"

        logger.info(f"Template: {template_name}, Sources: {source_files}, Format: {output_format}")

        if not template_name and not source_files:
            role_dir = STORAGE_DIR / role
            available = []
            if role_dir.exists():
                available = [f.name for f in role_dir.iterdir()
                             if f.suffix.lower() in ['.xlsx', '.xls', '.docx', '.pdf']]

            if available:
                files_list = "\n".join([f"- {f}" for f in available[:15]])
                return f"Укажите шаблон и файлы-источники данных.\n\n📁 Доступные файлы:\n{files_list}\n\n💡 Пример: 'Создай по шаблону template.xlsx из data.xlsx'", messages
            else:
                return "Файлы не найдены. Загрузите шаблон и файлы с данными.", messages

        if template_name:
            template_path = find_file(template_name, role)
            if not template_path:
                return f"❌ Шаблон не найден: {template_name}", messages

            try:
                schema = analyze_template(template_path)
                schema_text = format_schema_for_llm(schema)
            except Exception as e:
                logger.error(f"Template analysis error: {e}")
                return f"❌ Ошибка анализа шаблона: {e}", messages

            if source_files:
                source_contents = read_multiple_files(source_files, role)
                if not source_contents:
                    return "❌ Не удалось прочитать файлы-источники", messages

                mappings = map_multiple_sources(schema, source_contents)
                mapping_context = format_mapping_for_llm(schema, mappings)

                context = f"""ЗАДАЧА: Создать файл по структуре шаблона, используя данные из источников.

{schema_text}

{mapping_context}

ВАЖНО:
1. Структура ТОЧНО соответствует шаблону (те же колонки в том же порядке)
2. Данные берутся из источников и маппятся на колонки шаблона
3. Если в источнике нет данных для колонки - оставь пустым
4. Сохрани типы данных (числа как числа, текст как текст)
5. Порядок колонок: {schema.get_column_names()}

Верни ТОЛЬКО JSON без пояснений."""
            else:
                template_content = extract_content(template_path)
                template_preview = _format_content_for_llm(template_content)

                context = f"""ЗАДАЧА: Создать ПУСТОЙ файл по структуре шаблона.

{schema_text}

СОДЕРЖИМОЕ ШАБЛОНА:
{template_preview}

Верни JSON с пустой структурой (только заголовки, без данных):
```json
{{
  "output_format": "{output_format}",
  "output_name": "{output_name}",
  "sheets": [
    {{
      "name": "{schema.sheet_name or 'Лист1'}",
      "headers": {schema.get_column_names()},
      "rows": []
    }}
  ]
}}
```"""

            messages.append({"role": "user", "content": context})

            state["pending_template_build"] = {
                "template": template_name,
                "sources": source_files,
                "output_format": output_format,
                "output_name": output_name
            }
            memory.set_state(role, state)

            return None, messages

        elif source_files:
            source_contents = read_multiple_files(source_files, role)
            if not source_contents:
                return "❌ Не удалось прочитать файлы", messages

            sources_preview = "\n\n---\n\n".join([
                f"ФАЙЛ: {c.filename}\n{_format_content_for_llm(c)}"
                for c in source_contents
            ])

            context = f"""ЗАДАЧА: Объединить данные из файлов в один {output_format}.

ИСТОЧНИКИ:
{sources_preview}

Создай JSON для объединённого файла:
```json
{{
  "output_format": "{output_format}",
  "output_name": "{output_name}",
  "title": "Объединённые данные",
  "sheets": [
    {{
      "name": "Данные",
      "headers": [...колонки из источников...],
      "rows": [...все строки данных...]
    }}
  ]
}}
```"""

            messages.append({"role": "user", "content": context})

            state["pending_template_build"] = {
                "sources": source_files,
                "output_format": output_format,
                "output_name": output_name
            }
            memory.set_state(role, state)

            return None, messages

    if _is_edit_command(last_user_msg):
        logger.info("Router: команда редактирования")
        filename = _extract_filename_from_text(last_user_msg, role)

        if not filename:
            results = smart_search(last_user_msg, role, limit=5)
            excel_files = [r for r in results if r.get("is_table")]

            if len(excel_files) == 1:
                filename = excel_files[0]["filename"]
            elif len(excel_files) > 1:
                files_list = "\n".join([f"- {f['filename']}" for f in excel_files])
                return f"Найдено несколько файлов:\n{files_list}\n\nУкажите какой файл редактировать.", messages

        if not filename:
            role_dir = get_role_files_dir(role)
            all_excel = []
            if role_dir.exists():
                all_excel = [f.name for f in role_dir.iterdir()
                             if f.suffix.lower() in ['.xlsx', '.xls']]
            if all_excel:
                files_list = "\n".join([f"- {f}" for f in all_excel[:10]])
                return f"Не удалось определить файл. Доступные файлы:\n{files_list}", messages
            else:
                return "Excel файлы не найдены.", messages

        if _is_complex_edit_command(last_user_msg):
            file_content = read_excel_for_edit(filename, role=role)

            context = f"""Файл: {filename}

ВАЖНО: Колонка ROW содержит РЕАЛЬНЫЕ номера строк Excel. Используй именно эти номера!

Содержимое:
{file_content}

---
Инструкция: {last_user_msg}

Сгенерируй JSON:
```json
{{
  "filename": "{filename}",
  "operations": [
    {{"action": "delete_row", "row": N}},
    ...
  ]
}}
```

Операции: delete_row, edit_cell (row, col, value), add_row (data, after_row)
Удаляй строки от большего номера к меньшему!"""

            messages.append({"role": "user", "content": context})
            return None, messages

        _, operations = parse_excel_command(last_user_msg)

        if operations:
            result = edit_excel(filename, operations, role=role)
            if result.get("success"):
                return f"Выполнено!\n\nСкачать: {result['download_url']}", messages
            else:
                return f"Ошибка: {result.get('error')}", messages
        else:
            file_content = read_excel_for_edit(filename, role=role)

            context = f"""Файл: {filename}

ВАЖНО: Колонка ROW содержит РЕАЛЬНЫЕ номера строк Excel.

Содержимое:
{file_content}

---
Инструкция: {last_user_msg}

Сгенерируй JSON с операциями."""

            messages.append({"role": "user", "content": context})
            return None, messages

    if re.search(r"(найди|поиск|найди в файлах|search)\s+\w", last_user_msg, re.I):
        query = re.sub(r"(найди|поиск|найди в файлах|search)\s*", "", last_user_msg, flags=re.I).strip()
        if query:
            result = perform_search(query, role)
            return result, messages

    if re.search(r"(запомни|сохрани факт|добавь в память)", last_user_msg, re.I):
        fact = re.sub(r"(запомни|сохрани факт|добавь в память)\s*", "", last_user_msg, flags=re.I).strip()
        if fact and vector_store.is_connected():
            result = vector_store.add_memory(fact, "general", role)
            return result.get("message", "Ошибка"), messages

    if re.search(r"(сводка|сводку|обзор|summary).*(файл|документ|всех)", last_user_msg, re.I):
        result = await process_multiple_files(last_user_msg, role, top_n=20)
        return result, messages

    if re.search(r"(сравни|сравнение|compare)", last_user_msg, re.I):
        result = await process_multiple_files(last_user_msg, role, top_n=10)
        return result, messages

    edit_match = re.search(
        r'```json\s*(\{[\s\S]*?"operations"[\s\S]*?\})\s*```',
        last_user_msg, re.I
    )
    if edit_match:
        try:
            edit_data = json.loads(edit_match.group(1))
            filename = edit_data.get("filename")
            operations = edit_data.get("operations", [])

            if filename and operations:
                result = edit_excel(filename, operations, role=role)
                if result.get("success"):
                    return f"Файл отредактирован!\n\nСкачать: {result['download_url']}", messages
                else:
                    return f"Ошибка: {result.get('error')}", messages
        except json.JSONDecodeError:
            pass

    if any(ext in last_user_msg.lower() for ext in [".xlsx", ".xls"]):
        filename = _extract_filename_from_text(last_user_msg, role)
        if filename:
            content = read_excel(filename, role=role)
            return content, messages

    file_result = try_handle_file_command(last_user_msg, role)
    if file_result:
        return file_result, messages

    return None, messages