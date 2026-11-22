"""Проверки GUI без дисплея: импорт, геометрия, отсутствие tkinter в логике.

В этом окружении нет X-сервера, поэтому окно не запускается (mainloop не
вызывается). Проверяем то, что можно проверить без экрана: модуль
импортируется, tkinter не тянется в логику, геометрия клеток согласована,
все кнопки/методы на месте.
"""

import os
import subprocess
import sys
import unittest

import gui
from maze import generators, modes, solvers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DISPLAY = bool(os.environ.get("DISPLAY"))


class TestNoTkinterInLogic(unittest.TestCase):
    def test_logic_modules_do_not_import_tkinter(self):
        code = (
            "import sys;"
            "import maze.grid, maze.events, maze.generators, maze.solvers,"
            " maze.modes, maze.metrics, cli;"
            "print('tkinter' in sys.modules);"
            "print('gui' in sys.modules)"
        )
        process = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.split(), ["False", "False"])

    def test_gui_import_is_safe(self):
        """Импорт gui не создаёт окно и не падает без дисплея."""
        code = "import gui; print('ok', hasattr(gui, 'MazeApp'))"
        process = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                 capture_output=True, text=True, timeout=120,
                                 env={k: v for k, v in os.environ.items()
                                      if k != "DISPLAY"})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "ok True")


class TestGeometry(unittest.TestCase):
    def test_layout_sizes(self):
        for size in (10, 20, 50, 100):
            cell, gap, side = gui.layout(size)
            self.assertGreaterEqual(cell, 3)
            self.assertGreaterEqual(gap, 1)
            self.assertLess(gap, cell)
            self.assertEqual(side, size * cell + gap)
            self.assertLessEqual(side, 620)

    def test_cell_rect_inside_canvas(self):
        for size in (10, 20, 50, 100):
            cell, gap, side = gui.layout(size)
            for corner in ((0, 0), (size - 1, size - 1), (0, size - 1)):
                x0, y0, x1, y1 = gui.cell_rect(corner, cell, gap)
                self.assertGreaterEqual(x0, 0)
                self.assertGreaterEqual(y0, 0)
                self.assertLess(x1, side)
                self.assertLess(y1, side)
                self.assertLess(x0, x1)
                self.assertLess(y0, y1)

    def test_cells_do_not_overlap(self):
        cell, gap, _side = gui.layout(20)
        a = gui.cell_rect((3, 4), cell, gap)
        b = gui.cell_rect((4, 4), cell, gap)
        c = gui.cell_rect((3, 5), cell, gap)
        self.assertLess(a[2], b[0], "между клетками должен быть зазор-стена")
        self.assertLess(a[3], c[1])

    def test_cell_at_inverts_cell_rect(self):
        for size in (10, 20, 50, 100):
            cell, gap, _side = gui.layout(size)
            for x in (0, 1, size // 2, size - 1):
                for y in (0, size - 1):
                    x0, y0, x1, y1 = gui.cell_rect((x, y), cell, gap)
                    self.assertEqual(
                        gui.cell_at((x0 + x1) // 2, (y0 + y1) // 2, cell, gap, size),
                        (x, y),
                    )
            self.assertIsNone(gui.cell_at(-5, 0, cell, gap, size))
            self.assertIsNone(gui.cell_at(0, -5, cell, gap, size))

    def test_bridge_rect_covers_gap(self):
        cell, gap, _side = gui.layout(20)
        left = gui.cell_rect((2, 3), cell, gap)
        right = gui.cell_rect((3, 3), cell, gap)
        bridge = gui.bridge_rect((2, 3), (3, 3), cell, gap)
        self.assertAlmostEqual(bridge[0], left[2], delta=1)
        self.assertAlmostEqual(bridge[2], right[0], delta=1)
        self.assertLessEqual(bridge[1], left[1])
        self.assertGreaterEqual(bridge[3], left[3])
        # вертикальный проход
        top = gui.cell_rect((2, 3), cell, gap)
        bottom = gui.cell_rect((2, 4), cell, gap)
        bridge = gui.bridge_rect((2, 4), (2, 3), cell, gap)  # порядок не важен
        self.assertAlmostEqual(bridge[1], top[3], delta=1)
        self.assertAlmostEqual(bridge[3], bottom[1], delta=1)


class TestControls(unittest.TestCase):
    def test_mode_titles_map_to_builder(self):
        for title, mode, trap in gui.MODE_CHOICES:
            self.assertEqual(gui.mode_from_title(title), (mode, trap))
            # каждое сочетание действительно принимается Builder
            builder = modes.Builder(size=10, mode=mode, trap=trap)
            self.assertEqual(builder.mode, mode)
        self.assertEqual(gui.mode_from_title("неизвестно"), (1, None))

    def test_algorithm_titles(self):
        for title, key in gui.ALGO_CHOICES:
            algos = gui.algos_from_title(title)
            self.assertTrue(set(algos) <= set(solvers.ALGORITHMS))
            self.assertEqual(len(algos), 2 if key == "both" else 1)
        self.assertEqual(gui.algos_from_title("нет такого"), ["bfs", "astar"])

    def test_sizes_and_colors(self):
        self.assertEqual(gui.SIZES, (10, 20, 50, 100))
        required = {"wall", "closed", "open", "frontier", "visited", "path",
                    "start", "end"}
        self.assertTrue(required <= set(gui.COLORS))
        for value in gui.COLORS.values():
            self.assertRegex(value, r"^#[0-9a-f]{6}$")

    def test_generators_listed(self):
        values = sorted(generators.GENERATORS)
        self.assertEqual(values, ["dfs", "kruskal", "prim"])


class TestAppSurface(unittest.TestCase):
    """Класс окна содержит все методы, на которые опираются кнопки."""

    def test_required_methods(self):
        for name in ("on_generate", "on_solve", "on_pause", "on_reset_path",
                     "on_break_path", "mainloop"):
            self.assertTrue(hasattr(gui.MazeApp, name), name)
        self.assertTrue(issubclass(gui.MazeApp, gui.tk.Tk))
        self.assertTrue(hasattr(gui.MazeView, "reset"))
        self.assertTrue(hasattr(gui.MazeView, "carve"))
        self.assertTrue(hasattr(gui.MazeView, "paint"))

    def test_batch_size_bounds(self):
        self.assertGreaterEqual(gui.MIN_BATCH, 1)
        self.assertGreater(gui.MAX_BATCH, gui.MIN_BATCH)
        self.assertLessEqual(gui.FRAME_MS, 50)

    @unittest.skipIf(HAS_DISPLAY, "в окружении есть дисплей")
    def test_main_without_display_returns_error(self):
        if os.environ.pop("DISPLAY", None) is not None:
            self.addCleanup(os.environ.__setitem__, "DISPLAY", "restored")
        self.assertEqual(gui.main(size=10), 1)


if __name__ == "__main__":
    unittest.main()
