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
    def minimumLevels(self, possible: List[int]) -> int:
        s = sum(-1 if x == 0 else 1 for x in possible)
        t = 0
        for i, x in enumerate(possible[:-1], 1):
            t += -1 if x == 0 else 1
            if t > s - t:
                return i
        return -1
