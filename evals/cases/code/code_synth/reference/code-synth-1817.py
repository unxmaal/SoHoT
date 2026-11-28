# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 5]
    xs = [x % 8 for x in xs]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 7 for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    return len(set(xs))
