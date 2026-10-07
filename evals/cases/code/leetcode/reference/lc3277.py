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
    def maximumSubarrayXor(
        self, nums: List[int], queries: List[List[int]]
    ) -> List[int]:
        n = len(nums)
        f = [[0] * n for _ in range(n)]
        g = [[0] * n for _ in range(n)]
        for i in range(n - 1, -1, -1):
            f[i][i] = g[i][i] = nums[i]
            for j in range(i + 1, n):
                f[i][j] = f[i][j - 1] ^ f[i + 1][j]
                g[i][j] = max(f[i][j], g[i][j - 1], g[i + 1][j])
        return [g[l][r] for l, r in queries]
