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
    def sumDigitDifferences(self, nums: List[int]) -> int:
        n = len(nums)
        m = int(log10(nums[0])) + 1
        ans = 0
        for _ in range(m):
            cnt = Counter()
            for i, x in enumerate(nums):
                nums[i], y = divmod(x, 10)
                cnt[y] += 1
            ans += sum(v * (n - v) for v in cnt.values()) // 2
        return ans
