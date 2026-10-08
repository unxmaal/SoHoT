# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maxWeight(self, pizzas: List[int]) -> int:
        days = len(pizzas) // 4
        pizzas.sort()
        odd = (days + 1) // 2
        even = days - odd
        ans = sum(pizzas[-odd:])
        i = len(pizzas) - odd - 2
        for _ in range(even):
            ans += pizzas[i]
            i -= 2
        return ans
