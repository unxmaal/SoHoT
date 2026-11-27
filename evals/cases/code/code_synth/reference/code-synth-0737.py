# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def term(n):
    def mul(x, y):
        return [[sum(x[i][t] * y[t][j] for t in range(3)) % 998244353 for j in range(3)] for i in range(3)]
    if n < 3:
        return [0, 1, 3][n] % 998244353
    m, out = [[1, 4, 2], [1, 0, 0], [0, 1, 0]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    e = n - 2
    while e:
        if e & 1:
            out = mul(out, m)
        m = mul(m, m)
        e >>= 1
    return (out[0][0] * 3 + out[0][1] * 1 + out[0][2] * 0) % 998244353
