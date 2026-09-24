"""
Dynamic Municipal Waste Route Optimization - Streamlit dashboard.

    comparision.run_simulation()  ->  structured results  ->  this file

This file only DISPLAYS results.  It contains no simulation or OR-Tools logic.
Road-following geometry for the map comes from road_geometry.py and is used
for drawing only (the optimizer always uses road_distance_matrix.csv).

Run:  streamlit run app.py
"""

import html
import traceback
from pathlib import Path

import altair as alt
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import road_geometry
from comparision import run_simulation


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Dynamic Municipal Waste Route Optimization",
    page_icon="♻️",
    layout="wide"
)


# ============================================================
# CONSTANTS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

RED = "#d64545"        # fill >= threshold  -> collection required
GREEN = "#2f9e5b"      # fill <  threshold  -> skipped
BLUE = "#1f5fbf"       # OR-Tools routes
NEUTRAL = "#4b5b73"    # overview map markers

# Different trucks get different shades of blue.
TRUCK_BLUES = [
    "#1f5fbf", "#0b3d91", "#2d7dd2", "#3949ab", "#00629b",
    "#4a90d9", "#274690", "#1c7ed6", "#5b7fd6", "#0f4c81"
]

METHODS = ["Static", "Dynamic", "Dynamic + OR-Tools"]

METHOD_COLORS = ["#a3abb8", "#7aa2dc", BLUE]

CODE_FILES = [
    "comparision.py",
    "route_optimizer.py",
    "locations.csv",
    "road_distance_matrix.csv"
]


# ============================================================
# STREAMLIT VERSION HELPERS
# ============================================================

def _streamlit_version():

    parts = []

    for piece in st.__version__.split(".")[:2]:

        digits = "".join(ch for ch in piece if ch.isdigit())

        parts.append(int(digits) if digits else 0)

    return tuple(parts)


_NEW_WIDTH_API = _streamlit_version() >= (1, 50)

# fragments (rerun only part of the page) exist from Streamlit 1.37
fragment = getattr(st, "fragment", None) or (lambda func: func)


def stretch(func, *args, **kwargs):
    """Call a Streamlit element so that it fills its container."""

    options = [
        {"width": "stretch"},
        {"use_container_width": True}
    ]

    if not _NEW_WIDTH_API:
        options.reverse()

    for extra in options + [{}]:

        try:
            return func(*args, **kwargs, **extra)

        except (TypeError, st.errors.StreamlitAPIException):
            continue

    return func(*args, **kwargs)


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 2.2rem;
        max-width: 1500px;
    }

    .wr-kpi {
        border: 1px solid rgba(128, 128, 128, 0.30);
        border-radius: 8px;
        padding: 14px 16px 12px 16px;
        height: 100%;
    }
    .wr-kpi.accent {
        border-left: 5px solid var(--accent);
    }
    .wr-kpi .label {
        font-size: 0.86rem;
        opacity: 0.75;
    }
    .wr-kpi .value {
        font-size: 1.85rem;
        font-weight: 650;
        line-height: 1.2;
    }
    .wr-kpi .sub {
        font-size: 0.84rem;
        opacity: 0.8;
        margin-top: 2px;
    }

    .wr-scroll {
        overflow-y: auto;
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 8px;
    }
    table.wr-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.92rem;
    }
    table.wr-table th,
    table.wr-table td {
        text-align: center;
        vertical-align: middle;
        padding: 7px 10px;
        border-bottom: 1px solid rgba(128, 128, 128, 0.18);
    }
    table.wr-table th {
        font-weight: 650;
        background: rgba(128, 128, 128, 0.12);
    }
    table.wr-table tr.red-row td {
        background: rgba(214, 69, 69, 0.11);
    }
    table.wr-table tr.green-row td {
        background: rgba(47, 158, 91, 0.10);
    }

    .wr-truck {
        border: 1px solid rgba(128, 128, 128, 0.30);
        border-left: 5px solid var(--accent);
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }
    .wr-truck .head {
        font-weight: 650;
        font-size: 1.02rem;
    }
    .wr-truck .facts {
        font-size: 0.86rem;
        opacity: 0.85;
        margin: 2px 0 8px 0;
    }
    .wr-truck .stop {
        text-align: center;
        font-size: 0.9rem;
        padding: 3px 8px;
        border-radius: 5px;
        background: rgba(128, 128, 128, 0.10);
    }
    .wr-truck .stop.depot {
        font-weight: 650;
        background: rgba(31, 95, 191, 0.14);
    }
    .wr-truck .arrow {
        text-align: center;
        line-height: 1.1;
        opacity: 0.6;
    }

    div[data-testid="stButton"] button {
        white-space: nowrap;
        padding-left: 0.2rem;
        padding-right: 0.2rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# SMALL UI HELPERS
# ============================================================

def esc(value):
    return html.escape(str(value))


def kpi(label, value, sub="", accent=None):
    """HTML for one number card."""

    css_class = "wr-kpi accent" if accent else "wr-kpi"

    style = f' style="--accent:{accent}"' if accent else ""

    sub_html = f'<div class="sub">{sub}</div>' if sub else ""

    return (
        f'<div class="{css_class}"{style}>'
        f'<div class="label">{label}</div>'
        f'<div class="value">{value}</div>'
        f'{sub_html}</div>'
    )


def kpi_row(cards):
    """Show several kpi() cards side by side."""

    columns = st.columns(len(cards))

    for column, card in zip(columns, cards):

        with column:
            st.markdown(card, unsafe_allow_html=True)


def table_html(df, row_classes=None, max_height=None):
    """A centered HTML table (Streamlit's own grid cannot center cells)."""

    head = "".join(f"<th>{esc(c)}</th>" for c in df.columns)

    rows = []

    for i, record in enumerate(df.itertuples(index=False)):

        css_class = row_classes[i] if row_classes else ""

        cells = "".join(f"<td>{esc(v)}</td>" for v in record)

        rows.append(f'<tr class="{css_class}">{cells}</tr>')

    style = f' style="max-height:{max_height}px"' if max_height else ""

    return (
        f'<div class="wr-scroll"{style}>'
        f'<table class="wr-table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def show_table(df, row_classes=None, max_height=None):

    st.markdown(
        table_html(df, row_classes, max_height),
        unsafe_allow_html=True
    )


def hour_label(hour):
    return f"{hour:02d}:00"


# ============================================================
# STATE
# ============================================================

def init_state():

    defaults = {
        "results": None,
        "results_threshold": None,
        "auto_ran": False,
        "selected_hour": 0,
        "run_error": None
    }

    for key, value in defaults.items():

        st.session_state.setdefault(key, value)


@st.cache_resource
def simulation_store():
    """
    Server-wide cache of finished simulations.

    The simulation is deterministic (fixed seeds), so the result for a given
    threshold is always identical and only needs to be computed once.
    """

    return {}


def code_signature():
    """Changes when any code/data file changes, so stale results are dropped."""

    return tuple(
        (BASE_DIR / name).stat().st_mtime_ns
        for name in CODE_FILES
    )


# ============================================================
# DEPOT
# ============================================================

def current_depot():
    """Depot (lat, lon) from the sidebar or road_geometry.py, else None."""

    typed = road_geometry.parse_depot(
        st.session_state.get("depot_text", "")
    )

    return typed or road_geometry.DEPOT_LATLON


# ============================================================
# ROUTE POINTS (used for map geometry only)
# ============================================================

def coordinate_lookup(results):

    first_hour = results["hourly_state"][0]

    return {
        b["site_location"]: (b["latitude"], b["longitude"])
        for b in first_hour["bins"]
    }


def route_points(route, coordinates, depot):
    """
    Ordered (lat, lon) stops of one truck route.
    If the depot position is unknown, the depot legs are left out.
    """

    points = []

    for name in route["route"]:

        if name == "DEPOT":

            if depot is not None:
                points.append(depot)

        elif name in coordinates:

            points.append(coordinates[name])

    return points


# ============================================================
# RUN SIMULATION (with truthful progress)
# ============================================================

def run_and_store(threshold):

    store = simulation_store()

    key = (threshold, code_signature())

    st.session_state["run_error"] = None

    with st.status(
        f"Running simulation (threshold {threshold}%)...",
        expanded=True
    ) as status:

        log = st.empty()

        bar = st.progress(0.0)

        lines = []

        current = {"text": None}

        def render():

            shown = lines + (
                [current["text"]] if current["text"] else []
            )

            log.markdown("  \n".join(shown))

        def on_progress(event):

            stage = event["stage"]

            hour = event.get("hour")

            if stage == "start":

                lines.append(
                    f"✓ Loaded {event['locations']} collection locations"
                )
                lines.append(
                    "✓ Initialized bin fill levels"
                )

            elif stage == "hour_start":

                current["text"] = (
                    f"⟳ Hour {hour_label(hour)} - updating bin fill levels..."
                )

            elif stage == "optimizing":

                current["text"] = (
                    f"⟳ Hour {hour_label(hour)} - optimizing truck routes "
                    f"for {event['bins']} bins..."
                )

            elif stage == "hour_done":

                if event["bins"] == 0:

                    lines.append(
                        f"✓ Hour {hour_label(hour)} - no bin at "
                        f"{threshold}% or more, no trucks needed"
                    )

                else:

                    lines.append(
                        f"✓ Hour {hour_label(hour)} - {event['bins']} bins "
                        f"collected by {event['trucks']} truck(s), "
                        f"{event['distance']:.1f} km"
                    )

                current["text"] = None

                bar.progress(
                    (hour + 1) / 24,
                    text=f"Hour {hour + 1} of 24"
                )

            elif stage == "finalizing":

                current["text"] = (
                    "⟳ Calculating savings, fuel and CO₂..."
                )

            render()

        try:

            if key in store:

                results = store[key]

                lines.append(
                    "✓ Loaded the saved result for this threshold "
                    "(the simulation is deterministic)"
                )

                bar.progress(1.0, text="Done")

                render()

            else:

                results = run_simulation(
                    threshold=threshold,
                    progress_callback=on_progress
                )

                store[key] = results

            lines.append("✓ Savings, fuel and CO₂ calculated")

            # ------------------------------------------------
            # Road geometry for the map (drawing only)
            # ------------------------------------------------

            coordinates = coordinate_lookup(results)

            depot = current_depot()

            all_routes = [
                route_points(route, coordinates, depot)
                for event in results["routes"]["optimized"]
                for route in event["routes"]
            ]

            current["text"] = (
                f"⟳ Fetching road geometry for {len(all_routes)} "
                "truck routes..."
            )

            render()

            road_ok = road_geometry.prefetch_routes(all_routes)

            current["text"] = None

            if road_ok == len(set(map(tuple, all_routes))):

                lines.append("✓ Road geometry ready")

            else:

                lines.append(
                    "! Road geometry server not reachable - routes on "
                    "the map fall back to dashed straight connectors"
                )

            render()

            events = results["routes"]["optimized"]

            st.session_state["results"] = results

            st.session_state["results_threshold"] = threshold

            st.session_state["selected_hour"] = (
                min(e["hour"] for e in events) if events else 0
            )

            status.update(
                label="Simulation complete",
                state="complete",
                expanded=False
            )

        except Exception:

            st.session_state["run_error"] = traceback.format_exc()

            status.update(
                label="Simulation failed",
                state="error",
                expanded=True
            )


# ============================================================
# CHART
# ============================================================

def distance_chart(distance):

    values = [
        distance["static"],
        distance["dynamic"],
        distance["optimized"]
    ]

    labels = [
        f"{name}  ({value:,.2f} km)"
        for name, value in zip(METHODS, values)
    ]

    df = pd.DataFrame({
        "Method": labels,
        "Distance (km)": values
    })

    chart = (
        alt.Chart(df)
        .mark_bar(size=40, cornerRadiusEnd=4)
        .encode(
            y=alt.Y(
                "Method:N",
                sort=labels,
                title=None,
                axis=alt.Axis(labelFontSize=14, labelLimit=260)
            ),
            x=alt.X(
                "Distance (km):Q",
                title="Total distance over 24 hours (km)",
                scale=alt.Scale(domain=[0, max(values) * 1.05])
            ),
            color=alt.Color(
                "Method:N",
                scale=alt.Scale(domain=labels, range=METHOD_COLORS),
                legend=None
            ),
            tooltip=[
                alt.Tooltip("Method:N"),
                alt.Tooltip("Distance (km):Q", format=",.2f")
            ]
        )
        .properties(height=220)
    )

    return chart


# ============================================================
# MAPS
# ============================================================

def fit_map(m, lats, lons):

    m.fit_bounds(
        [[min(lats), min(lons)], [max(lats), max(lons)]],
        padding=(25, 25)
    )


def new_map(lats, lons):

    m = folium.Map(
        location=[
            sum(lats) / len(lats),
            sum(lons) / len(lons)
        ],
        zoom_start=10,
        tiles=None,
        control_scale=True
    )

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri World Street Map",
        overlay=False,
        control=True
    ).add_to(m)

    fit_map(m, lats, lons)

    return m


def add_depot(m, depot):

    if depot is None:
        return

    folium.Marker(
        location=list(depot),
        tooltip="Depot",
        icon=folium.Icon(color="darkblue", icon="home")
    ).add_to(m)


def show_map(m, height, key):
    """Zoomable/pannable map that does not rerun the app on every pan."""

    try:

        st_folium(
            m,
            height=height,
            use_container_width=True,
            returned_objects=[],
            key=key
        )

    except TypeError:

        st_folium(
            m,
            height=height,
            width=None,
            returned_objects=[],
            key=key
        )


def location_map(results, depot):
    """Overview map: where the bins are."""

    bins = results["hourly_state"][0]["bins"]

    lats = [b["latitude"] for b in bins]
    lons = [b["longitude"] for b in bins]

    if depot is not None:
        lats.append(depot[0])
        lons.append(depot[1])

    m = new_map(lats, lons)

    for b in bins:

        folium.CircleMarker(
            location=[b["latitude"], b["longitude"]],
            radius=6,
            color="#ffffff",
            weight=1.5,
            fill=True,
            fill_color=NEUTRAL,
            fill_opacity=0.9,
            tooltip=esc(b["site_location"])
        ).add_to(m)

    add_depot(m, depot)

    return m


LEGEND_TEMPLATE = """
<div style="position: fixed; bottom: 24px; left: 24px; z-index: 9999;
     background: rgba(255,255,255,0.95); color: #222; padding: 10px 12px;
     border: 1px solid #bbb; border-radius: 6px; font: 13px sans-serif;
     line-height: 1.7;">
  <div><span style="display:inline-block;width:12px;height:12px;border-radius:50%;
       background:__RED__;"></span>&nbsp; Collection required (fill &ge; __T__%)</div>
  <div><span style="display:inline-block;width:12px;height:12px;border-radius:50%;
       background:__GREEN__;"></span>&nbsp; Below threshold, skipped (&lt; __T__%)</div>
  <div><span style="display:inline-block;width:26px;height:4px;
       background:__BLUE__;vertical-align:middle;"></span>&nbsp; OR-Tools truck route</div>
  <div style="font-size:12px;color:#555;">Number = stop order on the route</div>
</div>
"""


def hour_map(state, event, threshold, depot, coordinates):
    """
    Map for one hour.
    Returns (map, road_following_all, assignment) where assignment maps
    bin name -> (truck, stop number).
    """

    bins = state["bins"]

    lats = [b["latitude"] for b in bins]
    lons = [b["longitude"] for b in bins]

    if depot is not None:
        lats.append(depot[0])
        lons.append(depot[1])

    m = new_map(lats, lons)

    assignment = {}

    road_following_all = True

    # ----------------------------------------------------
    # Blue truck routes (drawn first, markers go on top)
    # ----------------------------------------------------

    if event is not None:

        for route in event["routes"]:

            truck = route["truck"]

            for stop_number, name in enumerate(route["route"][1:-1], 1):
                assignment[name] = (truck, stop_number)

            geometry = road_geometry.get_route_path(
                route_points(route, coordinates, depot)
            )

            road_following_all &= geometry["road_following"]

            folium.PolyLine(
                locations=geometry["path"],
                color=TRUCK_BLUES[(truck - 1) % len(TRUCK_BLUES)],
                weight=5,
                opacity=0.85,
                dash_array=None if geometry["road_following"] else "8 8",
                tooltip=(
                    f"Truck {truck} | load {route['load']}/"
                    f"{route['capacity']} | "
                    f"{route['utilization']:.0f}% | "
                    f"{route['distance']:.1f} km"
                )
            ).add_to(m)

    # ----------------------------------------------------
    # Bins: RED >= threshold, GREEN < threshold
    # ----------------------------------------------------

    for b in bins:

        name = esc(b["site_location"])

        fill = b["fill_level"]

        if b["above_threshold"]:

            if b["site_location"] in assignment:

                truck, stop = assignment[b["site_location"]]

                tip = (
                    f"{name} - {fill}% (collection required)<br>"
                    f"Truck {truck}, stop {stop}"
                )

                badge = (
                    f"<div style='background:{RED};color:#fff;"
                    "width:22px;height:22px;border-radius:50%;"
                    "border:2px solid #fff;text-align:center;"
                    "font:700 11px/18px sans-serif;"
                    f"box-shadow:0 0 2px #000;'>{stop}</div>"
                )

                folium.Marker(
                    location=[b["latitude"], b["longitude"]],
                    icon=folium.DivIcon(
                        html=badge,
                        icon_size=(22, 22),
                        icon_anchor=(11, 11)
                    ),
                    tooltip=tip
                ).add_to(m)

            else:

                folium.CircleMarker(
                    location=[b["latitude"], b["longitude"]],
                    radius=8,
                    color="#ffffff",
                    weight=1.5,
                    fill=True,
                    fill_color=RED,
                    fill_opacity=0.95,
                    tooltip=f"{name} - {fill}% (collection required)"
                ).add_to(m)

        else:

            folium.CircleMarker(
                location=[b["latitude"], b["longitude"]],
                radius=6,
                color="#ffffff",
                weight=1.5,
                fill=True,
                fill_color=GREEN,
                fill_opacity=0.9,
                tooltip=f"{name} - {fill}% (below threshold, skipped)"
            ).add_to(m)

    add_depot(m, depot)

    legend = (
        LEGEND_TEMPLATE
        .replace("__RED__", RED)
        .replace("__GREEN__", GREEN)
        .replace("__BLUE__", BLUE)
        .replace("__T__", str(threshold))
    )

    m.get_root().html.add_child(folium.Element(legend))

    return m, road_following_all, assignment


# ============================================================
# HOUR-BY-HOUR EXPLORER
# ============================================================

def _select_hour(hour):

    st.session_state["selected_hour"] = hour


def hour_selector(states, event_hours):
    """Clickable 00:00 ... 23:00 timeline (two rows of twelve)."""

    selected = st.session_state["selected_hour"]

    for start in (0, 12):

        columns = st.columns(12)

        for offset, column in enumerate(columns):

            hour = start + offset

            label = hour_label(hour) + (
                " ●" if hour in event_hours else ""
            )

            with column:

                stretch(
                    st.button,
                    label,
                    key=f"hour_button_{hour}",
                    type="primary" if hour == selected else "secondary",
                    on_click=_select_hour,
                    args=(hour,)
                )


def truck_cards_html(event):

    cards = []

    for route in event["routes"]:

        truck = route["truck"]

        color = TRUCK_BLUES[(truck - 1) % len(TRUCK_BLUES)]

        parts = []

        stops = route["route"]

        for i, name in enumerate(stops):

            css = "stop depot" if name == "DEPOT" else "stop"

            parts.append(f'<div class="{css}">{esc(name)}</div>')

            if i < len(stops) - 1:
                parts.append('<div class="arrow">↓</div>')

        cards.append(
            f'<div class="wr-truck" style="--accent:{color}">'
            f'<div class="head">Truck {truck}</div>'
            f'<div class="facts">'
            f'Load: {route["load"]} / {route["capacity"]}<br>'
            f'Utilization: {route["utilization"]:.1f}%<br>'
            f'Distance: {route["distance"]:.1f} km</div>'
            f'{"".join(parts)}</div>'
        )

    return "".join(cards)


def bin_tables(state, assignment, threshold):
    """Collected (>= threshold) and skipped (< threshold) bin tables."""

    collected_rows = []
    collected_classes = []

    skipped_rows = []

    for b in sorted(
        state["bins"],
        key=lambda b: (-b["fill_level"], b["site_location"])
    ):

        name = b["site_location"]

        fill = f"{b['fill_level']}%"

        if b["above_threshold"]:

            if name in assignment:

                truck, stop = assignment[name]

                result = f"Collected - Truck {truck}, stop {stop}"

            else:

                result = "Not collected (no feasible plan)"

            collected_rows.append({
                "Location": name,
                "Fill": fill,
                "Threshold": f"≥ {threshold}%",
                "Result": result
            })

            collected_classes.append("red-row")

        else:

            skipped_rows.append({
                "Location": name,
                "Fill": fill,
                "Threshold": f"< {threshold}%",
                "Result": "Skipped"
            })

    left, right = st.columns(2)

    with left:

        st.markdown(
            f"##### Collected - at or above {threshold}% "
            f"({len(collected_rows)})"
        )

        if collected_rows:

            show_table(
                pd.DataFrame(collected_rows),
                collected_classes,
                max_height=420
            )

        else:

            st.info("No bin reached the threshold in this hour.")

    with right:

        st.markdown(
            f"##### Skipped - below {threshold}% ({len(skipped_rows)})"
        )

        if skipped_rows:

            show_table(
                pd.DataFrame(skipped_rows),
                ["green-row"] * len(skipped_rows),
                max_height=420
            )

        else:

            st.info("Every bin is at or above the threshold.")


@fragment
def hour_explorer():
    """Everything inside reruns on its own when an hour is clicked."""

    results = st.session_state["results"]

    threshold = results["assumptions"]["threshold_percent"]

    static_interval = results["assumptions"].get(
        "static_interval_hours", 3
    )

    states = {s["hour"]: s for s in results["hourly_state"]}

    events = {e["hour"]: e for e in results["routes"]["optimized"]}

    event_hours = set(events)

    hour_selector(states, event_hours)

    st.caption(
        f"● = trucks are dispatched in this hour (at least one bin at "
        f"{threshold}% or more). Click an hour to see the state of every bin."
    )

    hour = st.session_state["selected_hour"]

    state = states[hour]

    event = events.get(hour)

    depot = current_depot()

    coordinates = coordinate_lookup(results)

    # ----------------------------------------------------
    # Summary of the selected hour
    # ----------------------------------------------------

    n_total = len(state["bins"])

    n_red = state["bins_above_threshold"]

    kpi_row([
        kpi("Selected hour", hour_label(hour), accent=BLUE),
        kpi(
            f"Collection required (≥ {threshold}%)",
            f"{n_red} bins",
            accent=RED
        ),
        kpi(
            f"Skipped (< {threshold}%)",
            f"{n_total - n_red} bins",
            accent=GREEN
        ),
        kpi(
            "Trucks dispatched",
            f"{event and len(event['routes']) or 0}",
            accent=BLUE
        ),
        kpi(
            "Route distance",
            f"{event['distance']:.1f} km" if event else "0 km",
            f"{event['waste_collected']} units collected" if event else "",
            accent=BLUE
        )
    ])

    if state["static_collects_all"]:

        st.caption(
            f"A static schedule would visit all {n_total} bins in this "
            "hour, whatever their fill level."
        )

    if n_red == 0:

        st.info(
            f"No bin has reached {threshold}% in this hour, so no truck "
            "is dispatched."
        )

    # ----------------------------------------------------
    # Map + route order
    # ----------------------------------------------------

    map_col, route_col = st.columns([3, 2])

    with map_col:

        with st.spinner("Loading road geometry..."):

            m, road_ok, assignment = hour_map(
                state, event, threshold, depot, coordinates
            )

        show_map(
            m,
            height=600,
            key=f"hour_map_{hour}_{threshold}_{depot}"
        )

        if event is not None and not road_ok:

            st.warning(
                "The road-geometry server could not be reached, so the "
                "dashed lines are straight connectors between stops, NOT "
                "roads. Check the internet connection or set OSRM_URL."
            )

        if event is not None and depot is None:

            st.caption(
                "Depot coordinates are not part of the project data, so "
                "the first and last leg of each route (to/from the depot) "
                "are not drawn. Enter them in the sidebar to draw them."
            )

    with route_col:

        st.markdown("##### Route order")

        if event is None:

            st.info("No routes in this hour.")

        else:

            st.markdown(
                f'<div class="wr-scroll" style="max-height:600px;'
                f'padding:10px;">{truck_cards_html(event)}</div>',
                unsafe_allow_html=True
            )

    # ----------------------------------------------------
    # Truck summary + bin tables
    # ----------------------------------------------------

    if event is not None:

        st.markdown("##### Trucks in this hour")

        show_table(pd.DataFrame([
            {
                "Truck": f"Truck {r['truck']}",
                "Stops": len(r["route"]) - 2,
                "Load": r["load"],
                "Capacity": r["capacity"],
                "Utilization": f"{r['utilization']:.1f}%",
                "Distance (km)": f"{r['distance']:.2f}"
            }
            for r in event["routes"]
        ]))

    bin_tables(state, assignment, threshold)


# ============================================================
# DASHBOARD SECTIONS
# ============================================================

def section_distance(results):

    distance = results["distance"]

    savings = results["savings"]

    st.subheader("Total distance driven in 24 hours")

    stretch(st.altair_chart, distance_chart(distance))

    kpi_row([
        kpi("Static distance", f"{distance['static']:,.2f} km",
            "Every location, fixed schedule", accent="#a3abb8"),
        kpi("Dynamic distance", f"{distance['dynamic']:,.2f} km",
            "Only bins at or above the threshold", accent="#7aa2dc"),
        kpi("Dynamic + OR-Tools distance",
            f"{distance['optimized']:,.2f} km",
            "Same bins, optimized routes", accent=BLUE)
    ])

    st.write("")

    kpi_row([
        kpi("Saved by dynamic scheduling",
            f"{savings['scheduling_km']:,.2f} km",
            f"{savings['scheduling_percent']:.2f}% less than static",
            accent="#7aa2dc"),
        kpi("Additional saved by OR-Tools",
            f"{savings['optimization_km']:,.2f} km",
            f"{savings['optimization_percent']:.2f}% less than dynamic",
            accent=BLUE),
        kpi("Overall distance saved",
            f"{savings['overall_km']:,.2f} km",
            f"{savings['overall_percent']:.2f}% less than static",
            accent=GREEN)
    ])


def section_environment(results):

    fuel = results["fuel"]

    co2 = results["co2"]

    percent = results["savings"]["overall_percent"]

    st.subheader("Environmental Impact")

    kpi_row([
        kpi("Baseline fuel consumption",
            f"{fuel['static_liters']:,.2f} L",
            "Static schedule", accent="#a3abb8"),
        kpi("Fuel saved",
            f"{fuel['saved_liters']:,.2f} L",
            f"{percent:.2f}% below baseline", accent=GREEN),
        kpi("Baseline CO₂ emissions",
            f"{co2['static_kg']:,.2f} kg",
            "Static schedule", accent="#a3abb8"),
        kpi("CO₂ avoided",
            f"{co2['avoided_kg']:,.2f} kg",
            f"{percent:.2f}% below baseline", accent=GREEN)
    ])


def section_operations(results):

    trucks = results["trucks"]

    events = results["collection_events"]

    waste = results["waste"]

    utilization = results["truck_utilization"]

    st.subheader("Truck Operations")

    table_col, kpi_col = st.columns([3, 1])

    with table_col:

        show_table(pd.DataFrame({
            "Method": METHODS,
            "Truck trips": [
                trucks["static"], trucks["dynamic"], trucks["optimized"]
            ],
            "Collection events": [
                events["static"], events["dynamic"], events["optimized"]
            ],
            "Waste collected (units)": [
                f"{waste['static']:,}",
                f"{waste['dynamic']:,}",
                f"{waste['optimized']:,}"
            ],
            "Average truck utilization": [
                "-", "-",
                f"{utilization['optimized_average_percent']:.2f}%"
            ]
        }))

        st.caption(
            "Truck trips are cumulative over the 24 hours. In every OR-Tools "
            f"event up to {results['assumptions']['available_trucks']} "
            "trucks are available."
        )

    with kpi_col:

        st.markdown(
            kpi(
                "Average OR-Tools truck utilization",
                f"{utilization['optimized_average_percent']:.2f}%",
                f"of {results['assumptions']['truck_capacity']} units "
                "capacity",
                accent=BLUE
            ),
            unsafe_allow_html=True
        )

    if waste["dynamic_optimized_match"]:

        st.success(
            "Fair comparison: Dynamic and Dynamic + OR-Tools collected "
            "exactly the same waste. Only the routing is different."
        )

    else:

        st.warning(
            "Dynamic and OR-Tools did not collect the same waste. See the "
            "optimizer warnings below."
        )


def section_assumptions(results):

    a = results["assumptions"]

    st.subheader("Model assumptions")

    rows = [
        ("Collection threshold", f"{a['threshold_percent']}%"),
        ("Truck capacity", f"{a['truck_capacity']} units"),
        ("Available OR-Tools trucks", a["available_trucks"]),
        ("Fuel efficiency", f"{a['fuel_efficiency_km_per_liter']} km/L"),
        ("CO₂ factor", f"{a['co2_kg_per_liter']} kg/L")
    ]

    if "static_interval_hours" in a:

        rows.insert(1, (
            "Static schedule",
            f"every {a['static_interval_hours']} hours"
        ))

        rows.insert(1, (
            "Simulation",
            f"{a['locations']} locations, {a['simulation_hours']} hours"
        ))

    left, _ = st.columns([1, 1])

    with left:

        show_table(pd.DataFrame(rows, columns=["Parameter", "Value"]))


# ============================================================
# MAIN
# ============================================================

init_state()

st.title("Dynamic Municipal Waste Route Optimization")

st.markdown(
    "Static routes collect every location on a fixed schedule. Dynamic "
    "scheduling prioritizes bins that reach the collection threshold, "
    "while OR-Tools optimizes the truck routes using road distances and "
    "truck capacity."
)


# ---------------- sidebar ----------------

with st.sidebar:

    st.header("Simulation settings")

    threshold = st.slider(
        "Collection threshold (%)",
        min_value=50,
        max_value=90,
        value=70,
        step=5,
        key="threshold"
    )

    st.info(f"Bins at **{threshold}% or more** are collected.")

    run_clicked = stretch(
        st.button,
        "Run simulation",
        type="primary",
        key="run_button"
    )

    st.caption(
        "Seeds are fixed, so every threshold always gives the same "
        "result. Finished results are kept until the app restarts."
    )

    with st.expander("Depot location (optional)"):

        st.text_input(
            "Depot coordinates (latitude, longitude)",
            key="depot_text",
            placeholder="latitude, longitude",
            help=(
                "The depot position is not in the project data. Enter it "
                "here (or set DEPOT_LATLON in road_geometry.py) to draw "
                "the depot and the first and last leg of every route. "
                "This only affects the map, never the optimization."
            )
        )

        if (
            st.session_state.get("depot_text", "").strip()
            and road_geometry.parse_depot(
                st.session_state["depot_text"]
            ) is None
        ):

            st.warning("Use the format: latitude, longitude")


# ---------------- run when needed ----------------

if run_clicked or not st.session_state["auto_ran"]:

    st.session_state["auto_ran"] = True

    run_and_store(threshold)


if st.session_state["run_error"]:

    st.error("The simulation could not be completed.")

    with st.expander("Error details"):

        st.code(st.session_state["run_error"])


results = st.session_state["results"]

if results is None:

    st.info("Choose a threshold and click **Run simulation**.")

    st.stop()


if st.session_state["results_threshold"] != threshold:

    st.warning(
        f"The results below are for a {st.session_state['results_threshold']}% "
        f"threshold. Click **Run simulation** to apply {threshold}%."
    )


for warning in results.get("optimizer_warnings", []):

    st.warning(
        f"Hour {hour_label(warning['hour'])}: OR-Tools found no feasible "
        f"plan ({warning['error']})."
    )


# ---------------- dashboard ----------------

section_distance(results)

section_environment(results)

section_operations(results)

st.subheader("Collection locations")

st.caption(
    f"{results['assumptions'].get('locations', '')} waste bins. "
    "Zoom and pan to explore."
)

show_map(
    location_map(results, current_depot()),
    height=460,
    key=f"location_map_{current_depot()}"
)

st.subheader("Hour-by-hour simulation")

hour_explorer()

section_assumptions(results)

st.divider()

st.caption(
    "Dynamic Municipal Waste Route Optimization  |  Google OR-Tools with "
    "an OSRM road-distance matrix  |  Map geometry: OSRM road network"
)