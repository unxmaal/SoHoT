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
    def minOrAfterOperations(self, nums: List[int], k: int) -> int:
        ans = 0
        rans = 0
        for i in range(29, -1, -1):
            test = ans + (1 << i)
            cnt = 0
            val = 0
            for num in nums:
                if val == 0:
                    val = test & num
                else:
                    val &= test & num
                if val:
                    cnt += 1
            if cnt > k:
                rans += 1 << i
            else:
                ans += 1 << i
        return rans
