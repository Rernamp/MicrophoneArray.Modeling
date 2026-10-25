import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import io
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    import plotly.express as px
    from scipy import signal

    from rnmp.widgets import signal_views

    from scipy.io import wavfile

    return io, mo, np, signal, signal_views, wavfile


@app.cell
def _(mo):
    wav_file_w = mo.ui.file(label="wav file")
    wav_file_w
    return (wav_file_w,)


@app.cell
def _(io, mo, wav_file_w, wavfile):

    file = wav_file_w.value

    mo.stop(not file, mo.md("Wait to load file"))

    sample_rate, raw_samples = wavfile.read(io.BytesIO(file[0].contents))
    return raw_samples, sample_rate


@app.cell
def _(np, raw_samples, sample_rate):
    samples_count = raw_samples.shape[0]
    channels_count = raw_samples.shape[1]
    _indexes = np.linspace(0, samples_count-1, samples_count)
    time_points = _indexes / sample_rate
    return (time_points,)


@app.cell
def _(raw_samples):
    viewed_signal = raw_samples[:200,:]
    return (viewed_signal,)


@app.cell(hide_code=True)
def _(signal_views, time_points, viewed_signal):
    signal_views.plot_signals(time_points, viewed_signal)
    return


@app.cell
def _(signal, viewed_signal):
    upsampled_signal = signal.resample_poly(viewed_signal, up=8, down=1)
    return (upsampled_signal,)


@app.cell
def _(signal_views, time_points, upsampled_signal):
    signal_views.plot_signals(time_points, upsampled_signal)
    return


@app.cell
def _(np, time_points, viewed_signal):
    f = 1021
    time_sin = time_points[0:viewed_signal.shape[0]]
    ref_sin = np.sin(2 * np.pi * time_sin * f)
    return (ref_sin,)


@app.cell
def _(ref_sin, signal, signal_views, time_points, viewed_signal):
    _index = 0
    r = signal.correlate(ref_sin, viewed_signal[:,_index], mode='full', method='fft')
    lags = signal.correlation_lags(len(ref_sin), len(viewed_signal[:,_index]))
    r_norm = r / r[lags == 0]
    signal_views.plot_signals(time_points, r_norm)
    return


if __name__ == "__main__":
    app.run()
