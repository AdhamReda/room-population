"""
Simple tests for the 2D alignment functions.

These run OUTSIDE Revit because the module only uses `math` and `itertools`.
Run them with:   pytest

Each test is a normal function whose name starts with `test_`.
`assert` means "this must be true" - if it is false, the test fails.
"""
import math

from geometry_engine import (   
    centroid2d,
    rotate2d,
    mirror2d,
    signed_area,
    canonicalize_ccw,
    best_fit_rotation,
    rmse_for_fit,
    find_best_alignment,
    template_frame_vectors,
    template_frame_vectors_by_mirror,
)

# An irregular 4-sided shape (all sides different length), drawn counter-clockwise.
# Irregular on purpose: a square would match itself in many ways.
SHAPE = [(0, 0), (4, 0), (5, 3), (1, 2)]


def close(a, b):
    """Floating point numbers are rarely exactly equal, so compare with a tiny tolerance."""
    return math.isclose(a, b, abs_tol=1e-9)


def move_shape(points, angle=0.0, dx=0.0, dy=0.0, mirror=False):
    """Helper: optionally mirror, then rotate, then shift a shape."""
    result = []
    for p in points:
        if mirror:
            p = mirror2d(p)
        x, y = rotate2d(p, angle)
        result.append((x + dx, y + dy))
    return result


# ---------- small helper functions ----------

def test_centroid_of_square():
    assert centroid2d([(0, 0), (2, 0), (2, 2), (0, 2)]) == (1, 1)


def test_rotate_quarter_turn():
    x, y = rotate2d((1, 0), math.pi / 2)   # rotate 90 degrees
    assert close(x, 0)
    assert close(y, 1)


def test_mirror_flips_x():
    assert mirror2d((3, 4)) == (-3, 4)


def test_signed_area_ccw_is_positive():
    assert signed_area([(0, 0), (1, 0), (1, 1), (0, 1)]) == 1.0


def test_signed_area_cw_is_negative():
    assert signed_area([(0, 0), (0, 1), (1, 1), (1, 0)]) == -1.0


def test_canonicalize_reverses_clockwise_points():
    clockwise = SHAPE[::-1]
    assert canonicalize_ccw(clockwise) == SHAPE


def test_canonicalize_keeps_counter_clockwise_points():
    assert canonicalize_ccw(SHAPE) == SHAPE


# ---------- rotation and error ----------

def test_best_fit_rotation_finds_90_degrees():
    source = [(1, 0), (0, 1)]
    target = [(0, 1), (-1, 0)]          # same points turned 90 degrees
    assert close(best_fit_rotation(source, target), math.pi / 2)


def test_rmse_is_zero_for_identical_shapes():
    rmse, theta = rmse_for_fit(SHAPE, SHAPE)
    assert close(rmse, 0)
    assert close(theta, 0)


def test_rmse_known_value():
    # candidate is 2x bigger, so each point is off by exactly 1 -> RMSE = 1
    rmse, theta = rmse_for_fit([(1, 0), (-1, 0)], [(2, 0), (-2, 0)])
    assert close(rmse, 1.0)


# ---------- find_best_alignment ----------

def test_alignment_returns_none_if_not_enough_points():
    triangle = [(0, 0), (5, 0), (1, 3)]
    assert find_best_alignment(triangle, [(0, 0), (1, 1)]) is None


def test_alignment_identical_shape():
    result = find_best_alignment(SHAPE, SHAPE)
    assert close(result["rmse"], 0)
    assert result["mirrored"] is False


def test_alignment_rotated_and_moved_shape():
    candidate = move_shape(SHAPE, angle=0.7, dx=10, dy=-5)
    result = find_best_alignment(SHAPE, candidate)
    assert close(result["rmse"], 0)
    assert close(result["theta"], 0.7)          # it recovers the rotation
    assert result["mirrored"] is False


def test_alignment_when_candidate_is_drawn_clockwise():
    candidate = move_shape(SHAPE, angle=-0.6, dx=1, dy=2)[::-1]   # reversed order
    result = find_best_alignment(SHAPE, candidate)
    assert close(result["rmse"], 0)
    assert result["mirrored"] is False


def test_alignment_detects_mirrored_shape():
    candidate = move_shape(SHAPE, angle=0.3, dx=2, dy=2, mirror=True)
    result = find_best_alignment(SHAPE, candidate)
    assert close(result["rmse"], 0)
    assert result["mirrored"] is True


def test_alignment_ignores_extra_point():
    moved = move_shape(SHAPE, angle=0.5, dx=20, dy=20)
    candidate = moved[:2] + [(-50, 90)] + moved[2:]    # extra far-away point at index 2
    result = find_best_alignment(SHAPE, candidate)
    assert close(result["rmse"], 0)
    assert 2 not in result["indices"]                  # the extra point was not used


def test_alignment_different_shape_has_large_error():
    square = [(0, 0), (4, 0), (4, 4), (0, 4)]
    result = find_best_alignment(SHAPE, square)
    assert result["rmse"] > 0.1


# ---------- frame vectors ----------

def test_frame_vectors_for_3_4_5_point():
    x_dir, y_dir = template_frame_vectors([(3, 4), (-3, -4), (0, 1)])
    assert close(x_dir[0], 0.6) and close(x_dir[1], 0.8)
    assert close(y_dir[0], -0.8) and close(y_dir[1], 0.6)


def test_mirrored_frame_is_mirror_of_normal_frame():
    frames = template_frame_vectors_by_mirror(SHAPE)
    x_dir, y_dir = frames[False]
    assert frames[True] == (mirror2d(x_dir), mirror2d(y_dir))