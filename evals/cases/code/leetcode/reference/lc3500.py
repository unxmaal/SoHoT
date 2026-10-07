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
    def minimumCost(self, nums: List[int], cost: List[int], k: int) -> int:
        n = len(nums)
        s = list(accumulate(cost, initial=0))  # cost 的前缀和
        f = [0] * (n + 1)
        for i, sum_num in enumerate(accumulate(nums), 1):  # 这里把 i 加一了，下面不用加一
            f[i] = min(f[j] + sum_num * (s[i] - s[j]) + k * (s[n] - s[j])
                       for j in range(i))
        return f[n]
