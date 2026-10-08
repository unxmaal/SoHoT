# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def countSubarrays(self, nums: List[int]) -> int:
        return sum(
            (nums[i - 1] + nums[i + 1]) * 2 == nums[i] for i in range(1, len(nums) - 1)
        )
