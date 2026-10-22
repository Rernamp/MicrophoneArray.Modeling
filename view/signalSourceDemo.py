import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go
    from rnmp.widgets.signal_source import generate_signal, signal_source, signal_source_view

    return generate_signal, go, mo, np, signal_source, signal_source_view


@app.cell
def _(np):
    sample_rate = 48000
    duration = 0.01
    time = np.arange(int(sample_rate * duration)) / sample_rate
    return duration, sample_rate, time


@app.cell
def _(duration, sample_rate, signal_source):
    signal_ui = signal_source(sample_rate, duration)
    return (signal_ui,)


@app.cell
def _(signal_source_view, signal_ui):
    signal_source_view(signal_ui)
    return


@app.cell
def _(generate_signal, signal_ui, time):
    input_signal = generate_signal(signal_ui.value, time)
    return (input_signal,)


@app.cell
def _(go, input_signal, time):
    go.Figure(go.Scatter(x=time, y=input_signal, mode="lines", name="input_signal"))
    return


if __name__ == "__main__":
    app.run()
