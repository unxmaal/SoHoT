# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [int(x / 4) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = xs[-5:]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [min(6, max(1, x)) for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = [x + 2 for x in xs]
    xs = [x // 2 for x in xs]
    xs = [x * -2 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = xs[1:]
    xs = sorted(xs)
    return max(xs) if xs else -1
