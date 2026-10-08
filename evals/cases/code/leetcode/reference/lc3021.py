# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def flowerGame(self, n: int, m: int) -> int:
        a1 = (n + 1) // 2
        b1 = (m + 1) // 2
        a2 = n // 2
        b2 = m // 2
        return a1 * b2 + a2 * b1
