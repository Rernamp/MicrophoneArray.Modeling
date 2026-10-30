import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")

with app.setup:
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from rnmp.doa.music import (
        MIC_LAYOUT,
        alias_frequency,
        band_stft,
        covariances,
        direction_vectors,
        find_peaks_2d,
        mic_positions,
        music_spectrum,
        read_wav,
        steering_vectors,
    )
    from rnmp.doa.video import render_video, stereo_mix
    from rnmp.doa.views import sphere_animation

    DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # MUSIC: direction of arrival vs time

    The recording is cut into windows (STFT frames grouped with an overlap); every window gets its own
    broadband MUSIC spectrum, as in `music.py`. Windows without a clear source are filtered out by the gap
    between the signal and noise eigenvalues and by the energy.

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
    return duration, file_name, sample_rate, samples, track_names


@app.cell
def _(duration, sample_rate, track_names):
    _mic_channels = {name: i for i, name in enumerate(track_names) if i in MIC_LAYOUT}
    params_w = (
        mo.md("""
        {channels} {radius}

        {start} {end}

        {f_min} {f_max} {nfft}

        {window} {step}

        {sources} {grid_step}
        """)
        .batch(
            channels=mo.ui.multiselect(options=_mic_channels, value=list(_mic_channels), label="mics"),
            radius=mo.ui.number(start=1, stop=200, step=0.5, value=20, label="array radius, mm"),
            start=mo.ui.slider(start=0, stop=duration, step=0.1, value=0, label="from, s", include_input=True),
            end=mo.ui.slider(start=0, stop=duration, step=0.1, value=duration, label="to, s", include_input=True),
            f_min=mo.ui.slider(start=50, stop=sample_rate // 2, step=50, value=800, label="f min, Hz", include_input=True),
            f_max=mo.ui.slider(start=50, stop=sample_rate // 2, step=50, value=1200, label="f max, Hz", include_input=True),
            nfft=mo.ui.dropdown(options=["256", "512", "1024", "2048", "4096"], value="1024", label="FFT size"),
            window=mo.ui.slider(start=0.05, stop=5, step=0.05, value=0.25, label="window, s", include_input=True),
            step=mo.ui.slider(start=0.01, stop=5, step=0.01, value=0.1, label="step, s", include_input=True),
            sources=mo.ui.slider(start=1, stop=3, value=1, label="sources", include_input=True),
            grid_step=mo.ui.dropdown(options=["1", "2", "5"], value="2", label="grid step, deg"),
        )
        .form(submit_button_label="Compute")
    )
    params_w
    return (params_w,)


@app.cell
def _(params_w, sample_rate, samples):
    mo.stop(params_w.value is None, mo.md("Set the parameters and press **Compute**"))
    _p = params_w.value
    channels = sorted(_p["channels"])
    n_sources = _p["sources"]
    mo.stop(len(channels) <= n_sources, mo.md(f"MUSIC needs more mics than sources: {len(channels)} mics, {n_sources} sources"))
    mo.stop(_p["f_min"] >= _p["f_max"], mo.md("f min must be below f max"))
    mo.stop(_p["start"] >= _p["end"], mo.md("'from' must be before 'to'"))

    _nfft = int(_p["nfft"])
    _first, _last = int(_p["start"] * sample_rate), int(_p["end"] * sample_rate)
    freqs, _frame_times, _X = band_stft(samples[_first:_last, channels], sample_rate, _nfft, _p["f_min"], _p["f_max"])
    mo.stop(len(freqs) == 0, mo.md("No FFT bins in the band"))
    _frame_times = _frame_times + _p["start"]

    _hop = (_nfft // 2) / sample_rate  # scipy.signal.stft default overlap is nfft / 2
    _window_frames = max(2, round(_p["window"] / _hop))
    _step_frames = max(1, round(_p["step"] / _hop))
    track_step = _step_frames * _hop  # s between window centers
    _starts = range(0, _X.shape[2] - _window_frames + 1, _step_frames)
    mo.stop(len(_starts) == 0, mo.md("The window is longer than the analyzed range"))

    positions = mic_positions(channels, _p["radius"] * 1e-3)
    _grid_step = int(_p["grid_step"])
    azimuths_deg = np.arange(-180, 180, _grid_step)
    elevations_deg = np.arange(0, 90 + _grid_step, _grid_step).clip(max=90)
    _directions = direction_vectors(azimuths_deg, elevations_deg)
    _steering = steering_vectors(freqs, positions, _directions)  # same grid for every window

    track_times = np.empty(len(_starts))
    spectra_dB = np.empty((len(_starts), *_directions.shape[:-1]), dtype=np.float32)
    eig_gap_dB = np.empty(len(_starts))  # mean over bins of lambda_K / lambda_K+1
    energy_dB = np.empty(len(_starts))
    peak_az = np.full((len(_starts), n_sources), np.nan)
    peak_el = np.full((len(_starts), n_sources), np.nan)
    for _i, _s0 in enumerate(mo.status.progress_bar(_starts, title="MUSIC over windows")):
        _Xw = _X[:, :, _s0 : _s0 + _window_frames]
        _S, _eigvals = music_spectrum(covariances(_Xw), freqs, positions, _directions, n_sources, _steering)
        spectra_dB[_i] = 10 * np.log10(_S / _S.max())
        _eigvals = np.maximum(_eigvals, 1e-30)
        eig_gap_dB[_i] = np.mean(10 * np.log10(_eigvals[:, n_sources - 1] / _eigvals[:, n_sources]))
        energy_dB[_i] = 10 * np.log10(np.mean(np.abs(_Xw) ** 2) + 1e-30)
        track_times[_i] = _frame_times[_s0 : _s0 + _window_frames].mean()
        _el_idx, _az_idx = find_peaks_2d(spectra_dB[_i], n_sources)
        peak_az[_i, : len(_az_idx)] = azimuths_deg[_az_idx]
        peak_el[_i, : len(_el_idx)] = elevations_deg[_el_idx]
    energy_dB -= energy_dB.max()

    alias_freq = alias_frequency(positions)
    _warn = (
        mo.callout(mo.md(f"The band goes above {alias_freq:.0f} Hz: spatial aliasing, ghost peaks are possible"), kind="warn")
        if freqs.max() > alias_freq
        else None
    )
    mo.vstack([
        _w for _w in [
            _warn,
            mo.md(f"{len(_starts)} windows of {_window_frames * _hop:.3f} s, step {track_step:.3f} s, "
                  f"{len(freqs)} bins {freqs[0]:.0f}–{freqs[-1]:.0f} Hz"),
        ] if _w is not None
    ])
    return (
        azimuths_deg,
        channels,
        eig_gap_dB,
        elevations_deg,
        energy_dB,
        n_sources,
        peak_az,
        peak_el,
        spectra_dB,
        track_step,
        track_times,
    )


@app.cell
def _(n_sources):
    min_gap_w = mo.ui.slider(start=0, stop=30, step=0.5, value=3, label="min λ gap, dB", include_input=True)
    min_energy_w = mo.ui.slider(start=-80, stop=0, step=1, value=-40, label="min energy, dB", include_input=True)
    unwrap_w = mo.ui.checkbox(value=True, label="unwrap azimuth", disabled=n_sources > 1)
    db_range_w = mo.ui.slider(start=5, stop=60, step=5, value=30, label="dB range", include_input=True)

    mo.hstack([min_gap_w, min_energy_w, unwrap_w, db_range_w], justify="start", gap=2)
    return db_range_w, min_energy_w, min_gap_w, unwrap_w


@app.cell
def _(
    eig_gap_dB,
    energy_dB,
    min_energy_w,
    min_gap_w,
    n_sources,
    peak_az,
    peak_el,
    unwrap_w,
):
    valid = (eig_gap_dB >= min_gap_w.value) & (energy_dB >= min_energy_w.value)
    shown_az = peak_az.copy()
    if n_sources == 1 and unwrap_w.value and valid.any():
        shown_az[valid, 0] = np.unwrap(peak_az[valid, 0], period=360)
    shown_el = peak_el
    return shown_az, shown_el, valid


@app.cell(hide_code=True)
def _(
    azimuths_deg,
    db_range_w,
    eig_gap_dB,
    energy_dB,
    n_sources,
    shown_az,
    shown_el,
    spectra_dB,
    track_times,
    valid,
):
    _vmin = -float(db_range_w.value)

    _track = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                           subplot_titles=["azimuth", "elevation", "window quality"])
    for _k in range(n_sources):
        for _row, _values in [(1, shown_az[:, _k]), (2, shown_el[:, _k])]:
            _track.add_trace(go.Scatter(
                x=track_times[valid], y=_values[valid], mode="markers", name=f"source {_k + 1}",
                legendgroup=f"s{_k}", showlegend=_row == 1,
                marker=dict(size=6, color=eig_gap_dB[valid], colorscale="Plasma", cmin=0,
                            cmax=max(float(eig_gap_dB.max()), 1.0),
                            colorbar=dict(title="λ gap, dB", len=0.6, y=0.7) if _row == 1 and _k == 0 else None),
                hovertemplate="%{x:.2f} s: %{y:.0f}°<extra></extra>",
            ), row=_row, col=1)
            _track.add_trace(go.Scatter(
                x=track_times[~valid], y=_values[~valid], mode="markers", name="filtered out",
                legendgroup="filtered", showlegend=_row == 1 and _k == 0,
                marker=dict(size=4, color="lightgray"), hoverinfo="skip",
            ), row=_row, col=1)
    _track.add_trace(go.Scatter(x=track_times, y=eig_gap_dB, mode="lines", name="λ gap, dB"), row=3, col=1)
    _track.add_trace(go.Scatter(x=track_times, y=energy_dB, mode="lines", name="energy, dB"), row=3, col=1)
    _track.update_yaxes(title_text="deg (0 = user, 90 = right)", row=1, col=1)
    _track.update_yaxes(title_text="deg (90 = up)", range=[0, 90], row=2, col=1)
    _track.update_yaxes(title_text="dB", row=3, col=1)
    _track.update_xaxes(title_text="time, s", row=3, col=1)
    _track.update_layout(height=800)

    _azimuth_map = go.Figure(go.Heatmap(
        z=np.clip(spectra_dB.max(axis=1), _vmin, 0).T, x=track_times, y=azimuths_deg,
        colorscale="Viridis", zmin=_vmin, zmax=0, colorbar=dict(title="dB"),
    ))
    _azimuth_map.add_trace(go.Scatter(
        x=np.repeat(track_times[valid], n_sources), y=((shown_az[valid] + 180) % 360 - 180).ravel(),
        mode="markers", name="peaks", marker=dict(size=4, color="red"),
    ))
    _azimuth_map.update_layout(
        title="Spectrum over time (max over elevation)",
        xaxis_title="time, s",
        yaxis_title="azimuth, deg (0 = toward the user, 90 = right)",
        height=500,
    )

    mo.ui.tabs({"Track": _track, "Time × azimuth": _azimuth_map})
    return


@app.cell
def _(track_times):
    # the whole animation is one marimo output (10 MB limit), a frame is ~12 KB at a 2 deg grid
    MAX_SPHERE_FRAMES = 400
    only_valid_w = mo.ui.checkbox(value=False, label="sphere: only windows that pass the filters")
    sphere_every_w = mo.ui.slider(
        start=1, stop=max(1, len(track_times)), step=1, value=max(1, int(np.ceil(len(track_times) / 150))),
        label="sphere: every N-th window", include_input=True,
    )
    mo.hstack([only_valid_w, sphere_every_w], justify="start", gap=2)
    return MAX_SPHERE_FRAMES, only_valid_w, sphere_every_w


@app.cell(hide_code=True)
def _(
    MAX_SPHERE_FRAMES,
    azimuths_deg,
    db_range_w,
    elevations_deg,
    only_valid_w,
    peak_az,
    peak_el,
    spectra_dB,
    sphere_every_w,
    track_times,
    valid,
):
    _windows = (np.flatnonzero(valid) if only_valid_w.value else np.arange(len(track_times)))[:: sphere_every_w.value]
    mo.stop(len(_windows) == 0, mo.md("No windows pass the filters"))
    mo.stop(
        len(_windows) > MAX_SPHERE_FRAMES,
        mo.callout(mo.md(f"{len(_windows)} frames is too many for one output (max {MAX_SPHERE_FRAMES}): "
                         f"increase 'every N-th window'"), kind="warn"),
    )

    # every frame goes to the browser at once: draw the sphere on a grid not finer than 2 deg
    _stride = max(1, round(2 / (azimuths_deg[1] - azimuths_deg[0])))
    sphere_animation(
        spectra_dB[_windows][:, ::_stride, ::_stride],
        azimuths_deg[::_stride],
        elevations_deg[::_stride],
        peaks=[[(az, el) for az, el in zip(peak_az[i], peak_el[i]) if not np.isnan(az)] for i in _windows],
        labels=[f"{track_times[i]:.2f}" for i in _windows],
        titles=[
            f"Window {i + 1} / {len(track_times)}, t = {track_times[i]:.2f} s" + ("" if valid[i] else " (filtered out)")
            for i in _windows
        ],
        vmin=-float(db_range_w.value),
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Video

    The sphere and the tracks for every window, in real time, with the stereo sound of the analyzed range:
    left channel - mean of the left mics (ch0, ch3), right - of the right ones (ch1, ch2).
    """)
    return


@app.cell
def _(file_name):
    video_path_w = mo.ui.text(
        value=str(DATASETS_DIR / f"{Path(file_name).stem}_doa.mp4"), label="mp4 file", full_width=True
    )
    save_video_w = mo.ui.run_button(label="Save video")
    mo.hstack([video_path_w, save_video_w], widths=[1, 0], align="end")
    return save_video_w, video_path_w


@app.cell
def _(
    azimuths_deg,
    channels,
    db_range_w,
    elevations_deg,
    peak_az,
    peak_el,
    sample_rate,
    samples,
    save_video_w,
    spectra_dB,
    track_step,
    track_times,
    valid,
    video_path_w,
):
    mo.stop(not save_video_w.value, mo.md("Press **Save video** (uses the current filters and dB range)"))
    _path = Path(video_path_w.value)
    try:
        render_video(
            _path, spectra_dB, azimuths_deg, elevations_deg, peak_az, peak_el, track_times, valid, track_step,
            stereo_mix(samples, channels), sample_rate, vmin=-float(db_range_w.value),
            progress=lambda frames: mo.status.progress_bar(frames, title="Rendering video", remove_on_exit=True),
        )
    except (RuntimeError, OSError) as _e:
        mo.stop(True, mo.callout(mo.md(f"Video failed: {_e}"), kind="danger"))

    _size = _path.stat().st_size
    _saved = mo.md(f"Saved **{_path}** ({_size / 1e6:.1f} MB, {len(track_times) * track_step:.1f} s)")
    # marimo shows outputs up to 10 MB; a longer video is opened from the file
    mo.vstack([_saved, mo.video(_path.read_bytes())] if _size < 8e6 else [_saved])
    return


if __name__ == "__main__":
    app.run()
