# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minimumChairs(self, s: str) -> int:
        cnt = left = 0
        for c in s:
            if c == "E":
                if left:
                    left -= 1
                else:
                    cnt += 1
            else:
                left += 1
        return cnt
