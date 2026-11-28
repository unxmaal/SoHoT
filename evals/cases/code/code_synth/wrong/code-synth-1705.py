# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x // 3 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = xs[1:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, key=abs)
    xs = [x + 4 for x in xs]
    xs = xs[:3]
    xs = xs[:2]
    xs = sorted(xs)
    return max(xs) if xs else -1
