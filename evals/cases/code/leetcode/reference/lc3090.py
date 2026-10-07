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
    def maximumLengthSubstring(self, s: str) -> int:
        cnt = Counter()
        ans = i = 0
        for j, c in enumerate(s):
            cnt[c] += 1
            while cnt[c] > 2:
                cnt[s[i]] -= 1
                i += 1
            ans = max(ans, j - i + 1)
        return ans
