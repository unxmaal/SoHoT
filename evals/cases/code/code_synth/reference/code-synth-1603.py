# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 != 0]
    xs = [x // 3 for x in xs]
    xs = xs[:4]
    xs = [x * x for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x + 4 for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [int(x / 4) for x in xs]
    xs = xs[::-1]
    return sorted(xs)[:2]
