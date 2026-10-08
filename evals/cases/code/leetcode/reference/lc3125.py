# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxNumber(self, n: int) -> int:
        return (1 << (n.bit_length() - 1)) - 1
