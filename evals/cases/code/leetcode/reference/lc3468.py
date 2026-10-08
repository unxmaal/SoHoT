# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
  def countArrays(self, original: list[int], bounds: list[list[int]]) -> int:
    mn, mx = bounds[0]

    for i in range(1, len(original)):
      diff = original[i] - original[i - 1]
      mn = max(mn + diff, bounds[i][0])
      mx = min(mx + diff, bounds[i][1])

    return max(0, mx - mn + 1)
