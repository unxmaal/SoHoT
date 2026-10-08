# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def countPrefixSuffixPairs(self, words: List[str]) -> int:
        ans = 0
        for i, s in enumerate(words):
            for t in words[i + 1 :]:
                ans += t.endswith(s) and t.startswith(s)
        return ans
