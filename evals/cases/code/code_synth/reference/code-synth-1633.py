# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * 5 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [min(3, max(-2, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 4 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x * 3 for x in xs]
    xs = [x for x in xs if x % 2 != 0]
    xs = xs[-3:]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    return sorted(xs)[:2]
