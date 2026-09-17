import marimo

__generated_with = "0.23.15"
app = marimo.App()


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import altair as alt

    return alt, mo, np, pd


@app.cell
def _():
    K = 32
    sample_rate = 48000
    f_sin = 200
    samples_for_one_period = (int)(sample_rate / f_sin)
    return K, f_sin, sample_rate, samples_for_one_period


@app.cell(hide_code=True)
def _(K, f_sin, mo, sample_rate, samples_for_one_period):
    mo.md(rf"""
    **Sample rate**: {sample_rate}

    **K**: {K}

    **Sin frequency**: {f_sin}

    **Samples for one period**: {samples_for_one_period}
    """)
    return


@app.cell
def _(f_sin, np, sample_rate, samples_for_one_period):
    A = 1;
    _indexes = np.linspace(0, samples_for_one_period - 1, samples_for_one_period)
    time_points = _indexes / sample_rate
    y = A * np.sin(2 * np.pi * f_sin * time_points)
    return A, time_points, y


@app.cell
def _(K, sample_rate, samples_for_one_period):
    sample_rate_oversample = sample_rate * K
    samples_for_one_period_oversampled = samples_for_one_period * K
    return sample_rate_oversample, samples_for_one_period_oversampled


@app.cell
def _(np, sample_rate_oversample, samples_for_one_period_oversampled):
    _indexes_oversampled = np.linspace(0, samples_for_one_period_oversampled - 1, samples_for_one_period_oversampled)
    time_points_oversampled = _indexes_oversampled / sample_rate_oversample
    return (time_points_oversampled,)


@app.cell
def _(A, f_sin, np, time_points_oversampled):
    y_oversampled = A * np.sin(2 * np.pi * f_sin * time_points_oversampled)
    return (y_oversampled,)


@app.cell
def _(
    alt,
    chartfor,
    pd,
    time_points,
    time_points_oversampled,
    y,
    y_oversampled,
):
    y_df = pd.DataFrame({'x': time_points, 'y':y})
    y_oversampled_df = pd.DataFrame({'x': time_points_oversampled, 'y_oversampled':y_oversampled})

    chart_y = alt.Chart(y_df).mark_line(color="blue").encode(
        x='x',
        y='y'
    )
    chart_y_oversampled = alt.Chart(y_oversampled_df).mark_line(color="red").encode(
        x='x',
        y='y_oversampled'
    )
    chart = chart_y + chart_y_oversampled
    chartfor 
    return


@app.cell
def _(np, pd, y_oversampled):
    _accumulator = 0
    _prev_output_value = 0
    output_pdm = np.zeros(y_oversampled.shape)
    _states = []
    for i, value in enumerate(y_oversampled):    
        subtracted_value = 1 if _prev_output_value == 1 else -1

        delta = y_oversampled[i] - subtracted_value
        _accumulator += delta
        output_pdm[i] = 1 if _accumulator > 0 else 0
        _prev_output_value = output_pdm[i]

        _states.append({
            "iteration": i,
            "input": y_oversampled[i],
            "subtracted_value":subtracted_value,
            "delta":delta,
            "output_value":_prev_output_value,
            "accumulator":_accumulator
        })    

    state_df = pd.DataFrame(_states)
    state_df
    return (state_df,)


@app.cell
def _(alt, mo, state_df):
    chart_pdm = alt.Chart(state_df).mark_bar(color="blue").encode(
        x='iteration',
        y=alt.Y('output_value', scale=alt.Scale(domain=[-0.1,1.1]))
    
    ).interactive(bind_y=False)
    mo.ui.altair_chart(chart_pdm)
    return


if __name__ == "__main__":
    app.run()
