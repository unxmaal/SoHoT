# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-5:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x > -3]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 4 for x in xs]
    xs = [x * x for x in xs]
    xs = [x % 6 for x in xs]
    xs = xs[::-1]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    return max(xs) if xs else -1
