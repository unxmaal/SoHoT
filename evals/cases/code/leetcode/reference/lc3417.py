# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def zigzagTraversal(self, grid: List[List[int]]) -> List[int]:
        ok = True
        ans = []
        for i, row in enumerate(grid):
            if i % 2:
                row.reverse()
            for x in row:
                if ok:
                    ans.append(x)
                ok = not ok
        return ans
