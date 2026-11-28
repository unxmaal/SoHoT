# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x % 5 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > -2]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [x % 8 for x in xs]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = xs[::3]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = [x // 4 for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
