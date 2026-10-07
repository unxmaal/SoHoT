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
    def betterCompression(self, compressed: str) -> str:
        cnt = Counter()
        i, n = 0, len(compressed)
        while i < n:
            j = i + 1
            x = 0
            while j < n and compressed[j].isdigit():
                x = x * 10 + int(compressed[j])
                j += 1
            cnt[compressed[i]] += x
            i = j
        return "".join(sorted(f"{k}{v}" for k, v in cnt.items()))
