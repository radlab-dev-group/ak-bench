from math_utils import sum_of_squares


def test_sum_of_squares():
    assert sum_of_squares([1, 2, 3]) == 14
    assert sum_of_squares([]) == 0
    assert sum_of_squares([-1, 2]) == 5
