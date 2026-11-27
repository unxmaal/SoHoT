# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def elimination_order(n):
    people = list(range(1, n + 1))
    i, out = 0, []
    while people:
        i = (i + 2) % len(people)
        out.append(people.pop(i))
    return out
