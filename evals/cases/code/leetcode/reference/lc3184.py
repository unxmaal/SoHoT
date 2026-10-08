# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def countCompleteDayPairs(self, hours: List[int]) -> int:
        cnt = Counter()
        ans = 0
        for x in hours:
            ans += cnt[(24 - (x % 24)) % 24]
            cnt[x % 24] += 1
        return ans
