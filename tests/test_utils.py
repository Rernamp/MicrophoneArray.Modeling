import pytest
import sys
import os
import numpy as np

import utils.validate as validate

def test_valid_array_check():
    test_array = np.array([1])
    assert validate.is_vector_1d(test_array)
    assert validate.validate_vector(test_array) is None

def test_invalid_array_check():
    test_array = np.array([[], []])
    assert not validate.is_vector_1d(test_array)
    with pytest.raises(ValueError):
        validate.validate_vector(test_array)

