# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x + 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = xs[::2]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 4 != 0]
    xs = [int(x / 2) for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, reverse=True)
    return sum(xs)
