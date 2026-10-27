"""SYNTHETIC data generator: photo-like renders of parts and reference objects on a virtual mat, with exact GT.

Public API (see `dataset.py` for the folder format):

    generate_sample(spec, out_dir, *, seed) -> Path
    make_dataset(out_root, *, n, seed, presets=None, n_reference=0, ...) -> manifest dict
    list_samples(root) -> list[SampleMeta]
    load_sample(path) -> Sample(meta, photos)          # safe for agents: never reads gt.yaml
    load_gt(path) -> GroundTruth                      # scorers only (eval/, tests)

CLI: `uv run python -m tools.synth --out data/synthetic/bench --n 200 --seed 7`.
"""

from .dataset import (
    GENERATOR_VERSION,
    PRESETS,
    GroundTruth,
    GTDim,
    Sample,
    SampleMeta,
    SampleSpec,
    dataset_specs,
    generate_sample,
    list_samples,
    load_gt,
    load_sample,
    make_dataset,
)
from .reference_objects import REFERENCE_OBJECTS, ReferenceObject, SpecDim, get_reference_object, list_reference_objects

__all__ = [
    "GENERATOR_VERSION",
    "PRESETS",
    "REFERENCE_OBJECTS",
    "GTDim",
    "GroundTruth",
    "ReferenceObject",
    "Sample",
    "SampleMeta",
    "SampleSpec",
    "SpecDim",
    "dataset_specs",
    "generate_sample",
    "get_reference_object",
    "list_reference_objects",
    "list_samples",
    "load_gt",
    "load_sample",
    "make_dataset",
]
