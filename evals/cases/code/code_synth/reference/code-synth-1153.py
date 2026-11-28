# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[2:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = xs[::3]
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = [x + 4 for x in xs]
    xs = list(dict.fromkeys(xs))
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
