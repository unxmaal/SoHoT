# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def numberOfChild(self, n: int, k: int) -> int:
        k, mod = divmod(k, n - 1)
        return n - mod - 1 if k & 1 else mod
