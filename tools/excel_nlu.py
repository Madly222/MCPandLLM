import re
from typing import List, Dict, Any, Optional, Tuple


def parse_excel_command(command: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Преобразует команду на естественном языке в операции Excel.

    Возвращает: (filename или None, список операций)

    Примеры команд:
    - "Добавь колонку 'работ - тех обслуживание'"
    - "Добавь строку со значениями 312, 400, 450"
    - "Измени ячейку B2 на 500"
    - "В файле смета.xlsx добавь строку: кабель, 100м, 500 лей"
    - "Удали строку 15 в MICB_40лет.xlsx"
    - "Удали строки 10, 12, 15"
    - "Удали строки 10-15"
    """
    ops: List[Dict[str, Any]] = []

    filename = _extract_filename(command)

    _parse_add_column(command, ops)
    _parse_add_row(command, ops)
    _parse_edit_cell(command, ops)
    _parse_delete_row(command, ops)
    _parse_delete_column(command, ops)

    return filename, ops

def _extract_filename(command: str) -> Optional[str]:
    """
    Пытается вытащить имя файла из команды.
    Оставляем поведение совместимым с исходной версией, но чистим regex'ы.
    """
    patterns = [
        r"в файл[ае]?\s+['\"]?([^'\"\s]+\.xlsx?)['\"]?",
        r"файл\s+['\"]?([^'\"\s]+\.xlsx?)['\"]?",
        r"таблиц[аеуы]\s+['\"]?([^'\"\s]+\.xlsx?)['\"]?",
        r"смет[аеуы]\s+([^\s,]+)",
        r"([A-Za-z0-9_\-]+\.xlsx?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            if not filename.lower().endswith((".xlsx", ".xls")):
                filename += ".xlsx"
            return filename

    return None

def _try_parse_number(token: str) -> Any:
    """
    Пробует превратить строку в число.
    Поддерживает:
    - "10" → 10
    - "10.5" → 10.5
    - "10,5" → 10.5
    """
    token = token.strip().strip('"\'')
    if not token:
        return token

    if "," in token and "." not in token:
        candidate = token.replace(",", ".")
    else:
        candidate = token

    try:
        if "." in candidate:
            return float(candidate)
        return int(candidate)
    except ValueError:
        return token


def _parse_values(values_str: str) -> List[Any]:
    """
    Разбор списка значений в команде типа:
    - "312, 400, 450"
    - "кабель, 100м, 500"
    """
    values_str = re.sub(r"после строки \d+", "", values_str, flags=re.IGNORECASE).strip()

    if "," in values_str:
        parts = [p.strip() for p in values_str.split(",")]
    elif ";" in values_str:
        parts = [p.strip() for p in values_str.split(";")]
    else:
        parts = values_str.split()

    result: List[Any] = []
    for p in parts:
        if not p:
            continue
        result.append(_try_parse_number(p))

    return result

def _parse_add_column(command: str, ops: List[Dict[str, Any]]) -> bool:
    """
    Находит все фразы вида:
    - "добавь колонку 'Имя'"
    - "новая колонка 'Имя'"
    - "создай колонку Имя"
    - синоним 'столбец'
    """
    patterns = [
        r"добавь колонку ['\"](.+?)['\"]",
        r"добавь колонку ([^.,\n]+)",
        r"новая колонка ['\"](.+?)['\"]",
        r"создай колонку ['\"](.+?)['\"]",
        r"добавь столбец ['\"](.+?)['\"]",
        r"добавь столбец ([^.,\n]+)",
    ]

    found = False

    for pattern in patterns:
        for match in re.finditer(pattern, command, re.IGNORECASE):
            header = match.group(1).strip()

            after_match = re.search(
                r"после колонк[иуы]\s+(\d+|[A-Z])",
                command,
                re.IGNORECASE,
            )
            after_col = None
            if after_match:
                col = after_match.group(1)
                if col.isdigit():
                    after_col = int(col)
                else:
                    after_col = ord(col.upper()) - ord("A") + 1

            op: Dict[str, Any] = {"action": "add_column", "header": header}
            if after_col:
                op["after_col"] = after_col

            ops.append(op)
            found = True

    return found

def _parse_add_row(command: str, ops: List[Dict[str, Any]]) -> bool:
    """
    Поддерживаем варианты:
    - "добавь строку: a, b, c"
    - "добавь строку со значениями: a, b, c после строки 10"
    - "новая строка: a, b, c"
    - "вставь строку: a, b, c"
    - "добавь строку после строки 10: a, b, c"
    """
    found = False

    patterns = [
        r"добавь строку(?: со значениями)?[:\s]+(.+?)(?:после строки (\d+))?(?:[.!?]|$)",
        r"новая строка[:\s]+(.+?)(?:после строки (\d+))?(?:[.!?]|$)",
        r"вставь строку[:\s]+(.+?)(?:после строки (\d+))?(?:[.!?]|$)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, command, re.IGNORECASE):
            values_str = match.group(1).strip()
            after_row = int(match.group(2)) if match.group(2) else None
            values = _parse_values(values_str)

            op: Dict[str, Any] = {"action": "add_row", "data": values}
            if after_row:
                op["after_row"] = after_row
            ops.append(op)
            found = True

    simple_match = re.search(
        r"добавь строку .*?значениями[:\s]*([\d,;\s]+)",
        command,
        re.IGNORECASE,
    )
    if simple_match:
        values = [v.strip() for v in re.split(r"[,\s;]+", simple_match.group(1).strip()) if v]
        ops.append({"action": "add_row", "data": [_try_parse_number(v) for v in values]})
        found = True

    return found

def _parse_edit_cell(command: str, ops: List[Dict[str, Any]]) -> bool:
    """
    Примеры:
    - "измени ячейку B2 на 500"
    - "поменяй ячейку C10 на 'текст'"
    - "в ячейке D5 запиши 123"
    """
    patterns = [
        r"измени ячейку ([A-Z])(\d+) на (.+)",
        r"поменяй ячейку ([A-Z])(\d+) на (.+)",
        r"установи ячейку ([A-Z])(\d+) (?:на |в )(.+)",
        r"в ячейк[аеуы] ([A-Z])(\d+) (?:запиши|поставь|установи) (.+)",
    ]

    found = False

    for pattern in patterns:
        for match in re.finditer(pattern, command, re.IGNORECASE):
            col = match.group(1).upper()
            row = int(match.group(2))
            raw_value = match.group(3).strip().strip('"\'')
            value = _try_parse_number(raw_value)

            ops.append(
                {
                    "action": "edit_cell",
                    "row": row,
                    "col": col,
                    "value": value,
                }
            )
            found = True

    return found

def _parse_delete_row(command: str, ops: List[Dict[str, Any]]) -> bool:
    """
    Поддерживаем:
    - "удали строку 5"
    - "убери строку 5"
    - "удали строки 5, 7, 10"
    - "удали строки 5-10"
    """
    found = False

    multi_pattern = r"(удали|убери)\s+строк[уыи]\s+([\d,\s\-]+)"
    for match in re.finditer(multi_pattern, command, re.IGNORECASE):
        raw = match.group(2)
        parts = [p.strip() for p in raw.replace(" ", "").split(",") if p.strip()]
        rows: List[int] = []

        for part in parts:
            if "-" in part:
                try:
                    start_str, end_str = part.split("-", 1)
                    start = int(start_str)
                    end = int(end_str)
                    if start <= end:
                        rows.extend(list(range(start, end + 1)))
                    else:
                        rows.extend(list(range(end, start + 1)))
                except ValueError:
                    continue
            else:
                try:
                    rows.append(int(part))
                except ValueError:
                    continue

        for r in sorted(set(rows), reverse=True):
            ops.append({"action": "delete_row", "row": r})
        if rows:
            found = True

    single_patterns = [
        r"удали строку (\d+)",
        r"убери строку (\d+)",
        r"удалить строку (\d+)",
    ]

    for pattern in single_patterns:
        for match in re.finditer(pattern, command, re.IGNORECASE):
            row = int(match.group(1))
            ops.append({"action": "delete_row", "row": row})
            found = True

    return found

def _parse_delete_column(command: str, ops: List[Dict[str, Any]]) -> bool:
    """
    Поддерживаем:
    - "удали колонку 3"
    - "удали колонку C"
    - "удали колонки B, D"
    (последнее превращаем просто в несколько delete_column)
    """
    found = False

    multi_pattern = r"(удали|убери)\s+колонк[уыи]\s+([A-Z0-9,\s]+)"
    for match in re.finditer(multi_pattern, command, re.IGNORECASE):
        raw = match.group(2)
        parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
        for part in parts:
            col: Any = part
            if col.isdigit():
                col = int(col)
            ops.append({"action": "delete_column", "col": col})
            found = True

    single_patterns = [
        r"удали колонку (\d+|[A-Z])",
        r"убери колонку (\d+|[A-Z])",
    ]

    for pattern in single_patterns:
        for match in re.finditer(pattern, command, re.IGNORECASE):
            col: Any = match.group(1).upper()
            if col.isdigit():
                col = int(col)
            ops.append({"action": "delete_column", "col": col})
            found = True

    return found

def format_operations_for_llm(filename: str, ops: List[Dict[str, Any]]) -> str:
    """Форматирует операции в JSON для LLM (как и раньше)."""
    import json

    return f"""```json
{{
  "filename": "{filename}",
  "operations": {json.dumps(ops, ensure_ascii=False, indent=4)}
}}
```"""