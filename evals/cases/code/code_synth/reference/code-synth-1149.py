# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = sorted(xs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[1:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x for x in xs if x % 3 != 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * -1 for x in xs]
    xs = [x // 4 for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + 2 for x in xs]
    return len(set(xs))
