# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxAdjacentDistance(self, nums: List[int]) -> int:
        return max(max(abs(a - b) for a, b in pairwise(nums)), abs(nums[0] - nums[-1]))
