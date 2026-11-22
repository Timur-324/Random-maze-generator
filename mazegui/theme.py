"""Тёмная нейтральная тема: палитра, шрифты и QSS.

Цвета подобраны так, чтобы состояние лабиринта читалось сразу и не только
по оттенку (важно для дальтонизма):

* стены — светлые тонкие линии на тёмном полу: структура видна и на 10x10,
  и на 100x100;
* «посещённые» — синий градиент по порядку посещения (раньше темнее, позже
  светлее), поэтому видна волна BFS и «луч» A*;
* frontier — оранжевый, путь — малиновый, старт — зелёный круг с «S»,
  финиш — красный круг с «F», заблокированные — красно-серая штриховка;
* у старта, финиша и пути разная форма (круг с буквой против толстой линии),
  поэтому они различимы и в градациях серого.
"""

from PyQt6.QtGui import QColor, QFont

#: Основные цвета интерфейса.
COLORS = {
    "window": "#0f1319",
    "panel": "#161c25",
    "panel_alt": "#1b2330",
    "border": "#2a3543",
    "text": "#e8eef7",
    "text_dim": "#93a3b8",
    "accent": "#4aa8ff",
    "canvas_bg": "#080b10",
    "floor": "#243040",
    "closed": "#0d1420",
    "wall": "#e8f0f9",
    "wall_shadow": "#0a1017",
    "frontier": "#ffb020",
    "visited_dark": "#1d4d78",
    "visited_light": "#7cd2f5",
    "path": "#ff2d78",
    "path_halo": "#17040b",
    "start": "#25d366",
    "end": "#ff4d4d",
    "blocked": "#6d2f3f",
    "blocked_line": "#e79fb1",
    "ok": "#25d366",
    "warn": "#ffb020",
    "error": "#ff5a5a",
}

#: Цвет «посещённой» клетки по порядку раскрытия: 0 — только что раскрыта.
def visited_color(progress: float) -> QColor:
    """Градиент посещённых клеток: 0 — тёмно-синий, 1 — светло-голубой."""
    t = 0.0 if progress < 0.0 else (1.0 if progress > 1.0 else progress)
    dark = QColor(COLORS["visited_dark"])
    light = QColor(COLORS["visited_light"])
    return QColor(
        round(dark.red() + (light.red() - dark.red()) * t),
        round(dark.green() + (light.green() - dark.green()) * t),
        round(dark.blue() + (light.blue() - dark.blue()) * t),
    )


def font(size: int, bold: bool = False) -> QFont:
    """Шрифт интерфейса с нужным кеглем."""
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    return f


#: Стили интерфейса. QSS поддерживает селекторы по свойству, поэтому
#: состояние бейджа и подсветку «лучшего» значения задаёт само приложение.
STYLESHEET = f"""
QWidget {{
    background: {COLORS['window']};
    color: {COLORS['text']};
    font-size: 13px;
}}
QGroupBox {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 6px 8px 6px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 2px 6px;
    color: {COLORS['text_dim']};
}}
QLabel {{ background: transparent; }}
QLabel[role="hint"] {{ color: {COLORS['text_dim']}; }}
QLabel[role="caption"] {{ color: {COLORS['text_dim']}; font-size: 11px; }}
QLabel[role="value"] {{ font-size: 22px; font-weight: 700; }}
QLabel[role="paneTitle"] {{ font-size: 15px; font-weight: 700; }}
QLabel[role="paneStats"] {{ color: {COLORS['text_dim']}; font-size: 12px; }}
QLabel[role="status"] {{
    font-size: 16px; font-weight: 700; padding: 8px 10px;
    border-radius: 6px; background: {COLORS['panel_alt']};
    border: 1px solid {COLORS['border']};
}}
QLabel[state="ok"] {{ color: {COLORS['ok']}; }}
QLabel[state="warn"] {{ color: {COLORS['warn']}; }}
QLabel[state="error"] {{ color: {COLORS['error']}; }}
QLabel[state="idle"] {{ color: {COLORS['text']}; }}
QLabel[best="true"] {{ color: {COLORS['ok']}; }}
QLabel[role="valueSmall"] {{ font-size: 16px; font-weight: 700; }}
QLabel[role="rowLabel"] {{ color: {COLORS['text_dim']}; font-size: 12px; }}
QLabel[role="ratio"] {{ font-size: 15px; font-weight: 700; }}
QPushButton {{
    background: {COLORS['panel_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 7px 10px;
    min-height: 22px;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {COLORS['accent']}; }}
QPushButton:pressed {{ background: #232f3f; }}
QPushButton:disabled {{ color: #5d6a7a; border-color: #222b36; }}
QPushButton[accent="true"] {{
    background: #1d4ed8; border-color: #2f6bff;
}}
QPushButton[accent="true"]:hover {{ background: #2563eb; }}
QComboBox, QSpinBox, QLineEdit {{
    background: {COLORS['panel_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 4px 6px;
    min-height: 20px;
}}
QComboBox QAbstractItemView {{
    background: {COLORS['panel_alt']};
    selection-background-color: {COLORS['accent']};
}}
QRadioButton {{ spacing: 6px; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled,
QRadioButton:disabled, QLabel:disabled {{ color: #5d6a7a; }}
QSlider::groove:horizontal {{
    height: 6px; background: {COLORS['panel_alt']};
    border: 1px solid {COLORS['border']}; border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 16px; margin: -6px 0; border-radius: 8px;
    background: {COLORS['accent']};
}}
QProgressBar {{
    background: {COLORS['panel_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    text-align: center;
    color: {COLORS['text']};
    height: 18px;
}}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 5px; }}
QStatusBar {{ background: {COLORS['panel']}; border-top: 1px solid {COLORS['border']}; }}
QToolTip {{
    background: {COLORS['panel_alt']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['accent']};
    padding: 4px;
}}
"""
