# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def orArray(self, nums: List[int]) -> List[int]:
        return [a | b for a, b in pairwise(nums)]
