"""Plane geometry shared by the controller modules: angles, polygons, the signed
distance field of the map, ray casting and distances to wall segments.
Only the standard library and numpy."""

import math

import numpy as np

TWO_PI = 2.0 * math.pi


def wrap(a: float) -> float:
    """Angle to [-pi, pi)."""
    return (a + math.pi) % TWO_PI - math.pi


def inside(x: float, y: float, poly) -> bool:
    """Even-odd point in polygon for one point."""
    n = len(poly)
    c = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def inside_mask(px: np.ndarray, py: np.ndarray, poly) -> np.ndarray:
    """Even-odd point in polygon, vectorized over points."""
    c = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if y1 == y2:
            continue
        cond = (y1 > py) != (y2 > py)
        xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
        c ^= cond & (px < xint)
    return c


def wall_segments(map_) -> np.ndarray:
    """All building edges as rows [ax, ay, bx, by]."""
    segs = []
    for b in map_["buildings"]:
        p = np.asarray(b["polygon"], dtype=float)
        segs.append(np.hstack([p, np.roll(p, -1, axis=0)]))
    return np.vstack(segs) if segs else np.empty((0, 4))


def raycast(ox: float, oy: float, angles: np.ndarray, segs: np.ndarray) -> np.ndarray:
    """Distance to the first map wall along each ray (inf if none)."""
    if len(segs) == 0:
        return np.full(angles.shape, np.inf)
    dx, dy = np.cos(angles), np.sin(angles)
    px, py = segs[:, 0] - ox, segs[:, 1] - oy
    ex, ey = segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]
    den = dx[:, None] * ey[None, :] - dy[:, None] * ex[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (px * ey - py * ex)[None, :] / den
        u = (px[None, :] * dy[:, None] - py[None, :] * dx[:, None]) / den
    ok = (np.abs(den) > 1e-12) & (t > 1e-9) & (u >= 0) & (u <= 1)
    return np.where(ok, t, np.inf).min(axis=1)


def seg_dist(px: np.ndarray, py: np.ndarray, segs: np.ndarray) -> np.ndarray:
    """Distance from points (N,) to the nearest segment: (N,)."""
    if len(segs) == 0 or len(px) == 0:
        return np.full(len(px), np.inf)
    ax, ay, bx, by = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    ex, ey = bx - ax, by - ay
    ll = np.maximum(ex * ex + ey * ey, 1e-12)
    u = np.clip(((px[:, None] - ax) * ex + (py[:, None] - ay) * ey) / ll, 0.0, 1.0)
    dx = ax + u * ex - px[:, None]
    dy = ay + u * ey - py[:, None]
    return np.sqrt(dx * dx + dy * dy).min(axis=1)


class DistanceField:
    """Signed distance to the nearest wall (negative inside buildings), clamped,
    on a regular raster; bilinear lookup with gradient."""

    def __init__(self, polys, bounds, res: float = 0.1, clamp: float = 3.0):
        x0, y0, x1, y1 = bounds
        pad = clamp + 2.0
        self.res = res
        self.inv = 1.0 / res
        self.clamp = clamp
        self.x0 = x0 - pad
        self.y0 = y0 - pad
        self.nx = int(math.ceil((x1 - x0 + 2 * pad) / res)) + 1
        self.ny = int(math.ceil((y1 - y0 + 2 * pad) / res)) + 1
        d = np.full((self.ny, self.nx), clamp, dtype=np.float32)
        for poly in polys:
            for i in range(len(poly)):
                ax, ay = poly[i]
                bx, by = poly[(i + 1) % len(poly)]
                i0, i1 = self._ix(min(ax, bx) - clamp), self._ix(max(ax, bx) + clamp) + 1
                j0, j1 = self._iy(min(ay, by) - clamp), self._iy(max(ay, by) + clamp) + 1
                if i1 <= i0 or j1 <= j0:
                    continue
                gx = self.x0 + np.arange(i0, i1) * res
                gy = self.y0 + np.arange(j0, j1) * res
                X = gx[None, :]
                Y = gy[:, None]
                ex, ey = bx - ax, by - ay
                l2 = max(ex * ex + ey * ey, 1e-12)
                u = np.clip(((X - ax) * ex + (Y - ay) * ey) / l2, 0.0, 1.0)
                dist = np.hypot(ax + u * ex - X, ay + u * ey - Y).astype(np.float32)
                sl = d[j0:j1, i0:i1]
                np.minimum(sl, dist, out=sl)
        for poly in polys:
            i0, i1 = self._ix(poly[:, 0].min()), self._ix(poly[:, 0].max()) + 1
            j0, j1 = self._iy(poly[:, 1].min()), self._iy(poly[:, 1].max()) + 1
            if i1 <= i0 or j1 <= j0:
                continue
            gx = self.x0 + np.arange(i0, i1) * res
            gy = self.y0 + np.arange(j0, j1) * res
            X, Y = np.meshgrid(gx, gy)
            m = inside_mask(X, Y, poly)
            sl = d[j0:j1, i0:i1]
            sl[m] = -np.abs(sl[m])
        self.flat = d.ravel()

    def _ix(self, x: float) -> int:
        return int(min(max(math.floor((x - self.x0) * self.inv), 0), self.nx - 1))

    def _iy(self, y: float) -> int:
        return int(min(max(math.floor((y - self.y0) * self.inv), 0), self.ny - 1))

    def lookup(self, px, py):
        """Bilinear value and gradient. Outside the grid: clamp, zero gradient."""
        fx = (px - self.x0) * self.inv
        fy = (py - self.y0) * self.inv
        ix = np.floor(fx)
        iy = np.floor(fy)
        ok = (ix >= 0) & (ix < self.nx - 1) & (iy >= 0) & (iy < self.ny - 1)
        ix = np.where(ok, ix, 0).astype(np.intp)
        iy = np.where(ok, iy, 0).astype(np.intp)
        tx = fx - ix
        ty = fy - iy
        k = iy * self.nx + ix
        f = self.flat
        d00 = f[k]
        d10 = f[k + 1]
        d01 = f[k + self.nx]
        d11 = f[k + self.nx + 1]
        a = d10 - d00
        b = d01 - d00
        c = d11 - d10 - d01 + d00
        val = d00 + a * tx + b * ty + c * tx * ty
        gx = (a + c * ty) * self.inv
        gy = (b + c * tx) * self.inv
        val = np.where(ok, val, self.clamp)
        return val, np.where(ok, gx, 0.0), np.where(ok, gy, 0.0)

    def value(self, x: float, y: float) -> float:
        """Signed distance at one point."""
        val, _, _ = self.lookup(np.array([x]), np.array([y]))
        return float(val[0])


def map_bounds(map_, polys) -> list:
    bounds = map_.get("bounds")
    if not bounds:
        allp = np.vstack(polys) if polys else np.zeros((1, 2))
        bounds = [allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max()]
    return [float(b) for b in bounds]
