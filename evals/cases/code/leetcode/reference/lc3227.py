# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def doesAliceWin(self, s: str) -> bool:
        vowels = set("aeiou")
        return any(c in vowels for c in s)
