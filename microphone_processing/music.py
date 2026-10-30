import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")

with app.setup:
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go

    from rnmp.doa.music import (
        MIC_LAYOUT,
        alias_frequency,
        direction_vectors,
        find_peaks_2d,
        mic_positions,
        music_spectrum,
        read_wav,
        spatial_covariances,
    )
    from rnmp.doa.views import sphere_figure
    from rnmp.widgets import signal_views

    DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # MUSIC: direction of arrival

    The 4-mic square array, broadband MUSIC: the STFT gives a spatial covariance matrix per frequency bin,
    the noise subspace is built per bin and the null spectra are averaged over the selected band.

    Use PCM files (`*_pcm.wav`). Raw-PDM captures have to go through `recordering/pdm_to_pcm.py` first.
    """)
    return


@app.cell
def _():
    _local_files = sorted(p.name for p in DATASETS_DIR.glob("*.wav")) if DATASETS_DIR.is_dir() else []
    dataset_w = mo.ui.dropdown(
        options=_local_files,
        value=next((f for f in _local_files if f.endswith("_pcm.wav")), None),
        label="file from datasets/",
    )
    wav_file_w = mo.ui.file(filetypes=[".wav"], label="or upload a wav file")
    mo.hstack([dataset_w, wav_file_w], justify="start", gap=2)
    return dataset_w, wav_file_w


@app.cell
def _(dataset_w, wav_file_w):
    if wav_file_w.value:
        file_name = wav_file_w.name()
        _data = wav_file_w.contents()
    elif dataset_w.value:
        file_name = dataset_w.value
        _data = (DATASETS_DIR / file_name).read_bytes()
    else:
        mo.stop(True, mo.md("Choose or upload a wav file"))

    try:
        sample_rate, samples, track_names, _is_raw_pdm = read_wav(_data)
    except ValueError as _e:
        mo.stop(True, mo.callout(mo.md(f"Can't read **{file_name}**: {_e}"), kind="danger"))

    mo.stop(
        _is_raw_pdm,
        mo.callout(
            mo.md(f"**{file_name}** is a raw-PDM capture. Convert it first: `python recordering/pdm_to_pcm.py {file_name}`"),
            kind="danger",
        ),
    )

    duration = samples.shape[0] / sample_rate
    mo.md(
        f"**{file_name}**: {sample_rate} Hz, {samples.shape[1]} channels ({', '.join(track_names)}), "
        f"{duration:.2f} s"
    )
    return duration, sample_rate, samples, track_names


@app.cell
def _(duration, sample_rate, track_names):
    _mic_channels = {name: i for i, name in enumerate(track_names) if i in MIC_LAYOUT}
    channels_w = mo.ui.multiselect(options=_mic_channels, value=list(_mic_channels), label="mics")
    radius_w = mo.ui.number(start=1, stop=200, step=0.5, value=20, label="array radius, mm")
    start_w = mo.ui.slider(
        start=0, stop=max(duration - 0.01, 0), step=0.01, value=0, label="start, s", include_input=True
    )
    length_w = mo.ui.slider(
        start=0.01, stop=duration, step=0.01, value=min(1.0, duration), label="length, s", include_input=True
    )
    f_min_w = mo.ui.slider(start=50, stop=sample_rate // 2, step=50, value=500, label="f min, Hz", include_input=True)
    f_max_w = mo.ui.slider(start=50, stop=sample_rate // 2, step=50, value=4000, label="f max, Hz", include_input=True)
    nfft_w = mo.ui.dropdown(options=["256", "512", "1024", "2048", "4096"], value="1024", label="FFT size")
    sources_w = mo.ui.slider(start=1, stop=3, value=1, label="sources", include_input=True)
    grid_step_w = mo.ui.dropdown(options=["1", "2", "5"], value="2", label="grid step, deg")
    db_range_w = mo.ui.slider(start=5, stop=60, step=5, value=30, label="dB range", include_input=True)

    mo.vstack([
        mo.hstack([channels_w, radius_w], justify="start", gap=2),
        mo.hstack([start_w, length_w], justify="start", gap=2),
        mo.hstack([f_min_w, f_max_w, nfft_w], justify="start", gap=2),
        mo.hstack([sources_w, grid_step_w, db_range_w], justify="start", gap=2),
    ])
    return (
        channels_w,
        db_range_w,
        f_max_w,
        f_min_w,
        grid_step_w,
        length_w,
        nfft_w,
        radius_w,
        sources_w,
        start_w,
    )


@app.cell
def _(channels_w, length_w, sample_rate, samples, sources_w, start_w):
    channels = sorted(channels_w.value)
    mo.stop(
        len(channels) <= sources_w.value,
        mo.callout(mo.md(f"MUSIC needs more mics than sources: {len(channels)} mics, {sources_w.value} sources"), kind="warn"),
    )

    _first = int(start_w.value * sample_rate)
    viewed_signal = samples[_first : _first + int(length_w.value * sample_rate), channels]
    time_points = (_first + np.arange(viewed_signal.shape[0])) / sample_rate
    return channels, time_points, viewed_signal


@app.cell(hide_code=True)
def _(time_points, viewed_signal):
    _stride = max(1, viewed_signal.shape[0] // 20000)  # thin out long windows, display only
    signal_views.plot_signals(time_points[::_stride], viewed_signal[::_stride])
    return


@app.cell
def _(
    channels,
    f_max_w,
    f_min_w,
    grid_step_w,
    nfft_w,
    radius_w,
    sample_rate,
    sources_w,
    viewed_signal,
):
    _nfft = int(nfft_w.value)
    mo.stop(viewed_signal.shape[0] < 4 * _nfft, mo.md("The window is too short for this FFT size"))
    mo.stop(f_min_w.value >= f_max_w.value, mo.md("f min must be below f max"))

    freqs, R = spatial_covariances(viewed_signal, sample_rate, _nfft, f_min_w.value, f_max_w.value)
    mo.stop(len(freqs) == 0, mo.md("No FFT bins in the band"))

    positions = mic_positions(channels, radius_w.value * 1e-3)
    _step = int(grid_step_w.value)
    azimuths_deg = np.arange(-180, 180, _step)
    elevations_deg = np.arange(0, 90 + _step, _step).clip(max=90)
    S_MUSIC, eigvals = music_spectrum(
        R, freqs, positions, direction_vectors(azimuths_deg, elevations_deg), sources_w.value
    )
    S_MUSIC_dB = 10 * np.log10(S_MUSIC / S_MUSIC.max())

    alias_freq = alias_frequency(positions)
    return S_MUSIC_dB, alias_freq, azimuths_deg, eigvals, elevations_deg, freqs


@app.cell(hide_code=True)
def _(alias_freq, eigvals, freqs, sources_w):
    _eig_dB = 10 * np.log10(eigvals / eigvals[:, :1])
    _fig = go.Figure([
        go.Scatter(x=freqs, y=_eig_dB[:, i], mode="lines", name=f"λ{i + 1}") for i in range(_eig_dB.shape[1])
    ])
    _fig.update_layout(
        title=f"Covariance eigenvalues vs λ1 — a gap after λ{sources_w.value} means the source count is right",
        xaxis_title="f, Hz",
        yaxis_title="dB",
        height=350,
    )
    _warn = (
        mo.callout(mo.md(f"The band goes above {alias_freq:.0f} Hz: spatial aliasing, ghost peaks are possible"), kind="warn")
        if freqs.max() > alias_freq
        else None
    )
    mo.vstack([_w for _w in [_warn, _fig] if _w is not None])
    return


@app.cell(hide_code=True)
def _(S_MUSIC_dB, azimuths_deg, db_range_w, elevations_deg, sources_w):
    _vmin = -float(db_range_w.value)
    _clipped = np.clip(S_MUSIC_dB, _vmin, 0.0)
    _el_idx, _az_idx = find_peaks_2d(S_MUSIC_dB, sources_w.value)
    peaks = [(azimuths_deg[a], elevations_deg[e], S_MUSIC_dB[e, a]) for e, a in zip(_el_idx, _az_idx)]

    _heatmap = go.Figure(
        go.Heatmap(z=_clipped, x=azimuths_deg, y=elevations_deg, colorscale="Viridis", zmin=_vmin, zmax=0,
                   colorbar=dict(title="dB"))
    )
    _heatmap.add_trace(
        go.Scatter(x=[p[0] for p in peaks], y=[p[1] for p in peaks], mode="markers", name="peaks",
                   marker=dict(symbol="x", size=12, color="red"))
    )
    _heatmap.update_layout(
        title="MUSIC spectrum",
        xaxis_title="azimuth, deg (0 = toward the user, 90 = right)",
        yaxis_title="elevation, deg (90 = up)",
        height=500,
    )

    _sphere = sphere_figure(S_MUSIC_dB, azimuths_deg, elevations_deg, [(az, el) for az, el, _ in peaks], _vmin)

    _peaks_md = "\n".join(f"- azimuth **{az:.0f}°**, elevation **{el:.0f}°** ({db:.1f} dB)" for az, el, db in peaks)
    mo.vstack([mo.md(f"**Peaks:**\n\n{_peaks_md}"), mo.ui.tabs({"Map": _heatmap, "Sphere": _sphere})])
    return


if __name__ == "__main__":
    app.run()
