"""Synthetic CVRPTW-HF instance generator for Greater Santiago (PLAN.md §4)."""

from cvrptw_bench.generator.config import GeneratorConfig
from cvrptw_bench.generator.generate import (
    InstanceSpec,
    design_specs,
    generate_instance,
    generate_set,
    instance_seed,
)

__all__ = [
    "GeneratorConfig",
    "InstanceSpec",
    "design_specs",
    "generate_instance",
    "generate_set",
    "instance_seed",
]
