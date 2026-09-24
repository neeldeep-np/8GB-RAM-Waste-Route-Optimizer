# 8GB-RAM-Waste-Route-Optimizer
# Dynamic Municipal Waste Route Optimization

## Problem Statement

Municipal waste collection trucks often follow fixed routes regardless of the actual fill levels of waste bins. This can result in unnecessary collection trips, increased fuel consumption, longer travel distances, and higher CO₂ emissions.

## Our Solution

We developed a dynamic municipal waste collection system that uses simulated real-time bin fill levels to determine which bins require collection.

The selected bins are then routed using **Google OR-Tools**, allowing the system to generate optimized truck routes while considering operational constraints such as truck capacity and depot location.

The system compares three approaches:

1. **Static Collection** – follows a predetermined collection schedule.
2. **Dynamic Collection** – collects bins based on their current fill levels.
3. **Dynamic + OR-Tools** – dynamically selects bins and optimizes the collection routes using OR-Tools.

The results are presented through an interactive Streamlit dashboard.

## System Workflow

```text
Bin Locations
      ↓
Waste Fill-Level Simulation
      ↓
Identify Bins Requiring Collection
      ↓
Route Optimization
      ↓
Truck Routes
      ↓
Distance / Fuel / CO₂ Calculation
      ↓
Comparison Dashboard
```

## Key Features

* Simulated dynamic waste accumulation
* Dynamic identification of bins requiring collection
* Static vs Dynamic collection comparison
* Vehicle routing using Google OR-Tools
* Truck capacity constraints
* Depot-based routing
* Distance calculation
* Fuel consumption estimation
* CO₂ emission estimation
* Interactive Streamlit dashboard
* Route visualization on a map

## Technologies Used

* **Python** – core implementation
* **Pandas** – data processing
* **NumPy** – numerical calculations
* **Google OR-Tools** – vehicle route optimization
* **Streamlit** – interactive dashboard
* **Folium / Streamlit-Folium** – map visualization
* **Plotly** – data visualization

## Project Structure

```text
├── app.py
├── comparison.py
├── route_optimizer.py
├── locations.csv
├── road_distance_matrix.csv
├── requirements.txt
└── README.md
```

### `app.py`

The main Streamlit application and user interface.

### `comparison.py`

Runs the collection simulations and compares the Static, Dynamic, and OR-Tools approaches.

### `route_optimizer.py`

Contains the OR-Tools vehicle routing and optimization logic.

### `locations.csv`

Contains the simulated waste-bin locations and related information.

### `road_distance_matrix.csv`

Contains the road-distance data used by the routing system.

## Installation

Clone the repository:

```bash
git clone https://github.com/neeldeep-np/8GB-RAM-Waste-Route-Optimizer
cd dynamic-waste-route-optimization
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Running the Application

Start the Streamlit application:

```bash
streamlit run app.py
```

The dashboard will open in your browser.

## Optimization Approach

The system first identifies bins that require collection based on their simulated fill levels.

These locations are then provided to Google OR-Tools as a vehicle routing problem.

The optimization considers:

* Depot location
* Truck capacity
* Collection locations
* Travel distances
* Number of available trucks

The resulting routes are then used to calculate operational metrics such as total distance, estimated fuel consumption, and CO₂ emissions.

## Evaluation

The system evaluates the different collection strategies using metrics including:

* Number of collection events
* Number of truck trips
* Total distance traveled
* Fuel consumption
* Estimated CO₂ emissions

This allows the effect of dynamic collection and route optimization to be compared against a static collection strategy.

## Future Improvements

Possible future improvements include:

* Integration with real-time IoT bin sensors
* Live traffic data
* Real road-network routing
* Weather-aware route planning
* More detailed vehicle constraints
* Predictive waste-generation models
* Deployment across larger municipal areas
* Real-time fleet tracking

## Team

Developed as part of the **DATUM Hackathon 2026**.

**Problem Statement:** PS-3B – Dynamic Municipal Waste Route Optimization
