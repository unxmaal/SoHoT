# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def addedInteger(self, nums1: List[int], nums2: List[int]) -> int:
        return min(nums2) - min(nums1)
