import marimo

__generated_with = "0.23.16"
app = marimo.App()


@app.cell
def _():
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from utils.validate import validate_vector
    import scipy.fft as fft
    import altair as alt
    import marimo as mo

    return alt, fft, mo, np, pd


@app.cell
def _(mo):
    number_samples_slider = mo.ui.slider(10, 50, 1, value=20, label="number samples")
    return (number_samples_slider,)


@app.cell
def _(number_samples_slider):
    number_samples = number_samples_slider.value
    return (number_samples,)


@app.cell
def _(mo, number_samples):
    delay_samples_slider = mo.ui.slider(-number_samples, number_samples, 0.5, value=0, label="delay samples")
    return (delay_samples_slider,)


@app.cell
def _(delay_samples_slider):
    delay_samples = delay_samples_slider.value
    return (delay_samples,)


@app.cell
def _(np, number_samples):

    indexes = np.linspace(0, number_samples - 1, number_samples)
    return (indexes,)


@app.cell
def _(delay_samples, fft, indexes, np, number_samples):
    shift_exp = fft.fft(np.exp(-1j * 2 * np.pi * delay_samples * indexes / number_samples))
    return (shift_exp,)


@app.cell
def _(
    alt,
    delay_samples,
    delay_samples_slider,
    indexes,
    mo,
    np,
    number_samples_slider,
    pd,
    shift_exp,
):
    df = pd.DataFrame({
        'index': indexes,
        'real_part': np.real(shift_exp),
        'imag_part': np.imag(shift_exp),
    })

    data = df.melt(id_vars=['index'], var_name='Part of complex', value_name='Value')

    chart = alt.Chart(data).mark_line().encode(
        x=alt.X('index:Q', title='Index'),
        y=alt.Y('Value:Q', title='Value'),
        color=alt.Color('Part of complex:N', title='Part of complex')
    ).properties(
        width=600,
        height=400,
        title=f'Delayed by {delay_samples} index'
    ).interactive()

    reactive_chart = mo.ui.altair_chart(chart)
    mo.vstack([number_samples_slider,
    delay_samples_slider,
    reactive_chart])
    return


if __name__ == "__main__":
    app.run()
