# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maximumLengthSubstring(self, s: str) -> int:
        cnt = Counter()
        ans = i = 0
        for j, c in enumerate(s):
            cnt[c] += 1
            while cnt[c] > 2:
                cnt[s[i]] -= 1
                i += 1
            ans = max(ans, j - i + 1)
        return ans
