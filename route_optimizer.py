"""
Capacitated vehicle routing for the selected waste bins (Google OR-Tools).

What this module solves (unchanged):
    depot + selected bins + truck capacity + multiple trucks
    + OSRM road-distance matrix  ->  routes with minimum total road distance.

Only the plumbing was tidied: the road-distance matrix is now read from disk
once and cached, instead of being re-read on every hourly optimization.
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd
from ortools.constraint_solver import (
    pywrapcp,
    routing_enums_pb2
)


# ============================================================
# SETTINGS
# ============================================================

TRUCK_CAPACITY = 400
NUM_TRUCKS = 10

DEPOT_NAME = "DEPOT"

SOLVER_TIME_LIMIT_SECONDS = 5

ROAD_MATRIX_FILE = (
    Path(__file__).resolve().parent
    / "road_distance_matrix.csv"
)


# ============================================================
# ROAD-DISTANCE MATRIX (loaded once)
# ============================================================

@lru_cache(maxsize=1)
def load_road_matrix():
    """
    Load the OSRM road-distance matrix (metres) exactly once.

    Returns
    -------
    values : numpy.ndarray   (n x n) road distances in metres
    row_position : dict      location name -> row number
    col_position : dict      location name -> column number
    """

    matrix = pd.read_csv(
        ROAD_MATRIX_FILE,
        index_col=0
    )

    row_position = {
        name: i
        for i, name in enumerate(matrix.index)
    }

    col_position = {
        name: i
        for i, name in enumerate(matrix.columns)
    }

    return (
        matrix.to_numpy(dtype=float),
        row_position,
        col_position
    )


# ============================================================
# INPUT VALIDATION
# ============================================================

def _select_bins(data):
    """Return a validated copy of the bins that need collection."""

    if "needs_collection" not in data.columns:
        raise ValueError(
            "Input data must contain 'needs_collection' column."
        )

    if "waste_units" not in data.columns:
        raise ValueError(
            "Input data must contain 'waste_units' column."
        )

    bins = data[
        data["needs_collection"]
    ].copy()

    if len(bins) == 0:
        return bins

    bins["waste_units"] = pd.to_numeric(
        bins["waste_units"],
        errors="coerce"
    )

    if bins["waste_units"].isna().any():
        raise ValueError(
            "One or more selected bins have invalid waste_units."
        )

    if (bins["waste_units"] <= 0).any():
        raise ValueError(
            "Selected bins must have waste_units > 0."
        )

    return bins


def _empty_result(feasible=True, error=None):

    result = {
        "routes": [],
        "total_distance": 0,
        "bins_collected": 0,
        "trucks_used": 0,
        "feasible": feasible
    }

    if error:
        result["error"] = error

    return result


# ============================================================
# OPTIMIZE ROUTES
# ============================================================

def optimize_routes(data):

    # --------------------------------------------------------
    # 1. Select and validate bins that need collection
    # --------------------------------------------------------

    bins = _select_bins(data)

    if len(bins) == 0:
        return _empty_result()


    # --------------------------------------------------------
    # 2. A single bin larger than a truck can never be served
    # --------------------------------------------------------

    oversized_bins = bins[
        bins["waste_units"] > TRUCK_CAPACITY
    ]

    if len(oversized_bins) > 0:

        names = oversized_bins["site_location"].tolist()

        return _empty_result(
            feasible=False,
            error=(
                "These bins exceed truck capacity: "
                + ", ".join(names)
            )
        )


    # --------------------------------------------------------
    # 3. Selected locations: depot first, then the bins
    # --------------------------------------------------------

    road_values, row_position, col_position = load_road_matrix()

    location_names = (
        [DEPOT_NAME]
        + bins["site_location"].tolist()
    )

    missing_locations = [
        location
        for location in location_names
        if (
            location not in row_position
            or location not in col_position
        )
    ]

    if missing_locations:

        raise ValueError(
            "These locations are missing from "
            "road_distance_matrix.csv:\n"
            + "\n".join(missing_locations)
        )


    # --------------------------------------------------------
    # 4. Distance matrix for the selected locations (metres)
    # --------------------------------------------------------

    distance_matrix = [
        [
            int(round(road_values[
                row_position[from_location],
                col_position[to_location]
            ]))
            for to_location in location_names
        ]
        for from_location in location_names
    ]


    # --------------------------------------------------------
    # 5. Demand list (depot has zero demand)
    # --------------------------------------------------------

    demands = [0]

    demands.extend(
        bins["waste_units"]
        .astype(int)
        .tolist()
    )


    # --------------------------------------------------------
    # 6. OR-Tools routing model
    # --------------------------------------------------------

    manager = pywrapcp.RoutingIndexManager(
        len(location_names),
        NUM_TRUCKS,
        0
    )

    routing = pywrapcp.RoutingModel(
        manager
    )


    # Distance

    def distance_callback(from_index, to_index):

        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)

        return distance_matrix[from_node][to_node]


    distance_callback_index = (
        routing.RegisterTransitCallback(
            distance_callback
        )
    )

    routing.SetArcCostEvaluatorOfAllVehicles(
        distance_callback_index
    )


    # Waste demand

    def demand_callback(from_index):

        from_node = manager.IndexToNode(from_index)

        return demands[from_node]


    demand_callback_index = (
        routing.RegisterUnaryTransitCallback(
            demand_callback
        )
    )


    # Truck capacity

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,
        [TRUCK_CAPACITY] * NUM_TRUCKS,
        True,
        "Capacity"
    )


    # Search settings

    search_parameters = (
        pywrapcp.DefaultRoutingSearchParameters()
    )

    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy
        .PATH_CHEAPEST_ARC
    )

    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic
        .GUIDED_LOCAL_SEARCH
    )

    search_parameters.time_limit.seconds = (
        SOLVER_TIME_LIMIT_SECONDS
    )


    # --------------------------------------------------------
    # 7. Solve
    # --------------------------------------------------------

    solution = routing.SolveWithParameters(
        search_parameters
    )

    if not solution:

        return _empty_result(
            feasible=False,
            error="OR-Tools could not find a feasible solution."
        )


    # --------------------------------------------------------
    # 8. Extract routes
    # --------------------------------------------------------

    routes = []

    total_distance = 0

    trucks_used = 0

    for vehicle_id in range(NUM_TRUCKS):

        index = routing.Start(vehicle_id)

        route = [DEPOT_NAME]

        route_load = 0

        route_distance = 0

        while not routing.IsEnd(index):

            node = manager.IndexToNode(index)

            next_index = solution.Value(
                routing.NextVar(index)
            )

            next_node = manager.IndexToNode(next_index)

            # Waste collected at the current node (depot = 0)
            route_load += demands[node]

            # Road distance of this leg (metres)
            route_distance += distance_matrix[node][next_node]

            index = next_index

            if not routing.IsEnd(index):

                route.append(
                    location_names[
                        manager.IndexToNode(index)
                    ]
                )

        route.append(DEPOT_NAME)

        # Ignore unused trucks
        if len(route) > 2:

            trucks_used += 1

            distance_km = route_distance / 1000

            utilization = (
                route_load
                / TRUCK_CAPACITY
                * 100
            )

            routes.append({

                "truck": vehicle_id + 1,

                "route": route,

                "load": route_load,

                "capacity": TRUCK_CAPACITY,

                "utilization": utilization,

                "distance": distance_km

            })

            total_distance += distance_km


    return {

        "routes": routes,

        "total_distance": total_distance,

        "bins_collected": len(bins),

        "trucks_used": trucks_used,

        "feasible": True

    }
