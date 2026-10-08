# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minOperationsToMakeMedianK(self, nums: List[int], k: int) -> int:
        nums.sort()
        n = len(nums)
        m = n >> 1
        ans = abs(nums[m] - k)
        if nums[m] > k:
            for i in range(m - 1, -1, -1):
                if nums[i] <= k:
                    break
                ans += nums[i] - k
        else:
            for i in range(m + 1, n):
                if nums[i] >= k:
                    break
                ans += k - nums[i]
        return ans
