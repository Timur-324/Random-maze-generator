"""Тесты генераторов: идеальность, связность, воспроизводимость, шаги."""

import random
import unittest

from maze import generators, solvers
from maze.events import CARVE, VISIT
from maze.grid import Maze

SIZES = (10, 20, 50)
SEEDS = (0, 1, 2, 7, 12345)


def run_generator(name, size, seed, generator_name=None):
    maze = Maze(size, size)
    events = list(generators.generate(name, maze, random.Random(seed)))
    return maze, events


class TestGenerators(unittest.TestCase):
    def test_all_generators_present(self):
        self.assertEqual(set(generators.GENERATORS), {"dfs", "prim", "kruskal"})
        for name in generators.GENERATORS:
            self.assertIn(name, generators.GENERATOR_TITLES)
            self.assertIs(generators.get(name), generators.GENERATORS[name])
        with self.assertRaises(ValueError):
            generators.get("bogus")

    def test_perfect_tree(self):
        """Ровно N-1 пробитых стен + связность = идеальный лабиринт."""
        for name in generators.GENERATORS:
            for size in SIZES:
                for seed in SEEDS:
                    with self.subTest(generator=name, size=size, seed=seed):
                        maze, _events = run_generator(name, size, seed)
                        cells = maze.cell_count
                        self.assertEqual(maze.carved, cells - 1)
                        self.assertEqual(maze.cycles, 0)
                        self.assertTrue(maze.is_perfect)
                        self.assertEqual(
                            len(maze.reachable((0, 0))), cells,
                            "лабиринт должен быть связным",
                        )

    def test_single_simple_path(self):
        """Между любыми двумя клетками ровно один простой путь."""
        for name in generators.GENERATORS:
            maze, _ = run_generator(name, 12, 3)
            for start in ((0, 0), (5, 5), (11, 0)):
                for end in ((11, 11), (2, 9)):
                    with self.subTest(generator=name, start=start, end=end):
                        self.assertEqual(
                            solvers.count_shortest_paths(maze, start, end), 1
                        )
                        result = solvers.solve_bfs(maze, start, end)
                        self.assertTrue(result.found)
                        self.assertEqual(len(solvers.shortest_path_cells(maze, start, end)),
                                         result.steps + 1)

    def test_events_describe_carving(self):
        for name in generators.GENERATORS:
            for size in (10, 20):
                maze, events = run_generator(name, size, 5)
                with self.subTest(generator=name, size=size):
                    kinds = [event.kind for event in events]
                    self.assertEqual(kinds.count(CARVE), maze.cell_count - 1)
                    self.assertEqual(kinds.count(VISIT), maze.cell_count)
                    self.assertEqual(kinds[0], VISIT)
                    self.assertEqual(events[0].a, (0, 0))
                    # каждое событие CARVE — между соседними клетками
                    for event in events:
                        if event.kind == CARVE:
                            self.assertIn(event.b, maze.neighbors(event.a))
                            self.assertTrue(maze.is_open(event.a, event.b))

    def test_reproducible_by_seed(self):
        for name in generators.GENERATORS:
            for size in (10, 30):
                with self.subTest(generator=name, size=size):
                    first, _ = run_generator(name, size, 4242)
                    second, _ = run_generator(name, size, 4242)
                    self.assertEqual(first.signature(), second.signature())

    def test_different_seeds_differ(self):
        for name in generators.GENERATORS:
            first, _ = run_generator(name, 20, 1)
            second, _ = run_generator(name, 20, 2)
            self.assertNotEqual(first.signature(), second.signature())

    def test_does_not_use_global_random(self):
        """Глобальный random не должен влиять: только random.Random(seed)."""
        name = "dfs"
        random.seed(1)
        first, _ = run_generator(name, 20, 99)
        random.seed(2)
        second, _ = run_generator(name, 20, 99)
        self.assertEqual(first.signature(), second.signature())

    def test_100x100_no_recursion_limit(self):
        """DFS итеративный: 100x100 не упирается в лимит рекурсии."""
        maze, events = run_generator("dfs", 100, 0)
        self.assertEqual(maze.carved, 100 * 100 - 1)
        self.assertGreater(len(events), 0)
        self.assertTrue(maze.is_perfect)

    def test_start_cell_argument(self):
        maze = Maze(10, 10)
        events = list(generators.randomized_dfs(maze, random.Random(1), (4, 4)))
        self.assertEqual(events[0].a, (4, 4))
        self.assertTrue(maze.is_perfect)

    def test_bad_start_raises(self):
        maze = Maze(5, 5)
        with self.assertRaises(ValueError):
            list(generators.randomized_dfs(maze, random.Random(0), (9, 9)))
        maze.block((1, 1))
        with self.assertRaises(ValueError):
            list(generators.prim(maze, random.Random(0), (1, 1)))


if __name__ == "__main__":
    unittest.main()
