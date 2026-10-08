# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def areaOfMaxDiagonal(self, dimensions: List[List[int]]) -> int:
        ans = mx = 0
        for l, w in dimensions:
            t = l**2 + w**2
            if mx < t:
                mx = t
                ans = l * w
            elif mx == t:
                ans = max(ans, l * w)
        return ans
