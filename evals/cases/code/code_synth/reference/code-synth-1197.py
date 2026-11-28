# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x % 9 for x in xs]
    xs = sorted(xs)
    xs = [x + 4 for x in xs]
    xs = xs[:3]
    xs = [x + -1 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x >= 0]
    xs = [x % 9 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(5, max(-3, x)) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return max(xs) if xs else -1
