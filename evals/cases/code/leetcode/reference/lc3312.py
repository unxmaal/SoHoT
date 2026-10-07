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
    def gcdValues(self, nums: List[int], queries: List[int]) -> List[int]:
        mx = max(nums)
        cnt = Counter(nums)
        cnt_g = [0] * (mx + 1)
        for i in range(mx, 0, -1):
            v = 0
            for j in range(i, mx + 1, i):
                v += cnt[j]
                cnt_g[i] -= cnt_g[j]
            cnt_g[i] += v * (v - 1) // 2
        s = list(accumulate(cnt_g))
        return [bisect_right(s, q) for q in queries]
