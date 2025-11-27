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
    """
    ops = []
    filename = None

    filename = _extract_filename(command)

    if _parse_add_column(command, ops):
        pass

    if _parse_add_row(command, ops):
        pass

    if _parse_edit_cell(command, ops):
        pass

    if _parse_delete_row(command, ops):
        pass

    if _parse_delete_column(command, ops):
        pass

    return filename, ops


def _extract_filename(command: str) -> Optional[str]:
    patterns = [
        r"в файл[ае]?\s+['\"]?([^'\"]+\.xlsx?)['\"]?",
        r"файл\s+['\"]?([^'\"]+\.xlsx?)['\"]?",
        r"таблиц[ау|е|у]\s+['\"]?([^'\"]+\.xlsx?)['\"]?",
        r"смет[ау|е|у]\s+([^\s,]+)",
        r"([A-Za-z0-9_\-]+\.xlsx?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, command, re.I)
        if match:
            filename = match.group(1).strip()
            if not filename.endswith(('.xlsx', '.xls')):
                filename += '.xlsx'
            return filename

    return None


def _parse_add_column(command: str, ops: List[Dict]) -> bool:
    patterns = [
        r"добавь колонку ['\"](.+?)['\"]",
        r"добавь колонку (\S+)",
        r"новая колонка ['\"](.+?)['\"]",
        r"создай колонку ['\"](.+?)['\"]",
    ]

    for pattern in patterns:
        match = re.search(pattern, command, re.I)
        if match:
            header = match.group(1).strip()

            after_match = re.search(r"после колонки (\d+|[A-Z])", command, re.I)
            after_col = None
            if after_match:
                col = after_match.group(1)
                if col.isdigit():
                    after_col = int(col)
                else:
                    after_col = ord(col.upper()) - ord('A') + 1

            op = {"action": "add_column", "header": header}
            if after_col:
                op["after_col"] = after_col
            ops.append(op)
            return True

    return False


def _parse_add_row(command: str, ops: List[Dict]) -> bool:
    patterns = [
        r"добавь строку[:\s]+(.+?)(?:после строки (\d+))?$",
        r"добавь строку со значениями[:\s]+(.+?)(?:после строки (\d+))?$",
        r"новая строка[:\s]+(.+?)(?:после строки (\d+))?$",
        r"вставь строку[:\s]+(.+?)(?:после строки (\d+))?$",
    ]

    for pattern in patterns:
        match = re.search(pattern, command, re.I)
        if match:
            values_str = match.group(1).strip()
            after_row = int(match.group(2)) if match.group(2) else None

            values = _parse_values(values_str)

            op = {"action": "add_row", "data": values}
            if after_row:
                op["after_row"] = after_row
            ops.append(op)
            return True

    simple_match = re.search(r"добавь строку .*?значениями[:\s]*([\d,;\s]+)", command, re.I)
    if simple_match:
        values = [v.strip() for v in re.split(r"[,\s;]+", simple_match.group(1).strip()) if v]
        ops.append({"action": "add_row", "data": values})
        return True

    return False


def _parse_values(values_str: str) -> List[Any]:
    values_str = re.sub(r"после строки \d+", "", values_str, flags=re.I).strip()

    if ',' in values_str:
        parts = [p.strip() for p in values_str.split(',')]
    elif ';' in values_str:
        parts = [p.strip() for p in values_str.split(';')]
    else:
        parts = values_str.split()

    result = []
    for p in parts:
        if not p:
            continue
        p = p.strip().strip('"\'')

        try:
            if '.' in p:
                result.append(float(p))
            else:
                result.append(int(p))
        except ValueError:
            result.append(p)

    return result


def _parse_edit_cell(command: str, ops: List[Dict]) -> bool:
    patterns = [
        r"измени ячейку ([A-Z])(\d+) на (.+)",
        r"поменяй ячейку ([A-Z])(\d+) на (.+)",
        r"установи ячейку ([A-Z])(\d+) (?:на |в )(.+)",
        r"в ячейк[ау|е] ([A-Z])(\d+) (?:запиши|поставь|установи) (.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, command, re.I)
        if match:
            col = match.group(1).upper()
            row = int(match.group(2))
            value = match.group(3).strip().strip('"\'')

            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass

            ops.append({
                "action": "edit_cell",
                "row": row,
                "col": col,
                "value": value
            })
            return True

    return False


def _parse_delete_row(command: str, ops: List[Dict]) -> bool:
    patterns = [
        r"удали строку (\d+)",
        r"убери строку (\d+)",
        r"удалить строку (\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, command, re.I)
        if match:
            row = int(match.group(1))
            ops.append({"action": "delete_row", "row": row})
            return True

    return False


def _parse_delete_column(command: str, ops: List[Dict]) -> bool:
    patterns = [
        r"удали колонку (\d+|[A-Z])",
        r"убери колонку (\d+|[A-Z])",
    ]

    for pattern in patterns:
        match = re.search(pattern, command, re.I)
        if match:
            col = match.group(1)
            if col.isdigit():
                col = int(col)
            ops.append({"action": "delete_column", "col": col})
            return True

    return False


def format_operations_for_llm(filename: str, ops: List[Dict]) -> str:
    """Форматирует операции в JSON для LLM"""
    import json
    return f"""```json
{{
  "filename": "{filename}",
  "operations": {json.dumps(ops, ensure_ascii=False, indent=4)}
}}
```"""