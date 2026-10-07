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
    def maximumSubarraySum(self, nums: List[int], k: int) -> int:
        ans = -inf
        p = {nums[0]: 0}
        s, n = 0, len(nums)
        for i, x in enumerate(nums):
            s += x
            if x - k in p:
                ans = max(ans, s - p[x - k])
            if x + k in p:
                ans = max(ans, s - p[x + k])
            if i + 1 < n and (nums[i + 1] not in p or p[nums[i + 1]] > s):
                p[nums[i + 1]] = s
        return 0 if ans == -inf else ans
