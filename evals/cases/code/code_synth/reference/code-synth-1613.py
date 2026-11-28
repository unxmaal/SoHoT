# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x % 6 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x + 4 for x in xs]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 1]
    xs = [x * x for x in xs]
    xs = [min(3, max(-5, x)) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x >= 0]
    xs = xs[-4:]
    return sorted(xs)[:2]
