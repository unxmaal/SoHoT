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
    def sortMatrix(self, grid: List[List[int]]) -> List[List[int]]:
        n = len(grid)
        for k in range(n - 2, -1, -1):
            i, j = k, 0
            t = []
            while i < n and j < n:
                t.append(grid[i][j])
                i += 1
                j += 1
            t.sort()
            i, j = k, 0
            while i < n and j < n:
                grid[i][j] = t.pop()
                i += 1
                j += 1
        for k in range(n - 2, 0, -1):
            i, j = k, n - 1
            t = []
            while i >= 0 and j >= 0:
                t.append(grid[i][j])
                i -= 1
                j -= 1
            t.sort()
            i, j = k, n - 1
            while i >= 0 and j >= 0:
                grid[i][j] = t.pop()
                i -= 1
                j -= 1
        return grid
