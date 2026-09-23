import marimo

__generated_with = "0.24.2"
app = marimo.App()


@app.cell(hide_code=True)
def _():
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from utils.validate import validate_vector
    import scipy.fft as fft
    import altair as alt
    import marimo as mo

    return alt, mo, np, pd


@app.cell(hide_code=True)
def _():
    f = 100
    samples = 1024
    sample_rate = 48000
    return f, sample_rate, samples


@app.cell(hide_code=True)
def _(f, np, sample_rate, samples, timeList):
    indexes = np.linspace(0, samples - 1, samples)
    waveform = np.sin(2 * np.pi * f * timeList / sample_rate)
    return (waveform,)


@app.cell(hide_code=True)
def _(duration_s, mo):
    tDelaySlider = mo.ui.slider(-duration_s, duration_s, 0.0001, value= 1e-4, label="delay", include_input=True)
    mo.vstack([tDelaySlider])
    return (tDelaySlider,)


@app.cell(hide_code=True)
def _(np, tDelaySlider, waveform):
    tDelay = tDelaySlider.value
    fftData = np.fft.fft(waveform)
    return fftData, tDelay


@app.cell(hide_code=True)
def _(fftData, np, samples, tDelay, tend, tstart):
    samplePeriod = (tend - tstart) / (samples)
    tDelayInSamples = tDelay / samplePeriod
    N = fftData.shape[0]
    k = np.linspace(0, N-1, N) - np.floor(N / 2)
    timeDelayPhaseShift = np.exp(((-2*np.pi*1j*k*tDelayInSamples)/(N)) + (tDelayInSamples*np.pi*1j))

    # 3. Do the fftshift on the phase shift coefficients
    timeDelayPhaseShift = np.fft.ifftshift(timeDelayPhaseShift)

    # 4. Multiply the fft data with the coefficients to apply the time shift
    fftWithDelay = np.multiply(fftData, timeDelayPhaseShift)
    shiftedWaveform = np.fft.ifft(fftWithDelay)
    return (shiftedWaveform,)


@app.cell(hide_code=True)
def _(alt, mo, np, pd, shiftedWaveform, tDelay, waveform):
    df = pd.DataFrame({
        'time': np.linspace(0, len(waveform) - 1, len(waveform)),
        'orig_signal': waveform,
        'delayed_signal': shiftedWaveform.real,
    })

    data = df.melt(id_vars=['time'], var_name='Тип сигнала', value_name='Амплитуда')

    # Строим график с цветовой кодировкой
    chart = alt.Chart(data).mark_line().encode(
        x=alt.X('time:Q', title='Время, с'),
        y=alt.Y('Амплитуда:Q', title='Амплитуда'),
        color=alt.Color('Тип сигнала:N', title='Сигнал')
    ).properties(
        width=700,
        height=400,
        title=f'Delayed by {tDelay} second'
    ).interactive()

    reactive_chart = mo.ui.altair_chart(chart)
    reactive_chart
    return


if __name__ == "__main__":
    app.run()
