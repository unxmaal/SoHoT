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
    def calculateScore(self, s: str) -> int:
        d = defaultdict(list)
        ans = 0
        for i, x in enumerate(s):
            y = chr(ord("a") + ord("z") - ord(x))
            if d[y]:
                j = d[y].pop()
                ans += i - j
            else:
                d[x].append(i)
        return ans
