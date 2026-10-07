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
    def countSubmatrices(self, grid: List[List[int]], k: int) -> int:
        s = [[0] * (len(grid[0]) + 1) for _ in range(len(grid) + 1)]
        ans = 0
        for i, row in enumerate(grid, 1):
            for j, x in enumerate(row, 1):
                s[i][j] = s[i - 1][j] + s[i][j - 1] - s[i - 1][j - 1] + x
                ans += s[i][j] <= k
        return ans
