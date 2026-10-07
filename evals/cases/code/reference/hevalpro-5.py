# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/humaneval-pro@cd078f93d57d1902b5c3e4ae330166b2ca0e0e80, item 5.
from typing import List


def intersperse(numbers: List[int], delimeter: int) -> List[int]:
    """ Insert a number 'delimeter' between every two consecutive elements of input list `numbers'
    >>> intersperse([], 4)
    []
    >>> intersperse([1, 2, 3], 4)
    [1, 4, 2, 4, 3]
    """
    if not numbers:
        return []

    result = []

    for n in numbers[:-1]:
        result.append(n)
        result.append(delimeter)

    result.append(numbers[-1])

    return result


# Given a list of integers, intersperse a specified delimiter between every two consecutive elements of the list. Then, repeat this process with a different delimiter for the resulting list. Finally, return the list after both interspersing operations.
from typing import List


def intersperse(numbers: List[int], delimeter: int) -> List[int]:
    result = []
    for i in range(len(numbers)):
        if i > 0:
            result.append(delimeter)
        result.append(numbers[i])
    return result


def double_intersperse(numbers: List[int], delimeter1: int, delimeter2: int) -> List[int]:
    intermediate_list = intersperse(numbers, delimeter1)
    final_list = intersperse(intermediate_list, delimeter2)
    return final_list
