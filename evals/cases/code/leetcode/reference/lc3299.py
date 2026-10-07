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
    def getSum(self, nums: List[int]) -> int:
        def calc(nums: List[int]) -> int:
            n = len(nums)
            left = [0] * n
            right = [0] * n
            cnt = Counter()
            for i in range(1, n):
                cnt[nums[i - 1]] += 1 + cnt[nums[i - 1] - 1]
                left[i] = cnt[nums[i] - 1]
            cnt = Counter()
            for i in range(n - 2, -1, -1):
                cnt[nums[i + 1]] += 1 + cnt[nums[i + 1] + 1]
                right[i] = cnt[nums[i] + 1]
            return sum((l + r + l * r) * x for l, r, x in zip(left, right, nums)) % mod

        mod = 10**9 + 7
        x = calc(nums)
        nums.reverse()
        y = calc(nums)
        return (x + y + sum(nums)) % mod
