"""All tunable settings of the controller in one place."""

# ---------------------------------------------------------------- localization
# "odom": the pose is predicted from odometry (its scale is a filter state);
# "model": the pose is predicted from the own commands through the speed law
LOC_MODE = "odom"
# odometry mode: calibrate the odometry scale against the commanded motion too
SCALE_FROM_CMD = True

# ---------------------------------------------------------------------- mission
PICKUP_MARGIN = 0.5  # m, the estimate must be this much inside the pickup radius (plus 3 sigma)
PICKUP_FLOOR = 0.5  # m: with a very uncertain pose, being this close to `from` still counts
DOCK_DIST = 3.0  # m to the goal: docking phase
ARRIVE_DIST = 0.12  # m, estimate to the goal for "arrived"
ARRIVE_SIGMA = 0.08  # m, position sigma for "arrived"
ARRIVE_LATE_TICKS = 30  # standing at the goal this long, accept a looser sigma
ARRIVE_SIGMA_LATE = 0.15  # m
STATUS_MOVING_V = 0.05  # m/s, "moving" while the model speed is above this

# --------------------------------------------------------------- speed profile
ZONE_ALLOWANCE = 0.04  # m/s over the zone limit (the rule fines above +0.05)
ZONE_DECEL = 0.9  # m/s^2, braking into a slower zone
ZONE_MARGIN = 0.7  # m before the zone border (pose error plus one tick of delay)
PROFILE_STEP = 0.2  # m, sampling of the path for zone limits
LAT_ACCEL = 1.0  # m/s^2, lateral acceleration limit on arcs
TURN_DECEL = 0.9  # m/s^2, braking before sharp corners
DOCK_DECEL = 0.9  # m/s^2, square-root profile into the dock
DOCK_STOP_OFFSET = 0.02  # m, the profile reaches zero this far before the goal
DOCK_CREEP = 0.03  # m/s added to the dock profile so that the last centimetres are covered

# ------------------------------------------------------------------- following
LOOKAHEAD = 1.5  # m
ROTATE_ANGLE = 1.047  # rad (60 deg): rotate on the spot above this heading error
ROTATE_GAIN = 2.0  # w = gain * alpha while rotating, clipped to w_max
CURVE_V_MIN = 0.3  # m/s, curvature regulation never asks for less
DOCK_NEAR = 0.3  # m to the goal: no steering towards it any more
DOCK_STOP_DIST = 0.03  # m along the final segment: stop
REVERSE_MAX = 1.0  # m, back up if the goal was overshot by up to this
REVERSE_V = 0.3  # m/s, top speed backwards
DOCK_CROSS = 0.08  # m: goal off the heading line in the last DOCK_NEAR: back off and come in again
DOCK_BACKOFF = 0.8  # m from the goal to back off to

# ---------------------------------------------------------------- pickup route
GRID_RES = 0.5  # m
GRID_CLEARANCE = 1.4  # m from walls
GRID_EDGE_MARGIN = 1.0  # m inside the drivable area

# ------------------------------------------------------------------------ note
# short codes for the operator station; True appends localization diagnostics
NOTE_DEBUG = False

# ---------------------------------------------------------------------- safety
REAR_REACH = 0.5  # m behind the body: backing up stops for anything there
CLEARANCE = 0.3  # m, the body should not pass walls and objects closer than this
CLEARANCE_V = 0.3  # m/s while something is inside that band ahead

# ---------------------------------------------------------------- perception
TRACK_PERSIST = 15  # ticks a track (and a person that flickered out) is kept without returns
VEL_WINDOW = 10  # ticks of centre history for the velocity

# -------------------------------------------------------------------- bypass
BYPASS_HORIZON = 16.0  # m of path ahead searched for objects
BYPASS_TRIGGER = 0.25  # m: a point closer than R + this to the path axis triggers a bypass
BYPASS_CLEAR = 0.35  # m: the offset path passes points at R + this
BYPASS_MAX = 1.6  # m, largest offset
BYPASS_WALL = 0.3  # m: the offset centre stays R + this away from map walls
BYPASS_EXIT = 3.0  # m, S-transition back to the axis
BYPASS_MEMORY = 20  # ticks static points are remembered

# ------------------------------------------------------------ people (H1, H2)
PRED_HORIZON = 30  # ticks of forecast (3 s)
PRED_HOLD = 0.3  # s of the candidate speed before the escape manoeuvre
PRED_CANDIDATES = (1.39, 1.2, 1.0, 0.8, 0.6, 0.45)  # m/s, plus the crawl speed
CRAWL = 0.27  # m/s, below the 0.28 of the rule "person closer than 3 m"
NEAR_GAP = 3.0  # m, the rule "person closer than 3 m while faster than the crawl"
NEAR_MARGIN = 0.3  # m on top of NEAR_GAP
PASS_GAP = 0.5  # m, the rule "person closer than 0.5 m while moving at all"
PASS_MARGIN = 0.3  # m on top of PASS_GAP
SPREAD = 0.3  # forecast spread: this share of the walking speed times the time
YOUNG_SPEED = 1.2  # m/s: a track without a velocity yet is assumed to walk at us
PRED_MEMORY = 8  # ticks: the allowed speed is the minimum over this window
YIELD_STANDING = 4.6  # m to the centre of a standing person seen walking: stop at zero
YIELD_WALKING = 4.4  # m to a walking person heading at us: stop at zero
YIELD_WIDTH = 0.9  # m, wider clusters are not a single person
YIELD_MAX_TICKS = 150  # ticks of yielding to one person at most
YIELD_HOLD = 5  # ticks the yield stop is held after the reason is gone
START_GUARD = 0.8  # m: do not start while a non-static cluster is this close to the body
PATH_CORRIDOR = 0.12  # m: static points within R + this of the planned track ahead stop the platform
TRACK_AHEAD = 6.0  # m of the planned track handed to the safety layer

# ------------------------------------------------------------ safety details
STOP_MARGIN = 0.9  # m: object corridor length = v^2 / 2 + this (body stopping distance + 0.3 m)
CLOSE_MARGIN = 0.25  # m beyond the braking distance for the swept-footprint check
CLOSE_SIDE = 0.1  # m beside the body for the swept-footprint check
AHEAD_X = -0.2  # m: points further back than this are not "ahead"
DOCK_EXEMPT = 0.3  # m before the dock point: the object corridor (dock walls) no longer stops
ESTOP_GAP = 1.4  # m body gap: estop only for objects this close (the rule allows estop within 1.5 m)
ESTOP_MARGIN = 0.1  # m kept when judging whether normal braking is still enough
ESTOP_PERSON_DIST = 0.6  # m: raw returns this close to a person are the person, not an object
REAR_PEOPLE = 3.0  # m clearance: no backing up with a person behind closer than this
PERSON_RADIUS = 0.3  # m
WALK_SPEED = 0.3  # m/s: a person slower than this stands
YIELD_BEHIND = -0.5  # m: a standing person further back than this is behind, not in front
MAX_TRACES = 20  # tracebacks printed to stderr at most (then a counter)
WALK_MOVED = 0.6  # m in 1 s: the track walks (a person)
STILL_MOVED = 0.25  # m in 1 s: the track stands
STILL_TICKS = 30  # ticks standing next to a standing platform: an object
TRACK_BLEND = 1.5  # m: the track ahead blends from straight ahead onto the path over this
CORNER_WINDOW = 4.0  # m ahead where sharp corners limit the speed
CORNER_MIN = 0.2  # rad: smaller deflections are no corner
GRID_SNAP = 6  # cells searched for the nearest free cell of the pickup grid
BYPASS_LEAD = 1.2  # m: the offset is complete this far before the first object point
BYPASS_TRAIL = 1.0  # m: and held this far past the last one
BYPASS_KEEP = 4.5  # m past the object the offset is dropped; also the checked stretch before it
BYPASS_LATERAL = 3.6  # m: points further from the axis are ignored
ESTOP_CONF = 3  # ticks a static cluster must have been confirmed to count for estop
ESTOP_MIN_GAP = 0.05  # m: returns closer to the body than this are snow for the estop
ESTOP_SPREAD = 0.15  # m: three adjacent raw returns within this range spread are a surface
