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
  def separateSquares(self, squares: list[list[int]]) -> float:
    halfArea = sum((l**2 for _, _, l in squares)) / 2
    events = sorted([(y, True, l) for _, y, l in squares] +
                    [(y + l, False, l) for _, y, l in squares])
    area = 0
    width = 0
    prevY = 0

    for y, isStart, l in events:
      areaGain = width * (y - prevY)
      if area + areaGain >= halfArea:
        return prevY + (halfArea - area) / width
      area += areaGain
      width += l if isStart else -l
      prevY = y
