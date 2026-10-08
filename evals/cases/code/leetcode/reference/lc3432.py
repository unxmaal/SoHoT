# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def countPartitions(self, nums: List[int]) -> int:
        l, r = 0, sum(nums)
        ans = 0
        for x in nums[:-1]:
            l += x
            r -= x
            ans += (l - r) % 2 == 0
        return ans
