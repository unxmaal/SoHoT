# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def triangleType(self, nums: List[int]) -> str:
        nums.sort()
        if nums[0] + nums[1] <= nums[2]:
            return "none"
        if nums[0] == nums[2]:
            return "equilateral"
        if nums[0] == nums[1] or nums[1] == nums[2]:
            return "isosceles"
        return "scalene"
