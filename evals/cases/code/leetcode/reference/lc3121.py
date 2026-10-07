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
    def numberOfSpecialChars(self, word: str) -> int:
        first, last = {}, {}
        for i, c in enumerate(word):
            if c not in first:
                first[c] = i
            last[c] = i
        return sum(
            a in last and b in first and last[a] < first[b]
            for a, b in zip(ascii_lowercase, ascii_uppercase)
        )
