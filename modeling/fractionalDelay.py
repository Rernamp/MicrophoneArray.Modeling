import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    FFT fractional delay described in [cite](https://dsp.stackexchange.com/questions/60476/how-to-do-fft-fractional-time-delay-solved)
    """)
    return


@app.cell
def _(mo):
    sin_frequency_widget = mo.ui.slider(start=1, stop=1e3, step=1, include_input=True, label="Sin frequency, Hz")
    sin_frequency_widget
    return


if __name__ == "__main__":
    app.run()
