# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/humaneval-pro@cd078f93d57d1902b5c3e4ae330166b2ca0e0e80, item 9.
from typing import List, Tuple


def rolling_max(numbers: List[int]) -> List[int]:
    """ From a given list of integers, generate a list of rolling maximum element found until given moment
    in the sequence.
    >>> rolling_max([1, 2, 3, 2, 3, 4, 2])
    [1, 2, 3, 3, 3, 4, 4]
    """
    running_max = None
    result = []

    for n in numbers:
        if running_max is None:
            running_max = n
        else:
            running_max = max(running_max, n)

        result.append(running_max)

    return result


# Given a list of lists of integers, generate a list of lists where each sublist contains the rolling maximum elements for the corresponding sublist in the input. Additionally, find the maximum element across all sublists at each rolling position and return this as a single list.
from typing import List


def rolling_max_across_lists(list_of_lists: List[List[int]]) -> Tuple[List[List[int]], List[int]]:
    rolling_max_lists = [rolling_max(sublist) for sublist in list_of_lists]
    max_across_lists = [max(elements) for elements in zip(*rolling_max_lists)]
    return rolling_max_lists, max_across_lists

# Example usage:
# rolling_max_across_lists([[1, 2, 3, 2, 3, 4, 2], [5, 6, 2, 8, 3, 1, 9]])
