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
    def countPartitions(self, nums: List[int]) -> int:
        l, r = 0, sum(nums)
        ans = 0
        for x in nums[:-1]:
            l += x
            r -= x
            ans += (l - r) % 2 == 0
        return ans
