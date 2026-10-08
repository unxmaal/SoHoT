# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def kthCharacter(self, k: int) -> str:
        word = [0]
        while len(word) < k:
            word.extend([(x + 1) % 26 for x in word])
        return chr(ord("a") + word[k - 1])
