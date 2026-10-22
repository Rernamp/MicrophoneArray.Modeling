import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import io
    from scipy.io import wavfile

    return io, mo, wavfile


@app.cell
def _(mo):

    wav_file_w = mo.ui.file(label="wav file")
    wav_file_w
    return (wav_file_w,)


@app.cell
def _(io, wav_file_w, wavfile):
    file = wav_file_w.value
    sample_rate, raw_samples = wavfile.read(io.BytesIO(file[0].contents))
    return


@app.cell
def _():
    f_sin = 1021
    return


if __name__ == "__main__":
    app.run()
