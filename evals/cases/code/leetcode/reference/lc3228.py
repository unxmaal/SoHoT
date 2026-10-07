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
    def maxOperations(self, s: str) -> int:
        ans = cnt = 0
        for i, c in enumerate(s):
            if c == "1":
                cnt += 1
            elif i and s[i - 1] == "1":
                ans += cnt
        return ans
