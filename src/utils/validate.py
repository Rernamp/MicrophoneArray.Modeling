import numpy as np

def is_vector_1d(array: [np.ndarray]):
    return array.ndim == 1

def validate_vector(arr:[np.ndarray]):
    if not is_vector_1d(arr):
        raise ValueError(f"Expected 1D array, got shape {arr.shape}. ndim {arr.ndim}")

def generate_delays(signal:[np.ndarray], delays_s:[np.ndarray]):
    validate_vector(signal)
    validate_vector(delays_s)