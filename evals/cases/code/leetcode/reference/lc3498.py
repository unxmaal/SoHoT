# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def reverseDegree(self, s: str) -> int:
        ans = 0
        for i, c in enumerate(s, 1):
            x = 26 - (ord(c) - ord("a"))
            ans += i * x
        return ans
