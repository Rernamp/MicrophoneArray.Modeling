import numpy as np
import matplotlib.pyplot as plt
from utils.validate import validate_vector

sin_frequency = 440
sample_rate = 48e3
duration_s = 0.1
sin_phi0 = 0
number_samples = int(duration_s * sample_rate)
samples_for_one_period = int(sample_rate / sin_frequency)

time_points = np.linspace(0, duration_s, number_samples, endpoint=False)
y = np.sin(2 * np.pi * time_points * sin_frequency + sin_phi0)
validate_vector(y)

plt.plot(time_points, y)

plt.grid(True)
plt.show()