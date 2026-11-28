# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x // 3 for x in xs]
    xs = [x % 5 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[::3]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    xs = [x * -2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    xs = [x * -2 for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sum(xs)
