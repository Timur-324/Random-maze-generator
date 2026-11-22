"""Скриншоты как проверка: файлы существуют, не пустые и упомянуты в README.

Тест не «верит» картинкам: он открывает PNG через QImage, проверяет размер
окна и то, что в кадре действительно есть разные цвета (лабиринт, стены,
панели), а также что каждый файл вставлен в README.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QImage

from mazegui import shots

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")
SCENARIO_NAMES = [name for name, _handler in shots.SCENARIOS]


def distinct_colors(image: QImage, step: int = 7) -> int:
    seen = set()
    for x in range(0, image.width(), step):
        for y in range(0, image.height(), step):
            seen.add(image.pixelColor(x, y).rgb())
            if len(seen) > 64:
                return len(seen)
    return len(seen)


class TestScreenshots(unittest.TestCase):
    def test_files_exist_and_are_readable(self):
        for name in SCENARIO_NAMES:
            path = os.path.join(shots.DEFAULT_OUT, f"{name}.png")
            with self.subTest(name=name):
                self.assertTrue(os.path.exists(path), path)
                self.assertGreater(os.path.getsize(path), 20_000, path)
                image = QImage(path)
                self.assertFalse(image.isNull(), path)
                self.assertEqual(image.size(), QSize(*shots.WINDOW))
                self.assertGreater(distinct_colors(image), 8,
                                   "кадр не должен быть пустым")

    def test_screenshots_are_embedded_in_readme(self):
        with open(README, encoding="utf-8") as handle:
            text = handle.read()
        for name in SCENARIO_NAMES:
            with self.subTest(name=name):
                self.assertIn(f"docs/screenshots/{name}.png", text)

    def test_capture_pipeline_works_into_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = shots.make_all(tmp, scenarios=shots.SCENARIOS[:2])
            self.assertEqual(len(saved), 2)
            for path in saved:
                self.assertTrue(os.path.exists(path))
                self.assertGreater(os.path.getsize(path), 5_000)


if __name__ == "__main__":
    unittest.main()
