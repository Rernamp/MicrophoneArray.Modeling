import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from scipy.fft import fft, ifft, fftshift
    from scipy import signal
    from utils.signal import delay

    return delay, go, mo, np


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    FFT fractional delay described in [cite](https://dsp.stackexchange.com/questions/60476/how-to-do-fft-fractional-time-delay-solved)
    """)
    return


@app.cell
def _(mo):
    samples_count_widget = mo.ui.slider(value=10, start=2, stop=100, step=1e-2, label="Samples count", include_input=True)
    samples_count_widget
    return (samples_count_widget,)


@app.cell
def _(mo, samples_count_widget):
    samples_count = (int)(samples_count_widget.value)
    delay_samples_widget = mo.ui.slider(value=0, start=0, stop=samples_count, step=1e-2, label="Delay sample", include_input=True)
    delay_samples_widget
    return delay_samples_widget, samples_count


@app.cell
def _(delay_samples_widget, np, samples_count):
    _rng = np.random.default_rng(1)
    original_signal = _rng.uniform(0, 1, samples_count)
    delay_samples = delay_samples_widget.value
    return delay_samples, original_signal


@app.cell
def _(delay, delay_samples, np, original_signal, samples_count):
    n = 100
    resampled_indexes = np.linspace(0, samples_count * n - 1, samples_count * n) / n

    _x_old = np.arange(len(original_signal))
    _x_new = np.linspace(0, len(original_signal) - 1, (len(original_signal) - 1) * n + 1)

    resampled_delay_samples = int(delay_samples * n)
    resampled_signal = delay(np.interp(_x_new, _x_old, original_signal), resampled_delay_samples)
    resampled_delay_samples
    return resampled_indexes, resampled_signal


@app.cell
def _(delay, delay_samples, np, original_signal, samples_count):
    index = np.linspace(0, samples_count - 1, samples_count)
    delayed_signal = delay(original_signal, delay_samples)
    return delayed_signal, index


@app.cell
def _(
    delayed_signal,
    go,
    index,
    original_signal,
    resampled_indexes,
    resampled_signal,
):
    fig = go.Figure(
        data=[
            go.Scatter(x=index, y=original_signal, name="original_signal", mode="lines"),
            go.Scatter(x=index, y=delayed_signal, name="delayed_signal", mode="lines"),        
            go.Scatter(x=resampled_indexes, y=resampled_signal, name="resampled_signal", mode="lines"),        
        ]
    )

    fig
    return


if __name__ == "__main__":
    app.run()
