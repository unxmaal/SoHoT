# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [min(7, max(-2, x)) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[:6]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = xs[::-1]
    xs = [x for x in xs if x > 0]
    xs = [x * 2 for x in xs]
    xs = xs[::3]
    xs = [abs(x) for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = xs[::2]
    return sorted(xs)[:2]
