# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 4]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [min(7, max(-1, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    xs = sorted(xs)
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 7 != 0]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    return sum(xs)
