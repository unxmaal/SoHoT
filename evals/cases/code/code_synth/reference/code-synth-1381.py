# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x // 2 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = sorted(xs, key=abs)
    xs = [x + -1 for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[::2]
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 == 0]
    return sum(xs)
