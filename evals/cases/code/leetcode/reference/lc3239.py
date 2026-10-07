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
    def minFlips(self, grid: List[List[int]]) -> int:
        m, n = len(grid), len(grid[0])
        cnt1 = cnt2 = 0
        for row in grid:
            for j in range(n // 2):
                if row[j] != row[n - j - 1]:
                    cnt1 += 1
        for j in range(n):
            for i in range(m // 2):
                if grid[i][j] != grid[m - i - 1][j]:
                    cnt2 += 1
        return min(cnt1, cnt2)
