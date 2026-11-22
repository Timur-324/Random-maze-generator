"""Дополнительное усложнение №1: целенаправленный поиск трудного для A* лабиринта.

Задача: не просто генерировать случайные лабиринты, а искать такой, на
котором A* с манхэттенской эвристикой раскрывает как можно больше клеток
(то есть эвристика обманывает его сильнее всего).

Приспособленность особи — число клеток, раскрытых A* на пути от старта к
финишу. Особь — идеальный лабиринт (остовное дерево сетки). Мутация
сохраняет идеальность: снимаем случайное пробитое ребро дерева, дерево
распадается на две компоненты, и соединяем их случайной стеной между
компонентами. Это стандартный обмен ребра на пространстве остовных
деревьев: рёбер снова N-1, лабиринт остаётся связным и без циклов.

Поиск — простой генетический алгоритм: элита переходит в следующее
поколение без изменений, остальные дети получают 1-3 мутации от случайно
выбранных элитных родителей. Всё детерминировано по seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import generators, solvers
from .grid import Maze

Cell = tuple[int, int]


@dataclass
class Individual:
    maze: Maze
    explored: int
    steps: int | None
    origin: str = ""

    @property
    def score(self) -> int:
        return self.explored


def fitness(maze: Maze, start: Cell, end: Cell, algorithm: str = "astar") -> int:
    """Сколько клеток раскрывает алгоритм — это и есть «сложность»."""
    return solvers.solve(maze, start, end, algorithm).explored


def components(maze: Maze, origin: Cell) -> set[Cell]:
    """Клетки, достижимые из ``origin`` (для разрезания дерева)."""
    return maze.reachable(origin)


def mutate(maze: Maze, rng: random.Random, moves: int = 1) -> Maze:
    """Один-несколько обменов ребра; лабиринт остаётся идеальным деревом."""
    child = maze.copy()
    for _ in range(moves):
        carved = [
            (a, b)
            for a, b in child.internal_pairs()
            if not child.has_wall(a, b)
        ]
        if not carved:
            break
        a, b = carved[rng.randrange(len(carved))]
        child.add_wall(a, b)  # разрезали дерево на две компоненты
        left = components(child, a)
        candidates = [
            (u, v)
            for u, v in child.internal_pairs()
            if child.has_wall(u, v) and ((u in left) != (v in left))
        ]
        if not candidates:
            child.remove_wall(a, b)  # вернуть как было (не должно случаться)
            continue
        u, v = candidates[rng.randrange(len(candidates))]
        child.remove_wall(u, v)
    return child


class Hunt:
    """Генетический поиск лабиринта, самого трудного для выбранного алгоритма."""

    def __init__(
        self,
        size: int = 20,
        seed: int = 0,
        start: Cell | None = None,
        end: Cell | None = None,
        algorithm: str = "astar",
        population: int = 16,
        generations: int = 25,
        elite: int = 4,
    ) -> None:
        if population < 2:
            raise ValueError("популяция должна быть хотя бы 2")
        if not 0 < elite < population:
            raise ValueError("элита должна быть от 1 до population-1")
        if generations < 1:
            raise ValueError("поколений должно быть хотя бы 1")
        self.size = int(size)
        self.seed = int(seed)
        self.algorithm = algorithm
        self.population_size = int(population)
        self.generations = int(generations)
        self.elite = int(elite)
        self.rng = random.Random(self.seed)
        self.start = start or (0, 0)
        self.end = end or (self.size - 1, self.size - 1)
        self.history: list[tuple[int, int, float]] = []  # (поколение, max, mean)
        self.individuals: list[Individual] = []

    # ------------------------------------------------------------- особи
    def _seed_maze(self, index: int) -> Maze:
        """Стартовая особь: разные генераторы и разные seed'ы."""
        name = ("dfs", "prim", "kruskal")[index % 3]
        maze = Maze(self.size, self.size)
        for _event in generators.generate(name, maze,
                                          random.Random(self.seed * 1000 + index)):
            pass
        maze.start, maze.end = self.start, self.end
        return maze

    def _evaluate(self, maze: Maze, origin: str) -> Individual:
        result = solvers.solve(maze, self.start, self.end, self.algorithm)
        return Individual(maze, result.explored, result.steps, origin)

    def _initial_population(self) -> list[Individual]:
        return [self._evaluate(self._seed_maze(i), "seed") for i in
                range(self.population_size)]

    # -------------------------------------------------------------- поиск
    def run(self) -> dict:
        """Прогнать эволюцию и вернуть отчёт о лучшем лабиринте."""
        population = self._initial_population()
        population.sort(key=lambda ind: ind.score, reverse=True)
        best = population[0]
        start_score = self._evaluate(self._seed_maze(0), "baseline").explored
        self.history.append((0, best.score, sum(i.score for i in population)
                             / len(population)))

        for generation in range(1, self.generations + 1):
            elites = population[: self.elite]
            children = list(elites)
            while len(children) < self.population_size:
                parent = elites[self.rng.randrange(len(elites))]
                moves = 1 + self.rng.randrange(3)
                child = self._evaluate(mutate(parent.maze, self.rng, moves),
                                       f"mutant({parent.origin})")
                children.append(child)
            population = sorted(children, key=lambda ind: ind.score, reverse=True)
            if population[0].score > best.score:
                best = population[0]
            self.history.append((generation, population[0].score,
                                 sum(i.score for i in population) / len(population)))
        self.individuals = population
        return {
            "size": self.size,
            "seed": self.seed,
            "algorithm": self.algorithm,
            "start": self.start,
            "end": self.end,
            "baseline_explored": start_score,
            "best_explored": best.score,
            "best_steps": best.steps,
            "cells": self.size * self.size,
            "best_share": best.score / (self.size * self.size),
            "generations": self.generations,
            "population": self.population_size,
            "history": list(self.history),
            "maze": best.maze,
        }


def search_hardest(size: int = 20, seed: int = 0, **kwargs) -> dict:
    """Короткая обёртка: ``search_hardest(20, 1, generations=10)``."""
    return Hunt(size=size, seed=seed, **kwargs).run()
