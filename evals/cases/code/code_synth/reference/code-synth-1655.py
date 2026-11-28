# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x // 2 for x in xs]
    xs = xs[2:]
    xs = sorted(xs, key=abs)
    xs = [int(x / 2) for x in xs]
    xs = [x % 5 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
