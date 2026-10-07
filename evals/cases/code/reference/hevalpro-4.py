from typing import List


def mean_absolute_deviation(numbers: List[float]) -> float:
    """ For a given list of input numbers, calculate Mean Absolute Deviation
    around the mean of this dataset.
    Mean Absolute Deviation is the average absolute difference between each
    element and a centerpoint (mean in this case):
    MAD = average | x - x_mean |
    >>> mean_absolute_deviation([1.0, 2.0, 3.0, 4.0])
    1.0
    """
    mean = sum(numbers) / len(numbers)
    return sum(abs(x - mean) for x in numbers) / len(numbers)


# Given a list of lists of numbers, calculate the Mean Absolute Deviation (MAD) for each sublist and then find the overall Mean Absolute Deviation of these MADs. The overall MAD should be calculated around the mean of the MADs of the sublists.
def overall_mean_absolute_deviation(list_of_lists: List[List[float]]) -> float:
    mad_values = [mean_absolute_deviation(sublist) for sublist in list_of_lists]
    return mean_absolute_deviation(mad_values)
