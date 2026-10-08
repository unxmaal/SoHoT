# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minimumPushes(self, word: str) -> int:
        cnt = Counter(word)
        ans = 0
        for i, x in enumerate(sorted(cnt.values(), reverse=True)):
            ans += (i // 8 + 1) * x
        return ans
