# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minOperations(self, nums: List[int]) -> int:
        ans = v = 0
        for x in nums:
            x ^= v
            if x == 0:
                ans += 1
                v ^= 1
        return ans
