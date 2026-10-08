# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def isSubstringPresent(self, s: str) -> bool:
        st = {(a, b) for a, b in pairwise(s[::-1])}
        return any((a, b) in st for a, b in pairwise(s))
