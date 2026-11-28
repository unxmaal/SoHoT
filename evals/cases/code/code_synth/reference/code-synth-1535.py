# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[:4]
    xs = [x * 3 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x % 8 for x in xs]
    xs = xs[-3:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [min(10, max(1, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return max(xs) if xs else -1
