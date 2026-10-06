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
def _():
    f_sin = 1
    sample_rate = 100
    samples_count = 100
    return f_sin, sample_rate, samples_count


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    FFT fractional delay described in [cite](https://dsp.stackexchange.com/questions/60476/how-to-do-fft-fractional-time-delay-solved)
    """)
    return


@app.cell(hide_code=True)
def _():
    oversamples_factor = 100
    return (oversamples_factor,)


@app.cell
def _(mo, oversamples_factor, samples_count):
    _step = 1 / oversamples_factor
    delay_samples_widget = mo.ui.slider(value=0, start=0, stop=samples_count, step=_step, label="Delay sample", include_input=True)
    delay_samples_widget
    return (delay_samples_widget,)


@app.cell
def _(delay_samples_widget, f_sin, np, sample_rate, samples_count):
    indexes = np.linspace(0, samples_count - 1, samples_count)
    original_signal = np.sin(2 * np.pi * f_sin * indexes / sample_rate)

    delay_samples = delay_samples_widget.value
    return delay_samples, original_signal


@app.cell
def _():
    return


@app.cell
def _(
    delay_samples,
    f_sin,
    mo,
    np,
    oversamples_factor,
    sample_rate,
    samples_count,
):
    oversampled_indexes = np.linspace(0, samples_count * oversamples_factor - 1, samples_count * oversamples_factor) / oversamples_factor

    oversampled_delay_samples = int(delay_samples * oversamples_factor)

    oversampled_delayed_signal = np.sin(2 * np.pi * f_sin * oversampled_indexes / sample_rate)

    oversampled_delayed_signal = np.roll(oversampled_delayed_signal, oversampled_delay_samples)
    # oversampled_delayed_signal = delay(oversampled_delayed_signal, oversampled_delay_samples)
    mo.md(f"delay_samples: {delay_samples} oversampled_delay_samples {oversampled_delay_samples}")
    return oversampled_delayed_signal, oversampled_indexes


@app.cell
def _(oversampled_delayed_signal, oversamples_factor):
    decimade_signal = oversampled_delayed_signal[::oversamples_factor]
    return (decimade_signal,)


@app.cell
def _(delay, delay_samples, np, original_signal, samples_count):
    index = np.linspace(0, samples_count - 1, samples_count)
    delayed_signal = delay(original_signal, delay_samples)
    return delayed_signal, index


@app.cell
def _(
    decimade_signal,
    delayed_signal,
    go,
    index,
    original_signal,
    oversampled_delayed_signal,
    oversampled_indexes,
):
    fig = go.Figure(
        data=[
            go.Scatter(x=index, y=original_signal, name="original_signal", mode="lines"),
            go.Scatter(x=index, y=delayed_signal, name="delayed_signal", mode="lines"),
            go.Scatter(x=oversampled_indexes, y=oversampled_delayed_signal, name="oversampled_signal", mode="lines"),
            go.Scatter(x=index, y=decimade_signal, name="decimade_signal", mode="lines"),
            go.Scatter(x=index, y=(decimade_signal-delayed_signal), name="delta_", mode="lines"),
        ]
    )

    fig
    return


if __name__ == "__main__":
    app.run()
