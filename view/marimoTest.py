import marimo

__generated_with = "0.23.14"
app = marimo.App()


@app.cell
def _():
    import numpy as np
    import altair as alt
    import pandas as pd
    import marimo as mo

    # Включаем оптимизированный трансформер для работы с большими данными
    alt.data_transformers.enable('marimo_csv')

    return alt, mo, np, pd


@app.cell
def _(np, pd):
    # Генерируем тестовые данные
    np.random.seed(42)
    n_points = 5000
    x_values = np.arange(n_points)
    y_values = 5 + 0.3*x_values + 10*np.sin(x_values/20) + np.random.randn(n_points)*4
    df_main = pd.DataFrame({'x': x_values, 'y': y_values})
    return (df_main,)


@app.cell
def _(df_main, mo):
    # Создаём диапазонный слайдер
    range_slider = mo.ui.range_slider(
        start=0,
        stop=len(df_main)-1,
        step=10,
        value=(500, 2000),
        label="Выбор диапазона X",
        show_value=True
    )
    return (range_slider,)


@app.cell
def _(alt, df_main, range_slider):
    # Основной график с фильтрацией на стороне клиента
    start_val, end_val = range_slider.value

    # Базовый слой с фильтром
    base_chart = alt.Chart(df_main).transform_filter(
        (alt.datum.x >= start_val) & (alt.datum.x <= end_val)
    )

    # Линия
    line_chart = base_chart.mark_line(
        color='#2196F3',
        strokeWidth=2
    ).encode(
        x=alt.X('x:Q', title='X', scale=alt.Scale(domain=[0, len(df_main)])),
        y=alt.Y('y:Q', title='Значение'),
        tooltip=['x', 'y']
    ).properties(
        width=800,
        height=400,
        title='🔍 Детальный вид'
    )

    # Точки (с меньшей прозрачностью для производительности)
    points_chart = base_chart.mark_circle(
        color='#FF5722',
        size=30,
        opacity=0.3
    ).encode(
        x='x:Q',
        y='y:Q'
    )

    final_chart_altair = line_chart + points_chart
    return (final_chart_altair,)


@app.cell
def _(alt, df_main, pd, range_slider):
    # Мини-карта с выделенным диапазоном
    start_val_mini, end_val_mini = range_slider.value

    # Полный график (все данные)
    full_line_chart = alt.Chart(df_main).mark_line(
        color='#B0BEC5',
        strokeWidth=1,
        opacity=0.5
    ).encode(
        x=alt.X('x:Q', title='X', scale=alt.Scale(domain=[0, len(df_main)])),
        y=alt.Y('y:Q', title='Значение')
    )

    # Данные для прямоугольника подсветки
    rect_data_df = pd.DataFrame({
        'x_start': [start_val_mini],
        'x_end': [end_val_mini],
        'y_bottom': [df_main['y'].min()],
        'y_top': [df_main['y'].max()]
    })

    selection_rect_chart = alt.Chart(rect_data_df).mark_rect(
        color='#2196F3',
        opacity=0.2
    ).encode(
        x='x_start:Q',
        x2='x_end:Q',
        y='y_bottom:Q',
        y2='y_top:Q'
    )

    mini_chart_altair = (full_line_chart + selection_rect_chart).properties(
        width=800,
        height=80,
        title='🌍 Общий вид (выбранный диапазон подсвечен)'
    )
    return (mini_chart_altair,)


@app.cell
def _(df_main, range_slider):
    # Расчёт статистики
    start_idx_stats, end_idx_stats = range_slider.value
    filtered_data_stats = df_main.iloc[start_idx_stats:end_idx_stats]

    stats_markdown = f"""
    ### 📊 Статистика выбранного диапазона
    - **Индексы:** {start_idx_stats} — {end_idx_stats}
    - **Количество точек:** {len(filtered_data_stats)}
    - **Среднее значение:** {filtered_data_stats['y'].mean():.2f}
    - **Стандартное отклонение:** {filtered_data_stats['y'].std():.2f}
    - **Минимум:** {filtered_data_stats['y'].min():.2f}
    - **Максимум:** {filtered_data_stats['y'].max():.2f}
    """
    return (stats_markdown,)


@app.cell
def _(final_chart_altair, mini_chart_altair, mo, range_slider, stats_markdown):
    # Отображение всего вместе
    mo.vstack([
        mo.md("# 🎛️ Интерактивный выбор диапазона (Altair)"),
        mo.md("Перемещайте ползунок для выбора диапазона данных"),
        final_chart_altair,
        mini_chart_altair,
        mo.hstack([
            range_slider,
            mo.md(f"**Точек:** {range_slider.value[1] - range_slider.value[0]}")
        ]),
        mo.md(stats_markdown)
    ])
    return


if __name__ == "__main__":
    app.run()
