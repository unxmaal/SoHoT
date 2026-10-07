# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 21.
# Write a function to find the maximum difference between available pairs in the given tuple list.
def max_difference(test_list):
  return max(abs(a - b) for a, b in test_list)


# Given a list of tuples, each containing two integers, write a function to find the maximum sum of differences between all possible pairs of tuples. Each tuple in the list should be compared with every other tuple exactly once.
def max_sum_of_differences(tuple_list):
    max_sum = 0
    for i in range(len(tuple_list)):
        for j in range(i + 1, len(tuple_list)):
            max_sum += max_difference([tuple_list[i], tuple_list[j]])
    return max_sum
