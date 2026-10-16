import numpy as np
from scipy.fft import fft, ifft, fftshift


def delay(input_signal, delay_samples):
    input_signal_fft = fft(input_signal)
    samples_count = len(input_signal)
    index = np.linspace(0, samples_count - 1, len(input_signal))
    shiftCoef = np.exp(-1j * 2 * np.pi * index * delay_samples /
                       samples_count + np.pi * 1j * delay_samples)
    fft_delayed_signal = np.multiply(input_signal_fft, fftshift(shiftCoef))
    delayed_signal = np.real(ifft(fft_delayed_signal))
    return delayed_signal

def generate_noise(signal_shape, signal_power, snr_db, rng=None):
    if rng is None:
        rng = np.random.default_rng()

    noise_power = signal_power / (10 ** (snr_db / 10.0))
    noise_std = np.sqrt(noise_power)

    noise = rng.normal(loc=0.0, scale=noise_std, size=signal_shape)
    return noise

def add_noise(signal, target_snr_db):
    signal_power = np.mean(np.abs(signal) ** 2)
    snr_linear = 10 ** (target_snr_db / 10)
    noise_power = signal_power / snr_linear
    noise_sigma = np.sqrt(noise_power)
    noise = np.random.normal(0, noise_sigma, size=signal.shape)

    return signal + noise