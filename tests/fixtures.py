"""A small synthetic world for the tests: one straight road with a dock at each end."""

import math

CONFIG = {
    "dt": 0.1,
    "robot": {
        "radius": 0.9,
        "v_min": -0.5,
        "v_max": 1.39,
        "w_max": 1.0,
        "accel": 0.5,
        "decel": 1.2,
        "estop_decel": 2.5,
    },
    "lidar": {
        "beams": 360,
        "angle_min_deg": 0,
        "angle_increment_deg": 1,
        "max_range": 20,
        "sigma": 0.03,
        "fog_max_range": 6,
        "fog_dropout": 0.1,
        "snow_false_rate": 0.03,
        "snow_false_range": [0.3, 3.0],
    },
    "odom": {
        "scale_error_abs_range": [0.01, 0.04],
        "sigma_rel": 0.02,
        "sigma_lat_rel": 0.005,
        "heading_rw_deg_per_sqrt_min": 0.5,
        "snow_multiplier": 3,
    },
    "imu": {
        "yaw_rate_sigma": 0.01,
        "yaw_rate_bias_sigma": 0.0002,
        "heading_sigma": 0.002,
        "heading_rw_deg_per_sqrt_min": 0.3,
    },
    "gnss": {
        "bias_tau_s": 30,
        "bias_sigma": 0.25,
        "white_sigma": 0.3,
        "jump_interval_s": [60, 120],
        "jump_size_m": [3, 8],
        "jump_duration_s": [2, 5],
    },
    "pedestrian": {"radius": 0.3},
    "mission": {"arrival_hold_s": 1.0, "pickup_radius": 2.0},
}

# road y 7.5..12.5 from x 0 to 60, walls north and south of it, docks at both ends
MAP = {
    "bounds": [-5.0, 0.0, 65.0, 20.0],
    "drivable": [[[0.0, 7.5], [60.0, 7.5], [60.0, 12.5], [0.0, 12.5]]],
    "buildings": [
        {"id": "N", "polygon": [[0.0, 13.0], [60.0, 13.0], [60.0, 15.0], [0.0, 15.0]]},
        {"id": "S", "polygon": [[0.0, 5.0], [60.0, 5.0], [60.0, 7.0], [0.0, 7.0]]},
        {"id": "W", "polygon": [[-3.0, 5.0], [-1.0, 5.0], [-1.0, 15.0], [-3.0, 15.0]]},
        {"id": "E", "polygon": [[61.0, 5.0], [63.0, 5.0], [63.0, 15.0], [61.0, 15.0]]},
    ],
    "points": {
        "warehouse": {"x": 0.5, "y": 10.0, "heading": math.pi, "tol": 0.2},
        "shop_a": {"x": 59.5, "y": 10.0, "heading": 0.0, "tol": 0.2},
    },
    "zones": [
        {
            "id": "SL",
            "type": "speed_limit",
            "v_max": 0.8,
            "polygon": [[30.0, 7.5], [40.0, 7.5], [40.0, 12.5], [30.0, 12.5]],
        },
    ],
}

PATH_WA = [[0.5, 10.0], [3.0, 10.0], [57.0, 10.0], [59.5, 10.0]]
PATH_AW = list(reversed(PATH_WA))


def mission(mid="m1", frm="warehouse", to="shop_a", path=None):
    p = MAP["points"][to]
    return {
        "id": mid,
        "index": 0,
        "count": 2,
        "from": frm,
        "to": to,
        "goal": [p["x"], p["y"], p["heading"]],
        "tol": 0.2,
        "t_start": 0.0,
        "deadline_s": 100.0,
        "reference_path": path or PATH_WA,
    }


def obs(t=0.0, m=None, ranges=None, dx=0.0):
    return {
        "t": t,
        "lidar": {"ranges": ranges if ranges is not None else [float("nan")] * 360},
        "odom": {"dx": dx, "dy": 0.0, "dtheta": 0.0},
        "imu": {"yaw_rate": 0.0, "heading": 0.0},
        "gnss": {"x": None, "y": None, "valid": False, "hdop": None},
        "mission": m,
    }
