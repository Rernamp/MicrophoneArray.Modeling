import numpy as np

from widgets.signal_source import GENERATORS, generate_signal, signal_source


def test_every_signal_generates_from_ui_defaults():
    sample_rate, duration = 48000, 0.01
    time = np.arange(int(sample_rate * duration)) / sample_rate
    value = signal_source(sample_rate, duration).value

    for kind in GENERATORS:
        signal = generate_signal({**value, "kind": kind}, time)
        assert signal.shape == time.shape
        assert np.all(np.isfinite(signal))


def test_gaussian_pulse_peaks_at_center():
    time = np.linspace(0, 1, 1001)
    value = {"kind": "gauss", "gauss": {"center": 0.3, "width": 0.05, "amplitude": 2.0}}
    signal = generate_signal(value, time)
    assert np.isclose(time[np.argmax(signal)], 0.3)
    assert np.isclose(signal.max(), 2.0)
