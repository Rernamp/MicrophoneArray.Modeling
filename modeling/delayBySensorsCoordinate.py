import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np

    return (mo,)


@app.cell
def _(mo):
    element_pos_ui = mo.ui.matrix([[1, 1, 1]])
    elements = mo.ui.array([element_pos_ui], )
    elements
    return


if __name__ == "__main__":
    app.run()
