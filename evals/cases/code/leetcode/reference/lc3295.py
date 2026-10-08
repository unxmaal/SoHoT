# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def reportSpam(self, message: List[str], bannedWords: List[str]) -> bool:
        s = set(bannedWords)
        return sum(w in s for w in message) >= 2
