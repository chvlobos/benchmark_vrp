"""Interactive route map (folium / Leaflet): one toggleable layer per route,
tooltips with the schedule of every stop, unserved customers in red."""

from __future__ import annotations

from pathlib import Path

import folium

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.solution import Solution
from cvrptw_bench.viz.style import (
    DEPOT_COLOR,
    UNSERVED_COLOR,
    fmt_int,
    hhmm,
    route_shade,
    type_color_map,
)

ESRI_GRAY = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/"
    "MapServer/tile/{z}/{y}/{x}"
)
ESRI_ATTR = "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"


def _add_tiles(fmap: folium.Map, basemap: str) -> None:
    """Keyless tile layers; the first one added is the one shown."""
    if basemap == "none":
        return
    layers = {
        "esri-gray": [
            ("Esri light gray", ESRI_GRAY, ESRI_ATTR),
            ("OpenStreetMap", "OpenStreetMap", None),
        ],
        "osm": [
            ("OpenStreetMap", "OpenStreetMap", None),
            ("Esri light gray", ESRI_GRAY, ESRI_ATTR),
        ],
        "esri-street": [
            (
                "Esri streets",
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/"
                "MapServer/tile/{z}/{y}/{x}",
                ESRI_ATTR,
            ),
            ("OpenStreetMap", "OpenStreetMap", None),
        ],
        "carto": [("CartoDB positron (API key)", "CartoDB positron", None)],
    }.get(basemap, [("OpenStreetMap", "OpenStreetMap", None)])
    for name, tiles, attr in layers:
        kw = {"name": name, "control": True}
        if attr:
            kw["attr"] = attr
        folium.TileLayer(tiles=tiles, **kw).add_to(fmap)


def plot_map_html(
    instance: Instance, solution: Solution, path: str | Path, basemap: str = "esri-gray"
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cust = {c.id: c for c in instance.customers}
    colors = type_color_map(instance)
    served, cost = solution.objective

    fmap = folium.Map(
        location=[instance.depot.lat, instance.depot.lon],
        zoom_start=11,
        tiles=None,
        control_scale=True,
    )
    _add_tiles(fmap, basemap)
    title = (
        f"<div style='position:fixed;top:10px;left:60px;z-index:9999;background:#fcfcfbee;"
        f"padding:6px 10px;border:1px solid #e6e5e1;border-radius:4px;"
        f"font:13px sans-serif;color:#0b0b0b'>"
        f"<b>{instance.name}</b> · {solution.solver} · served {served}/{instance.n} · "
        f"cost {fmt_int(cost)} CLP · {solution.metrics.get('distance_km', 0):.0f} km</div>"
    )
    fmap.get_root().html.add_child(folium.Element(title))

    folium.Marker(
        [instance.depot.lat, instance.depot.lon],
        tooltip="Depot",
        icon=folium.Icon(color="black", icon="home", prefix="fa"),
    ).add_to(fmap)

    shade_idx: dict[str, int] = {}
    for r in sorted(solution.routes, key=lambda r: r.vehicle_id):
        base = colors[r.vehicle_type]
        k = shade_idx.get(r.vehicle_type, 0)
        shade_idx[r.vehicle_type] = k + 1
        col = route_shade(base, k)
        name = (
            f"v{r.vehicle_id:02d} {r.vehicle_type} · {len(r.stops)} stops · "
            f"{r.distance_m / 1000:.1f} km · {hhmm(r.depart)}–{hhmm(r.return_time)}"
        )
        fg = folium.FeatureGroup(name=name, show=True)
        pts = [[instance.depot.lat, instance.depot.lon]]
        for i, s in enumerate(r.stops, 1):
            c = cust[s.customer]
            pts.append([c.lat, c.lon])
            tip = (
                f"<b>Customer {c.id}</b> (stop {i} of v{r.vehicle_id:02d} {r.vehicle_type})<br>"
                f"demand {c.demand} · service {c.service_time // 60} min<br>"
                f"window {hhmm(c.tw_start)}–{hhmm(c.tw_end)} ({c.tw_class})<br>"
                f"arrival {hhmm(s.arrival)} · wait {s.wait // 60} min · "
                f"start {hhmm(s.service_start)} · leave {hhmm(s.departure)}"
            )
            folium.CircleMarker(
                [c.lat, c.lon],
                radius=3 + min(c.demand, 800) / 160,
                color=col,
                fill=True,
                fill_opacity=0.9,
                weight=1,
                tooltip=tip,
            ).add_to(fg)
        pts.append([instance.depot.lat, instance.depot.lon])
        folium.PolyLine(pts, color=col, weight=2.5, opacity=0.85, tooltip=name).add_to(fg)
        fg.add_to(fmap)

    if solution.unserved:
        fg = folium.FeatureGroup(name=f"unserved ({len(solution.unserved)})", show=True)
        for u in solution.unserved:
            c = cust[u.customer]
            folium.CircleMarker(
                [c.lat, c.lon],
                radius=4 + min(c.demand, 800) / 160,
                color=UNSERVED_COLOR,
                fill=False,
                weight=2,
                tooltip=(
                    f"<b>Customer {c.id}</b> — unserved ({u.reason})<br>"
                    f"demand {c.demand} · window {hhmm(c.tw_start)}–{hhmm(c.tw_end)} ({c.tw_class})"
                ),
            ).add_to(fg)
        fg.add_to(fmap)

    folium.LayerControl(collapsed=True).add_to(fmap)
    fmap.fit_bounds(
        [
            [min(c.lat for c in instance.customers), min(c.lon for c in instance.customers)],
            [max(c.lat for c in instance.customers), max(c.lon for c in instance.customers)],
        ]
    )
    fmap.save(str(path))
    return path


__all__ = ["plot_map_html", "DEPOT_COLOR"]
