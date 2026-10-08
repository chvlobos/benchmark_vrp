"""Compare a secondary run against a base run (PLAN.md §12): the variant's solvers are
renamed with a suffix, joined to the base run on the common instances, and judged with
the same coverage-first gaps as the main report. Output: a markdown summary plus CSVs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cvrptw_bench.report.aggregate import (
    SEED_NAME,
    SOLVER_LABEL,
    SOLVER_ORDER,
    add_gaps,
    collect,
    overall,
)
from cvrptw_bench.report.build_html import _pairwise


def combine(
    base_dir: str | Path,
    exp_dir: str | Path,
    instances_dir: str | Path | None,
    suffix: str,
) -> pd.DataFrame:
    """Base rows + experiment rows (solvers renamed ``<name><suffix>``), common instances only."""
    base = collect(base_dir, instances_dir)
    exp = collect(exp_dir, instances_dir)
    exp = exp[exp["solver"] != SEED_NAME].copy()
    exp["solver"] = exp["solver"].astype(str) + suffix
    common = sorted(set(base["instance"]) & set(exp["instance"]))
    base = base[base["instance"].isin(common)].copy()
    base["solver"] = base["solver"].astype(str)
    df = pd.concat([base, exp], ignore_index=True)
    order = [s for s in SOLVER_ORDER if s in set(df["solver"])]
    for s in SOLVER_ORDER:
        if s + suffix in set(df["solver"]):
            order.insert(order.index(s) + 1 if s in order else len(order), s + suffix)
    order += sorted(set(df["solver"]) - set(order))
    df["solver"] = pd.Categorical(df["solver"], categories=order)
    return add_gaps(df.sort_values(["n", "instance", "solver"]).reset_index(drop=True))


def _label(s: str, suffix: str) -> str:
    if s.endswith(suffix) and suffix:
        return SOLVER_LABEL.get(s[: -len(suffix)], s[: -len(suffix)]) + " " + suffix.strip("_")
    return SOLVER_LABEL.get(s, s)


def _md_table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                cells.append("–" if np.isnan(v) else floatfmt.format(v))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _pairwise_line(df: pd.DataFrame, a: str, b: str, suffix: str) -> str | None:
    pw = _pairwise(df, a, b)
    if not pw:
        return None
    la, lb = _label(a, suffix), _label(b, suffix)
    return (
        f"**{la} vs {lb}** on {pw['n']} instances: {la} serves more customers on {pw['more_cov']}, "
        f"fewer on {pw['less_cov']}; at equal coverage it is cheaper on {pw['cheaper']}, dearer on "
        f"{pw['dearer']} (ties {pw['tie']}), cost {pw['rel_mean']:+.2f} % on average "
        f"(median {pw['rel_median']:+.2f} %, range {pw['rel_min']:+.1f} % to {pw['rel_max']:+.1f} %)."
    )


def compare_runs(
    base_dir: str | Path,
    exp_dir: str | Path,
    instances_dir: str | Path | None,
    suffix: str,
    title: str,
    description: str,
    out_path: str | Path | None = None,
) -> Path:
    exp_dir = Path(exp_dir)
    out_path = Path(out_path) if out_path else exp_dir / "comparison.md"
    df = combine(base_dir, exp_dir, instances_dir, suffix)
    n_inst = df["instance"].nunique()
    solvers = [s for s in df["solver"].cat.categories if s != SEED_NAME]
    variants = [s for s in solvers if s.endswith(suffix)]
    originals = [s[: -len(suffix)] for s in variants]

    ov = overall(df)
    ov["solver"] = ov["solver"].astype(str).map(lambda s: _label(s, suffix))
    ov_cols = [
        "solver",
        "coverage_deficit_sum",
        "at_best_coverage",
        "cost_gap_pct_mean",
        "cost_gap_pct_max",
        "best_cost_wins",
        "time_to_best_s_mean",
    ]
    ov_show = ov[ov_cols].rename(
        columns={
            "coverage_deficit_sum": "missed",
            "at_best_coverage": "at best coverage",
            "cost_gap_pct_mean": "gap % mean",
            "cost_gap_pct_max": "gap % max",
            "best_cost_wins": "best cost",
            "time_to_best_s_mean": "ttb s",
        }
    )

    lines = [f"# {title}", "", description, ""]
    lines += [
        f"{n_inst} instances (those present in both runs). Best known coverage and cost per "
        "instance are taken over **all** rows below, base and variant together, so a gap of 0 means "
        "the best of both.",
        "",
        _md_table(ov_show),
        "",
        "## Head to head",
        "",
    ]
    for v, o in zip(variants, originals, strict=True):
        line = _pairwise_line(df, v, o, suffix)
        if line:
            lines += [line, ""]
    if "ortools" in solvers:
        for v in variants:
            if not v.startswith("ortools"):
                line = _pairwise_line(df, v, "ortools", suffix)
                if line:
                    lines += [line, ""]
    # per-size detail for the variants and their originals
    detail = (
        df[df["solver"].isin(variants + originals)]
        .groupby(["n", "solver"], observed=True)
        .agg(
            missed=("coverage_deficit", "sum"),
            at_best_cov=("cost_gap", "count"),
            gap_mean=("cost_gap", lambda x: 100 * x.mean() if x.notna().any() else np.nan),
            best_cost=("is_best", "sum"),
            ttb=("time_to_best_s", "mean"),
        )
        .reset_index()
    )
    detail["solver"] = detail["solver"].astype(str).map(lambda s: _label(s, suffix))
    lines += ["## By instance size", "", _md_table(detail), ""]
    per_inst = (
        df[df["solver"].isin(variants + originals)]
        .pivot_table(
            index=["instance", "n", "capacity_stress"],
            columns="solver",
            values=["served", "total_cost"],
            aggfunc="first",
            observed=True,
        )
        .reset_index()
    )
    per_inst.columns = [
        (c if not s else f"{_label(str(s), suffix)} {c}") for c, s in per_inst.columns
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    per_inst.to_csv(out_path.with_name("comparison_by_instance.csv"), index=False)
    ov.to_csv(out_path.with_name("comparison_overall.csv"), index=False)
    lines += [
        "Per-instance served / cost for every column: `comparison_by_instance.csv`; "
        "the full overall table: `comparison_overall.csv`.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
