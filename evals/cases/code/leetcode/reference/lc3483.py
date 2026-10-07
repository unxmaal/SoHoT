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
    def totalNumbers(self, digits: List[int]) -> int:
        s = set()
        for i, a in enumerate(digits):
            if a & 1:
                continue
            for j, b in enumerate(digits):
                if i == j:
                    continue
                for k, c in enumerate(digits):
                    if c == 0 or k in (i, j):
                        continue
                    s.add(c * 100 + b * 10 + a)
        return len(s)
