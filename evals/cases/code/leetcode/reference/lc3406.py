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
  def answerString(self, word: str, numFriends: int) -> str:
    if numFriends == 1:
      return word
    s = self._lastSubstring(word)
    sz = len(word) - numFriends + 1
    return s[:min(len(s), sz)]

  # Same as 1163. Last Substring in Lexicographical Order
  def _lastSubstring(self, s: str) -> str:
    i = 0
    j = 1
    k = 0  # the number of the same letters of s[i..n) and s[j..n)

    while j + k < len(s):
      if s[i + k] == s[j + k]:
        k += 1
      elif s[i + k] > s[j + k]:
        # Skip s[j..j + k) and advance to s[j + k + 1] to find a possible
        # lexicographically larger substring since s[i..i + k) == s[j..j + k)
        # and s[i + k] > s[j + k).
        j = j + k + 1
        k = 0
      else:
        # Skip s[i..i + k) and advance to s[i + k + 1] or s[j] to find a
        # possible lexicographically larger substring since
        # s[i..i + k) == s[j..j + k) and s[i + k] < s[j + k).
        # Note that it's unnecessary to explore s[i + k + 1..j) if
        # i + k + 1 < j since they are already explored by j.
        i = max(i + k + 1, j)
        j = i + 1
        k = 0

    return s[i:]
