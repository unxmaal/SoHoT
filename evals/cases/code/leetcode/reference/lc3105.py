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
    def longestMonotonicSubarray(self, nums: List[int]) -> int:
        ans = t = 1
        for i, x in enumerate(nums[1:]):
            if nums[i] < x:
                t += 1
                ans = max(ans, t)
            else:
                t = 1
        t = 1
        for i, x in enumerate(nums[1:]):
            if nums[i] > x:
                t += 1
                ans = max(ans, t)
            else:
                t = 1
        return ans
