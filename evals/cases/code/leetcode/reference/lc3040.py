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
    def maxOperations(self, nums: List[int]) -> int:
        @cache
        def dfs(i: int, j: int, s: int) -> int:
            if j - i < 1:
                return 0
            ans = 0
            if nums[i] + nums[i + 1] == s:
                ans = max(ans, 1 + dfs(i + 2, j, s))
            if nums[i] + nums[j] == s:
                ans = max(ans, 1 + dfs(i + 1, j - 1, s))
            if nums[j - 1] + nums[j] == s:
                ans = max(ans, 1 + dfs(i, j - 2, s))
            return ans

        n = len(nums)
        a = dfs(2, n - 1, nums[0] + nums[1])
        b = dfs(0, n - 3, nums[-1] + nums[-2])
        c = dfs(1, n - 2, nums[0] + nums[-1])
        return 1 + max(a, b, c)
