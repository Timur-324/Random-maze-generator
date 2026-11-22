"""Фоновые вычисления в QThread, чтобы окно не замирало.

Генерация не нуждается в потоке: она и так идёт потоком событий по таймеру.
А вот поиск (несколько прогонов ради честного замера времени) и
генетическая оптимизация лабиринта занимают десятки миллисекунд (а
оптимизация — секунды), поэтому выполняются в отдельных потоках и
возвращают результат сигналом.

Модель лабиринта во время работы воркера только читается: интерфейс на это
время блокирует кнопки, которые могли бы её изменить.
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from maze import hunt, metrics


class SearchWorker(QThread):
    """Считает пути BFS/A* (с замером времени) в фоне."""

    ready = pyqtSignal(int, object)     # run_id, {algo: SearchResult}
    failed = pyqtSignal(int, str)

    def __init__(self, run_id: int, maze, start, end, algorithms,
                 repeats: int = metrics.DEFAULT_REPEATS, parent=None) -> None:
        super().__init__(parent)
        self._run_id = run_id
        self._maze = maze
        self._start = start
        self._end = end
        self._algorithms = tuple(algorithms)
        self._repeats = repeats

    def run(self) -> None:  # noqa: D401 - метод QThread
        try:
            results = {
                algo: metrics.measure(self._maze, self._start, self._end, algo,
                                      repeats=self._repeats, record=True)
                for algo in self._algorithms
            }
        except Exception as exc:  # pragma: no cover - защита от неожиданностей
            self.failed.emit(self._run_id, str(exc))
            return
        self.ready.emit(self._run_id, results)


class HuntWorker(QThread):
    """Ищет лабиринт, максимально трудный для A* (генетический поиск)."""

    ready = pyqtSignal(int, object)     # run_id, отчёт hunt.search_hardest
    failed = pyqtSignal(int, str)

    def __init__(self, run_id: int, size: int, seed: int, population: int,
                 generations: int, algorithm: str = "astar", parent=None) -> None:
        super().__init__(parent)
        self._run_id = run_id
        self._size = size
        self._seed = seed
        self._population = population
        self._generations = generations
        self._algorithm = algorithm

    def run(self) -> None:  # noqa: D401 - метод QThread
        try:
            report = hunt.search_hardest(
                size=self._size, seed=self._seed, algorithm=self._algorithm,
                population=self._population, generations=self._generations,
            )
        except Exception as exc:  # pragma: no cover
            self.failed.emit(self._run_id, str(exc))
            return
        self.ready.emit(self._run_id, report)
