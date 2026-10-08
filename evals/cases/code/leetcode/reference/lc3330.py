# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def possibleStringCount(self, word: str) -> int:
        return 1 + sum(x == y for x, y in pairwise(word))
