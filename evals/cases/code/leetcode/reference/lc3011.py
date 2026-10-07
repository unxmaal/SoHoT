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
    def canSortArray(self, nums: List[int]) -> bool:
        pre_mx = 0
        i, n = 0, len(nums)
        while i < n:
            cnt = nums[i].bit_count()
            j = i + 1
            mi = mx = nums[i]
            while j < n and nums[j].bit_count() == cnt:
                mi = min(mi, nums[j])
                mx = max(mx, nums[j])
                j += 1
            if pre_mx > mi:
                return False
            pre_mx = mx
            i = j
        return True
