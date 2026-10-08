# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def hasSameDigits(self, s: str) -> bool:
        t = list(map(int, s))
        n = len(t)
        for k in range(n - 1, 1, -1):
            for i in range(k):
                t[i] = (t[i] + t[i + 1]) % 10
        return t[0] == t[1]
