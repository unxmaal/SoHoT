# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x for x in xs if x % 7 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x // 3 for x in xs]
    xs = xs[:2]
    xs = [x + 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 != 0]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 7]
    xs = xs[:3]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return xs
