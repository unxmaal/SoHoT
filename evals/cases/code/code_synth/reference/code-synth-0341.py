# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [min(4, max(-3, x)) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = xs[:6]
    xs = [x * 5 for x in xs]
    xs = xs[::2]
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-4:]
    xs = xs[:3]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
