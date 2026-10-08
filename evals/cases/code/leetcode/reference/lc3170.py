# Imported by evals/importers from hf:newfacade/LeetCodeDataset@215604aeed660029df7de2fea5a4d7b6ed476a08.
class Solution:
    def clearStars(self, s: str) -> str:
        g = defaultdict(list)
        n = len(s)
        rem = [False] * n
        for i, c in enumerate(s):
            if c == "*":
                rem[i] = True
                for a in ascii_lowercase:
                    if g[a]:
                        rem[g[a].pop()] = True
                        break
            else:
                g[c].append(i)
        return "".join(c for i, c in enumerate(s) if not rem[i])
