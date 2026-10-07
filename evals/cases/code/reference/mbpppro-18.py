# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 18.
# Write a function to find the nth octagonal number.
def is_octagonal(n):
    return 3 * n * n - 2 * n


# Given a list of integers, determine the sum of the first 10 octagonal numbers for each integer in the list. If an integer is less than 1, return 0 for that integer.
def sum_of_octagonal_numbers(lst):
    result = []
    for num in lst:
        if num < 1:
            result.append(0)
        else:
            sum_octagonal = sum(is_octagonal(i) for i in range(1, min(num, 10) + 1))
            result.append(sum_octagonal)
    return result
