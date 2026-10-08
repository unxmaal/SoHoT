# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def hasMatch(self, s: str, p: str) -> bool:
        i = 0
        for t in p.split("*"):
            j = s.find(t, i)
            if j == -1:
                return False
            i = j + len(t)
        return True
