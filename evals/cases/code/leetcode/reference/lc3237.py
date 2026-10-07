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
    def simulationResult(self, windows: List[int], queries: List[int]) -> List[int]:
        s = set()
        ans = []
        for q in queries[::-1]:
            if q not in s:
                ans.append(q)
                s.add(q)
        for w in windows:
            if w not in s:
                ans.append(w)
        return ans
