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
    def minimumOperations(self, grid: List[List[int]]) -> int:
        ans = 0
        for col in zip(*grid):
            pre = -1
            for cur in col:
                if pre < cur:
                    pre = cur
                else:
                    pre += 1
                    ans += pre - cur
        return ans
