# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def maximumPoints(self, enemyEnergies: List[int], currentEnergy: int) -> int:
        enemyEnergies.sort()
        if currentEnergy < enemyEnergies[0]:
            return 0
        ans = 0
        for i in range(len(enemyEnergies) - 1, -1, -1):
            ans += currentEnergy // enemyEnergies[0]
            currentEnergy %= enemyEnergies[0]
            currentEnergy += enemyEnergies[i]
        return ans
