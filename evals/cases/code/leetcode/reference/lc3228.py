# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxOperations(self, s: str) -> int:
        ans = cnt = 0
        for i, c in enumerate(s):
            if c == "1":
                cnt += 1
            elif i and s[i - 1] == "1":
                ans += cnt
        return ans
