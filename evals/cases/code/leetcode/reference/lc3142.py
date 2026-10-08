# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def satisfiesConditions(self, grid: List[List[int]]) -> bool:
        m, n = len(grid), len(grid[0])
        for i, row in enumerate(grid):
            for j, x in enumerate(row):
                if i + 1 < m and x != grid[i + 1][j]:
                    return False
                if j + 1 < n and x == grid[i][j + 1]:
                    return False
        return True
