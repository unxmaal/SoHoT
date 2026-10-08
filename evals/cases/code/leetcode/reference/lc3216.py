# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def getSmallestString(self, s: str) -> str:
        for i, (a, b) in enumerate(pairwise(map(ord, s))):
            if (a + b) % 2 == 0 and a > b:
                return s[:i] + s[i + 1] + s[i] + s[i + 2 :]
        return s
