"""Тесты CLI: запуск, вывод, детерминизм, ASCII, скорость."""

import argparse
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, expect=0):
    process = subprocess.run(
        [sys.executable, "cli.py", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    if process.returncode != expect:
        raise AssertionError(
            f"код {process.returncode} вместо {expect}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process.stdout


class TestCliRun(unittest.TestCase):
    def test_example_from_task(self):
        out = run_cli("run", "--size", "50", "--start", "0,0", "--end", "49,49",
                      "--seed", "12345", "--algo", "astar", "--generator", "dfs",
                      "--mode", "1")
        self.assertIn("50x50", out)
        self.assertIn("seed .................. 12345", out)
        self.assertIn("кратчайший путь:", out)
        self.assertIn("исследовано клеток", out)
        self.assertIn("посещено клеток", out)
        self.assertIn("время", out)
        # для 50x50 ASCII не печатаем
        self.assertNotIn("+--+", out)

    def test_ascii_for_small_mazes(self):
        out = run_cli("run", "--size", "10", "--seed", "1", "--algo", "bfs",
                      "--mode", "1", "--no-time")
        self.assertIn("+--+", out)
        self.assertIn("S", out)
        self.assertIn("E", out)
        self.assertIn("*", out)

    def test_no_ascii_flag(self):
        out = run_cli("run", "--size", "10", "--seed", "1", "--no-ascii")
        self.assertNotIn("+--+", out)

    def test_determinism_byte_identical(self):
        args = ("run", "--size", "20", "--seed", "777", "--mode", "2",
                "--generator", "kruskal", "--algo", "both", "--no-time")
        first = run_cli(*args)
        second = run_cli(*args)
        self.assertEqual(first, second)
        self.assertEqual(first.encode(), second.encode())

    def test_timing_does_not_change_result(self):
        base = ("run", "--size", "20", "--seed", "777", "--mode", "3", "--trap", "b",
                "--algo", "both")
        with_time = run_cli(*base).splitlines()
        without = run_cli(*base, "--no-time").splitlines()
        filtered = [line for line in with_time if "время" not in line]
        self.assertEqual(filtered, without)

    def test_same_seed_same_path(self):
        args = ("run", "--size", "20", "--seed", "42", "--mode", "1",
                "--algo", "both", "--no-time")
        out = run_cli(*args)
        steps = [line.split()[-2] for line in out.splitlines()
                 if line.strip().startswith("путь")]
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0], steps[1], "BFS и A* должны дать одну длину")

    def test_mode3_prints_ratio(self):
        out = run_cli("run", "--size", "20", "--seed", "3", "--mode", "3",
                      "--trap", "a", "--algo", "both", "--no-time")
        self.assertIn("explored(A*)/explored(BFS)", out)

    def test_all_sizes_and_generators(self):
        """CLI работает для всех размеров и всех трёх генераторов."""
        started = time.perf_counter()
        for size in (10, 20, 50, 100):
            for generator in ("dfs", "prim", "kruskal"):
                out = run_cli("run", "--size", str(size), "--generator", generator,
                              "--seed", "5", "--algo", "astar", "--mode", "1",
                              "--no-time", "--no-ascii")
                self.assertIn(f"{size}x{size}", out)
                self.assertIn("кратчайший путь:", out)
        self.assertLess(time.perf_counter() - started, 120)
        # 100x100 не должен быть медленным
        started = time.perf_counter()
        run_cli("run", "--size", "100", "--seed", "1", "--algo", "both",
                "--no-ascii", "--no-time")
        self.assertLess(time.perf_counter() - started, 20)

    def test_bad_start_exit_code(self):
        process = subprocess.run(
            [sys.executable, "cli.py", "run", "--size", "10", "--start", "50,50"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("вне лабиринта", process.stderr)

    def test_bad_cell_format(self):
        process = subprocess.run(
            [sys.executable, "cli.py", "run", "--size", "10", "--end", "abc"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(process.returncode, 2)

    def test_bench(self):
        out = run_cli("bench", "--sizes", "10,20", "--repeats", "1")
        self.assertIn("BFS исл.", out)
        for label in ("1", "2", "3a", "3b"):
            self.assertIn(label, out)

    def test_hunt(self):
        out = run_cli("hunt", "--size", "10", "--seed", "3",
                      "--population", "6", "--generations", "2")
        self.assertIn("лучший найденный", out)
        self.assertIn("клеток", out)

    def test_no_command_shows_help(self):
        out = run_cli()
        self.assertIn("usage", out.lower())

    def test_open_gui_passes_state(self):
        """--gui передаёт в окно ровно то состояние, что посчитал CLI."""
        from unittest import mock

        import cli
        from maze import modes

        _maze, info = modes.build(size=10, seed=7, mode=2, cycle_density=0.1)
        args = argparse.Namespace(algo="both")
        with mock.patch("gui.main", return_value=0) as fake:
            self.assertEqual(cli.open_gui(args, info), 0)
        kwargs = fake.call_args.kwargs
        self.assertEqual(kwargs["size"], 10)
        self.assertEqual(kwargs["seed"], 7)
        self.assertEqual(kwargs["mode"], 2)
        self.assertEqual(kwargs["algorithm"], "both")
        self.assertTrue(kwargs["autostart"])


if __name__ == "__main__":
    unittest.main()
