import pickle
from typing import Any

import numpy as np


class PolyReferenceMotion:
    def __init__(self, polynomial_coefficients: str) -> None:
        with open(polynomial_coefficients, "rb") as f:
            data = pickle.load(f)
        self.dx_range: list[float] = [0, 0]
        self.dy_range: list[float] = [0, 0]
        self.dtheta_range: list[float] = [0, 0]
        self.dxs: list[float] = []
        self.dys: list[float] = []
        self.dthetas: list[float] = []
        self.data_array: list = []
        self.period: float | None = None
        self.fps: float | None = None
        self.frame_offsets: Any = None
        self.startend_double_support_ratio: float | None = None
        self.start_offset: int | None = None
        self.nb_steps_in_period: int | None = None

        self.process(data)

    def process(self, data: dict) -> None:
        print("[Poly ref data] Processing ...")
        _data: dict = {}
        for name in data:
            split = name.split("_")
            dx = float(split[0])
            dy = float(split[1])
            dtheta = float(split[2])

            if self.period is None:
                period = data[name]["period"]
                fps = data[name]["fps"]
                startend_double_support_ratio = data[name]["startend_double_support_ratio"]
                self.period = period
                self.fps = fps
                self.frame_offsets = data[name]["frame_offsets"]
                self.startend_double_support_ratio = startend_double_support_ratio
                self.start_offset = int(startend_double_support_ratio * fps)
                self.nb_steps_in_period = int(period * fps)

            if dx not in self.dxs:
                self.dxs.append(dx)

            if dy not in self.dys:
                self.dys.append(dy)

            if dtheta not in self.dthetas:
                self.dthetas.append(dtheta)

            self.dx_range = [min(dx, self.dx_range[0]), max(dx, self.dx_range[1])]
            self.dy_range = [min(dy, self.dy_range[0]), max(dy, self.dy_range[1])]
            self.dtheta_range = [
                min(dtheta, self.dtheta_range[0]),
                max(dtheta, self.dtheta_range[1]),
            ]

            if dx not in _data:
                _data[dx] = {}

            if dy not in _data[dx]:
                _data[dx][dy] = {}

            if dtheta not in _data[dx][dy]:
                _data[dx][dy][dtheta] = data[name]

            _coeffs = data[name]["coefficients"]
            _data[dx][dy][dtheta] = list(_coeffs.values())

        self.dxs = sorted(self.dxs)
        self.dys = sorted(self.dys)
        self.dthetas = sorted(self.dthetas)

        nb_dx = len(self.dxs)
        nb_dy = len(self.dys)
        nb_dtheta = len(self.dthetas)

        data_array: list = nb_dx * [None]
        for x, dx in enumerate(self.dxs):
            data_array[x] = nb_dy * [None]
            for y, dy in enumerate(self.dys):
                data_array[x][y] = nb_dtheta * [None]
                for th, dtheta in enumerate(self.dthetas):
                    data_array[x][y][th] = _data[dx][dy][dtheta]
        self.data_array = data_array

        print("[Poly ref data] Done processing")

    def vel_to_index(self, dx, dy, dtheta) -> tuple[int, int, int]:

        dx = np.clip(dx, self.dx_range[0], self.dx_range[1])
        dy = np.clip(dy, self.dy_range[0], self.dy_range[1])
        dtheta = np.clip(dtheta, self.dtheta_range[0], self.dtheta_range[1])

        ix = np.argmin(np.abs(np.array(self.dxs) - dx))
        iy = np.argmin(np.abs(np.array(self.dys) - dy))
        itheta = np.argmin(np.abs(np.array(self.dthetas) - dtheta))

        return int(ix), int(iy), int(itheta)

    def sample_polynomial(self, t: float, coeffs) -> list:
        ret = []
        for c in coeffs:
            ret.append(np.polyval(np.flip(c), t))

        return ret

    def get_reference_motion(self, dx, dy, dtheta, i) -> list:
        ix, iy, itheta = self.vel_to_index(dx, dy, dtheta)
        t = i % self.nb_steps_in_period / self.nb_steps_in_period
        t = np.clip(t, 0.0, 1.0)  # safeguard
        ret = self.sample_polynomial(t, self.data_array[ix][iy][itheta])
        return ret
