# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxDifference(self, s: str) -> int:
        cnt = Counter(s)
        a, b = 0, inf
        for v in cnt.values():
            if v % 2:
                a = max(a, v)
            else:
                b = min(b, v)
        return a - b
