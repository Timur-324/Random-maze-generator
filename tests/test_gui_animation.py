"""Конвейер анимации GUI без экрана: настоящие события, заглушки вместо Canvas.

Окно (tk.Tk) не создаётся — объекта хватает через ``object.__new__``,
поэтому тест работает в окружении без дисплея. Проверяется именно логика
анимации: сколько событий доходит до панелей, что красится, что пишется
в подписи и строку состояния.
"""

import unittest

import gui
from maze import metrics, modes, solvers


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeView:
    """Заглушка панели: запоминает, что и каким цветом покрасили."""

    def __init__(self):
        self.caption = FakeVar()
        self.colors = {}
        self.clears = 0
        self.markers = 0
        self.carves = 0
        self.size = 0

    def reset(self, size):
        self.colors.clear()
        self.size = size

    def paint(self, cell, color):
        self.colors[cell] = color

    def carve(self, a, b):
        self.carves += 1

    def clear_states(self):
        self.colors.clear()
        self.clears += 1

    def draw_markers(self, start, end):
        self.markers += 1


class FakeButton:
    def configure(self, **kwargs):
        self.kwargs = kwargs


def make_app(views, results=None, stage="idle"):
    """Экземпляр MazeApp без Tk: только то, что нужно анимации."""
    app = object.__new__(gui.MazeApp)
    app.views = list(views)
    app.results = dict(results or {})
    app.info = None
    app.maze = None
    app._tasks = []
    app._stage = stage
    app._paused = False
    app._job = None
    app._current_path = None
    app._screen_key = None
    app.speed_var = FakeVar(64)
    app.status = FakeVar()
    app.algo_var = FakeVar("Оба (сравнить)")
    app.mode_var = FakeVar(gui.MODE_CHOICES[0][0])
    app.seed_var = FakeVar("12345")
    app.pause_button = FakeButton()
    app.after = lambda ms, fn=None: None
    app.after_cancel = lambda job: None
    app._schedule = lambda: None
    app._table_clear = lambda: None
    app._table_fill = lambda algos: None
    return app


def drain(app, limit=100000):
    """Крутить _tick, пока не закончатся задачи."""
    for _ in range(limit):
        if not app._tasks:
            return
        app._tick()
    raise AssertionError("анимация не завершилась")


class TestSearchPipeline(unittest.TestCase):
    def test_events_reach_view_and_path_is_drawn(self):
        maze, info = modes.build(size=20, seed=1, mode=1)
        result = metrics.measure(maze, info.start, info.end, "astar",
                                 repeats=1, record=True)
        view = FakeView()
        app = make_app([view], {"astar": result}, stage="search")
        app.maze = maze
        app._tasks = [{
            "stream": iter(result.events),
            "handle": lambda event, v=view: app._handle_search(event, v),
            "done": False,
            "algo": "astar",
            "view": view,
        }]
        drain(app)

        # каждая раскрытая клетка получила цвет (visited или уже path)
        expanded = {event.a for event in result.events if event.kind == "expand"}
        self.assertTrue(expanded)
        self.assertTrue(expanded <= set(view.colors))
        for cell in result.path:
            self.assertEqual(view.colors[cell], gui.COLORS["path"])
        # подпись панели содержит длину пути и число исследованных
        caption = view.caption.get()
        self.assertIn(str(result.steps), caption)
        self.assertIn(str(result.explored), caption)
        # итоговая строка состояния содержит время
        self.assertIn("мс", app.status.get())
        self.assertIsNotNone(app._current_path)

    def test_no_path_is_reported(self):
        maze, info = modes.build(size=10, seed=0, mode=1)
        for neighbor in maze.neighbors(info.end):
            maze.block(neighbor)
        result = metrics.measure(maze, info.start, info.end, "bfs",
                                 repeats=1, record=True)
        view = FakeView()
        app = make_app([view], {"bfs": result}, stage="search")
        app.maze = maze
        app._tasks = [{
            "stream": iter(result.events),
            "handle": lambda event, v=view: app._handle_search(event, v),
            "done": False,
            "algo": "bfs",
            "view": view,
        }]
        drain(app)
        self.assertIn("выхода нет", view.caption.get())
        self.assertIn("выхода нет", app.status.get())
        self.assertIsNone(app._current_path)

    def test_mode2_highlights_alternatives(self):
        """В режиме 2 подсвечиваются клетки альтернативных кратчайших маршрутов."""
        maze, info = modes.build(size=20, seed=2, mode=2, cycle_density=0.15)
        result = metrics.measure(maze, info.start, info.end, "bfs",
                                 repeats=1, record=True)
        view = FakeView()
        app = make_app([view], {"bfs": result}, stage="search")
        app.maze = maze
        app.info = info
        app._tasks = [{
            "stream": iter(result.events),
            "handle": lambda event, v=view: app._handle_search(event, v),
            "done": False,
            "algo": "bfs",
            "view": view,
        }]
        drain(app)
        alternatives = [c for c, color in view.colors.items()
                        if color == gui.COLORS["alternative"]]
        self.assertTrue(alternatives, "должны подсветиться альтернативные клетки")
        for cell in result.path:
            self.assertEqual(view.colors[cell], gui.COLORS["path"])

    def test_pause_freezes_progress(self):
        maze, info = modes.build(size=20, seed=3, mode=1)
        result = metrics.measure(maze, info.start, info.end, "bfs",
                                 repeats=1, record=True)
        view = FakeView()
        app = make_app([view], {"bfs": result}, stage="search")
        app.maze = maze
        app._tasks = [{
            "stream": iter(result.events),
            "handle": lambda event, v=view: app._handle_search(event, v),
            "done": False,
            "algo": "bfs",
            "view": view,
        }]
        app.on_pause()
        self.assertTrue(app._paused)
        app._tick()  # на паузе ничего не рисуется
        self.assertEqual(view.colors, {})
        app.on_pause()  # сняли паузу
        self.assertFalse(app._paused)
        drain(app)
        self.assertTrue(view.colors)


class TestGenerationPipeline(unittest.TestCase):
    def test_both_panels_get_same_carves(self):
        builder = modes.Builder(size=10, seed=5, mode=2)
        first, second = FakeView(), FakeView()
        app = make_app([first, second], stage="generation")
        app.maze = builder.maze
        app._builder = builder
        app._tasks = [{
            "stream": builder.steps(),
            "handle": app._handle_build,
            "done": False,
        }]
        drain(app)
        self.assertIsNotNone(app.info)
        self.assertEqual(first.carves, builder.maze.carved)
        self.assertEqual(second.carves, builder.maze.carved)
        # все клетки открыты, мостиков ровно столько, сколько проходов
        self.assertEqual(len(first.colors), 100)
        self.assertTrue(all(c == gui.COLORS["open"] for c in first.colors.values()))
        self.assertEqual(first.markers, 1)
        self.assertIn("циклов", app.status.get())

    def test_mode3_reports_ratio(self):
        builder = modes.Builder(size=10, seed=2, mode=3, trap="a")
        view = FakeView()
        app = make_app([view], stage="generation")
        app.maze = builder.maze
        app._builder = builder
        app._tasks = [{
            "stream": builder.steps(),
            "handle": app._handle_build,
            "done": False,
        }]
        drain(app)
        self.assertIn("explored(A*)/explored(BFS)", app.status.get())


class TestBreakPath(unittest.TestCase):
    def test_break_path_rebuilds_or_reports_dead_end(self):
        messages = []
        for seed in range(6):
            maze, info = modes.build(size=12, seed=seed, mode=1)
            path = solvers.solve_bfs(maze, info.start, info.end).path
            view = FakeView()
            app = make_app([view])
            app.maze = maze
            app.info = info
            app.seed_var = FakeVar(str(seed))
            app._current_path = path
            app.on_break_path()
            messages.append(app.status.get())
        self.assertTrue(all("замурована" in message or "Нечего" in message
                            for message in messages))
        self.assertTrue(any("выхода больше нет" in message for message in messages))
        self.assertTrue(any("путь перестроен" in message or "выхода больше нет" in message
                            for message in messages))

    def test_break_without_path_is_harmless(self):
        maze, info = modes.build(size=10, seed=0, mode=1)
        app = make_app([FakeView()])
        app.maze = maze
        app.info = info
        app._current_path = None
        app.on_break_path()
        self.assertIn("Сначала найдите путь", app.status.get())


if __name__ == "__main__":
    unittest.main()
