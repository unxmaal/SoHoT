# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def transformArray(self, nums: List[int]) -> List[int]:
        even = sum(x % 2 == 0 for x in nums)
        for i in range(even):
            nums[i] = 0
        for i in range(even, len(nums)):
            nums[i] = 1
        return nums
