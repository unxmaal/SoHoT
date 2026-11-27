# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def term(n):
    def mul(x, y):
        return [[sum(x[i][t] * y[t][j] for t in range(3)) % 1000000007 for j in range(3)] for i in range(3)]
    if n < 3:
        return [3, 0, 4][n] % 1000000007
    m, out = [[4, 1, 4], [1, 0, 0], [0, 1, 0]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    e = n - 2
    while e:
        if e & 1:
            out = mul(out, m)
        m = mul(m, m)
        e >>= 1
    return (out[0][0] * 4 + out[0][1] * 0 + out[0][2] * 3) % 1000000007
