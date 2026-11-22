"""Тесты GUI на PyQt6 в offscreen-режиме (без дисплея).

Окно действительно создаётся, кнопки нажимаются, анимация прокручивается до
конца, клик по холсту ставит старт/финиш, режим сравнения создаёт два холста.
Логика (``maze/*``) при этом не меняется — тестируется ровно то, что видит
пользователь.

Запуск::

    QT_QPA_PLATFORM=offscreen python -m unittest discover tests
"""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton, QSlider, QSpinBox

from mazegui import shots
from mazegui.app import MazeApp
from mazegui.canvas import MazeCanvas
from mazegui.legend import LegendWidget
from mazegui.theme import COLORS

_APP = None


def setUpModule():
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])
    else:
        _APP = QApplication.instance()
    # прогреваем стили, чтобы размеры виджетов были окончательными
    shots.pump(2)


def tearDownModule():
    global _APP
    _APP = None


def make_window() -> MazeApp:
    window = MazeApp()
    window.resize(*shots.WINDOW)
    window.show()
    shots.pump(3)
    return window


class WindowTestCase(unittest.TestCase):
    def setUp(self):
        self.window = make_window()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        shots.pump(2)


class TestWindow(WindowTestCase):
    def test_default_size_and_title(self):
        self.assertEqual(self.window.width(), 1400)
        self.assertEqual(self.window.height(), 850)
        self.assertIn("лабиринт", self.window.windowTitle().lower())
        self.assertTrue(self.window.minimumWidth() >= 1000)

    def test_resizable(self):
        self.window.resize(1200, 760)
        shots.pump(3)
        self.assertEqual(self.window.width(), 1200)
        self.assertEqual(self.window.height(), 760)

    def test_all_controls_have_tooltips(self):
        widgets = (self.window.findChildren(QPushButton)
                   + self.window.findChildren(QComboBox)
                   + self.window.findChildren(QSpinBox)
                   + self.window.findChildren(QSlider)
                   + self.window.findChildren(MazeCanvas))
        # внутренние редакторы QSpinBox/QComboBox подсказку наследуют от поля
        direct = [w for w in widgets
                  if not isinstance(w, QLineEdit)
                  or not isinstance(w.parent(), (QComboBox, QSpinBox))]
        self.assertGreater(len(direct), 15)
        without = [type(w).__name__ + ":" + (w.text() if hasattr(w, "text") else "")
                   for w in direct if not w.toolTip()]
        self.assertEqual(without, [], "у всех элементов управления должны быть подсказки")

    def test_legend_always_visible_and_complete(self):
        legend = self.window.findChild(LegendWidget)
        self.assertIsNotNone(legend)
        self.assertFalse(legend.isHidden())
        labels = [label for label, _key in LegendWidget.ITEMS]
        for required in ("стена", "проход", "frontier", "посещённые",
                         "путь", "старт", "финиш", "заблокировано"):
            self.assertIn(required, labels)
        self.assertGreater(legend.height(), 20)

    def test_empty_state_has_single_canvas_and_hint(self):
        self.assertEqual(len(self.window._visible_panes()), 1)
        self.assertIsNone(self.window.maze)
        self.assertIn("Сгенерировать", self.window.panes[0].canvas._empty_hint)


class TestGeneration(WindowTestCase):
    def test_generate_10x10(self):
        shots.select(self.window, size=10, algorithm="bfs", seed=12345)
        shots.generate(self.window)
        self.assertIsNotNone(self.window.maze)
        self.assertEqual(self.window.maze.width, 10)
        self.assertTrue(self.window.maze.is_perfect)
        self.assertIsNotNone(self.window.info)
        self.assertEqual(self.window.info.alternative_paths, 1)
        canvas = self.window.panes[0].canvas
        self.assertIs(canvas.maze, self.window.maze)
        # лабиринт занимает почти всё окно и клетки квадратные
        self.assertGreater(canvas.cell_pixel_size(), 40)
        self.assertIn("Готово", self.window.stats.badge.text())

    def test_generation_is_animated_to_the_end(self):
        shots.select(self.window, size=20, seed=5)
        self.window.on_generate()
        self.assertGreater(len(self.window.tasks), 0)
        self.assertEqual(self.window._stage, "generation")
        shots.settle(self.window)
        self.assertEqual(self.window.tasks, [])
        self.assertEqual(self.window.progress.value(), 100)
        self.assertEqual(self.window.progress_label.text(), "анимация: 100 %")

    def test_pause_and_step(self):
        shots.select(self.window, size=50, seed=1)
        self.window.speed_slider.setValue(0)   # медленно: по событию за шаг
        self.window.on_generate()
        self.window.timer.stop()               # тест сам двигает анимацию
        consumed = self.window._consumed
        self.window.on_step()                  # «Шаг» ставит паузу и двигает раз
        self.assertGreater(self.window._consumed, consumed)
        self.assertTrue(self.window._paused)
        consumed = self.window._consumed
        self.window._on_tick()                 # на паузе тик ничего не делает
        self.assertEqual(self.window._consumed, consumed)
        self.window.on_pause()                 # сняли паузу
        self.assertFalse(self.window._paused)
        self.window.timer.stop()
        self.window._on_tick()
        self.assertGreater(self.window._consumed, consumed)

    def test_all_generators_and_sizes(self):
        for size in (10, 20):
            for generator in ("dfs", "prim", "kruskal"):
                with self.subTest(size=size, generator=generator):
                    shots.select(self.window, size=size, generator=generator,
                                 seed=3)
                    shots.generate(self.window)
                    self.assertTrue(self.window.maze.is_perfect)
                    self.assertEqual(self.window.maze.carved, size * size - 1)


class TestSearch(WindowTestCase):
    def test_bfs_path_and_stats(self):
        shots.select(self.window, size=20, algorithm="bfs", seed=7)
        shots.generate(self.window)
        shots.solve(self.window)
        self.assertIn("bfs", self.window.results)
        result = self.window.results["bfs"]
        self.assertTrue(result.found)
        self.assertEqual(self.window.panes[0].canvas._path, result.path)
        self.assertIn(str(result.steps), self.window.stats.tile_value("steps"))
        self.assertIn(str(result.explored),
                      self.window.stats.tile_value("explored"))
        self.assertNotEqual(self.window.stats.tile_value("time"), "—")
        self.assertIn("путь найден", self.window.stats.badge.text())

    def test_compare_mode_has_two_canvases(self):
        shots.select(self.window, size=20, algorithm="both", seed=2)
        shots.generate(self.window)
        shots.solve(self.window)
        panes = self.window._visible_panes()
        self.assertEqual(len(panes), 2)
        self.assertEqual(set(self.window.results), {"bfs", "astar"})
        self.assertEqual(self.window.results["bfs"].steps,
                         self.window.results["astar"].steps)
        ratio_text = self.window.stats.ratio_label.text()
        self.assertIn("explored(A*)", ratio_text)
        ratio = (self.window.results["astar"].explored
                 / self.window.results["bfs"].explored)
        self.assertIn(f"{ratio:.3f}", ratio_text)
        # таблица сравнения заполнена и лучший результат подсвечен
        cells = self.window.stats._compare_cells
        self.assertEqual(cells[(2, 1)].text(), f"{self.window.results['bfs'].explored:,}".replace(",", " "))
        best = [key for key, label in cells.items() if label.property("best")]
        self.assertTrue(best)

    def test_mode3_trap_runs_both_algorithms(self):
        shots.select(self.window, size=20, mode=3, trap="b", seed=5)
        self.window.on_generate()
        shots.settle(self.window)
        self.assertEqual(self.window.info.mode, 3)
        self.assertEqual(self.window.info.trap, "b")
        self.assertEqual(set(self.window.results), {"bfs", "astar"})
        ratio = (self.window.results["astar"].explored
                 / self.window.results["bfs"].explored)
        self.assertGreaterEqual(ratio, 0.8)
        self.assertEqual(len(self.window._visible_panes()), 2)

    def test_mode3a_ratio_small(self):
        shots.select(self.window, size=20, mode=3, trap="a", seed=1)
        self.window.on_generate()
        shots.settle(self.window)
        ratio = (self.window.results["astar"].explored
                 / self.window.results["bfs"].explored)
        self.assertLessEqual(ratio, 0.3)

    def test_no_path_state(self):
        shots.select(self.window, size=10, algorithm="both", seed=4)
        shots.generate(self.window)
        for cell in self.window.maze.neighbors(self.window.maze.end):
            self.window.maze.block(cell)
        shots.solve(self.window)
        self.assertFalse(self.window.results["bfs"].found)
        self.assertIn("выхода нет", self.window.stats.badge.text())
        self.assertIsNone(self.window._current_path)


class TestMouseAndEndpoints(WindowTestCase):
    def cell_point(self, cell):
        canvas = self.window.panes[0].canvas
        return canvas.cell_rect(cell).center().toPoint()

    def test_click_sets_start_then_finish(self):
        shots.select(self.window, size=20, algorithm="bfs", seed=9)
        shots.generate(self.window)
        canvas = self.window.panes[0].canvas
        self.window.start_radio.setChecked(True)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, self.cell_point((4, 5)))
        self.assertEqual(tuple(self.window.maze.start), (4, 5))
        self.window.end_radio.setChecked(True)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, self.cell_point((11, 12)))
        self.assertEqual(tuple(self.window.maze.end), (11, 12))
        # координаты видны в полях
        self.assertEqual(self.window.start_x.value(), 4)
        self.assertEqual(self.window.start_y.value(), 5)
        self.assertEqual(self.window.end_x.value(), 11)
        self.assertEqual(self.window.end_y.value(), 12)
        # и путь ищется уже между новыми клетками
        shots.solve(self.window)
        result = self.window.results["bfs"]
        self.assertEqual(result.path[0], (4, 5))
        self.assertEqual(result.path[-1], (11, 12))

    def test_right_click_sets_opposite(self):
        shots.select(self.window, size=20, seed=3)
        shots.generate(self.window)
        canvas = self.window.panes[0].canvas
        self.window.start_radio.setChecked(True)
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton,
                         Qt.KeyboardModifier.NoModifier, self.cell_point((7, 7)))
        self.assertEqual(tuple(self.window.maze.end), (7, 7))

    def test_click_precision_100x100(self):
        shots.select(self.window, size=100, seed=1)
        shots.generate(self.window)
        canvas = self.window.panes[0].canvas
        for cell in ((0, 0), (99, 99), (37, 64), (50, 50), (99, 0)):
            with self.subTest(cell=cell):
                self.assertEqual(canvas.cell_at(self.cell_point(cell)), cell)

    def test_coordinates_fields_move_endpoints(self):
        shots.select(self.window, size=20, seed=3)
        shots.generate(self.window)
        self.window.start_x.setValue(2)
        self.window.start_y.setValue(3)
        self.assertEqual(tuple(self.window.maze.start), (2, 3))

    def test_hover_updates_status(self):
        shots.select(self.window, size=20, seed=3)
        shots.generate(self.window)
        canvas = self.window.panes[0].canvas
        QTest.mouseMove(canvas, self.cell_point((6, 7)))
        shots.pump(2)
        self.assertIn("(6, 7)", self.window.coords_label.text())


class TestBreakPathAndOptimize(WindowTestCase):
    def test_break_path_in_perfect_maze_kills_route(self):
        """В идеальном лабиринте блокировка клетки пути отрезает финиш."""
        shots.select(self.window, size=12, algorithm="bfs", seed=2, mode=1)
        shots.generate(self.window)
        shots.solve(self.window)
        self.assertIsNotNone(self.window._current_path)
        self.window.on_break_path()
        shots.settle(self.window)
        self.assertTrue(self.window.maze.blocked)
        self.assertIsNone(self.window._current_path)
        self.assertIn("выхода нет", self.window.stats.badge.text())

    def test_break_path_in_cyclic_maze_rebuilds(self):
        """В режиме 2 обычно находится обходной маршрут."""
        shots.select(self.window, size=14, algorithm="bfs", seed=5, mode=2)
        self.window.cycles_spin.setValue(30)
        shots.generate(self.window)
        shots.solve(self.window)
        self.assertIsNotNone(self.window._current_path)
        self.window.on_break_path()
        shots.settle(self.window)
        self.assertTrue(self.window.maze.blocked)
        # либо обходной маршрут, либо честное «выхода нет» — но без зависания
        badge = self.window.stats.badge.text()
        if self.window._current_path is None:
            self.assertIn("выхода нет", badge)
        else:
            self.assertIn("путь найден", badge)

    def test_break_without_path_is_harmless(self):
        self.window.on_break_path()
        self.assertIn("сначала найдите путь",
                      self.window.stats.badge.text().lower())

    def test_optimize_button_runs_worker(self):
        shots.select(self.window, size=10, seed=1)
        self.window._hunt_population = lambda: 6
        self.window._hunt_generations = lambda: 2
        self.window.on_optimize()
        deadline = time.time() + 60
        while self.window._hunt_worker is not None and \
                self.window._hunt_worker.isRunning() and time.time() < deadline:
            shots.pump()
            time.sleep(0.005)
        shots.settle(self.window)
        self.assertIsNotNone(self.window.maze)
        self.assertEqual(self.window.hunt_label.text(), "оптимизация: готово")
        # после оптимизации интерфейс сам запускает сравнение BFS и A*
        self.assertEqual(set(self.window.results), {"bfs", "astar"})
        self.assertGreaterEqual(self.window.results["astar"].explored,
                                self.window.results["bfs"].explored * 0.8)


class TestReset(WindowTestCase):
    def test_reset_path_clears_colors(self):
        shots.select(self.window, size=20, algorithm="bfs", seed=4)
        shots.generate(self.window)
        shots.solve(self.window)
        self.assertIsNotNone(self.window.panes[0].canvas._path)
        self.window.on_reset_path()
        shots.pump(2)
        self.assertIsNone(self.window.panes[0].canvas._path)
        self.assertEqual(self.window.results, {})
        self.assertEqual(self.window.stats.tile_value("steps"), "—")

    def test_params_change_stops_animation(self):
        shots.select(self.window, size=50, seed=1)
        self.window.speed_slider.setValue(0)
        self.window.on_generate()
        self.assertTrue(self.window.tasks)
        self.window.mode_combo.setCurrentIndex(2)
        shots.pump(2)
        self.assertEqual(self.window.tasks, [])
        self.assertEqual(self.window._stage, "idle")


class TestPerformance(unittest.TestCase):
    def test_100x100_paint_is_fast(self):
        report = shots.measure_fps(100, seconds=1.0, during="search")
        self.assertGreaterEqual(report["fps"], 30.0, report)
        self.assertLess(report["frame_ms"], 33.0, report)


class TestNoTkinter(unittest.TestCase):
    def test_logic_modules_do_not_import_tkinter(self):
        import subprocess
        import sys

        code = (
            "import sys;"
            "import maze.grid, maze.generators, maze.solvers, maze.modes,"
            " maze.metrics, maze.hunt, cli;"
            "print('tkinter' in sys.modules);"
            "print('PyQt6' in sys.modules);"
            "print('gui' in sys.modules)"
        )
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        process = subprocess.run([sys.executable, "-c", code], cwd=root,
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.split(), ["False", "False", "False"])

    def test_launcher_importable(self):
        import gui

        self.assertTrue(callable(gui.main))


class TestHeadless(unittest.TestCase):
    def test_main_without_display_returns_error(self):
        """Без DISPLAY окно не создаётся, а печатается понятное сообщение."""
        import subprocess
        import sys

        env = {key: value for key, value in os.environ.items()
               if key not in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM")}
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        process = subprocess.run([sys.executable, "gui.py"], cwd=root, env=env,
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertIn("нет дисплея", process.stderr)


class TestCanvasGeometry(unittest.TestCase):
    def test_square_cells_fit_window(self):
        window = make_window()
        try:
            shots.select(window, size=100, seed=1, algorithm="astar")
            shots.generate(window)
            canvas = window.panes[0].canvas
            x0, y0, size = canvas.geometry_info()
            self.assertGreater(size, 3)
            self.assertGreaterEqual(x0, 0)
            self.assertGreaterEqual(y0, 0)
            self.assertLessEqual(x0 + size * 100, canvas.width())
            self.assertLessEqual(y0 + size * 100, canvas.height())
        finally:
            window.close()
            window.deleteLater()
            shots.pump(2)

    def test_zoom_and_reset(self):
        window = make_window()
        try:
            shots.select(window, size=20, seed=1)
            shots.generate(window)
            canvas = window.panes[0].canvas
            base = canvas.cell_pixel_size()
            canvas.set_zoom(2.0)
            self.assertGreater(canvas.cell_pixel_size(), base)
            canvas.reset_view()
            self.assertEqual(canvas.cell_pixel_size(), base)
        finally:
            window.close()
            window.deleteLater()
            shots.pump(2)


if __name__ == "__main__":
    unittest.main()
