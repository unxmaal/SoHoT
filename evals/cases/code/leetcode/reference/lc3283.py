# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
import random
import functools
import collections
import string
import math
import datetime

from typing import *
from functools import *
from collections import *
from itertools import *
from heapq import *
from bisect import *
from string import *
from operator import *
from math import *

inf = float('inf')

class Solution:
    def maxMoves(self, kx: int, ky: int, positions: List[List[int]]) -> int:
        @cache
        def dfs(last: int, state: int, k: int) -> int:
            if state == 0:
                return 0
            if k:
                res = 0
                for i, (x, y) in enumerate(positions):
                    if state >> i & 1:
                        t = dfs(i, state ^ (1 << i), k ^ 1) + dist[last][x][y]
                        if res < t:
                            res = t
                return res
            else:
                res = inf
                for i, (x, y) in enumerate(positions):
                    if state >> i & 1:
                        t = dfs(i, state ^ (1 << i), k ^ 1) + dist[last][x][y]
                        if res > t:
                            res = t
                return res

        n = len(positions)
        m = 50
        dist = [[[-1] * m for _ in range(m)] for _ in range(n + 1)]
        dx = [1, 1, 2, 2, -1, -1, -2, -2]
        dy = [2, -2, 1, -1, 2, -2, 1, -1]
        positions.append([kx, ky])
        for i, (x, y) in enumerate(positions):
            dist[i][x][y] = 0
            q = deque([(x, y)])
            step = 0
            while q:
                step += 1
                for _ in range(len(q)):
                    x1, y1 = q.popleft()
                    for j in range(8):
                        x2, y2 = x1 + dx[j], y1 + dy[j]
                        if 0 <= x2 < m and 0 <= y2 < m and dist[i][x2][y2] == -1:
                            dist[i][x2][y2] = step
                            q.append((x2, y2))

        ans = dfs(n, (1 << n) - 1, 1)
        dfs.cache_clear()
        return ans
