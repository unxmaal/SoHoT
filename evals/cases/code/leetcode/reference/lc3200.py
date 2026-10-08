# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxHeightOfTriangle(self, red: int, blue: int) -> int:
        ans = 0
        for k in range(2):
            c = [red, blue]
            i, j = 1, k
            while i <= c[j]:
                c[j] -= i
                j ^= 1
                ans = max(ans, i)
                i += 1
        return ans
