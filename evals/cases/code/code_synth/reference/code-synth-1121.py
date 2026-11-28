# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = xs[3:]
    xs = xs[:3]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x > 4]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = xs[-3:]
    xs = xs[:5]
    xs = [x * x for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    xs = sorted(xs, reverse=True)
    return sum(xs)
