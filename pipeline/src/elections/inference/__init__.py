"""Ecological-inference estimators, reconciliation, and accounting bounds.

Estimates are conditional on the model; accounting bounds document what aggregate
counts cannot identify.
"""

from .arrays import ConvergenceError, project_simplex
from .bounds import (grouped_section_bounds, linear_contrast_bounds, mobility_bounds, national_bounds,
                     section_bounds)
from .estimator import (HierarchyFit, Moments, fit_hierarchy, fit_rows, predict_shares, prediction_score,
                        section_moments)
from .reconciliation import SectionFlows, bridge_mobility, reconcile_section, reconcile_sections, reconcile_table

__all__ = [
    "ConvergenceError", "HierarchyFit", "Moments", "SectionFlows", "bridge_mobility",
    "fit_hierarchy", "fit_rows", "grouped_section_bounds",
    "linear_contrast_bounds", "mobility_bounds", "national_bounds", "predict_shares",
    "prediction_score", "project_simplex", "reconcile_section", "reconcile_sections",
    "reconcile_table", "section_bounds", "section_moments",
]
