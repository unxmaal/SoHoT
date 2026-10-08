# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxScore(self, nums: List[int]) -> int:
        s = sum(nums)
        if len(nums) & 1:
            return s - min(nums)
        return s - min(a + b for a, b in pairwise(nums))
