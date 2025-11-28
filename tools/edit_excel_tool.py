import os
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from copy import copy

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "storage"))
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", BASE_DIR / "downloads"))
SERVER_URL = os.getenv("SERVER_URL", "http://172.22.22.73:8000")

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _find_source_file(filename: str) -> Optional[Path]:
    for directory in [STORAGE_DIR, DOWNLOADS_DIR]:
        path = directory / filename
        if path.exists():
            logger.info(f"Найден файл: {path}")
            return path

    filename_clean = filename.lower().replace(' ', '').replace('(', '').replace(')', '')

    for directory in [STORAGE_DIR, DOWNLOADS_DIR]:
        if not directory.exists():
            continue
        for filepath in directory.iterdir():
            if filepath.suffix.lower() in ['.xlsx', '.xls']:
                name_clean = filepath.name.lower().replace(' ', '').replace('(', '').replace(')', '')
                if filename_clean == name_clean:
                    logger.info(f"Найден файл по fuzzy: {filepath}")
                    return filepath

                if filename_clean.replace('.xlsx', '').replace('.xls', '') in name_clean:
                    logger.info(f"Найден файл по частичному совпадению: {filepath}")
                    return filepath

    logger.error(f"Файл не найден: {filename}")
    logger.error(f"STORAGE_DIR: {STORAGE_DIR}, существует: {STORAGE_DIR.exists()}")
    if STORAGE_DIR.exists():
        logger.error(f"Файлы в storage: {[f.name for f in STORAGE_DIR.iterdir()]}")

    return None


def _generate_output_filename(original: str) -> str:
    stem = Path(original).stem
    suffix = Path(original).suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stem}_edited_{timestamp}{suffix}"


def _copy_cell_style(source_cell, target_cell):
    if source_cell.has_style:
        target_cell.font = copy(source_cell.font)
        target_cell.border = copy(source_cell.border)
        target_cell.fill = copy(source_cell.fill)
        target_cell.number_format = copy(source_cell.number_format)
        target_cell.protection = copy(source_cell.protection)
        target_cell.alignment = copy(source_cell.alignment)


def edit_excel(
        filename: str,
        operations: List[Dict[str, Any]],
        sheet_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Редактирует Excel файл безопасно, проверяя строки, колонки и существование директорий.
    """
    source_path = _find_source_file(filename)
    if not source_path:
        return {"success": False, "error": f"Файл {filename} не найден"}

    try:
        wb = load_workbook(source_path)
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active if not sheet_name else None
        if ws is None:
            return {"success": False, "error": f"Лист '{sheet_name}' не найден"}

        ops_applied = 0

        for op in operations:
            action = op.get("action", "").lower()

            if action == "add_row":
                data = op.get("data", [])
                after_row = op.get("after_row", ws.max_row)
                after_row = max(after_row, 0)
                ws.insert_rows(after_row + 1)
                for col_idx, value in enumerate(data, start=1):
                    cell = ws.cell(row=after_row + 1, column=col_idx, value=value)
                    if after_row > 0:
                        source_cell = ws.cell(row=after_row, column=col_idx)
                        _copy_cell_style(source_cell, cell)
                ops_applied += 1

            elif action == "edit_cell":
                row = op.get("row")
                col = op.get("col")
                value = op.get("value")
                if row is None or col is None:
                    logger.warning(f"Пропущены row/col для edit_cell: {op}")
                    continue
                if isinstance(col, str):
                    from openpyxl.utils import column_index_from_string
                    col = column_index_from_string(col)
                ws.cell(row=row, column=col, value=value)
                ops_applied += 1

            elif action == "delete_row":
                row = op.get("row")
                if row and row > 0:
                    ws.delete_rows(row)
                    ops_applied += 1

            elif action == "add_column":
                header = op.get("header", "")
                after_col = op.get("after_col", ws.max_column)
                after_col = max(after_col, 0)
                ws.insert_cols(after_col + 1)
                ws.cell(row=1, column=after_col + 1, value=header)
                ops_applied += 1

            elif action == "delete_column":
                col = op.get("col")
                if col is None:
                    logger.warning(f"Пропущен col для delete_column: {op}")
                    continue
                if isinstance(col, str):
                    from openpyxl.utils import column_index_from_string
                    col = column_index_from_string(col)
                ws.delete_cols(col)
                ops_applied += 1

            else:
                logger.warning(f"Неизвестная операция: {action}")

        # Генерация выходного файла
        if not DOWNLOADS_DIR.exists():
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

        output_filename = _generate_output_filename(filename)
        output_path = DOWNLOADS_DIR / output_filename
        wb.save(output_path)
        wb.close()

        download_url = f"{SERVER_URL}/download/{output_filename}"

        return {
            "success": True,
            "download_url": download_url,
            "filename": output_filename,
            "operations_applied": ops_applied
        }

    except Exception as e:
        logger.error(f"Ошибка редактирования {filename}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

def add_row_to_excel(
        filename: str,
        row_data: List[Any],
        after_row: Optional[int] = None,
        sheet_name: Optional[str] = None
) -> Dict[str, Any]:
    """Упрощённая функция добавления строки"""
    op = {"action": "add_row", "data": row_data}
    if after_row:
        op["after_row"] = after_row
    return edit_excel(filename, [op], sheet_name)


def edit_cell_in_excel(
        filename: str,
        row: int,
        col: Any,
        value: Any,
        sheet_name: Optional[str] = None
) -> Dict[str, Any]:
    """Упрощённая функция изменения ячейки"""
    return edit_excel(filename, [{"action": "edit_cell", "row": row, "col": col, "value": value}], sheet_name)


def delete_row_from_excel(
        filename: str,
        row: int,
        sheet_name: Optional[str] = None
) -> Dict[str, Any]:
    """Упрощённая функция удаления строки"""
    return edit_excel(filename, [{"action": "delete_row", "row": row}], sheet_name)


def get_excel_preview(filename: str, rows: int = 10, sheet_name: Optional[str] = None) -> Dict[str, Any]:
    """Получить превью таблицы для LLM"""
    source_path = _find_source_file(filename)
    if not source_path:
        return {"success": False, "error": f"Файл {filename} не найден"}

    try:
        wb = load_workbook(source_path, data_only=True)

        if sheet_name:
            ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
        else:
            ws = wb.active

        data = []
        for row_idx, row in enumerate(ws.iter_rows(max_row=rows + 1, values_only=True), start=1):
            row_data = [str(cell) if cell is not None else "" for cell in row]
            data.append({"row": row_idx, "values": row_data})

        wb.close()

        return {
            "success": True,
            "filename": filename,
            "sheet": ws.title,
            "total_rows": ws.max_row,
            "total_cols": ws.max_column,
            "preview": data
        }

    except Exception as e:
        return {"success": False, "error": str(e)}