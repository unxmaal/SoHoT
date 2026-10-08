# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minimumOperations(self, grid: List[List[int]]) -> int:
        ans = 0
        for col in zip(*grid):
            pre = -1
            for cur in col:
                if pre < cur:
                    pre = cur
                else:
                    pre += 1
                    ans += pre - cur
        return ans
