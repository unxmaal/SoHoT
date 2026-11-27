# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def perm_rank(s):
    from collections import Counter
    from math import factorial
    counts, rank = Counter(s), 0
    for i, ch in enumerate(s):
        for other in sorted(counts, reverse=False):
            if other == ch:
                break
            if counts[other]:
                counts[other] -= 1
                perms = factorial(len(s) - i - 1)
                for c in counts.values():
                    perms //= factorial(c)
                rank += perms
                counts[other] += 1
        counts[ch] -= 1
    return rank
