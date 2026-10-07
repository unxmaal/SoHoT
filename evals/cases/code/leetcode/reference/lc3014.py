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
    def minimumPushes(self, word: str) -> int:
        n = len(word)
        ans, k = 0, 1
        for _ in range(n // 8):
            ans += k * 8
            k += 1
        ans += k * (n % 8)
        return ans
