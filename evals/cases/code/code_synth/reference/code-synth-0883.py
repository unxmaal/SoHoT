# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def term(n):
    def mul(x, y):
        return [[sum(x[i][t] * y[t][j] for t in range(3)) % 1000000007 for j in range(3)] for i in range(3)]
    if n < 3:
        return [4, 3, 3][n] % 1000000007
    m, out = [[5, 5, 1], [1, 0, 0], [0, 1, 0]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    e = n - 2
    while e:
        if e & 1:
            out = mul(out, m)
        m = mul(m, m)
        e >>= 1
    return (out[0][0] * 3 + out[0][1] * 3 + out[0][2] * 4) % 1000000007
