"""Тесты замеров: время, сравнение, статистика лабиринта."""

import unittest

from maze import metrics, modes, solvers


class TestMetrics(unittest.TestCase):
    def test_bench_time_positive(self):
        maze, info = modes.build(size=20, seed=1, mode=1)
        for algorithm in ("bfs", "astar"):
            elapsed = metrics.bench_time(maze, info.start, info.end, algorithm,
                                         repeats=3)
            self.assertGreater(elapsed, 0.0)
            self.assertLess(elapsed, 5000.0)

    def test_measure_uses_separate_timing(self):
        maze, info = modes.build(size=20, seed=1, mode=1)
        result = metrics.measure(maze, info.start, info.end, "astar", repeats=3)
        self.assertTrue(result.found)
        self.assertGreater(result.elapsed_ms, 0.0)
        # события записаны, счётчики согласованы с событиями
        self.assertGreater(len(result.events), 0)
        self.assertEqual(result.steps, len(result.path) - 1)

    def test_compare_and_ratio(self):
        maze, info = modes.build(size=30, seed=2, mode=2, cycle_density=0.1)
        results = metrics.compare(maze, info.start, info.end, repeats=2)
        self.assertEqual([r.algorithm for r in results], ["bfs", "astar"])
        self.assertEqual(results[0].steps, results[1].steps)
        ratio = metrics.explored_ratio(results)
        self.assertIsNotNone(ratio)
        self.assertAlmostEqual(
            ratio, results[1].explored / results[0].explored, places=9
        )
        self.assertIsNone(metrics.explored_ratio(results[:1]))

    def test_bad_repeats(self):
        maze, info = modes.build(size=10, seed=0, mode=1)
        with self.assertRaises(ValueError):
            metrics.bench_time(maze, info.start, info.end, "bfs", repeats=0)

    def test_maze_stats(self):
        maze, info = modes.build(size=25, seed=3, mode=2, cycle_density=0.1)
        stats = metrics.maze_stats(maze)
        self.assertEqual(stats["size"], "25x25")
        self.assertEqual(stats["cells"], 625)
        self.assertEqual(stats["cycles"], maze.cycles)
        self.assertGreater(stats["cycles"], 0)
        self.assertGreater(stats["dead_ends"], 0)
        self.assertLessEqual(stats["dead_end_share"], 1.0)
        self.assertGreaterEqual(stats["mean_open_degree"], 1.0)
        self.assertGreaterEqual(stats["stretch"], 1.0)
        self.assertGreaterEqual(stats["shortest_paths"], 1)
        self.assertEqual(stats["manhattan"], solvers.manhattan(info.start, info.end))
        self.assertEqual(stats["steps"], solvers.solve_bfs(
            maze, info.start, info.end).steps)

    def test_stats_without_path(self):
        maze, info = modes.build(size=10, seed=0, mode=1)
        for nb in maze.neighbors(maze.end):
            maze.block(nb)
        stats = metrics.maze_stats(maze)
        self.assertIsNone(stats["steps"])
        self.assertIsNone(stats["stretch"])
        self.assertEqual(stats["shortest_paths"], 0)


if __name__ == "__main__":
    unittest.main()
