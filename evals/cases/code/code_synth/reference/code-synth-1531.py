# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x for x in xs if x > 5]
    xs = xs[-2:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[:2]
    xs = [x for x in xs if x % 3 != 0]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 7 for x in xs]
    xs = xs[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:3]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sorted(xs)[:2]
