"""Переиспользуемый блок выбора входного сигнала для marimo-блокнотов.

Использование в блокноте (три ячейки):

    signal_ui = signal_source(sample_rate, duration)      # создать
    signal_source_view(signal_ui)                         # показать
    x = generate_signal(signal_ui.value, time)            # получить сигнал

Чтобы добавить новый сигнал: функция в utils/generators.py,
строка в GENERATORS и описание параметров в _default_params.
"""

from dataclasses import dataclass

import marimo as mo

from utils import generators


@dataclass(frozen=True)
class Param:
    label: str
    start: float
    stop: float
    step: float
    value: float


GENERATORS = {
    "sine": generators.sine,
    "gauss": generators.gaussian_pulse,
    "chirp": generators.linear_chirp,
    "noise": generators.white_noise,
}

LABELS = {
    "sine": "Синусоида",
    "gauss": "Колокол (гауссов импульс)",
    "chirp": "ЛЧМ (chirp)",
    "noise": "Белый шум",
}


def _default_params(sample_rate, duration):
    nyquist = sample_rate / 2
    amplitude = Param("Амплитуда", 0, 10, 0.1, 1)
    return {
        "sine": {
            "frequency": Param("Частота, Гц", 0, nyquist, nyquist / 1000, nyquist / 10),
            "amplitude": amplitude,
            "phase_deg": Param("Фаза, град", -180, 180, 1, 0),
        },
        "gauss": {
            "center": Param("Центр, с", 0, duration, duration / 1000, duration / 2),
            "width": Param("Ширина (σ), с", duration / 1000, duration, duration / 1000, duration / 20),
            "amplitude": amplitude,
        },
        "chirp": {
            "f_start": Param("Начальная частота, Гц", 0, nyquist, nyquist / 1000, 0),
            "f_stop": Param("Конечная частота, Гц", 0, nyquist, nyquist / 1000, nyquist / 4),
            "amplitude": amplitude,
        },
        "noise": {
            "amplitude": amplitude,
            "seed": Param("Seed", 0, 1000, 1, 0),
        },
    }


def _slider(param):
    return mo.ui.slider(
        start=param.start,
        stop=param.stop,
        step=param.step,
        value=param.value,
        label=param.label,
        include_input=True,
    )


def signal_source(sample_rate, duration, default="sine", overrides=None):
    """Создаёт UI выбора сигнала. Результат нужно сохранить в глобальную переменную ячейки.

    overrides позволяет поменять диапазон любого параметра под конкретный блокнот:
        overrides={"sine": {"frequency": Param("Частота, Гц", 0, 5, 0.1, 1)}}
    """
    params = _default_params(sample_rate, duration)
    for kind, kind_overrides in (overrides or {}).items():
        params[kind].update(kind_overrides)

    controls = {
        "kind": mo.ui.dropdown(
            options={LABELS[kind]: kind for kind in GENERATORS},
            value=LABELS[default],
            label="Входной сигнал",
        )
    }
    for kind, kind_params in params.items():
        controls[kind] = mo.ui.dictionary(
            {name: _slider(param) for name, param in kind_params.items()}
        )
    return mo.ui.dictionary(controls)


def signal_source_view(signal_ui):
    """Показывает выпадающий список и ползунки только выбранного сигнала."""
    kind = signal_ui["kind"].value
    return mo.vstack([signal_ui["kind"], signal_ui[kind].vstack()])


def generate_signal(signal_value, time):
    """signal_value — это signal_ui.value (обычный dict), time — массив отсчётов времени в секундах."""
    kind = signal_value["kind"]
    return GENERATORS[kind](time, **signal_value[kind])
