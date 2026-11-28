# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = xs[-4:]
    xs = xs[::2]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    return sum(xs)
