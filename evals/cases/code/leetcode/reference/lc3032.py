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
    def numberCount(self, a: int, b: int) -> int:
        @cache
        def dfs(pos: int, mask: int, limit: bool) -> int:
            if pos >= len(num):
                return 1 if mask else 0
            up = int(num[pos]) if limit else 9
            ans = 0
            for i in range(up + 1):
                if mask >> i & 1:
                    continue
                nxt = 0 if mask == 0 and i == 0 else mask | 1 << i
                ans += dfs(pos + 1, nxt, limit and i == up)
            return ans

        num = str(a - 1)
        x = dfs(0, 0, True)
        dfs.cache_clear()
        num = str(b)
        y = dfs(0, 0, True)
        return y - x
