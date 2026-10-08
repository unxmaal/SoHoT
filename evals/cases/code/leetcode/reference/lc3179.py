# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def valueAfterKSeconds(self, n: int, k: int) -> int:
        a = [1] * n
        mod = 10**9 + 7
        for _ in range(k):
            for i in range(1, n):
                a[i] = (a[i] + a[i - 1]) % mod
        return a[n - 1]
