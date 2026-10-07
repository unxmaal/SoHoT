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
    def maximumEnergy(self, energy: List[int], k: int) -> int:
        ans = -inf
        n = len(energy)
        for i in range(n - k, n):
            j, s = i, 0
            while j >= 0:
                s += energy[j]
                ans = max(ans, s)
                j -= k
        return ans
