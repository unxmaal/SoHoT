# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def smallestNumber(self, n: int, t: int) -> int:
        for i in count(n):
            p = 1
            x = i
            while x:
                p *= x % 10
                x //= 10
            if p % t == 0:
                return i
