# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def canAliceWin(self, n: int) -> bool:
        x, k = 10, 0
        while n >= x:
            n -= x
            x -= 1
            k += 1
        return k % 2 == 1
