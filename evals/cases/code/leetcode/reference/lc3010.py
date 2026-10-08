# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minimumCost(self, nums: List[int]) -> int:
        a, b, c = nums[0], inf, inf
        for x in nums[1:]:
            if x < b:
                c, b = b, x
            elif x < c:
                c = x
        return a + b + c
