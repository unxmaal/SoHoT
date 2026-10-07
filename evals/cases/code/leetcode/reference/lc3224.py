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
    def minChanges(self, nums: List[int], k: int) -> int:
        d = [0] * (k + 2)
        n = len(nums)
        for i in range(n // 2):
            x, y = nums[i], nums[-i - 1]
            if x > y:
                x, y = y, x
            d[0] += 1
            d[y - x] -= 1
            d[y - x + 1] += 1
            d[max(y, k - x) + 1] -= 1
            d[max(y, k - x) + 1] += 2
        return min(accumulate(d))
