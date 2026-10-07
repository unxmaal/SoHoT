# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 8.
# Write a function to sort a given matrix in ascending order according to the sum of its rows.
def sort_matrix(M):
    result = sorted(M, key=sum)
    return result


# Given a list of matrices, write a function to sort each matrix in ascending order according to the sum of its rows, and then return a list of the sorted matrices. If two matrices have the same sum, they should remain in the order they were provided.
def sort_matrices(matrices):
    sorted_matrices = [sort_matrix(matrix) for matrix in matrices]
    return sorted(sorted_matrices, key=lambda x: sum(sum(row) for row in x))
