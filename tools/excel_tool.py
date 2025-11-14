# tools/excel_tool.py
from typing import Optional
from openpyxl import load_workbook, Workbook
from agent.memory import memory
from tools.utils import BASE_FILES_DIR

def read_excel(filename: str) -> str:
    path = BASE_FILES_DIR / filename
    if not path.exists():
        return f"Файл '{filename}' не найден."
    try:
        wb = load_workbook(path)
        sheets_text = []
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            data = []
            for row in ws.iter_rows(values_only=True):
                data.append([str(cell) if cell is not None else "" for cell in row])
            sheets_text.append(f"Лист: {sheet}\n" + "\n".join([", ".join(r) for r in data]))
        return "\n\n".join(sheets_text)
    except Exception as e:
        return f"Ошибка при чтении Excel: {e}"

def write_excel(filename: str, sheet_name: str, data: list) -> str:
    path = BASE_FILES_DIR / filename
    if path.exists():
        wb = load_workbook(path)
    else:
        wb = Workbook()

    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        ws.delete_rows(1, ws.max_row)
    else:
        ws = wb.create_sheet(sheet_name)

    for row in data:
        ws.append(row)

    wb.save(path)
    return f"Файл '{filename}' успешно обновлён."

def select_excel_file(user_id: str, choice: str) -> Optional[str]:
    matched_files = memory.get_user_files(user_id)
    if not matched_files:
        return "Сначала выполните команду поиска Excel файла."
    try:
        index = int(choice.strip()) - 1
        if 0 <= index < len(matched_files):
            selected_file = matched_files[index]
            memory.clear_user_files(user_id)
            state = memory.get_state(user_id) or {}
            state["awaiting_excel_choice"] = False
            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return read_excel(selected_file.name)
    except Exception:
        pass
    return "Некорректный выбор файла. Введите номер из списка."