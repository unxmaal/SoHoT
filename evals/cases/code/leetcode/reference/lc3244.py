# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def shortestDistanceAfterQueries(
        self, n: int, queries: List[List[int]]
    ) -> List[int]:
        nxt = list(range(1, n))
        ans = []
        cnt = n - 1
        for u, v in queries:
            if 0 < nxt[u] < v:
                i = nxt[u]
                while i < v:
                    cnt -= 1
                    nxt[i], i = 0, nxt[i]
                nxt[u] = v
            ans.append(cnt)
        return ans
