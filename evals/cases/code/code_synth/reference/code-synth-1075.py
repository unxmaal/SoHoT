# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = xs[1:]
    xs = xs[:5]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[-3:]
    xs = [x for x in xs if x >= 0]
    return sum(xs)
