# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def stableMountains(self, height: List[int], threshold: int) -> List[int]:
        return [i for i in range(1, len(height)) if height[i - 1] > threshold]
