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
    def maxSum(self, nums: List[int]) -> int:
        mx = max(nums)
        if mx <= 0:
            return mx
        ans = 0
        s = set()
        for x in nums:
            if x < 0 or x in s:
                continue
            ans += x
            s.add(x)
        return ans
