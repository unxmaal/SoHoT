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
    def maxPossibleScore(self, start: List[int], d: int) -> int:
        def check(mi: int) -> bool:
            last = -inf
            for st in start:
                if last + mi > st + d:
                    return False
                last = max(st, last + mi)
            return True

        start.sort()
        l, r = 0, start[-1] + d - start[0]
        while l < r:
            mid = (l + r + 1) >> 1
            if check(mid):
                l = mid
            else:
                r = mid - 1
        return l
