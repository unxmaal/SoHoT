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
    def minConnectedGroups(self, intervals: List[List[int]], k: int) -> int:
        intervals.sort()
        merged = [intervals[0]]
        for s, e in intervals[1:]:
            if merged[-1][1] < s:
                merged.append([s, e])
            else:
                merged[-1][1] = max(merged[-1][1], e)
        ans = len(merged)
        for i, (_, e) in enumerate(merged):
            j = bisect_left(merged, [e + k + 1, 0])
            ans = min(ans, len(merged) - (j - i - 1))
        return ans
