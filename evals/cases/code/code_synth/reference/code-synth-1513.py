# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[1:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-4:]
    xs = [x + -3 for x in xs]
    xs = [x % 6 for x in xs]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = xs[-2:]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x + -3 for x in xs]
    xs = [x * -1 for x in xs]
    return len(set(xs))
