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
  def countArrays(self, original: list[int], bounds: list[list[int]]) -> int:
    mn, mx = bounds[0]

    for i in range(1, len(original)):
      diff = original[i] - original[i - 1]
      mn = max(mn + diff, bounds[i][0])
      mx = min(mx + diff, bounds[i][1])

    return max(0, mx - mn + 1)
