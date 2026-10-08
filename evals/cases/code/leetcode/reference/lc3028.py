# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def returnToBoundaryCount(self, nums: List[int]) -> int:
        return sum(s == 0 for s in accumulate(nums))
