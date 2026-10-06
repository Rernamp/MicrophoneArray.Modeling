import numpy as np
from scipy.fft import fft, ifft, fftshift

def delay(input_signal, delay_samples):
    input_signal_fft = fft(input_signal)
    samples_count = len(input_signal)
    index = np.linspace(0, samples_count - 1, len(input_signal))
    shiftCoef = np.exp(-1j* 2 * np.pi * index * delay_samples / samples_count + np.pi * 1j * delay_samples)
    fft_delayed_signal = np.multiply(input_signal_fft, fftshift(shiftCoef))
    delayed_signal = np.real(ifft(fft_delayed_signal))
    return delayed_signal