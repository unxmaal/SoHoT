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
    def assignElements(self, groups: List[int], elements: List[int]) -> List[int]:
        mx = max(groups)
        d = [-1] * (mx + 1)
        for j, x in enumerate(elements):
            if x > mx or d[x] != -1:
                continue
            for y in range(x, mx + 1, x):
                if d[y] == -1:
                    d[y] = j
        return [d[x] for x in groups]
