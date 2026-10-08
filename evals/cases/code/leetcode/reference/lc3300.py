# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minElement(self, nums: List[int]) -> int:
        return min(sum(int(b) for b in str(x)) for x in nums)
