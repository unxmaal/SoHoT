# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[3:]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x % 3 != 0]
    xs = [x % 3 for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = xs[:5]
    xs = [x * 3 for x in xs]
    xs = xs[:4]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x // 2 for x in xs]
    xs = xs[:3]
    xs = [int(x / 2) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return len(set(xs))
