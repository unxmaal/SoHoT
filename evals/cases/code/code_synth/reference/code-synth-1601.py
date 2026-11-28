# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = [x for x in xs if x % 3 != 0]
    xs = [int(x / 4) for x in xs]
    xs = xs[-3:]
    xs = [x for x in xs if x > -1]
    xs = xs[:2]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = list(dict.fromkeys(xs))
    xs = [x * 3 for x in xs]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[:2]
