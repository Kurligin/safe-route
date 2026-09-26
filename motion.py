"""The platform speed law (from config): the wheel speed after one tick for a target."""


def speed_law(v: float, v_t: float, estop: bool, robot, dt: float) -> float:
    """robot: config["robot"] (accel, decel, estop_decel). Braking or a sign change goes at decel,
    through zero first; speeding up at accel; estop brakes to zero at estop_decel."""
    if estop:
        target, rate = 0.0, robot["estop_decel"]
    elif v * v_t < 0 or abs(v_t) < abs(v):
        target, rate = (v_t if v * v_t >= 0 else 0.0), robot["decel"]
    else:
        target, rate = v_t, robot["accel"]
    return v + min(max(target - v, -rate * dt), rate * dt)
