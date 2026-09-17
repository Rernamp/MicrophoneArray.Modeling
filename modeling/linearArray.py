import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd

    return mo, np, pd


@app.cell
def _(mo):
    number_elements_ui = mo.ui.number(value=4, start=2, stop=128, step=1, label="Number elements")
    angle_of_arrival_ui = mo.ui.number(value=0, start=-90, stop=90, step=0.1, label="Angle of arrival (deg)")
    mic_distance_ui = mo.ui.number(value=2e-2, start=1e-2, stop=1, step=1e-3, label="Distance between adjacent elements (m)")
    sample_rate_ui = mo.ui.number(value=48e3, start=8e3, stop=192e3, step=1, label="Sample rate (Hz)")
    return (
        angle_of_arrival_ui,
        mic_distance_ui,
        number_elements_ui,
        sample_rate_ui,
    )


@app.cell
def _(
    angle_of_arrival_ui,
    mic_distance_ui,
    mo,
    number_elements_ui,
    sample_rate_ui,
):
    controls = mo.vstack([number_elements_ui, 
            angle_of_arrival_ui,
            mic_distance_ui,
            sample_rate_ui
    ])
    controls
    return


@app.cell
def _(angle_of_arrival_ui, mic_distance_ui, np, number_elements_ui):
    number_elements = number_elements_ui.value
    index_by_mic = np.linspace(0, number_elements - 1, number_elements)
    mic_distance = mic_distance_ui.value
    angle_of_arrival = angle_of_arrival_ui.value
    speed_of_sound = 343
    delay_by_mic = (index_by_mic * mic_distance * np.sin(np.deg2rad(angle_of_arrival))) / speed_of_sound
    return delay_by_mic, index_by_mic


@app.cell
def _(delay_by_mic, index_by_mic, mo, pd, sample_rate_ui):
    delay_by_mic_ms = delay_by_mic * 1e3
    delay_by_mic_samples = delay_by_mic * sample_rate_ui.value
    mo.ui.table(pd.DataFrame({
        "Mic index": index_by_mic,
        "Delay, samples": delay_by_mic_samples,
        "Delay, s": delay_by_mic,
        "Delay, ms": delay_by_mic_ms,    
    }))
    return


if __name__ == "__main__":
    app.run()
