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
    def stringSequence(self, target: str) -> List[str]:
        ans = []
        for c in target:
            s = ans[-1] if ans else ""
            for a in ascii_lowercase:
                t = s + a
                ans.append(t)
                if a == c:
                    break
        return ans
