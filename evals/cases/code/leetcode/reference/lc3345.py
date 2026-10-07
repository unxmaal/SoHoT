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
    def smallestNumber(self, n: int, t: int) -> int:
        for i in count(n):
            p = 1
            x = i
            while x:
                p *= x % 10
                x //= 10
            if p % t == 0:
                return i
