"""Self-contained HTML report for a benchmark run (PLAN.md §8.4)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.io as pio
from jinja2 import Template

from cvrptw_bench import __version__
from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.solution import Solution
from cvrptw_bench.report import charts
from cvrptw_bench.report.aggregate import (
    SEED_NAME,
    SOLVER_LABEL,
    add_gaps,
    by_factor,
    collect,
    coverage_profile,
    overall,
    performance_profile,
    write_tables,
)

FACTOR_TITLES = {
    "n": "instance size (customers)",
    "capacity_stress": "capacity stress (%)",
    "tw_profile": "time-window profile",
    "family": "spatial family",
}


# ------------------------------------------------------------------ helpers
def _fig_html(fig) -> str:
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config={"displaylogo": False})


def _img_b64(path: Path) -> str | None:
    if not path.exists():
        return None
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


COLUMN_LABELS = {
    "n": "n",
    "capacity_stress": "stress %",
    "tw_profile": "windows",
    "family": "family",
    "solver": "solver",
    "instances": "instances",
    "valid": "valid",
    "coverage_pct_mean": "coverage % (mean)",
    "coverage_deficit_sum": "missed (sum)",
    "at_best_coverage": "at best coverage",
    "cost_gap_pct_mean": "cost gap % (mean)",
    "cost_gap_pct_max": "cost gap % (max)",
    "best_cost_wins": "best cost (wins)",
    "wall_time_s_mean": "wall s (mean)",
    "time_to_best_s_mean": "time to best s (mean)",
}


def _table_html(df: pd.DataFrame, float_fmt: str = "{:,.2f}") -> str:
    return df.rename(columns=COLUMN_LABELS).to_html(
        index=False,
        classes="tbl",
        border=0,
        na_rep="–",
        float_format=lambda x: float_fmt.format(x),
        escape=False,
    )


def _complete_instances(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Keep the instances on which every solver (seed aside) has a result.

    A partial run — or a solver added later with ``--resume`` — would otherwise
    bias every aggregate towards the instances it happened to finish.
    Returns (filtered df, names of the dropped instances).
    """
    solvers = [s for s in df["solver"].cat.categories if s != SEED_NAME]
    have = df[df["solver"] != SEED_NAME].groupby("instance")["solver"].nunique()
    complete = set(have[have >= len(solvers)].index)
    dropped = sorted(set(df["instance"]) - complete)
    return df[df["instance"].isin(complete)].reset_index(drop=True), dropped


def _pct(x) -> str:
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.1f} %"


def _solver_stats(df: pd.DataFrame) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    n_inst = df["instance"].nunique()
    for s in df["solver"].cat.categories:
        d = df[df["solver"] == s]
        stats[s] = {
            "label": SOLVER_LABEL.get(s, s),
            "n": int(len(d)),
            "valid": int(d["valid"].sum()),
            "at_best_cov": int(d["cost_gap"].count()),
            "best_cost": int(d["is_best"].sum()),
            "gap_mean": float(100 * d["cost_gap"].mean())
            if d["cost_gap"].notna().any()
            else np.nan,
            "gap_median": float(100 * d["cost_gap"].median())
            if d["cost_gap"].notna().any()
            else np.nan,
            "gap_max": float(100 * d["cost_gap"].max()) if d["cost_gap"].notna().any() else np.nan,
            "deficit": int(np.nan_to_num(d["coverage_deficit"].sum())),
            "wall_mean": float(d["wall_time_s"].mean()),
            "ttb_mean": float(d["time_to_best_s"].mean())
            if d["time_to_best_s"].notna().any()
            else np.nan,
            "share_best_cov": 100.0 * d["cost_gap"].count() / n_inst,
            "share_best_cost": 100.0 * d["is_best"].sum() / n_inst,
        }
    return stats


def _pairwise(df: pd.DataFrame, a: str, b: str) -> dict | None:
    """How a compares with b instance by instance (lexicographic served, then cost)."""
    if a not in df["solver"].cat.categories or b not in df["solver"].cat.categories:
        return None
    da = df[df["solver"] == a].set_index("instance")
    db = df[df["solver"] == b].set_index("instance")
    common = da.index.intersection(db.index)
    da, db = da.loc[common], db.loc[common]
    more_cov = int((da["served"] > db["served"]).sum())
    less_cov = int((da["served"] < db["served"]).sum())
    same = da["served"] == db["served"]
    cheaper = int(((da["total_cost"] < db["total_cost"]) & same).sum())
    dearer = int(((da["total_cost"] > db["total_cost"]) & same).sum())
    tie = int(((da["total_cost"] == db["total_cost"]) & same).sum())
    rel = (da["total_cost"][same] / db["total_cost"][same] - 1.0) * 100
    return {
        "a": SOLVER_LABEL.get(a, a),
        "b": SOLVER_LABEL.get(b, b),
        "n": int(len(common)),
        "more_cov": more_cov,
        "less_cov": less_cov,
        "same_cov": int(same.sum()),
        "cheaper": cheaper,
        "dearer": dearer,
        "tie": tie,
        "rel_mean": float(rel.mean()) if len(rel) else np.nan,
        "rel_median": float(rel.median()) if len(rel) else np.nan,
        "rel_min": float(rel.min()) if len(rel) else np.nan,
        "rel_max": float(rel.max()) if len(rel) else np.nan,
    }


def _ranked(solvers: list[str], stats: dict[str, dict]) -> list[str]:
    """Solvers from strongest to weakest, in the objective's own order: fewest customers
    missed over the set, then most best-cost instances, then lowest mean cost gap."""
    return sorted(
        solvers,
        key=lambda s: (
            stats[s]["deficit"],
            -stats[s]["best_cost"],
            np.nan_to_num(stats[s]["gap_mean"], nan=np.inf),
        ),
    )


def _conclusions(df: pd.DataFrame, stats: dict[str, dict], meta: dict) -> list[str]:
    """Data-driven conclusions in plain English (paragraphs)."""
    solvers = [s for s in df["solver"].cat.categories if s != SEED_NAME]
    n_inst = df["instance"].nunique()
    out: list[str] = []
    invalid = int((~df["valid"]).sum())
    n_solver_rows = int((df["solver"] != SEED_NAME).sum())
    n_seed_rows = int((df["solver"] == SEED_NAME).sum())
    out.append(
        f"All {n_solver_rows} solver results"
        + (f" (and the {n_seed_rows} generator seed solutions)" if n_seed_rows else "")
        + " were re-evaluated by the independent validator; "
        + (
            "every one of them is feasible."
            if invalid == 0
            else f"{invalid} are invalid and were excluded from every 'best'."
        )
    )
    ranked = _ranked(solvers, stats)
    lead = ranked[0]
    st = stats[lead]
    out.append(
        f"{st['label']} is the strongest method on this set (coverage first, then cost): it reaches the best "
        f"known coverage on {st['at_best_cov']} of {n_inst} instances, misses {st['deficit']} customers in total, "
        f"and has the best known cost on {st['best_cost']} ({_pct(st['share_best_cost'])}); its cost gap "
        f"averages {_pct(st['gap_mean'])} (median {_pct(st['gap_median'])}, worst {_pct(st['gap_max'])})."
    )
    for s in ranked[1:]:
        st = stats[s]
        out.append(
            f"{st['label']}: best known coverage on {st['at_best_cov']} instances, best cost on {st['best_cost']}; "
            f"mean cost gap {_pct(st['gap_mean'])} (median {_pct(st['gap_median'])}, worst {_pct(st['gap_max'])}); "
            f"{st['deficit']} customers missed in total vs the best known coverage."
        )
    pw = _pairwise(df, "cw_ls", "ortools")
    if pw:
        out.append(
            f"Head to head, {pw['a']} vs {pw['b']} on {pw['n']} instances: {pw['b']} serves more customers on "
            f"{pw['less_cov']}, fewer on {pw['more_cov']}; at equal coverage {pw['a']} is cheaper on {pw['cheaper']}, "
            f"dearer on {pw['dearer']} (ties {pw['tie']}), with a cost {pw['rel_mean']:+.1f} % on average "
            f"(median {pw['rel_median']:+.1f} %, range {pw['rel_min']:+.1f} % to {pw['rel_max']:+.1f} %)."
        )
    pwh = _pairwise(df, "hexaly", "ortools")
    if pwh:
        out.append(
            f"The license question, head to head: {pwh['a']} vs {pwh['b']} on {pwh['n']} instances, {pwh['a']} "
            f"serves more customers on {pwh['more_cov']}, fewer on {pwh['less_cov']}; at equal coverage it is "
            f"cheaper on {pwh['cheaper']}, dearer on {pwh['dearer']} (ties {pwh['tie']}), with a cost "
            f"{pwh['rel_mean']:+.1f} % on average (median {pwh['rel_median']:+.1f} %, range "
            f"{pwh['rel_min']:+.1f} % to {pwh['rel_max']:+.1f} %) — same machine, same limits, one thread each."
        )
    if "hexaly" in solvers:
        h = df[df["solver"] == "hexaly"]
        by_stress = h.groupby("capacity_stress", observed=True)["coverage_deficit"].sum()
        top = by_stress.index.max()
        at_top = h[(h["capacity_stress"] == top) & h["cost_gap"].notna()]
        by_n_wins = h.groupby("n", observed=True)["is_best"].sum()
        out.append(
            f"Where Hexaly loses is coverage, not cost: {int(by_stress.get(top, 0))} of its "
            f"{stats['hexaly']['deficit']} missed customers are on the {int(top)} % stress instances, where it reaches "
            f"the best known coverage on {len(at_top)} of {int((h['capacity_stress'] == top).sum())} — and on those "
            f"{len(at_top)} its cost gap is only {_pct(float(100 * at_top['cost_gap'].mean())) if len(at_top) else '–'}. "
            "Its best-cost wins by size: "
            + ", ".join(f"{int(v)} at n={int(k)}" for k, v in by_n_wins.items())
            + ". The shortfall is not an artefact of the objective's shape: in the secondary experiments "
            "(results/experiments/README.md) neither hard time-window constraints nor a single penalised objective "
            "(served × big-M − cost, the shape OR-Tools optimises) served more customers. Thread count and a longer "
            "limit — Hexaly's natural setting, deliberately not used in this equal-footing table — are studied there too."
        )
        pwc = _pairwise(df, "hexaly", "cw_ls")
        if pwc:
            out.append(
                f"Hexaly vs the own heuristic ({pwc['b']}): Hexaly serves more customers on {pwc['more_cov']}, fewer on "
                f"{pwc['less_cov']}; at equal coverage it is cheaper on {pwc['cheaper']}, dearer on {pwc['dearer']}, "
                f"with a cost {pwc['rel_mean']:+.1f} % on average (median {pwc['rel_median']:+.1f} %)."
            )
    pw2 = _pairwise(df, "cw", "cw_ls")
    if pw2:
        out.append(
            f"The local search earns its keep: plain Clarke-Wright costs {pw2['rel_mean']:+.1f} % on average "
            f"vs CW + local search at equal coverage and misses {stats['cw']['deficit']} customers vs "
            f"{stats['cw_ls']['deficit']} — for a wall time of {stats['cw']['wall_mean']:.1f} s against the full limit."
        )
    # stress / windows
    bs = by_factor(df, "capacity_stress")
    hard = bs[bs["capacity_stress"] == bs["capacity_stress"].max()]
    if not hard.empty:
        parts = [
            f"{SOLVER_LABEL.get(r.solver, r.solver)} {r.coverage_pct_mean:.1f} %"
            for r in hard.itertuples()
        ]
        out.append(
            f"Over-subscribed instances (stress {int(hard['capacity_stress'].iloc[0])} %): mean coverage "
            + ", ".join(parts)
            + ". Differences of one or two customers here are the interesting ones — they are the part of the fleet "
            "capacity a method manages to consolidate."
        )
    bt = by_factor(df, "tw_profile")
    if not bt.empty:
        tight = bt[bt["tw_profile"] == "T"]
        loose = bt[bt["tw_profile"] == "L"]
        if not tight.empty and not loose.empty:
            parts = []
            for s in solvers:
                gt = tight[tight["solver"] == s]["cost_gap_pct_mean"]
                gl = loose[loose["solver"] == s]["cost_gap_pct_mean"]
                if len(gt) and len(gl):
                    parts.append(
                        f"{SOLVER_LABEL.get(s, s)} {float(gl.iloc[0]):.1f} % → {float(gt.iloc[0]):.1f} %"
                    )
            if parts:
                out.append("Mean cost gap from loose to tight windows: " + "; ".join(parts) + ".")
    bn = by_factor(df, "n")
    if not bn.empty and bn["n"].nunique() >= 2:
        # does the gap between the heuristics and the best method widen with size?
        gap_parts = []
        for s in ranked[1:]:
            d = bn[bn["solver"] == s].sort_values("n")
            if len(d) and d["cost_gap_pct_mean"].notna().any():
                gap_parts.append(
                    f"{SOLVER_LABEL.get(s, s)} "
                    + " → ".join(
                        f"{float(r.cost_gap_pct_mean):.1f} % (n={int(r.n)})" for r in d.itertuples()
                    )
                )
        if gap_parts:
            out.append("Mean cost gap by instance size: " + "; ".join(gap_parts) + ".")
        ttb_parts = []
        for s in solvers:
            d = bn[bn["solver"] == s].sort_values("n")
            if len(d):
                ttb_parts.append(
                    f"{SOLVER_LABEL.get(s, s)} {float(d['time_to_best_s_mean'].iloc[0]):.0f} s at n={int(d['n'].iloc[0])} "
                    f"→ {float(d['time_to_best_s_mean'].iloc[-1]):.0f} s at n={int(d['n'].iloc[-1])}"
                )
        out.append(
            "Mean time to the best solution found, smallest to largest size: "
            + "; ".join(ttb_parts)
            + ". A value close to the limit means the search was still improving when stopped."
        )
        # was the leader still improving at the largest size? then the limit, not the
        # heuristics, sets the size of the gap there
        big = bn[(bn["n"] == bn["n"].max()) & (bn["solver"] == lead)]
        lim = df[df["n"] == bn["n"].max()]["time_limit_s"].max()
        if len(big) and lim and float(big["time_to_best_s_mean"].iloc[0]) > 0.7 * float(lim):
            out.append(
                f"At n = {int(bn['n'].max())} {SOLVER_LABEL.get(lead, lead)} found its final solution at "
                f"{float(big['time_to_best_s_mean'].iloc[0]):.0f} s of the {float(lim):.0f} s allowed on average, "
                "i.e. it was still improving when stopped. Any narrowing of the other methods' gaps at that size "
                "says more about the time limit than about the methods; a longer tier for the largest size "
                "(configuration only) would likely widen it again."
            )
    hw = meta.get("host", {})
    out.append(
        f"Hardware: {hw.get('platform', '?')}, {hw.get('cpu_count', '?')} logical CPUs, Python {hw.get('python', '?')}, "
        f"OR-Tools {hw.get('packages', {}).get('ortools', '?')}; {meta.get('workers', 1)} parallel worker(s), "
        "every solver single-threaded, one common wall-clock limit per instance size."
    )
    if "hexaly" not in solvers:
        out.append(
            "Hexaly is not in this run (evaluation license pending). Its adapter plugs into the same runner and "
            "validator; <code>bench run --solvers hexaly --out &lt;run dir&gt;</code> on the same run directory "
            "adds its column (resume skips what is done) and <code>bench report</code> regenerates this page."
        )
    return out


def _recommendations(df: pd.DataFrame, stats: dict[str, dict]) -> list[tuple[str, str]]:
    solvers = [s for s in df["solver"].cat.categories if s != SEED_NAME]
    ranked = _ranked(solvers, stats)
    lead = SOLVER_LABEL.get(ranked[0], ranked[0])
    n_inst = df["instance"].nunique()
    recs: list[tuple[str, str]] = []
    if "ortools" in solvers:
        st = stats["ortools"]
        standing = (
            "Best quality in this run within the same time limit"
            if ranked[0] == "ortools"
            else f"Second to {lead} in this run (mean gap {_pct(st['gap_mean'])}, {st['deficit']} customers missed)"
        )
        recs.append(
            (
                "OR-Tools (free, Apache 2.0)",
                f"{standing}; the Routing library handles time windows, capacities, heterogeneous fleets and "
                "optional customers out of the box. Its cost is engineering: modelling in its dimension/callback "
                "idiom, C++-side matrices to keep it fast from Python, and little control over the search beyond "
                "the metaheuristic switch. Default choice for a daily planning tool at this scale.",
            )
        )
    if "cw_ls" in solvers:
        st = stats["cw_ls"]
        verdict = (
            "It is the best method in this run, so the case for a solver rests on modelling comfort, not quality."
            if ranked[0] == "cw_ls"
            else f"Not worth it as a replacement for {lead} on a standard CVRPTW."
        )
        recs.append(
            (
                "Own heuristic (Clarke-Wright + local search)",
                f"Within {_pct(st['gap_mean'])} of the best known cost on average, at best coverage on "
                f"{st['at_best_cov']} of {n_inst} instances ({st['deficit']} customers missed), in plain Python with "
                "full control of every rule. Worth it when the business rules do not fit a solver's model, when the "
                "plan must be re-optimised incrementally in seconds, or when dependencies must stay minimal. "
                + verdict,
            )
        )
    if "cw" in solvers:
        st = stats["cw"]
        recs.append(
            (
                "Clarke-Wright alone",
                f"A {st['wall_mean']:.1f}-second answer that is {_pct(st['gap_mean'])} more expensive on average and "
                f"misses {st['deficit']} customers over the set. Fine as a first plan, a warm start or an interactive "
                "'what if' estimate; not a production optimiser.",
            )
        )
    if "hexaly" in solvers:
        st = stats["hexaly"]
        standing = (
            "Best quality in this run within the same time limit"
            if ranked[0] == "hexaly"
            else f"Behind {lead} in this run"
        )
        recs.append(
            (
                "Hexaly (commercial)",
                f"{standing}: best known coverage on {st['at_best_cov']} of {n_inst} instances "
                f"({st['deficit']} customers missed), best cost on {st['best_cost']}, mean gap {_pct(st['gap_mean'])}. "
                "Its model is plain arithmetic on list variables (69 code lines here, against 42 for OR-Tools' "
                "Routing model and about 900 for the own heuristic): not shorter than OR-Tools on a textbook "
                "CVRPTW, but every extra business rule is one more expression rather than a new dimension or "
                "callback, and it is multi-threaded out of the box, which this single-thread comparison does not "
                "credit (results/experiments/ holds the multi-thread and longer-limit runs, judged against this "
                "table). Judge the license against the head-to-head with OR-Tools above, those experiments, and "
                "the kind of side constraints your real problems carry.",
            )
        )
    else:
        recs.append(
            (
                "Hexaly (pending)",
                "To be added when the evaluation license arrives; the decision hinges on whether it closes the gap "
                "to (or beats) OR-Tools at the same time limit, and on how much modelling effort it saves.",
            )
        )
    return recs


# ------------------------------------------------------------------- report
TEMPLATE = Template(
    r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<script>{{ plotly_js }}</script>
<style>
:root{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8985;--grid:#e6e5e1;--accent:#2a78d6}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--ink);font:14px/1.5 Inter,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 24px 80px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:44px 0 12px;padding-top:12px;border-top:1px solid var(--grid)}
h3{font-size:15px;margin:22px 0 8px}
p{max-width:820px}.sub{color:var(--ink2);margin:0 0 18px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}
.tile{border:1px solid var(--grid);border-radius:8px;padding:12px 14px}
.tile .v{font-size:22px;font-weight:600}.tile .l{color:var(--ink2);font-size:12px}
.tile .s{font-size:12px;color:var(--ink2)}
.tbl{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0 4px}
.tbl th,.tbl td{padding:5px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
.tbl th{color:var(--ink2);font-weight:600;text-align:right;background:#f4f3f0;position:sticky;top:0;cursor:pointer}
.tbl td:first-child,.tbl th:first-child,.tbl td:nth-child(2),.tbl th:nth-child(2){text-align:left}
.tblwrap{overflow-x:auto;border:1px solid var(--grid);border-radius:8px;max-height:560px;overflow-y:auto}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.fig{border:1px solid var(--grid);border-radius:8px;padding:6px;margin:10px 0;overflow-x:auto}
.gallery img{max-width:100%;border:1px solid var(--grid);border-radius:6px}
.gallery .cap{font-size:12px;color:var(--ink2);margin:4px 0 14px}
.note{border-left:3px solid var(--accent);padding:6px 12px;color:var(--ink2);background:#f4f3f0;border-radius:0 6px 6px 0;max-width:820px}
.rec{border:1px solid var(--grid);border-radius:8px;padding:12px 14px;margin:8px 0}
.rec b{display:block;margin-bottom:4px}
.legend span{display:inline-block;width:11px;height:11px;border-radius:2px;margin:0 6px 0 14px;vertical-align:-1px}
footer{color:var(--muted);font-size:12px;margin-top:40px}
</style></head><body><main>
<h1>{{ title }}</h1>
<p class="sub">{{ subtitle }}</p>
<p class="legend">Solvers:
{% for s, c in solver_colors %}<span style="background:{{ c }}"></span>{{ s }}{% endfor %}</p>

<div class="tiles">
{% for t in tiles %}<div class="tile"><div class="l">{{ t.l }}</div><div class="v">{{ t.v }}</div><div class="s">{{ t.s }}</div></div>{% endfor %}
</div>

<h2>1. Setup</h2>
<p>{{ setup }}</p>
<div class="note">Fairness: every solver receives the same instance files, the same integer distance / time / cost
matrices, the same seed, one thread, and the same wall-clock limit for its instance size
({{ limits }}). A solver may finish earlier (Clarke-Wright does); the limit is a cap, not a target.
Every result is re-evaluated from the visiting orders by an independent validator, which is the only
source of the numbers below. Gaps are computed <em>coverage first</em>: the best known coverage per instance is
the maximum served among valid results (the generator's seed solution included); a result with fewer customers
gets a coverage deficit and no cost gap; among results at best coverage, the cost gap is cost / best cost − 1.</div>

<h2>2. Overall</h2>
<div class="tblwrap">{{ overall_table }}</div>
<div class="fig">{{ fig_wins }}</div>
<div class="grid2"><div class="fig">{{ fig_deficit }}</div><div class="fig">{{ fig_profile }}</div></div>

<h2>3. Where each method wins and loses</h2>
{% for key, title, table, fig in factors %}
<h3>By {{ title }}</h3>
<div class="tblwrap">{{ table }}</div>
<div class="fig">{{ fig }}</div>
{% endfor %}

<h2>4. Time</h2>
<div class="fig">{{ fig_time }}</div>
<p>Wall time is bounded by the limit for every solver except Clarke-Wright, which stops after its 20 starts.
"Time to best" is when the returned solution was first found; a value close to the limit means the search was
still improving when it was stopped.</p>
{% for f in convergence %}<div class="fig">{{ f }}</div>{% endfor %}

{% if gallery %}
<h2>5. A look at the routes</h2>
<div class="gallery">
{% for g in gallery %}
<h3>{{ g.instance }} — {{ g.desc }}</h3>
<div class="grid2">
{% for item in g.plots %}<div><img src="{{ item.src }}" alt="{{ item.cap }}"><div class="cap">{{ item.cap }}</div></div>{% endfor %}
</div>
{% endfor %}
</div>
{% endif %}

<h2>6. Conclusions</h2>
{% for p in conclusions %}<p>{{ p }}</p>{% endfor %}
<h3>Which tool when</h3>
{% for b, t in recommendations %}<div class="rec"><b>{{ b }}</b>{{ t }}</div>{% endfor %}

<h2>7. Every instance</h2>
<p class="sub">served / cost (CLP) / cost gap to best known (%) / time to best (s), per solver. Click a header to sort.</p>
<div class="tblwrap">{{ instance_table }}</div>

<h2>8. Methods in one paragraph each</h2>
{% for b, t in methods %}<div class="rec"><b>{{ b }}</b>{{ t }}</div>{% endfor %}

<footer>Generated {{ generated }} by cvrptw-bench {{ version }} · run directory {{ run_dir }} · CSV twins of every table are next to this file.</footer>
</main>
<script>
document.querySelectorAll('table.tbl').forEach(function(t){
  t.querySelectorAll('th').forEach(function(th,i){
    th.addEventListener('click',function(){
      var tb=t.tBodies[0],rows=Array.from(tb.rows),asc=th.dataset.asc!=='1';
      rows.sort(function(a,b){var x=a.cells[i].innerText.replace(/[^0-9eE+.-]/g,''),y=b.cells[i].innerText.replace(/[^0-9eE+.-]/g,'');
        var nx=parseFloat(x),ny=parseFloat(y);if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;
        return asc?a.cells[i].innerText.localeCompare(b.cells[i].innerText):b.cells[i].innerText.localeCompare(a.cells[i].innerText);});
      rows.forEach(function(r){tb.appendChild(r)});t.querySelectorAll('th').forEach(function(h){delete h.dataset.asc});th.dataset.asc=asc?'1':'0';
    });
  });
});
</script>
</body></html>
"""
)

METHODS = [
    (
        "Instances",
        "108 synthetic instances in Greater Santiago: 4 sizes (100, 200, 400, 600 customers) × 3 spatial families "
        "(R uniform, C clustered, RC mixed) × 3 time-window profiles (L loose, M mixed, T tight) × 3 capacity-stress "
        "levels (60, 85, 105 % of fleet capacity). Three vehicle types (800 / 1 600 / 3 200 units; fixed cost "
        "20 000 / 30 000 / 45 000 CLP; 350 / 500 / 700 CLP per km), hard windows, free waiting, one trip per vehicle, "
        "Haversine × 1.3 at 30 km/h. Windows are centred on a seed solution, so every instance at 60 % stress has a "
        "known full-coverage solution and the 105 % ones are over-subscribed by design.",
    ),
    (
        "Objective",
        "Lexicographic: maximise the number of customers served, then minimise total cost = fixed cost of the "
        "vehicles used + per-km cost by vehicle type. Implemented natively in each solver (penalty larger than any "
        "routing cost in OR-Tools; strict lexicographic acceptance in the heuristics) and recomputed by the validator.",
    ),
    (
        "Clarke-Wright (cw)",
        "Directed savings on 30-nearest-neighbour pairs with O(1) time-window merge checks; every feasible merge is "
        "taken while there are more routes than vehicles, then only merges that lower the real cost with the vehicle "
        "types the loads imply; smallest available type per route; leftovers re-inserted (in a route, in a route "
        "upgraded to a bigger spare vehicle, or alone on a spare vehicle); 20 randomised starts (λ ∈ [0.6, 1.4], "
        "±10 % noise), best by (served, −cost).",
    ),
    (
        "CW + local search (cw_ls)",
        "Variable-neighbourhood descent from the Clarke-Wright starts: relocate, swap, 2-opt*, or-opt (2–3), "
        "intra-route 2-opt, route split, route elimination, vehicle re-typing, and an insertion pass for unserved "
        "customers (direct, upgrade, spare vehicle, ejection of a neighbour). First improvement, candidate lists, "
        "O(1) inter-route feasibility; the descent is repeated from successive starts until the common time limit.",
    ),
    (
        "OR-Tools (ortools)",
        "Google OR-Tools Routing 9.15: per-type cost matrices registered in C++ and assigned per vehicle, fixed cost "
        "per vehicle used, capacity dimension, time dimension (cumul = service start, slack = waiting, windows, free "
        "departure), optional customers via disjunctions with one uniform penalty above any routing cost, "
        "PATH_CHEAPEST_ARC + guided local search, single thread. Its objective equals the validator's cost plus "
        "penalty × dropped on every run (asserted in the tests).",
    ),
    (
        "Hexaly (hexaly)",
        "Hexaly Optimizer 15 (Python SDK): one list variable per vehicle with a disjoint constraint (optional "
        "customers), capacity as a sum over the list, service starts as a recursive array with free departure "
        "and free waiting, hard windows and return before closing as constraints, cost = fixed cost if the list "
        "is not empty + arc costs from the type's matrix; two lexicographic objectives (maximise served, "
        "minimise cost); Hexaly's own search, single thread, seed and time limit from the common config. Its "
        "objective values are recomputed by the validator on every run.",
    ),
    (
        "Generator seed",
        "The sweep + repair solution the generator built to place the time windows. Not a contender — a sanity "
        "reference: every method should beat it.",
    ),
]


def build_report(
    run_dir: str | Path,
    instances_dir: str | Path | None = "instances",
    out_path: str | Path | None = None,
    gallery: int = 3,
    basemap: str = "esri-gray",
    dpi: int = 110,
    log=print,
) -> Path:
    run_dir = Path(run_dir)
    out_path = Path(out_path) if out_path else run_dir / "report.html"
    df = collect(run_dir, instances_dir)
    if df.empty:
        raise SystemExit(f"no solutions found under {run_dir}")
    df, incomplete = _complete_instances(df)
    if df.empty:
        raise SystemExit(f"no instance under {run_dir} has a result from every solver")
    if incomplete:
        log(f"report: {len(incomplete)} instance(s) without a result from every solver left out")
    df = add_gaps(df)
    tables_dir = out_path.parent / "tables"
    write_tables(df, tables_dir)
    meta = {}
    if (run_dir / "run_meta.json").exists():
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    stats = _solver_stats(df)
    solvers = [s for s in df["solver"].cat.categories if s != SEED_NAME]
    n_inst = df["instance"].nunique()
    limits = meta.get("config", {}).get("time_limits_s", {})
    limits_txt = (
        ", ".join(f"≤{k}: {v} s" for k, v in limits.items() if str(k).isdigit()) or "see run config"
    )

    # --- tiles
    total_h = df[df["solver"] != SEED_NAME]["wall_time_s"].sum() / 3600
    tiles = [
        {"l": "instances", "v": n_inst, "s": f"{df['n'].min()}–{df['n'].max()} customers"},
        {
            "l": "solvers",
            "v": len(solvers),
            "s": ", ".join(SOLVER_LABEL.get(s, s) for s in solvers),
        },
        {
            "l": "compute",
            "v": f"{total_h:.1f} h",
            "s": f"{meta.get('workers', 1)} worker(s), single-threaded solvers",
        },
        {
            "l": "valid solver results",
            "v": f"{int(df.loc[df['solver'] != SEED_NAME, 'valid'].sum())}"
            f"/{int((df['solver'] != SEED_NAME).sum())}",
            "s": "independent validator",
        },
    ]
    for s in solvers:
        st = stats[s]
        tiles.append(
            {
                "l": st["label"],
                "v": f"{st['best_cost']}/{n_inst}",
                "s": f"best cost · mean gap {_pct(st['gap_mean'])} · missed {st['deficit']}",
            }
        )

    # --- tables
    ov = overall(df)
    ov["solver"] = ov["solver"].map(lambda s: SOLVER_LABEL.get(s, s))
    factor_blocks = []
    for key in ("n", "capacity_stress", "tw_profile", "family"):
        t = by_factor(df, key)
        t["solver"] = t["solver"].map(lambda s: SOLVER_LABEL.get(s, s))
        factor_blocks.append(
            (
                key,
                FACTOR_TITLES[key],
                _table_html(t),
                _fig_html(charts.cost_gap_box(df, key, FACTOR_TITLES[key])),
            )
        )

    # --- per-instance wide table
    rows = []
    for inst, g in df.groupby("instance", sort=False):
        r0 = g.iloc[0]
        row = {
            "instance": inst,
            "n": int(r0["n"]),
            "family": r0["family"],
            "tw": r0["tw_profile"],
            "stress": None if pd.isna(r0["capacity_stress"]) else int(r0["capacity_stress"]),
        }
        for s in list(df["solver"].cat.categories):
            gs = g[g["solver"] == s]
            if gs.empty:
                continue
            x = gs.iloc[0]
            lab = SOLVER_LABEL.get(s, s)
            row[f"{lab} served"] = int(x["served"])
            row[f"{lab} cost"] = int(x["total_cost"])
            row[f"{lab} gap %"] = (
                np.nan if pd.isna(x["cost_gap"]) else round(100 * x["cost_gap"], 2)
            )
            if s != SEED_NAME:
                row[f"{lab} ttb s"] = (
                    np.nan if pd.isna(x["time_to_best_s"]) else round(float(x["time_to_best_s"]), 1)
                )
        rows.append(row)
    inst_table = pd.DataFrame(rows).sort_values(["n", "instance"])

    # --- convergence: one instance per size
    conv_figs = []
    for n in sorted(df["n"].unique()):
        cands = [
            i for i in df[df["n"] == n]["instance"].unique() if i.startswith("RC-") and "-M-85" in i
        ]
        name = cands[0] if cands else df[df["n"] == n]["instance"].iloc[0]
        traces = {}
        for s in solvers:
            p = run_dir / name / s / "solution.json"
            if p.exists():
                traces[s] = [tuple(t) for t in Solution.load(p).trace]
        if traces:
            conv_figs.append(_fig_html(charts.convergence_fig(traces, name, int(n))))

    # --- gallery
    gal = []
    if gallery > 0 and instances_dir is not None:
        from cvrptw_bench.viz import plot_all

        picks = []
        for fam in ("RC", "R", "C"):
            c = df[
                (df["family"] == fam)
                & (df["n"] == 400)
                & (df["tw_profile"] == "T")
                & (df["capacity_stress"] == 105)
            ]
            if not c.empty:
                picks.append(c["instance"].iloc[0])
        picks = picks[:gallery]
        for name in picks:
            inst = Instance.load(Path(instances_dir) / f"{name}.json")
            items = []
            for s in [x for x in ("ortools", "hexaly", "cw_ls") if x in solvers]:
                sdir = run_dir / name / s
                if not (sdir / "solution.json").exists():
                    continue
                sol = Solution.load(sdir / "solution.json")
                if not (sdir / "map.png").exists() or not (sdir / "gantt.png").exists():
                    log(f"gallery: plotting {name}/{s}")
                    plot_all(inst, sol, sdir, basemap=basemap, dpi=dpi, html=False)
                served, cost = sol.objective
                for kind, cap in (("map", "routes"), ("gantt", "schedule")):
                    src = _img_b64(sdir / f"{kind}.png")
                    if src:
                        items.append(
                            {
                                "src": src,
                                "cap": f"{SOLVER_LABEL.get(s, s)} — {cap}: {served}/{inst.n} served, {cost:,} CLP",
                            }
                        )
            f = inst.meta.get("factors", {})
            gal.append(
                {
                    "instance": name,
                    "desc": f"{f.get('n')} customers, {f.get('family')} layout, {f.get('tw_profile')} windows, {f.get('capacity_stress')} % stress",
                    "plots": items,
                }
            )

    hw = meta.get("host", {})
    probe = meta.get("cpu_probe") or {}
    probe_txt = (
        f" A CPU probe at the start of the run measured {probe.get('effective_cores', '?')} effective core(s) for "
        f"{meta.get('workers', 1)} concurrent jobs (each job ran {probe.get('slowdown', '?')}x slower than alone), "
        "so the limits below are wall-clock seconds of that share of a core — the same share for every solver."
        if probe.get("effective_cores") is not None
        else ""
    )
    setup = (
        f"Run started {meta.get('started', '?')} on {hw.get('platform', '?')} ({hw.get('cpu_count', '?')} logical CPUs), "
        f"Python {hw.get('python', '?')}, OR-Tools {hw.get('packages', {}).get('ortools', '?')}, "
        f"cvrptw-bench {meta.get('package_version', __version__)}. Solvers: "
        + ", ".join(SOLVER_LABEL.get(s, s) for s in solvers)
        + f". {n_inst} instances, {len(df[df['solver'] != SEED_NAME])} solver results, "
        f"{total_h:.1f} h of solver wall time with {meta.get('workers', 1)} worker(s)."
        + probe_txt
        + (
            f" The run directory was resumed {len(meta['resumed'])} time(s) (last {meta['resumed'][-1]}): "
            "an interrupted run continues where it stopped and a solver added later runs only its own jobs, "
            "on the same machine and limits."
            if meta.get("resumed")
            else ""
        )
        + (
            f" {len(incomplete)} instance(s) without a result from every solver are left out of this page: "
            + ", ".join(incomplete[:12])
            + ("…" if len(incomplete) > 12 else "")
            + "."
            if incomplete
            else ""
        )
    )
    html = TEMPLATE.render(
        title="CVRPTW with heterogeneous fleet — Santiago benchmark",
        subtitle=" · ".join(SOLVER_LABEL.get(s, s) for s in reversed(solvers))
        + f" on {n_inst} synthetic instances, same limits, same judge",
        solver_colors=[
            (SOLVER_LABEL.get(s, s), charts.SOLVER_COLOR.get(s, "#999"))
            for s in list(df["solver"].cat.categories)
        ],
        tiles=tiles,
        setup=setup,
        limits=limits_txt,
        overall_table=_table_html(ov),
        fig_wins=_fig_html(charts.wins_bar(df)),
        fig_deficit=_fig_html(charts.coverage_deficit_bars(df)),
        fig_profile=_fig_html(
            charts.performance_profile_fig(performance_profile(df), coverage_profile(df))
        ),
        factors=factor_blocks,
        fig_time=_fig_html(charts.time_to_best_box(df, limits_txt)),
        convergence=conv_figs,
        gallery=gal,
        conclusions=_conclusions(df, stats, meta),
        recommendations=_recommendations(df, stats),
        instance_table=_table_html(inst_table, "{:,.1f}"),
        methods=METHODS,
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        version=__version__,
        run_dir=str(run_dir),
        plotly_js=pio.get_plotlyjs()
        if hasattr(pio, "get_plotlyjs")
        else __import__("plotly").offline.get_plotlyjs(),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    log(
        f"report written to {out_path} ({out_path.stat().st_size / 1e6:.1f} MB); tables in {tables_dir}"
    )
    return out_path
