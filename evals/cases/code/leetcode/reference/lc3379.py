# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def constructTransformedArray(self, nums: List[int]) -> List[int]:
        ans = []
        n = len(nums)
        for i, x in enumerate(nums):
            ans.append(nums[(i + x + n) % n] if x else 0)
        return ans
