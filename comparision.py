"""
24-hour comparison of three waste-collection strategies.

    Static              every location, every STATIC_INTERVAL hours
    Dynamic             only bins at or above the fill threshold
    Dynamic + OR-Tools  the SAME bins as Dynamic, routed by OR-Tools

Fairness: the three systems keep independent copies of the fill state, but all
three receive the same initial fill (seed 42) and the same hourly increments
(seed 1000 + hour).  Dynamic and OR-Tools therefore select the same bins at
the same hours; only the routing differs.

Simulation logic, seeds, thresholds and assumptions are unchanged.
Additions (all backwards compatible):
    * results["hourly_state"]      state of all bins for EVERY hour
    * results["optimizer_warnings"] hours where OR-Tools had no feasible plan
    * run_simulation(progress_callback=...) for a truthful progress display
"""

from pathlib import Path

import numpy as np
import pandas as pd

from route_optimizer import (
    optimize_routes,
    load_road_matrix,
    TRUCK_CAPACITY,
    NUM_TRUCKS,
    DEPOT_NAME
)


# ============================================================
# SETTINGS
# ============================================================

THRESHOLD = 70

START_HOUR = 0
END_HOUR = 23

STATIC_INTERVAL = 3

FUEL_EFFICIENCY = 3.0       # km per liter
CO2_PER_LITER = 2.68        # kg CO2 per liter

INITIAL_FILL_SEED = 42      # do not change
HOURLY_SEED_BASE = 1000     # hour h uses seed 1000 + h; do not change

LOCATIONS_FILE = (
    Path(__file__).resolve().parent
    / "locations.csv"
)


# ============================================================
# LOAD DATA (once, at import)
# ============================================================

locations = pd.read_csv(LOCATIONS_FILE)

# Reproducible initial fill levels
rng = np.random.default_rng(INITIAL_FILL_SEED)

locations["initial_fill"] = rng.integers(
    0,
    101,
    len(locations)
)

NUM_LOCATIONS = len(locations)

LOCATION_NAMES = locations["site_location"].tolist()
LOCATION_LATS = locations["latitude"].astype(float).tolist()
LOCATION_LONS = locations["longitude"].astype(float).tolist()


# Hourly waste increments (hour 0 has none), generated once.
HOURLY_INCREASE = {
    hour: np.random.default_rng(
        HOURLY_SEED_BASE + hour
    ).integers(
        0,
        11,
        NUM_LOCATIONS
    )
    for hour in range(START_HOUR + 1, END_HOUR + 1)
}


# ============================================================
# FIXED ROUTE ORDER (used by Static and Dynamic)
# ============================================================

FIXED_ROUTE_ORDER = LOCATION_NAMES

FIXED_ROUTE_POSITION = {
    name: i
    for i, name in enumerate(FIXED_ROUTE_ORDER)
}


# ============================================================
# ROAD DISTANCE MATRIX (shared, cached in route_optimizer)
# ============================================================

road_values, road_row, road_col = load_road_matrix()

missing_locations = [
    location
    for location in [DEPOT_NAME] + LOCATION_NAMES
    if location not in road_row or location not in road_col
]

if missing_locations:

    raise ValueError(
        f"Missing locations in road distance matrix: "
        f"{missing_locations}"
    )


def road_distance(from_location, to_location):
    """Road distance in metres between two named locations."""

    return road_values[
        road_row[from_location],
        road_col[to_location]
    ]


# ============================================================
# STATIC / DYNAMIC FIXED-ORDER ROUTE CALCULATION
# ============================================================

def calculate_fixed_route(selected_bins):

    if len(selected_bins) == 0:

        return {
            "distance": 0,
            "trucks_used": 0,
            "bins_collected": 0,
            "waste_collected": 0,
            "routes": []
        }

    selected_bins = selected_bins.copy()

    # Preserve fixed route order
    selected_bins["route_order"] = (
        selected_bins["site_location"]
        .map(FIXED_ROUTE_POSITION)
    )

    selected_bins = selected_bins.sort_values(
        "route_order"
    )

    # --------------------------------------------------------
    # Split bins between truck trips according to capacity
    # --------------------------------------------------------

    routes = []

    current_route = []
    current_load = 0

    for _, row in selected_bins.iterrows():

        demand = int(row["waste_units"])

        if (
            current_route
            and current_load + demand > TRUCK_CAPACITY
        ):

            routes.append({
                "route": current_route,
                "load": current_load
            })

            current_route = []
            current_load = 0

        current_route.append(row["site_location"])

        current_load += demand

    if current_route:

        routes.append({
            "route": current_route,
            "load": current_load
        })

    # --------------------------------------------------------
    # Calculate route distances
    # --------------------------------------------------------

    total_distance = 0

    route_details = []

    for truck_number, route_info in enumerate(routes, start=1):

        route = route_info["route"]
        load = route_info["load"]

        previous = DEPOT_NAME

        route_distance = 0

        for location in route:

            route_distance += road_distance(previous, location)

            previous = location

        # Return to depot
        route_distance += road_distance(previous, DEPOT_NAME)

        distance_km = float(route_distance / 1000)

        utilization = (load / TRUCK_CAPACITY) * 100

        route_details.append({

            "truck": truck_number,

            "route": [DEPOT_NAME] + route + [DEPOT_NAME],

            "load": load,

            "capacity": TRUCK_CAPACITY,

            "utilization": utilization,

            "distance": distance_km
        })

        total_distance += distance_km

    return {

        "distance": total_distance,

        "trucks_used": len(routes),

        "bins_collected": len(selected_bins),

        "waste_collected": int(
            selected_bins["waste_units"].sum()
        ),

        "routes": route_details
    }


# ============================================================
# SMALL HELPERS
# ============================================================

def _select_bins(fill, mask):
    """Rows of `locations` whose bins are selected, with waste = fill."""

    selected = locations.loc[mask].copy()

    selected["fill_level"] = fill[mask].values
    selected["waste_units"] = fill[mask].values
    selected["needs_collection"] = True

    return selected


def _percent(part, whole):
    """Percentage that avoids dividing by zero."""

    return (part / whole) * 100 if whole else 0.0


def _notify(callback, **event):
    """Send a progress event if a callback was supplied."""

    if callback is not None:
        callback(event)


def _hourly_snapshot(hour, fill, threshold, collected):
    """
    State of every bin at `hour` (after the hourly increase, before
    collection).  `collected` is True only if OR-Tools produced a plan.
    """

    values = fill.to_numpy()

    bins = []

    for name, lat, lon, value in zip(
        LOCATION_NAMES,
        LOCATION_LATS,
        LOCATION_LONS,
        values
    ):

        above = bool(value >= threshold)

        bins.append({
            "site_location": name,
            "latitude": lat,
            "longitude": lon,
            "fill_level": int(value),
            "above_threshold": above,
            "collected": above and collected,
            "skipped": not above
        })

    return {

        "hour": hour,

        "bins": bins,

        "bins_above_threshold": sum(
            b["above_threshold"] for b in bins
        ),

        "collected_bins": [
            b["site_location"] for b in bins if b["collected"]
        ],

        "skipped_bins": [
            b["site_location"] for b in bins if b["skipped"]
        ],

        # The static schedule would visit every bin at this hour
        "static_collects_all": (
            hour % STATIC_INTERVAL == 0
        )
    }


# ============================================================
# MAIN SIMULATION
# ============================================================

def run_simulation(
    threshold=THRESHOLD,
    progress_callback=None
):
    """
    Run the 24-hour simulation and return all results as one dict.

    progress_callback(event: dict) is optional.  Events:
        {"stage": "start", "locations": n, "hours": n}
        {"stage": "hour_start", "hour": h}
        {"stage": "optimizing", "hour": h, "bins": n}
        {"stage": "hour_done", "hour": h, "bins": n,
         "trucks": k, "distance": km}
        {"stage": "finalizing"}
    """

    _notify(
        progress_callback,
        stage="start",
        locations=NUM_LOCATIONS,
        hours=END_HOUR - START_HOUR + 1
    )

    # --------------------------------------------------------
    # Three identical but independent fill states
    # --------------------------------------------------------

    static_fill = locations["initial_fill"].copy()

    dynamic_fill = locations["initial_fill"].copy()

    or_tools_fill = locations["initial_fill"].copy()

    # --------------------------------------------------------
    # Counters
    # --------------------------------------------------------

    static_distance = 0
    dynamic_distance = 0
    or_tools_distance = 0

    static_trucks = 0
    dynamic_trucks = 0
    or_tools_trucks = 0

    static_events = 0
    dynamic_events = 0
    or_tools_events = 0

    static_total_waste = 0
    dynamic_total_waste = 0
    or_tools_total_waste = 0

    static_route_history = []
    dynamic_route_history = []
    or_tools_route_history = []

    # Bin state at the hours where OR-Tools had bins to collect
    # (kept exactly as before for compatibility)
    or_tools_bin_history = []

    # Bin state for EVERY hour (used by the hour-by-hour dashboard)
    hourly_state = []

    optimizer_warnings = []

    or_tools_utilization_values = []


    # ========================================================
    # HOURLY SIMULATION
    # ========================================================

    for hour in range(START_HOUR, END_HOUR + 1):

        _notify(progress_callback, stage="hour_start", hour=hour)

        # ----------------------------------------------------
        # Generate waste during the hour (same for all three)
        # ----------------------------------------------------

        if hour > 0:

            increase = HOURLY_INCREASE[hour]

            static_fill = np.clip(static_fill + increase, 0, 100)

            dynamic_fill = np.clip(dynamic_fill + increase, 0, 100)

            or_tools_fill = np.clip(or_tools_fill + increase, 0, 100)


        # ====================================================
        # 1. STATIC FIXED ROUTING
        # ====================================================

        if hour % STATIC_INTERVAL == 0:

            static_selected = locations.copy()

            static_selected["fill_level"] = static_fill.values

            static_selected["waste_units"] = static_fill.values

            static_selected["needs_collection"] = True

            result = calculate_fixed_route(static_selected)

            static_distance += result["distance"]
            static_trucks += result["trucks_used"]
            static_total_waste += result["waste_collected"]
            static_events += 1

            static_route_history.append({
                "hour": hour,
                "routes": result["routes"],
                "distance": result["distance"],
                "bins_collected": result["bins_collected"],
                "waste_collected": result["waste_collected"]
            })

            # Empty all bins
            static_fill[:] = 0


        # ====================================================
        # 2. DYNAMIC SCHEDULING
        # ====================================================

        dynamic_mask = dynamic_fill >= threshold

        if dynamic_mask.any():

            dynamic_selected = _select_bins(
                dynamic_fill,
                dynamic_mask
            )

            result = calculate_fixed_route(dynamic_selected)

            dynamic_distance += result["distance"]
            dynamic_trucks += result["trucks_used"]
            dynamic_total_waste += result["waste_collected"]
            dynamic_events += 1

            dynamic_route_history.append({
                "hour": hour,
                "routes": result["routes"],
                "distance": result["distance"],
                "bins_collected": result["bins_collected"],
                "waste_collected": result["waste_collected"]
            })

            # Empty collected bins
            dynamic_fill[dynamic_mask] = 0


        # ====================================================
        # 3. DYNAMIC + OR-TOOLS
        # ====================================================

        # Fill levels at this hour, before anything is collected
        pre_collection_fill = or_tools_fill.copy()

        or_tools_mask = or_tools_fill >= threshold

        plan_found = False

        hour_bins = 0
        hour_trucks = 0
        hour_distance = 0.0

        if or_tools_mask.any():

            or_tools_selected = _select_bins(
                or_tools_fill,
                or_tools_mask
            )

            hour_bins = len(or_tools_selected)

            # ------------------------------------------------
            # Save bin state BEFORE collection (for the frontend)
            # ------------------------------------------------

            bin_state = locations[
                ["site_location", "latitude", "longitude"]
            ].copy()

            bin_state["fill_level"] = or_tools_fill.values

            bin_state["needs_collection"] = (
                or_tools_fill.values >= threshold
            )

            bin_state["status"] = np.where(

                or_tools_fill.values >= threshold,

                "Needs Collection",

                np.where(
                    or_tools_fill.values >= 50,
                    "Warning",
                    "OK"
                )
            )

            or_tools_bin_history.append({

                "hour": hour,

                "bins": bin_state.to_dict(orient="records")
            })

            # ------------------------------------------------
            # Optimize routes
            # ------------------------------------------------

            _notify(
                progress_callback,
                stage="optimizing",
                hour=hour,
                bins=hour_bins
            )

            result = optimize_routes(or_tools_selected)

            if result["feasible"]:

                plan_found = True

                hour_trucks = result["trucks_used"]
                hour_distance = result["total_distance"]

                or_tools_distance += result["total_distance"]
                or_tools_trucks += result["trucks_used"]

                waste_collected = int(
                    or_tools_selected["waste_units"].sum()
                )

                or_tools_total_waste += waste_collected

                or_tools_events += 1

                or_tools_route_history.append({
                    "hour": hour,
                    "routes": result["routes"],
                    "distance": result["total_distance"],
                    "bins_collected": result["bins_collected"],
                    "waste_collected": waste_collected
                })

                for route in result["routes"]:

                    or_tools_utilization_values.append(
                        route["utilization"]
                    )

                # Empty collected bins
                or_tools_fill[or_tools_mask] = 0

            else:

                # Not silently ignored any more: the bins stay full
                # (as before) but the dashboard can now warn about it.
                optimizer_warnings.append({
                    "hour": hour,
                    "error": result.get("error", "Infeasible")
                })


        # ----------------------------------------------------
        # Snapshot of every bin at this hour (dashboard data)
        # ----------------------------------------------------

        snapshot = _hourly_snapshot(
            hour,
            pre_collection_fill,
            threshold,
            plan_found
        )

        snapshot["trucks"] = hour_trucks
        snapshot["distance"] = hour_distance

        hourly_state.append(snapshot)

        _notify(
            progress_callback,
            stage="hour_done",
            hour=hour,
            bins=hour_bins,
            trucks=hour_trucks,
            distance=hour_distance
        )


    _notify(progress_callback, stage="finalizing")


    # ========================================================
    # SAVINGS
    # ========================================================

    scheduling_savings = static_distance - dynamic_distance

    optimization_savings = dynamic_distance - or_tools_distance

    total_savings = static_distance - or_tools_distance

    scheduling_percent = _percent(scheduling_savings, static_distance)

    optimization_percent = _percent(optimization_savings, dynamic_distance)

    overall_percent = _percent(total_savings, static_distance)


    # ========================================================
    # FUEL
    # ========================================================

    static_fuel = static_distance / FUEL_EFFICIENCY

    dynamic_fuel = dynamic_distance / FUEL_EFFICIENCY

    or_tools_fuel = or_tools_distance / FUEL_EFFICIENCY

    fuel_saved = static_fuel - or_tools_fuel


    # ========================================================
    # CO2
    # ========================================================

    static_co2 = static_fuel * CO2_PER_LITER

    dynamic_co2 = dynamic_fuel * CO2_PER_LITER

    or_tools_co2 = or_tools_fuel * CO2_PER_LITER

    co2_avoided = static_co2 - or_tools_co2


    # ========================================================
    # TRUCK UTILIZATION
    # ========================================================

    if or_tools_utilization_values:

        average_or_tools_utilization = (
            sum(or_tools_utilization_values)
            / len(or_tools_utilization_values)
        )

    else:

        average_or_tools_utilization = 0


    # ========================================================
    # RETURN EVERYTHING
    # ========================================================

    return {

        "distance": {
            "static": round(static_distance, 2),
            "dynamic": round(dynamic_distance, 2),
            "optimized": round(or_tools_distance, 2)
        },

        "savings": {
            "scheduling_km": round(scheduling_savings, 2),
            "scheduling_percent": round(scheduling_percent, 2),
            "optimization_km": round(optimization_savings, 2),
            "optimization_percent": round(optimization_percent, 2),
            "overall_km": round(total_savings, 2),
            "overall_percent": round(overall_percent, 2)
        },

        # Cumulative truck trips over the whole simulation
        "trucks": {
            "static": static_trucks,
            "dynamic": dynamic_trucks,
            "optimized": or_tools_trucks
        },

        "collection_events": {
            "static": static_events,
            "dynamic": dynamic_events,
            "optimized": or_tools_events
        },

        "waste": {
            "static": static_total_waste,
            "dynamic": dynamic_total_waste,
            "optimized": or_tools_total_waste,

            # Fairness check
            "dynamic_optimized_match": (
                dynamic_total_waste == or_tools_total_waste
            )
        },

        "truck_utilization": {
            "optimized_average_percent": round(
                average_or_tools_utilization,
                2
            )
        },

        "fuel": {
            "static_liters": round(static_fuel, 2),
            "dynamic_liters": round(dynamic_fuel, 2),
            "optimized_liters": round(or_tools_fuel, 2),
            "saved_liters": round(fuel_saved, 2)
        },

        "co2": {
            "static_kg": round(static_co2, 2),
            "dynamic_kg": round(dynamic_co2, 2),
            "optimized_kg": round(or_tools_co2, 2),
            "avoided_kg": round(co2_avoided, 2)
        },

        "assumptions": {
            "threshold_percent": threshold,
            "truck_capacity": TRUCK_CAPACITY,
            "available_trucks": NUM_TRUCKS,
            "fuel_efficiency_km_per_liter": FUEL_EFFICIENCY,
            "co2_kg_per_liter": CO2_PER_LITER,

            # Added (informational)
            "static_interval_hours": STATIC_INTERVAL,
            "simulation_hours": END_HOUR - START_HOUR + 1,
            "locations": NUM_LOCATIONS
        },

        "routes": {
            "static": static_route_history,
            "dynamic": dynamic_route_history,
            "optimized": or_tools_route_history
        },

        # Unchanged: bin state at hours where OR-Tools had bins to collect
        "bin_history": or_tools_bin_history,

        # New: every hour, every bin
        "hourly_state": hourly_state,

        # New: hours where OR-Tools returned no feasible plan (normally empty)
        "optimizer_warnings": optimizer_warnings
    }


# ============================================================
# RUN DIRECTLY
# ============================================================

def _print_report(results):

    a = results["assumptions"]

    sections = [
        ("DISTANCE", [
            ("Static fixed routing", f"{results['distance']['static']:.2f} km"),
            ("Dynamic scheduling", f"{results['distance']['dynamic']:.2f} km"),
            ("Dynamic + OR-Tools", f"{results['distance']['optimized']:.2f} km"),
        ]),
        ("DISTANCE SAVINGS", [
            ("Scheduling savings", f"{results['savings']['scheduling_km']:.2f} km ({results['savings']['scheduling_percent']:.2f}%)"),
            ("OR-Tools savings", f"{results['savings']['optimization_km']:.2f} km ({results['savings']['optimization_percent']:.2f}%)"),
            ("Overall savings", f"{results['savings']['overall_km']:.2f} km ({results['savings']['overall_percent']:.2f}%)"),
        ]),
        ("TRUCK TRIPS", [
            ("Static truck trips", results["trucks"]["static"]),
            ("Dynamic truck trips", results["trucks"]["dynamic"]),
            ("OR-Tools truck trips", results["trucks"]["optimized"]),
        ]),
        ("COLLECTION EVENTS", [
            ("Static collection events", results["collection_events"]["static"]),
            ("Dynamic collection events", results["collection_events"]["dynamic"]),
            ("OR-Tools collection events", results["collection_events"]["optimized"]),
        ]),
        ("WASTE COLLECTED", [
            ("Static waste collected", f"{results['waste']['static']} units"),
            ("Dynamic waste collected", f"{results['waste']['dynamic']} units"),
            ("OR-Tools waste collected", f"{results['waste']['optimized']} units"),
            ("Dynamic vs OR-Tools match", "YES" if results["waste"]["dynamic_optimized_match"] else "NO"),
        ]),
        ("TRUCK UTILIZATION", [
            ("Average OR-Tools utilization", f"{results['truck_utilization']['optimized_average_percent']:.2f}%"),
        ]),
        ("FUEL", [
            ("Static fuel", f"{results['fuel']['static_liters']:.2f} L"),
            ("Dynamic fuel", f"{results['fuel']['dynamic_liters']:.2f} L"),
            ("OR-Tools fuel", f"{results['fuel']['optimized_liters']:.2f} L"),
            ("Fuel saved", f"{results['fuel']['saved_liters']:.2f} L"),
        ]),
        ("CO2", [
            ("Static CO2", f"{results['co2']['static_kg']:.2f} kg"),
            ("Dynamic CO2", f"{results['co2']['dynamic_kg']:.2f} kg"),
            ("OR-Tools CO2", f"{results['co2']['optimized_kg']:.2f} kg"),
            ("CO2 avoided", f"{results['co2']['avoided_kg']:.2f} kg"),
        ]),
        ("MODEL ASSUMPTIONS", [
            ("Collection threshold", f"{a['threshold_percent']}%"),
            ("Truck capacity", f"{a['truck_capacity']} units"),
            ("Available trucks", a["available_trucks"]),
            ("Fuel efficiency", f"{a['fuel_efficiency_km_per_liter']} km/L"),
            ("CO2 factor", f"{a['co2_kg_per_liter']} kg/L"),
        ]),
    ]

    print("\n" + "=" * 60)
    print("MUNICIPAL WASTE ROUTE OPTIMIZATION RESULTS")
    print("=" * 60)

    for title, rows in sections:

        print(f"\n{title}")
        print("-" * 60)

        for label, value in rows:
            print(f"{label + ':':<32}{value}")

    for warning in results["optimizer_warnings"]:
        print(f"\nWARNING hour {warning['hour']}: {warning['error']}")

    print("\n" + "=" * 60)
    print("SIMULATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":

    _print_report(run_simulation())
