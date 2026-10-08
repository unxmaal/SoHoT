# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def minCosts(self, cost: List[int]) -> List[int]:
        for i in range(1, len(cost)):
            cost[i] = min(cost[i], cost[i - 1])
        return cost
