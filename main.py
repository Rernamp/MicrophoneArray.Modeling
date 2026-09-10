import numpy as np
import matplotlib.pyplot as plt


def main():
    duration_s = 1
    sample_rate = 48e3
    
    sin_frequency = 400
    sin_phi0 = np.pi / 2

    num_samples = int(duration_s * sample_rate)
    time_points = np.linspace(0, duration_s, num_samples, endpoint=False)
    
    y = np.sin(2 * np.pi * time_points * sin_frequency + sin_phi0)


if __name__ == "__main__":
    main()
