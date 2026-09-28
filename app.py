"""Десктоп-приложение «Расчёт впускного коллектора ВАЗ 21124» (pywebview + Edge WebView2).

Интерфейс — ui/index.html, расчёты — calc.py. JS вызывает методы класса Api
через мост pywebview (window.pywebview.api.<метод>).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import webview

import calc

APP_NAME = "VAZ21124-IntakeCalc"
TITLE = "Расчёт впускного коллектора ВАЗ 21124"


def resource(rel: str) -> str:
    """Путь к ресурсу и из исходников, и из собранного PyInstaller-exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return str(base / rel)


def settings_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def _dialog(kind: str):
    ft = getattr(webview, "FileDialog", None)
    if ft is not None:
        return getattr(ft, kind)
    return {"SAVE": webview.SAVE_DIALOG, "OPEN": webview.OPEN_DIALOG}[kind]


def _first(path):
    if isinstance(path, (list, tuple)):
        return path[0] if path else None
    return path


class Api:
    def __init__(self) -> None:
        self._window: webview.Window | None = None

    # --- расчёт
    def compute(self, params: dict) -> dict:
        return calc.compute(params)

    def defaults(self) -> dict:
        return dict(calc.DEFAULTS)

    def version(self) -> str:
        return calc.__version__

    # --- автосохранение последних параметров
    def load_settings(self) -> dict:
        try:
            return json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_settings(self, params: dict) -> bool:
        try:
            settings_path().write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except OSError:
            return False

    # --- файлы
    def export_report(self, params: dict) -> str | None:
        if self._window is None:
            return None
        path = _first(self._window.create_file_dialog(
            _dialog("SAVE"), save_filename="intake_report.txt", file_types=("Текст (*.txt)",)))
        if not path:
            return None
        Path(path).write_text(calc.report(calc.compute(params)), encoding="utf-8")
        return str(path)

    def save_config(self, params: dict) -> str | None:
        if self._window is None:
            return None
        path = _first(self._window.create_file_dialog(
            _dialog("SAVE"), save_filename="intake_config.json", file_types=("Конфигурация (*.json)",)))
        if not path:
            return None
        data = {"app": APP_NAME, "version": calc.__version__, "params": calc.normalize(params)}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def open_config(self) -> dict | None:
        if self._window is None:
            return None
        path = _first(self._window.create_file_dialog(
            _dialog("OPEN"), file_types=("Конфигурация (*.json)",)))
        if not path:
            return None
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return calc.normalize(data.get("params", data))


def main() -> None:
    api = Api()
    api._window = webview.create_window(
        TITLE,
        url=resource("ui/index.html"),
        js_api=api,
        width=1440,
        height=920,
        min_size=(1100, 720),
        background_color="#07090f",
    )
    webview.start()


if __name__ == "__main__":
    main()
