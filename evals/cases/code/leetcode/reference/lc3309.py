# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxGoodNumber(self, nums: List[int]) -> int:
        ans = 0
        for arr in permutations(nums):
            num = int("".join(bin(i)[2:] for i in arr), 2)
            ans = max(ans, num)
        return ans
