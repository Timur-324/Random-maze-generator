"""Тесты модели лабиринта (maze.grid)."""

import unittest

from maze.grid import ALL_WALLS, E, N, S, W, Maze


class TestMazeBasics(unittest.TestCase):
    def test_initial_state(self):
        maze = Maze(4, 3)
        self.assertEqual(maze.width, 4)
        self.assertEqual(maze.height, 3)
        self.assertEqual(maze.cell_count, 12)
        self.assertEqual(set(maze.walls), {ALL_WALLS})
        self.assertEqual(maze.carved, 0)
        self.assertEqual(maze.start, (0, 0))
        self.assertEqual(maze.end, (3, 2))

    def test_index_roundtrip(self):
        maze = Maze(5, 7)
        for cell in maze.cells():
            self.assertEqual(maze.cell_at(maze.index(cell)), cell)
        self.assertEqual(maze.index((3, 2)), 2 * 5 + 3)

    def test_neighbors_order_and_bounds(self):
        maze = Maze(3, 3)
        self.assertEqual(maze.neighbors((1, 1)), [(1, 0), (2, 1), (1, 2), (0, 1)])
        self.assertEqual(maze.neighbors((0, 0)), [(1, 0), (0, 1)])
        self.assertEqual(maze.neighbors((2, 2)), [(2, 1), (1, 2)])

    def test_wall_is_shared_between_cells(self):
        maze = Maze(3, 3)
        self.assertTrue(maze.has_wall((0, 0), (1, 0)))
        self.assertTrue(maze.remove_wall((0, 0), (1, 0)))
        self.assertEqual(maze.carved, 1)
        # стена снята с обеих сторон
        self.assertFalse(maze.walls[maze.index((0, 0))] & E)
        self.assertFalse(maze.walls[maze.index((1, 0))] & W)
        self.assertFalse(maze.has_wall((1, 0), (0, 0)))
        self.assertEqual(maze.open_neighbors((0, 0)), [(1, 0)])
        # повторное снятие ничего не меняет
        self.assertFalse(maze.remove_wall((0, 0), (1, 0)))
        self.assertEqual(maze.carved, 1)
        # и обратно
        self.assertTrue(maze.add_wall((0, 0), (1, 0)))
        self.assertEqual(maze.carved, 0)
        self.assertTrue(maze.has_wall((0, 0), (1, 0)))

    def test_vertical_walls(self):
        maze = Maze(2, 2)
        maze.remove_wall((0, 0), (0, 1))
        self.assertEqual(maze.walls[maze.index((0, 0))] & S, 0)
        self.assertEqual(maze.walls[maze.index((0, 1))] & N, 0)
        self.assertEqual(maze.open_neighbors((0, 1)), [(0, 0)])

    def test_non_adjacent_raises(self):
        maze = Maze(3, 3)
        with self.assertRaises(ValueError):
            maze.has_wall((0, 0), (2, 2))
        with self.assertRaises(ValueError):
            maze.remove_wall((0, 0), (0, 0))

    def test_copy_is_independent(self):
        maze = Maze(4, 4)
        maze.remove_wall((0, 0), (1, 0))
        clone = maze.copy()
        self.assertEqual(clone.signature(), maze.signature())
        clone.remove_wall((1, 0), (2, 0))
        self.assertNotEqual(clone.signature(), maze.signature())
        self.assertEqual(maze.carved, 1)
        self.assertEqual(clone.carved, 2)
        clone.block((3, 3))
        self.assertEqual(maze.blocked, set())

    def test_blocked_cell_is_impassable(self):
        maze = Maze(3, 3)
        maze.remove_wall((0, 0), (1, 0))
        maze.remove_wall((1, 0), (2, 0))
        self.assertIn((1, 0), maze.open_neighbors((0, 0)))
        maze.block((1, 0))
        self.assertNotIn((1, 0), maze.open_neighbors((0, 0)))
        self.assertEqual(maze.reachable((0, 0)), {(0, 0)})
        self.assertTrue(maze.unblock((1, 0)))
        self.assertIn((1, 0), maze.open_neighbors((0, 0)))

    def test_cycles_and_perfect(self):
        maze = Maze(3, 3)
        self.assertFalse(maze.is_perfect)  # пока не связный
        self.assertEqual(maze.cycles, 0)
        # дерево-«змейка» на 9 клетках
        order = [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (0, 1), (0, 2), (1, 2), (2, 2)]
        for a, b in zip(order, order[1:]):
            maze.remove_wall(a, b)
        self.assertEqual(maze.carved, 8)
        self.assertEqual(maze.cycles, 0)
        self.assertTrue(maze.is_perfect)
        # лишний проход -> цикл
        maze.remove_wall((0, 0), (0, 1))
        self.assertEqual(maze.cycles, 1)
        self.assertFalse(maze.is_perfect)

    def test_wall_density(self):
        maze = Maze(2, 2)
        self.assertEqual(maze.internal_wall_total(), 4)
        self.assertAlmostEqual(maze.wall_density(), 1.0)
        maze.remove_wall((0, 0), (1, 0))
        self.assertAlmostEqual(maze.wall_density(), 0.75)

    def test_ascii(self):
        maze = Maze(3, 3)
        maze.remove_wall((0, 0), (1, 0))
        text = maze.to_ascii([(0, 0), (1, 0)])
        self.assertIn("S", text)
        self.assertIn("E", text)
        self.assertIn("*", text)
        self.assertIn("+--+", text)
        self.assertEqual(len(text.splitlines()), 2 * 3 + 1)
        # старт и финиш не перекрываются знаком пути
        self.assertNotIn("*S", text)
        maze.block((2, 2))
        self.assertIn("X", maze.to_ascii())

    def test_invalid_size(self):
        with self.assertRaises(ValueError):
            Maze(0, 5)


if __name__ == "__main__":
    unittest.main()
