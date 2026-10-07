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
    def maxFrequency(self, nums: List[int], k: int, numOperations: int) -> int:
        cnt = defaultdict(int)
        d = defaultdict(int)
        for x in nums:
            cnt[x] += 1
            d[x] += 0
            d[x - k] += 1
            d[x + k + 1] -= 1
        ans = s = 0
        for x, t in sorted(d.items()):
            s += t
            ans = max(ans, min(s, cnt[x] + numOperations))
        return ans
