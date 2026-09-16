import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import io

    import marimo as mo
    import numpy as np
    import pandas as pd
    import plotly.express as px
    from scipy.io import wavfile

    return io, mo, np, pd, px, wavfile


@app.cell
def _(mo):
    title_markdown = "# 🎙️ WAV Channel Viewer"
    mo.md(title_markdown)
    return


@app.cell
def _(mo):
    file_uploader = mo.ui.file(
        filetypes=[".wav"],
        kind="area",
        label="Перетащите сюда .wav файл",
    )
    file_uploader
    return (file_uploader,)


@app.cell
def _(file_uploader, io, mo, np, wavfile):
    mo.stop(
        len(file_uploader.value) == 0,
        mo.md("⬆️ Загрузите WAV файл, чтобы увидеть график каналов."),
    )

    uploaded_file = file_uploader.value[0]
    sample_rate, raw_samples = wavfile.read(io.BytesIO(uploaded_file.contents))

    # Приводим к форме (n_samples, n_channels) независимо от того, моно это или стерео
    if raw_samples.ndim == 1:
        raw_samples = raw_samples[:, np.newaxis]

    n_samples, n_channels = raw_samples.shape

    # Нормализуем целочисленные форматы к диапазону [-1, 1] для единообразной оси Y
    if np.issubdtype(raw_samples.dtype, np.integer):
        max_abs_value = np.iinfo(raw_samples.dtype).max
        samples = raw_samples.astype(np.float64) / max_abs_value
    else:
        samples = raw_samples.astype(np.float64)

    duration_seconds = n_samples / sample_rate
    return (
        duration_seconds,
        n_channels,
        n_samples,
        raw_samples,
        sample_rate,
        samples,
        uploaded_file,
    )


@app.cell
def _(duration_seconds, mo, n_channels, n_samples, sample_rate, uploaded_file):
    mo.md(f"""
    **Файл:** {uploaded_file.name}
    &nbsp;·&nbsp; **Частота дискретизации:** {sample_rate} Гц
    &nbsp;·&nbsp; **Каналов:** {n_channels}
    &nbsp;·&nbsp; **Сэмплов:** {n_samples}
    &nbsp;·&nbsp; **Длительность:** {duration_seconds:.3f} с
    """)
    return


@app.cell
def _(n_samples, np, sample_rate):
    # Ограничиваем число точек на канал, чтобы график оставался отзывчивым
    # и вывод не превышал лимит размера вывода marimo
    max_points_per_channel = 10_000
    decimation_step = max(1, n_samples // max_points_per_channel)

    sample_indices = np.arange(0, n_samples, decimation_step)
    time_axis = sample_indices / sample_rate
    return sample_indices, time_axis


@app.cell
def _(mo, n_channels):
    channel_checkboxes = mo.ui.array(
        [
            mo.ui.checkbox(value=True, label=f"Канал {channel_index + 1}")
            for channel_index in range(n_channels)
        ]
    )
    mo.hstack(channel_checkboxes, justify="start", gap=1.5)
    return (channel_checkboxes,)


@app.cell
def _(mo):
    amplitude_mode_selector = mo.ui.radio(
        options=["Нормализованные [-1, 1]", "Сырые данные"],
        value="Нормализованные [-1, 1]",
        label="Данные амплитуды",
    )
    amplitude_mode_selector
    return (amplitude_mode_selector,)


@app.cell
def _(
    amplitude_mode_selector,
    channel_checkboxes,
    mo,
    n_channels,
    pd,
    raw_samples,
    sample_indices,
    samples,
    time_axis,
):
    selected_channel_indices = [
        channel_index
        for channel_index in range(n_channels)
        if channel_checkboxes.value[channel_index]
    ]

    mo.stop(
        len(selected_channel_indices) == 0,
        mo.md("☑️ Отметьте хотя бы один канал, чтобы увидеть график."),
    )

    use_raw_amplitude = amplitude_mode_selector.value == "Сырые данные"
    amplitude_samples = raw_samples if use_raw_amplitude else samples
    amplitude_axis_label = (
        f"Амплитуда (сырые данные, {raw_samples.dtype})"
        if use_raw_amplitude
        else "Амплитуда (нормализовано, -1..1)"
    )

    channels_df = pd.concat(
        [
            pd.DataFrame(
                {
                    "time": time_axis,
                    "amplitude": amplitude_samples[sample_indices, channel_index],
                    "channel": f"Канал {channel_index + 1}",
                }
            )
            for channel_index in selected_channel_indices
        ],
        ignore_index=True,
    )
    return amplitude_axis_label, channels_df


@app.cell
def _(amplitude_axis_label, channels_df, px):
    # Plotly из коробки умеет зумиться отдельно по X или по Y:
    # достаточно потащить мышью прямо по подписям нужной оси
    # (перетаскивание в области графика зумит обе оси сразу).
    wav_chart = px.line(
        channels_df,
        x="time",
        y="amplitude",
        color="channel",
        labels={"time": "Время, с", "amplitude": amplitude_axis_label, "channel": "Канал"},
        title="Осциллограмма всех каналов",
    ).update_layout(height=450, dragmode="zoom")
    return (wav_chart,)


@app.cell
def _(mo, wav_chart):
    mo.ui.plotly(
        wav_chart,
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToAdd": ["zoomIn2d", "zoomOut2d", "autoScale2d"],
        },
    )
    return


if __name__ == "__main__":
    app.run()
