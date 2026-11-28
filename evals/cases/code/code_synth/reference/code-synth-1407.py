# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [x for x in xs if x > -2]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[-5:]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[1:]
    xs = [x for x in xs if x > 8]
    xs = xs[-4:]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 3 != 0]
    xs = xs[::-1]
    return sum(xs)
