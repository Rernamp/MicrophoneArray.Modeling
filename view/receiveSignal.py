import marimo

__generated_with = "0.23.14"
app = marimo.App()


@app.cell
def _():
    import numpy as np
    import altair as alt
    import pandas as pd
    import marimo as mo
    import utils.validate as validate

    return alt, mo, np, pd, validate


@app.cell
def _(np):
    sin_frequency = 440
    sample_rate = 48e3
    duration_s = 0.1
    sin_phi0 = np.pi / 2
    number_samples = int(duration_s * sample_rate)
    samples_for_one_period = int(sample_rate / sin_frequency)
    return duration_s, number_samples, sin_frequency, sin_phi0


@app.cell
def _(duration_s, np, number_samples, sin_frequency, sin_phi0, validate):
    time_points = np.linspace(0, duration_s, number_samples, endpoint=False)
    y = np.sin(2 * np.pi * time_points * sin_frequency + sin_phi0)
    validate.validate_vector(y)
    return time_points, y


@app.cell
def _(alt, duration_s, pd, time_points, y):
    y_frame = pd.DataFrame({"time": time_points, "y":y})
    full_line_chart = alt.Chart(y_frame).mark_line(

    ).encode(
        x=alt.X('time:Q', title='Time, s', scale=alt.Scale(domain=[0, duration_s])),
        y=alt.Y('y:Q', title='Amplitude')
    )
    return (full_line_chart,)


@app.cell
def _(full_line_chart, mo):
    chart = mo.ui.altair_chart(full_line_chart)
    chart
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
