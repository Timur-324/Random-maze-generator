#!/usr/bin/env python3
"""Точка входа графического интерфейса (PyQt6).

Запуск::

    python gui.py
    python cli.py run --size 20 --seed 1 --mode 1 --gui

Вся логика лабиринтов лежит в пакете ``maze`` (стандартная библиотека, без
Qt), весь код окна — в пакете ``mazegui``. Единственная внешняя зависимость
проекта — PyQt6::

    pip install -r requirements.txt
"""

from __future__ import annotations

import sys


def main(**initial) -> int:
    """Открыть окно. Возвращает код выхода (3 — если PyQt6 не установлен)."""
    try:
        from mazegui.app import main as run
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        print(
            "Для GUI нужен PyQt6: pip install -r requirements.txt\n"
            f"Подробности: {exc}",
            file=sys.stderr,
        )
        return 3
    return run(**initial)


if __name__ == "__main__":
    sys.exit(main())
