# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minimumLength(self, s: str) -> int:
        cnt = Counter(s)
        return sum(1 if x & 1 else 2 for x in cnt.values())
