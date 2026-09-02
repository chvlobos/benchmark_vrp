"""Aggregation and the self-contained HTML report (PLAN.md §8.4)."""

from cvrptw_bench.report.aggregate import add_gaps, by_factor, collect, overall, write_tables
from cvrptw_bench.report.build_html import build_report

__all__ = ["add_gaps", "build_report", "by_factor", "collect", "overall", "write_tables"]
