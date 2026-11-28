# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = xs[::2]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = xs[-2:]
    xs = xs[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = xs[:4]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 3 != 0]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[:2]
    xs = [x // 3 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(xs))
    xs = xs[::3]
    xs = xs[::-1]
    return sum(xs)
