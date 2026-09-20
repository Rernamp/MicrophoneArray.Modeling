import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd

    return mo, np, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Delay of sensors
    $$
        \tau_n= \frac{\textbf{a}^T \textbf{p}_n}{c},
    $$
    where $\textbf{p}_n$ - sensors pose, $c$ - sound speed,
    $$
        \mathbf{a} = \begin{bmatrix} -\sin\theta \cos\phi \\ -\sin\theta \sin\phi \\ -\cos\theta \end{bmatrix}.
    $$
    $\theta$ - polar angle, $\phi$ - azimuthal angle
    """)
    return


@app.cell
def _(mo):
    number_elements = 4
    square_side_widget = mo.ui.slider(value=36e-3, start=1e-3, stop=10,step=1e-3, label="Square side, m", include_input=True)
    polar_angle_widget = mo.ui.slider(value=90, start=0, stop=90,step=5e-1, label="Polar angle, deg", include_input=True)
    azimuthal_angle_widget = mo.ui.slider(value=45, start=-180, stop=180,step=5e-1, label="Azimuthal angle, deg", include_input=True)
    sample_rate_widget = mo.ui.slider(value=48000, start=8000, stop=192000,step=1e3, label="Sample rate, Hz", include_input=True)
    return (
        azimuthal_angle_widget,
        polar_angle_widget,
        sample_rate_widget,
        square_side_widget,
    )


@app.cell
def _(
    azimuthal_angle_widget,
    mo,
    polar_angle_widget,
    sample_rate_widget,
    square_side_widget,
):
    mo.vstack([
        square_side_widget,
        polar_angle_widget,
        azimuthal_angle_widget,
        sample_rate_widget
    ])
    return


@app.cell
def _(azimuthal_angle_widget, np, polar_angle_widget, square_side_widget):
    square_side = square_side_widget.value
    poses = np.array([
        [square_side / 2, square_side / 2, 0],
        [-square_side / 2, square_side / 2, 0],
        [square_side / 2, -square_side / 2, 0],
        [-square_side / 2, -square_side / 2, 0],
    ]).T
    polar_angle = np.deg2rad(polar_angle_widget.value)
    azimuthal_angle = np.deg2rad(azimuthal_angle_widget.value)
    a = np.array([
        -np.sin(polar_angle) * np.cos(azimuthal_angle),
        -np.sin(polar_angle) * np.sin(azimuthal_angle),
        -np.cos(polar_angle)
    ])
    print(f"a {a.shape}, poses {poses.shape}")
    print(f"a {a}")
    print(f"poses {poses}")

    return a, poses


@app.cell
def _(a, poses):
    c = 343
    tau = (a.T @ poses) / c
    print(tau)
    return (tau,)


@app.cell
def _(pd, poses, sample_rate_widget, tau):
    sample_rate = sample_rate_widget.value
    table = {
        "posesX": poses[0,:],
        "posesY": poses[1,:],
        "posesZ": poses[2,:],
        "tau":tau,
        "tau_ms":tau * 1e3,
        "tau_sample":tau * sample_rate
    }
    df = pd.DataFrame(table)
    df
    return


if __name__ == "__main__":
    app.run()
