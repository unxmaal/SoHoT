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
    def medianOfUniquenessArray(self, nums: List[int]) -> int:
        def check(mx: int) -> bool:
            cnt = defaultdict(int)
            k = l = 0
            for r, x in enumerate(nums):
                cnt[x] += 1
                while len(cnt) > mx:
                    y = nums[l]
                    cnt[y] -= 1
                    if cnt[y] == 0:
                        cnt.pop(y)
                    l += 1
                k += r - l + 1
                if k >= (m + 1) // 2:
                    return True
            return False

        n = len(nums)
        m = (1 + n) * n // 2
        return bisect_left(range(n), True, key=check)
