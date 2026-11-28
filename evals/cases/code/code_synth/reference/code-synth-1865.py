# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x // 3 for x in xs]
    xs = [x for x in xs if x > 4]
    xs = [int(x / 2) for x in xs]
    xs = [x for x in xs if x > -2]
    xs = [min(6, max(-2, x)) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = [x // 2 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs)
    return sorted(xs)[:2]
