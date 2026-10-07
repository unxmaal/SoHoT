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
    def minMoves(self, rooks: List[List[int]]) -> int:
        rooks.sort()
        ans = sum(abs(x - i) for i, (x, _) in enumerate(rooks))
        rooks.sort(key=lambda x: x[1])
        ans += sum(abs(y - j) for j, (_, y) in enumerate(rooks))
        return ans
