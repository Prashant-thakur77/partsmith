"""Metrology: calibration mats, mat detection and pose, capture gate, segmentation, contour → millimetres, fit check.

Everything here is deterministic code. Units are millimetres (`_mm`), angles degrees (`_deg`).
Frames: the MAT frame has x right, y down, z into the table, origin at the mat's top-left; the PART frame has its origin at
the centre of the measured min-area rectangle, long side +X, Y up.
"""
