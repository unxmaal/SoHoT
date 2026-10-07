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
  def countPathsWithXorValue(self, grid: list[list[int]], k: int) -> int:
    MOD = 1_000_000_007
    m = len(grid)
    n = len(grid[0])

    @functools.lru_cache(None)
    def count(i: int, j: int, xors: int) -> int:
      """
      Return the number of paths from (i, j) to (m - 1, n - 1) with XOR value
      `xors`.
      """
      if i == m or j == n:
        return 0
      xors ^= grid[i][j]
      if i == m - 1 and j == n - 1:
        return int(xors == k)
      right = count(i, j + 1, xors)
      down = count(i + 1, j, xors)
      return (right + down) % MOD

    return count(0, 0, 0)
