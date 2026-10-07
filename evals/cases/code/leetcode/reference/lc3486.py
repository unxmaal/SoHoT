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
  # Similar to 3425. Longest Special Path
  def longestSpecialPath(
      self,
      edges: list[list[int]],
      nums: list[int]
  ) -> list[int]:
    maxLength = 0
    minNodes = 1
    graph = [[] for _ in range(len(nums))]

    for u, v, w in edges:
      graph[u].append((v, w))
      graph[v].append((u, w))

    prefix = [0]
    lastSeenDepth = {}

    def dfs(
        u: int,
        prev: int,
        leftBoundary: list[int],
    ) -> None:
      nonlocal maxLength, minNodes
      prevDepth = lastSeenDepth.get(nums[u], 0)
      lastSeenDepth[nums[u]] = len(prefix)

      if prevDepth != 0:
        leftBoundary = sorted(leftBoundary + [prevDepth])[-2:]

      length = prefix[-1] - prefix[leftBoundary[0]]
      nodes = len(prefix) - leftBoundary[0]
      if length > maxLength or (length == maxLength and nodes < minNodes):
        maxLength = length
        minNodes = nodes

      for v, w in graph[u]:
        if v == prev:
          continue
        prefix.append(prefix[-1] + w)
        dfs(v, u, leftBoundary)
        prefix.pop()

      lastSeenDepth[nums[u]] = prevDepth

    dfs(0, -1, leftBoundary=[0, 0])
    return [maxLength, minNodes]
