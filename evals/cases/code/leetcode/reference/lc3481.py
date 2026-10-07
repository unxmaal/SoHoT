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
    def applySubstitutions(self, replacements: List[List[str]], text: str) -> str:
        def dfs(s: str) -> str:
            i = s.find("%")
            if i == -1:
                return s
            j = s.find("%", i + 1)
            if j == -1:
                return s
            key = s[i + 1 : j]
            replacement = dfs(d[key])
            return s[:i] + replacement + dfs(s[j + 1 :])

        d = {s: t for s, t in replacements}
        return dfs(text)
