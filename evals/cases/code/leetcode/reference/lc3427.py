# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def subarraySum(self, nums: List[int]) -> int:
        s = list(accumulate(nums, initial=0))
        return sum(s[i + 1] - s[max(0, i - x)] for i, x in enumerate(nums))
