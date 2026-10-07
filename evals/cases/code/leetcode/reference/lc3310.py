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
    def remainingMethods(
        self, n: int, k: int, invocations: List[List[int]]
    ) -> List[int]:
        def dfs(i: int):
            suspicious[i] = True
            for j in g[i]:
                if not suspicious[j]:
                    dfs(j)

        def dfs2(i: int):
            vis[i] = True
            for j in f[i]:
                if not vis[j]:
                    suspicious[j] = False
                    dfs2(j)

        f = [[] for _ in range(n)]
        g = [[] for _ in range(n)]
        for a, b in invocations:
            f[a].append(b)
            f[b].append(a)
            g[a].append(b)
        suspicious = [False] * n
        dfs(k)

        vis = [False] * n
        ans = []
        for i in range(n):
            if not suspicious[i] and not vis[i]:
                dfs2(i)
        return [i for i in range(n) if not suspicious[i]]
