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

# 树状数组模板
class Fenwick:
    def __init__(self, n: int):
        self.tree = [0] * (n + 1)

    def add(self, i: int) -> None:
        while i < len(self.tree):
            self.tree[i] += 1
            i += i & -i

    # [1,i] 中的元素和
    def pre(self, i: int) -> int:
        res = 0
        while i > 0:
            res += self.tree[i]
            i &= i - 1
        return res

    # [l,r] 中的元素和
    def query(self, l: int, r: int) -> int:
        return self.pre(r) - self.pre(l - 1)

class Solution:
    def maxRectangleArea(self, xCoord: List[int], yCoord: List[int]) -> int:
        points = sorted(zip(xCoord, yCoord))
        ys = sorted(set(yCoord))  # 离散化用

        ans = -1
        tree = Fenwick(len(ys))
        tree.add(bisect_left(ys, points[0][1]) + 1)  # 离散化
        pre = {}
        for (x1, y1), (x2, y2) in pairwise(points):
            y = bisect_left(ys, y2) + 1  # 离散化
            tree.add(y)
            if x1 != x2:  # 两点不在同一列
                continue
            cur = tree.query(bisect_left(ys, y1) + 1, y)
            if y2 in pre and pre[y2][1] == y1 and pre[y2][2] + 2 == cur:
                ans = max(ans, (x2 - pre[y2][0]) * (y2 - y1))
            pre[y2] = (x1, y1, cur)
        return ans
