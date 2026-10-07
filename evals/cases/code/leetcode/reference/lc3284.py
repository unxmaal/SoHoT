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
        mod = 10**9 + 7
        f = g = 1
        s = t = nums[0]
        ans = nums[0]
        for x, y in pairwise(nums):
            if y - x == 1:
                f += 1
                s += f * y
                ans = (ans + s) % mod
            else:
                f = 1
                s = y
            if y - x == -1:
                g += 1
                t += g * y
                ans = (ans + t) % mod
            else:
                g = 1
                t = y
            if abs(y - x) != 1:
                ans = (ans + y) % mod
        return ans
