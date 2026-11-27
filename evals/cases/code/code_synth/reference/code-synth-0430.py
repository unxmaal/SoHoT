# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(rows):
    tot = {}
    for n, d, s in rows:
        a = tot.setdefault(d, [0, 0])
        a[0] += s
        a[1] += 1
    return sorted(n for n, d, s in rows if s * tot[d][1] > tot[d][0])
