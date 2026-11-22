"""Сценарии для скриншотов и замеров: ``python -m mazegui.shots``.

Скрипт создаёт окно в offscreen-режиме, доводит его до нужного состояния
(генерация, поиск, пауза посреди анимации) и сохраняет `widget.grab()` в
PNG. Те же функции использует набор тестов, поэтому «то, что на скриншоте»
и «то, что проверяется» — один и тот же код.

Запуск::

    QT_QPA_PLATFORM=offscreen python -m mazegui.shots
    QT_QPA_PLATFORM=offscreen python -m mazegui.shots --out docs/screenshots
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from .app import MazeApp  # noqa: E402

WINDOW = (1400, 850)
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "docs", "screenshots")


# --------------------------------------------------------------------------
# Вспомогательные функции: прокрутка событий и ожидание состояния
# --------------------------------------------------------------------------
_APP: QApplication | None = None


def ensure_app() -> QApplication:
    """Один QApplication на процесс (иначе Qt падает при создании виджетов)."""
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv[:1])
    return _APP


def pump(times: int = 1) -> None:
    app = ensure_app()
    for _ in range(times):
        app.processEvents()


def new_window() -> MazeApp:
    app = MazeApp()
    app.resize(*WINDOW)
    app.show()
    pump(2)
    return app


#: Пачка при ускоренной прокрутке (скриншоты и тесты не ждут анимацию).
FAST_BATCH = 4000


def run_animation(app: MazeApp, share: float = 1.0) -> None:
    """Прокрутить анимацию до конца (или на долю ``share``)."""
    target = int(app._total_events * share)
    done = 0
    while app.tasks and done < target:
        step = min(max(1, app._batch()), FAST_BATCH)
        app._advance(step)
        done += step
        if done % (FAST_BATCH * 2) == 0:
            pump()


def wait_for(app: MazeApp, predicate, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        pump()
        if predicate():
            return True
        time.sleep(0.004)
    return False


def settle(app: MazeApp, timeout: float = 60.0) -> bool:
    """Дождаться полной тишины: ни воркеров, ни анимации, ни отложенных вызовов."""
    deadline = time.time() + timeout
    quiet_since = None
    while time.time() < deadline:
        pump()
        worker = getattr(app, "_worker", None)
        busy = (bool(app.tasks) or app._stage != "idle"
                or (worker is not None and worker.isRunning()))
        if busy:
            quiet_since = None
            if app.tasks:
                app._advance(min(max(1, app._batch()), FAST_BATCH))
            else:
                time.sleep(0.002)
            continue
        quiet_since = quiet_since or time.time()
        if time.time() - quiet_since >= 0.06:
            pump(3)
            return True
        time.sleep(0.01)
    return False


def select(app: MazeApp, size=None, generator=None, mode=None, trap=None,
           algorithm=None, seed=None) -> None:
    if size is not None:
        app.size_combo.setCurrentIndex(app.size_combo.findText(f"{size} × {size}"))
    if generator is not None:
        index = app.generator_combo.findData(generator)
        app.generator_combo.setCurrentIndex(index)
    if mode is not None:
        index = app.mode_combo.findData(mode)
        app.mode_combo.setCurrentIndex(index)
    if trap is not None:
        index = app.trap_combo.findData(trap)
        app.trap_combo.setCurrentIndex(index)
    if algorithm is not None:
        index = app.algo_combo.findData(algorithm)
        app.algo_combo.setCurrentIndex(index)
    if seed is not None:
        app.seed_edit.setCurrentText(str(seed))
    pump()


def generate(app: MazeApp) -> None:
    app.on_generate()
    settle(app)


def solve(app: MazeApp) -> None:
    app.on_solve()
    wait_for(app, lambda: app._stage in ("search", "idle"))
    if app.tasks:
        run_animation(app)
    settle(app)


# --------------------------------------------------------------------------
# Сценарии
# --------------------------------------------------------------------------
def shot_empty(app: MazeApp) -> None:
    """Пустое окно: только панели, без лабиринта."""


def shot_generated(app: MazeApp) -> None:
    select(app, size=10, generator="dfs", mode=1, algorithm="bfs", seed=12345)
    generate(app)


def shot_path_bfs(app: MazeApp) -> None:
    select(app, size=20, generator="dfs", mode=1, algorithm="bfs", seed=7)
    generate(app)
    solve(app)


def shot_mid_astar(app: MazeApp) -> None:
    select(app, size=50, generator="prim", mode=1, algorithm="astar", seed=11)
    generate(app)
    app.on_solve()
    wait_for(app, lambda: app._stage == "search")
    pump(2)
    run_animation(app, share=0.45)
    pump(3)


def shot_compare(app: MazeApp) -> None:
    select(app, size=50, generator="dfs", mode=1, algorithm="both", seed=3)
    generate(app)
    solve(app)


def shot_trap_3b(app: MazeApp) -> None:
    select(app, size=20, generator="dfs", mode=3, trap="b", seed=5)
    app.on_generate()
    settle(app)          # режим 3 сам запускает сравнение после генерации
    wait_for(app, lambda: bool(app.results))
    if app.tasks:
        run_animation(app)
    settle(app)


def shot_100(app: MazeApp) -> None:
    select(app, size=100, generator="dfs", mode=1, algorithm="astar", seed=2)
    generate(app)
    solve(app)


def shot_no_path(app: MazeApp) -> None:
    select(app, size=10, generator="dfs", mode=1, algorithm="both", seed=4)
    generate(app)
    for cell in app.maze.neighbors(app.maze.end):
        app.maze.block(cell)
    app.on_solve()
    wait_for(app, lambda: app._stage == "search")
    app._paint_blocked()
    if app.tasks:
        run_animation(app)
    settle(app)


SCENARIOS = (
    ("01-empty", shot_empty),
    ("02-generated-10x10", shot_generated),
    ("03-path-20x20-bfs", shot_path_bfs),
    ("04-mid-animation-50x50-astar", shot_mid_astar),
    ("05-compare-50x50", shot_compare),
    ("06-trap-3b-20x20", shot_trap_3b),
    ("07-path-100x100", shot_100),
    ("08-no-path-10x10", shot_no_path),
)


def capture(app: MazeApp, path: str) -> str:
    pump(2)
    pixmap = app.grab()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not pixmap.save(path):
        raise RuntimeError(f"не удалось сохранить {path}")
    return path


def make_all(outdir: str = DEFAULT_OUT, scenarios=SCENARIOS) -> list[str]:
    """Снять все сценарии; возвращает список путей к PNG."""
    ensure_app()
    saved = []
    for name, handler in scenarios:
        app = new_window()
        try:
            handler(app)
            saved.append(capture(app, os.path.join(outdir, f"{name}.png")))
        finally:
            app.close()
            app.deleteLater()
            pump(2)
    return saved


# --------------------------------------------------------------------------
# Замер плавности: сколько кадров в секунду реально рисуется
# --------------------------------------------------------------------------
def measure_fps(size: int = 100, seconds: float = 2.0,
                during: str = "generation") -> dict:
    """FPS и среднее время кадра для анимации ``size x size``.

    Считаются именно отрисованные кадры (`paintEvent`), а не тики таймера,
    поэтому число честное: если отрисовка не успевает, FPS падает.
    """
    app = new_window()
    try:
        select(app, size=size, generator="dfs", mode=1, algorithm="astar", seed=1)
        app.speed_slider.setValue(5)      # медленно: анимация длится дольше замера
        if during == "generation":
            app.on_generate()
        else:
            generate(app)
            app.on_solve()
            wait_for(app, lambda: app._stage == "search")
        canvas = app.panes[0].canvas
        canvas.reset_paint_stats()
        app.timer.start()
        started = time.perf_counter()
        while app.tasks and time.perf_counter() - started < seconds:
            pump()
            time.sleep(0.001)
        elapsed = time.perf_counter() - started
        frames, paint_ms = canvas.paint_stats()
        return {
            "size": size,
            "during": during,
            "seconds": round(elapsed, 3),
            "frames": frames,
            "fps": round(frames / elapsed, 1) if elapsed else 0.0,
            "frame_ms": round(paint_ms / frames, 2) if frames else 0.0,
        }
    finally:
        app.timer.stop()
        app.close()
        app.deleteLater()
        pump(2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Скриншоты и замеры GUI")
    parser.add_argument("--out", default=DEFAULT_OUT, help="каталог для PNG")
    parser.add_argument("--fps", action="store_true", help="только замер FPS")
    args = parser.parse_args(argv)
    ensure_app()
    if args.fps:
        for during in ("generation", "search"):
            print(measure_fps(100, during=during))
        return 0
    for path in make_all(args.out):
        print(path)
    print(measure_fps(100, during="generation"))
    print(measure_fps(100, during="search"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
