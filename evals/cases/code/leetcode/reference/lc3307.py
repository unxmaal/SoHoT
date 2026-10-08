# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def kthCharacter(self, k: int, operations: List[int]) -> str:
        n, i = 1, 0
        while n < k:
            n *= 2
            i += 1
        d = 0
        while n > 1:
            if k > n // 2:
                k -= n // 2
                d += operations[i - 1]
            n //= 2
            i -= 1
        return chr(d % 26 + ord("a"))
