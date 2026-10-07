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
    def getSmallestString(self, s: str, k: int) -> str:
        cs = list(s)
        for i, c1 in enumerate(s):
            for c2 in ascii_lowercase:
                if c2 >= c1:
                    break
                d = min(ord(c1) - ord(c2), 26 - ord(c1) + ord(c2))
                if d <= k:
                    cs[i] = c2
                    k -= d
                    break
        return "".join(cs)
