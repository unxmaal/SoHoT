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
    def minimumAddedInteger(self, nums1: List[int], nums2: List[int]) -> int:
        def f(x: int) -> bool:
            i = j = cnt = 0
            while i < len(nums1) and j < len(nums2):
                if nums2[j] - nums1[i] != x:
                    cnt += 1
                else:
                    j += 1
                i += 1
            return cnt <= 2

        nums1.sort()
        nums2.sort()
        ans = inf
        for i in range(3):
            x = nums2[0] - nums1[i]
            if f(x):
                ans = min(ans, x)
        return ans
