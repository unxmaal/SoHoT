# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minimumSumSubarray(self, nums: List[int], l: int, r: int) -> int:
        n = len(nums)
        ans = inf
        for i in range(n):
            s = 0
            for j in range(i, n):
                s += nums[j]
                if l <= j - i + 1 <= r and s > 0:
                    ans = min(ans, s)
        return -1 if ans == inf else ans
