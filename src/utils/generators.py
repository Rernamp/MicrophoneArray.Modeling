import numpy as np
from scipy.signal import chirp


def sine(time, frequency, amplitude=1.0, phase_deg=0.0):
    return amplitude * np.sin(2 * np.pi * frequency * time + np.deg2rad(phase_deg))


def gaussian_pulse(time, center, width, amplitude=1.0):
    return amplitude * np.exp(-0.5 * ((time - center) / width) ** 2)


def linear_chirp(time, f_start, f_stop, amplitude=1.0):
    return amplitude * chirp(time, f0=f_start, t1=time[-1], f1=f_stop, method="linear")


def white_noise(time, amplitude=1.0, seed=0):
    rng = np.random.default_rng(int(seed))
    return amplitude * rng.standard_normal(len(time))
