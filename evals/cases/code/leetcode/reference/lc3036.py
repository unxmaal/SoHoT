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

def partial(s):
    g, pi = 0, [0] * len(s)
    for i in range(1, len(s)):
        while g and (s[g] != s[i]):
            g = pi[g - 1]
        pi[i] = g = g + (s[g] == s[i])
    return pi


def match(s, pat):
    pi = partial(pat)
    g, idx = 0, []
    for i in range(len(s)):
        while g and pat[g] != s[i]:
            g = pi[g - 1]
        g += pat[g] == s[i]
        if g == len(pi):
            idx.append(i + 1 - g)
            g = pi[g - 1]
    return idx


def string_find(s, pat):
    pi = partial(pat)
    g = 0
    for i in range(len(s)):
        while g and pat[g] != s[i]:
            g = pi[g - 1]
        g += pat[g] == s[i]
        if g == len(pi):
            return True
    return False


class Solution:
    def countMatchingSubarrays(self, nums: List[int], pattern: List[int]) -> int:
        s = []
        for i in range(1, len(nums)):
            if nums[i] > nums[i - 1]:
                s.append(1)
            elif nums[i] == nums[i - 1]:
                s.append(0)
            else:
                s.append(-1)
        return len(match(s, pattern))
