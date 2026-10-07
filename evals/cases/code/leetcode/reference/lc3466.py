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
    def maxCoins(self, lane1: List[int], lane2: List[int]) -> int:
        @cache
        def dfs(i: int, j: int, k: int) -> int:
            if i >= n:
                return 0
            x = lane1[i] if j == 0 else lane2[i]
            ans = max(x, dfs(i + 1, j, k) + x)
            if k > 0:
                ans = max(ans, dfs(i + 1, j ^ 1, k - 1) + x)
                ans = max(ans, dfs(i, j ^ 1, k - 1))
            return ans

        n = len(lane1)
        ans = -inf
        for i in range(n):
            ans = max(ans, dfs(i, 0, 2))
        return ans
