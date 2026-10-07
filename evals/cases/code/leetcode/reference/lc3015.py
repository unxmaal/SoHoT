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
    def countOfPairs(self, n: int, x: int, y: int) -> List[int]:
        x, y = x - 1, y - 1
        ans = [0] * n
        for i in range(n):
            for j in range(i + 1, n):
                a = j - i
                b = abs(i - x) + 1 + abs(j - y)
                c = abs(i - y) + 1 + abs(j - x)
                ans[min(a, b, c) - 1] += 2
        return ans
