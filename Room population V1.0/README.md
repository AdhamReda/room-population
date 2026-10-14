# Revit Module – 2D Alignment Helpers

This module finds the best alignment between a template polygon and a set of
candidate points (rotation, mirroring, and best-matching points).

## Runs outside Revit

The alignment code (`alignment.py`) only uses Python's built-in `math` and
`itertools`. It does **not** use the Revit API, so it can be imported and tested
on any machine with Python, without Revit installed. Inside Revit it is simply
imported as a normal module.

## Tests

Unit tests are in `tests/test_alignment.py` and use [pytest](https://pytest.org).
They cover:

- helper functions (centroid, rotation, mirror, signed area, CCW ordering)
- rotation angle and RMSE calculation
- `find_best_alignment`: identical, rotated/moved, clockwise-drawn, mirrored,
  extra points, different shape, and too-few-points cases
- the template frame vectors

### How to run

```bash
pip install pytest
pytest
```

All tests run in well under a second and do not need Revit.

## Project structure

```
alignment.py            # the module (usable inside Revit)
tests/test_alignment.py # unit tests (run outside Revit)
pytest.ini              # tells pytest where to find the module
README.md
```
