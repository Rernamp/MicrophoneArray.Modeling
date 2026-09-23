import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    speed_widget = mo.ui.slider(value=343, start=300, step=1e-3, stop=3e8, include_input=True, label="Speed, m/s")
    sin_frequency_widget = mo.ui.slider(value=300, start=1, step=1e-3, stop=3e8, include_input=True, label="Sin frequency, Hz")
    return sin_frequency_widget, speed_widget


@app.cell
def _(mo, sin_frequency_widget, speed_widget):
    mo.vstack([
        speed_widget,
        sin_frequency_widget
    ])
    return


@app.cell
def _(sin_frequency_widget, speed_widget):
    wavelength = 1e3 * speed_widget.value / sin_frequency_widget.value
    half_wavelength = wavelength / 2
    return half_wavelength, wavelength


@app.cell(hide_code=True)
def _(half_wavelength, mo, wavelength):
    mo.md(f"""
    $\lambda$ = {wavelength} mm

    $\lambda$ = {half_wavelength} mm
    """)
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
