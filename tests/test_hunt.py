"""Тесты дополнительного усложнения №1: поиск трудного для A* лабиринта."""

import random
import unittest

from maze import generators, hunt, solvers
from maze.grid import Maze


def perfect(size=10, seed=0, name="dfs"):
    maze = Maze(size, size)
    for _event in generators.generate(name, maze, random.Random(seed)):
        pass
    return maze


class TestMutation(unittest.TestCase):
    def test_mutation_keeps_ideal_maze(self):
        rng = random.Random(1)
        maze = perfect(12, 3)
        for _ in range(30):
            maze = hunt.mutate(maze, rng, moves=1 + rng.randrange(3))
            self.assertEqual(maze.carved, 12 * 12 - 1)
            self.assertEqual(maze.cycles, 0)
            self.assertTrue(maze.is_perfect)
            self.assertEqual(len(maze.reachable((0, 0))), 144)

    def test_mutation_changes_something(self):
        rng = random.Random(5)
        maze = perfect(10, 1)
        seen = {maze.signature()}
        for _ in range(10):
            maze = hunt.mutate(maze, rng)
            seen.add(maze.signature())
        self.assertGreater(len(seen), 1)


class TestHunt(unittest.TestCase):
    def test_report(self):
        report = hunt.search_hardest(size=10, seed=1, population=10, generations=5)
        self.assertEqual(report["size"], 10)
        self.assertEqual(report["cells"], 100)
        self.assertGreaterEqual(report["best_explored"], report["baseline_explored"])
        self.assertLessEqual(report["best_explored"], 100)
        self.assertGreater(report["best_steps"] or 0, 0)
        self.assertAlmostEqual(report["best_share"], report["best_explored"] / 100)
        self.assertEqual(len(report["history"]), 6)  # поколение 0 + 5
        self.assertTrue(report["maze"].is_perfect)

    def test_deterministic(self):
        first = hunt.search_hardest(size=10, seed=7, population=8, generations=3)
        second = hunt.search_hardest(size=10, seed=7, population=8, generations=3)
        self.assertEqual(first["best_explored"], second["best_explored"])
        self.assertEqual(first["maze"].signature(), second["maze"].signature())

    def test_fixed_goal_is_used(self):
        report = hunt.search_hardest(size=10, seed=0, population=6, generations=2,
                                     start=(2, 3), end=(8, 7))
        self.assertEqual(report["start"], (2, 3))
        self.assertEqual(report["end"], (8, 7))
        result = solvers.solve(report["maze"], (2, 3), (8, 7), "astar")
        self.assertTrue(result.found)

    def test_snake_beats_random_maze(self):
        """Змей-ловушка сложнее случайного идеального лабиринта для A*."""
        report = hunt.search_hardest(size=20, seed=0, population=8, generations=2)
        random_maze_explored = solvers.solve_astar(
            perfect(20, 0), (0, 0), (19, 19)).explored
        self.assertGreaterEqual(report["best_explored"], random_maze_explored)

    def test_bad_parameters(self):
        with self.assertRaises(ValueError):
            hunt.Hunt(size=10, population=1)
        with self.assertRaises(ValueError):
            hunt.Hunt(size=10, population=4, elite=4)
        with self.assertRaises(ValueError):
            hunt.Hunt(size=10, generations=0)


if __name__ == "__main__":
    unittest.main()
