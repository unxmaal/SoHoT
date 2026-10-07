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
  def maxFrequency(self, nums: list[int], k: int) -> int:
    return nums.count(k) + max(self._kadane(nums, target, k)
                               for target in range(1, 51)
                               if target != k)

  def _kadane(self, nums: list[int], target: int, k: int) -> int:
    """
    Returns the maximum achievable frequency of `k` by Kakane's algorithm,
    where each `target` in subarrays is transformed to `k`.
    """
    maxSum = 0
    sum = 0
    for num in nums:
      if num == target:
        sum += 1
      elif num == k:
        sum -= 1
      if sum < 0:  # Reset sum if it becomes negative (Kadane's spirit).
        sum = 0
      maxSum = max(maxSum, sum)
    return maxSum
