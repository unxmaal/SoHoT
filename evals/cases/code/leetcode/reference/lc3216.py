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
    def getSmallestString(self, s: str) -> str:
        for i, (a, b) in enumerate(pairwise(map(ord, s))):
            if (a + b) % 2 == 0 and a > b:
                return s[:i] + s[i + 1] + s[i] + s[i + 2 :]
        return s
