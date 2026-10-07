# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/humaneval-pro@cd078f93d57d1902b5c3e4ae330166b2ca0e0e80, item 0.
from typing import List


def has_close_elements(numbers: List[float], threshold: float) -> bool:
    """ Check if in given list of numbers, are any two numbers closer to each other than
    given threshold.
    >>> has_close_elements([1.0, 2.0, 3.0], 0.5)
    False
    >>> has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
    True
    """
    for idx, elem in enumerate(numbers):
        for idx2, elem2 in enumerate(numbers):
            if idx != idx2:
                distance = abs(elem - elem2)
                if distance < threshold:
                    return True

    return False


# Given a list of lists of floats, determine if there exists any list where at least two numbers are closer to each other than a given threshold. If such a list exists, return the indices of the lists where this condition is met. If no such list exists, return an empty list.
def find_close_elements_lists(list_of_lists: List[List[float]], threshold: float) -> List[int]:
    """ Find the indices of lists where at least two numbers are closer to each other than the given threshold.
    >>> find_close_elements_lists([[1.0, 2.0, 3.0], [1.0, 2.8, 3.0, 4.0, 5.0, 2.0]], 0.5)
    [1]
    >>> find_close_elements_lists([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], 0.3)
    []
    """
    return [i for i, lst in enumerate(list_of_lists) if has_close_elements(lst, threshold)]
