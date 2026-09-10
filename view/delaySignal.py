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

    return alt, mo, np, pd


@app.cell
def _():
    f1 = 12.8
    f2 = 22.6
    samples = 1024
    tstart = 0.0
    tend = 1.0
    duration_s = tend - tstart
    return duration_s, f1, f2, samples, tend, tstart


@app.cell
def _(f1, f2, np, samples, tend, tstart):
    timeList = np.linspace(tstart, tend, samples)
    waveform = np.sin(2 * np.pi * f1 * timeList) + 1*np.sin(2 * np.pi * f2 * timeList)
    return (waveform,)


@app.cell
def _(duration_s, mo):
    tDelaySlider = mo.ui.slider(-duration_s, duration_s, 0.0001, value= 1e-4, label="delay")
    mo.vstack([tDelaySlider])
    return (tDelaySlider,)


@app.cell
def _(np, tDelaySlider, waveform):
    tDelay = tDelaySlider.value
    fftData = np.fft.fft(waveform)
    return fftData, tDelay


@app.cell
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


@app.cell
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
