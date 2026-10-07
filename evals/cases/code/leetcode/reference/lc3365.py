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
    def isPossibleToRearrange(self, s: str, t: str, k: int) -> bool:
        cnt = Counter()
        n = len(s)
        m = n // k
        for i in range(0, n, m):
            cnt[s[i : i + m]] += 1
            cnt[t[i : i + m]] -= 1
        return all(v == 0 for v in cnt.values())
