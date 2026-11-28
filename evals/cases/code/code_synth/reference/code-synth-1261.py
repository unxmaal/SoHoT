# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = sorted(xs, key=abs)
    xs = [x * 5 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x > 0]
    xs = [x // 2 for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 9 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x % 3 for x in xs]
    xs = xs[-5:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return sorted(xs)[:2]
