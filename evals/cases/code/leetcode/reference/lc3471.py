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
    def largestInteger(self, nums: List[int], k: int) -> int:
        def f(k: int) -> int:
            for i, x in enumerate(nums):
                if i != k and x == nums[k]:
                    return -1
            return nums[k]

        if k == 1:
            cnt = Counter(nums)
            return max((x for x, v in cnt.items() if v == 1), default=-1)
        if k == len(nums):
            return max(nums)
        return max(f(0), f(len(nums) - 1))
