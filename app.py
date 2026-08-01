"""
Zero Waste Logistics — Routing Dashboard
=========================================
Pipeline this app runs end-to-end, live, in the browser:

  OSM data (or MySQL) -> KD-Tree nearest-neighbor search -> Distance matrix
  -> Ant Colony Optimization (ACO) -> Folium route map + analytics

If a MySQL connection is configured in the sidebar it will pull your real
`location` table. Otherwise it falls back to a realistic demo dataset around
Prayagraj so the app always runs standalone.
"""

import os
import random
from typing import Optional

import numpy as np
import pandas as pd
import folium
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from scipy.spatial import KDTree, distance_matrix
from streamlit_folium import st_folium

PLACE_NAME = "Prayagraj, Uttar Pradesh, India"
GRAPH_CACHE_PATH = "prayagraj_drive_network.graphml"

# --------------------------------------------------------------------------
# PAGE CONFIG + THEME
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="Zero Waste Logistics",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetric"] {
        background-color: #161b22;
        border: 1px solid #262c36;
        border-radius: 10px;
        padding: 14px 18px 8px 18px;
    }
    div[data-testid="stMetricValue"] { color: #58a6ff; }
    .stTabs [data-baseweb="tab"] { font-size: 15px; padding: 8px 16px; }
    h1, h2, h3 { letter-spacing: -0.3px; }
    .route-pill {
        display: inline-block; padding: 2px 10px; border-radius: 999px;
        background: #1f6feb22; color: #58a6ff; font-size: 12px; margin-right: 6px;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

AMENITY_COLORS = {
    "restaurant": "orange",
    "hospital": "red",
    "college": "purple",
    "other": "gray",
}
AMENITY_ICONS = {
    "restaurant": "cutlery",
    "hospital": "plus-square",
    "college": "graduation-cap",
    "other": "map-marker",
}

CITY_CENTER = [25.4490, 81.8340]  # Prayagraj / Civil Lines, used as a fallback depot

# --------------------------------------------------------------------------
# DATA LOADING
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_demo_locations(n_extra: int = 14, seed: int = 42) -> pd.DataFrame:
    """Synthetic but realistic location set around Civil Lines, Prayagraj."""
    rng = random.Random(seed)
    base = [
        ("Garbage Depot (Start)", 25.4484, 81.8333, "other"),
        ("Vijaya Hospital & Trauma Centre", 25.4492, 81.8345, "hospital"),
        ("Eden - Cafe by Connoisseur", 25.4505, 81.8322, "restaurant"),
        ("Bikanerwala", 25.4512, 81.8338, "restaurant"),
        ("Narayan Hospital", 25.4498, 81.8355, "hospital"),
        ("Mela Restaurant", 25.4480, 81.8348, "restaurant"),
    ]
    names_pool = [
        ("Anand Bhavan Sweets", "restaurant"), ("City Hospital", "hospital"),
        ("Ewing Christian College", "college"), ("Prayag Cafe", "restaurant"),
        ("SRN Hospital Annex", "hospital"), ("Global Bites", "restaurant"),
        ("Allahabad Degree College", "college"), ("Sunrise Multi-Speciality", "hospital"),
        ("Spice Route", "restaurant"), ("St. Joseph's College", "college"),
        ("Green Leaf Kitchen", "restaurant"), ("Metro Hospital", "hospital"),
        ("Curry House", "restaurant"), ("Civil Lines Institute", "college"),
    ]
    rows = []
    for idx, (name, lat, lon, am) in enumerate(base):
        rows.append((idx, name, lat, lon, am))
    for i, (name, am) in enumerate(names_pool[:n_extra]):
        lat = CITY_CENTER[0] + rng.uniform(-0.012, 0.012)
        lon = CITY_CENTER[1] + rng.uniform(-0.012, 0.012)
        rows.append((len(base) + i, name, lat, lon, am))
    return pd.DataFrame(rows, columns=["node_id", "name", "latitude", "longitude", "amenity_type"])


@st.cache_data(show_spinner=False)
def load_mysql_locations(host, user, password, database) -> pd.DataFrame:
    import mysql.connector
    conn = mysql.connector.connect(host=host, user=user, password=password, database=database)
    # noinspection SqlNoDataSourceInspection
    df = pd.read_sql("SELECT node_id, name, latitude, longitude, amenity_type FROM location", conn)
    conn.close()
    # MySQL DECIMAL columns come back as Python decimal.Decimal, which breaks
    # downstream float math (KDTree, distance_matrix, ACO, random.uniform, etc.)
    # -- same bug you hit in the notebook. Cast once, here, at the source.
    df["latitude"] = df["latitude"].astype(float)
    df["longitude"] = df["longitude"].astype(float)
    return df


@st.cache_data(show_spinner=False)
def simulate_demand(locations_df: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    """Recreates the notebook's synthetic historical-request generator,
    used here to size the 'waste volume' KPI and weight stop priority."""
    rng = random.Random(seed)
    records = []
    for _, r in locations_df.iterrows():
        amenity = r["amenity_type"]
        if amenity == "restaurant":
            n = rng.randint(15, 45)
        elif amenity == "hospital":
            n = rng.randint(30, 60)
        else:
            n = rng.randint(5, 20)
        total_volume = sum(max(2.0, rng.gauss(15.0, 5.0)) for _ in range(n))
        records.append((r["node_id"], n, round(total_volume, 1)))
    return pd.DataFrame(records, columns=["node_id", "num_requests_30d", "waste_kg_30d"])


# --------------------------------------------------------------------------
# TRUCK LOCATION (dynamic, matching the notebook's get_truck_location)
# --------------------------------------------------------------------------
def get_truck_location(source: str, locations_df: pd.DataFrame,
                        host=None, user=None, password=None, database=None):
    """
    Mirrors the notebook's get_truck_location function so the live app and the
    notebook tell the same story, instead of the app using a hardcoded point.

    source="Fixed depot (Civil Lines)" : CITY_CENTER constant -- a real, named depot.
    source="Simulate (random in service area)" : random point inside the bounding
        box of the actual location data -- good for demoing "the truck moves".
    source="Live GPS (MySQL truck_telemetry)" : latest row from a truck_telemetry
        table, for when real hardware/GPS is wired up. Requires that table to exist.
    """
    if source == "Live GPS (MySQL truck_telemetry)":
        import mysql.connector
        conn = mysql.connector.connect(host=host, user=user, password=password, database=database)
        cursor = conn.cursor()
        # noinspection SqlNoDataSourceInspection
        cursor.execute("SELECT latitude, longitude FROM truck_telemetry ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row is None:
            raise ValueError("No telemetry rows found in truck_telemetry table.")
        return [float(row[0]), float(row[1])]

    if source == "Simulate (random in service area)":
        lat_min, lat_max = float(locations_df["latitude"].min()), float(locations_df["latitude"].max())
        lon_min, lon_max = float(locations_df["longitude"].min()), float(locations_df["longitude"].max())
        return [random.uniform(lat_min, lat_max), random.uniform(lon_min, lon_max)]

    return CITY_CENTER  # "Fixed depot (Civil Lines)"


# --------------------------------------------------------------------------
# ROUTING: KD-TREE NEAREST NEIGHBORS
# --------------------------------------------------------------------------
def nearest_stops(locations_df: pd.DataFrame, truck_location, k: int) -> pd.DataFrame:
    # .astype(float) makes the dtype explicit for both KDTree and static type
    # checkers -- locations_df may still carry object/Decimal dtype if it came
    # straight from MySQL without the cast applied upstream.
    coords = locations_df[["latitude", "longitude"]].to_numpy(dtype=float)
    tree = KDTree(coords)
    k = min(k, len(locations_df) - 1)
    distances, indices = tree.query(truck_location, k=k)
    return locations_df.iloc[indices].assign(kdtree_distance=distances)


# --------------------------------------------------------------------------
# ROUTING: REAL ROAD-NETWORK DISTANCES (instead of straight-line/Euclidean)
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner="Downloading road network from OpenStreetMap (first run only)...")
def load_road_graph(place_name: str = PLACE_NAME):
    import osmnx as ox
    if os.path.exists(GRAPH_CACHE_PATH):
        return ox.load_graphml(GRAPH_CACHE_PATH)
    graph = ox.graph_from_place(place_name, network_type="drive")
    ox.save_graphml(graph, GRAPH_CACHE_PATH)
    return graph


def road_distance_matrix(route_coords: np.ndarray, road_graph) -> np.ndarray:
    """Real shortest-path distances (km) between points, snapped onto the road graph.
    O(n) Dijkstra runs instead of O(n^2) pairwise calls."""
    import networkx as nx
    import osmnx as ox

    lats, lons = route_coords[:, 0], route_coords[:, 1]
    # Cast to a plain Python list[int]: ox.distance.nearest_nodes' return type is
    # loosely typed by the stub, which was making the static checker infer `dst`
    # below as a huge Union that (incorrectly) includes non-hashable types like
    # ndarray/DataFrame. A plain int is unambiguously hashable and matches what
    # these values actually are at runtime (OSM node IDs).
    node_ids = [int(nid) for nid in ox.distance.nearest_nodes(road_graph, X=lons, Y=lats)]

    n = len(node_ids)
    dist_m = np.zeros((n, n))
    for i, src in enumerate(node_ids):
        lengths = nx.single_source_dijkstra_path_length(road_graph, src, weight="length")
        for j, dst in enumerate(node_ids):
            if i != j:
                dist_m[i, j] = lengths.get(dst, np.inf)

    finite_vals = dist_m[np.isfinite(dist_m)]
    if finite_vals.size:
        dist_m[~np.isfinite(dist_m)] = finite_vals.max() * 10  # penalize unreachable pairs

    return dist_m / 1000.0  # meters -> km


# --------------------------------------------------------------------------
# ROUTING: FULL ANT COLONY OPTIMIZATION
# --------------------------------------------------------------------------
def run_aco(dist_mat: np.ndarray, num_ants=10, num_iterations=50,
            evaporation_rate=0.5, alpha=1.0, beta=2.0, seed=0):
    rng = random.Random(seed)
    num_nodes = int(dist_mat.shape[0])
    pheromones = np.ones((num_nodes, num_nodes))
    heuristic = 1.0 / (dist_mat + 1e-10)

    best_path, best_len = None, float("inf")
    history = []  # best-so-far length per iteration, for the convergence chart

    for _ in range(num_iterations):
        all_paths, all_lengths = [], []
        for _ant in range(num_ants):
            current, path, visited, length = 0, [0], {0}, 0.0
            while len(visited) < num_nodes:
                probs = []
                for nxt in range(num_nodes):
                    if nxt not in visited:
                        tau = pheromones[current][nxt] ** alpha
                        eta = heuristic[current][nxt] ** beta
                        probs.append(tau * eta)
                    else:
                        probs.append(0.0)
                total = sum(probs)
                probs = [p / total for p in probs] if total > 0 else [1 / num_nodes] * num_nodes
                nxt_node = rng.choices(range(num_nodes), weights=probs, k=1)[0]
                length += dist_mat[current][nxt_node]
                current = nxt_node
                path.append(current)
                visited.add(current)
            all_paths.append(path)
            all_lengths.append(length)
            if length < best_len:
                best_len, best_path = length, path

        # Evaporate + deposit pheromones
        pheromones *= (1 - evaporation_rate)
        for path, length in zip(all_paths, all_lengths):
            for i in range(len(path) - 1):
                pheromones[path[i]][path[i + 1]] += 1.0 / length
        history.append(best_len)

    return best_path, best_len, history


def naive_route_length(dist_mat: np.ndarray) -> float:
    """Simple nearest-neighbor greedy baseline, for the 'savings vs naive' KPI."""
    n = int(dist_mat.shape[0])
    visited, current, total = {0}, 0, 0.0
    while len(visited) < n:
        candidates = [(dist_mat[current][j], j) for j in range(n) if j not in visited]
        d, j = min(candidates)
        total += d
        current = j
        visited.add(j)
    return total


# --------------------------------------------------------------------------
# SIDEBAR — CONTROLS
# --------------------------------------------------------------------------
st.sidebar.title("🚛 Control Panel")

data_source = st.sidebar.radio("Data source", ["Demo dataset", "Connect to MySQL"], index=0)

mysql_creds: dict[str, Optional[str]] = dict(host=None, user=None, password=None, database=None)
if data_source == "Connect to MySQL":
    st.sidebar.caption("Credentials are only kept in this session's memory.")
    mysql_creds["host"] = st.sidebar.text_input("Host", "localhost")
    mysql_creds["user"] = st.sidebar.text_input("User", "root")
    mysql_creds["password"] = st.sidebar.text_input("Password", type="password")
    mysql_creds["database"] = st.sidebar.text_input("Database", "zero_waste_logistics")
    try:
        locations_df = load_mysql_locations(**mysql_creds)
        st.sidebar.success(f"Loaded {len(locations_df)} locations from MySQL")
    except Exception as e:
        st.sidebar.error(f"Connection failed, using demo data instead.\n\n{e}")
        locations_df = load_demo_locations()
else:
    locations_df = load_demo_locations()

st.sidebar.markdown("---")
st.sidebar.subheader("Truck location")
truck_source_options = ["Fixed depot (Civil Lines)", "Simulate (random in service area)"]
if data_source == "Connect to MySQL":
    truck_source_options.append("Live GPS (MySQL truck_telemetry)")
truck_source = st.sidebar.selectbox(
    "How to determine the truck's current position",
    truck_source_options,
    index=0,
    help="Matches the get_truck_location() approach from the notebook -- no hardcoded "
         "coordinates. 'Live GPS' requires a truck_telemetry table in MySQL.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Distance mode")
distance_mode = st.sidebar.radio(
    "How to measure distance between stops",
    ["Straight-line (fast)", "Real road network (accurate)"],
    index=0,
    help="Road network mode downloads Prayagraj's street graph once (cached to disk "
         "afterward) and computes actual driving distances instead of straight lines.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Route settings")
num_stops = st.sidebar.slider("Number of pickup stops", 3, min(12, len(locations_df) - 1), 6)
amenity_filter = st.sidebar.multiselect(
    "Filter by amenity type",
    options=sorted(locations_df["amenity_type"].unique()),
    default=sorted(locations_df["amenity_type"].unique()),
)

st.sidebar.markdown("---")
st.sidebar.subheader("ACO hyperparameters")
num_ants = st.sidebar.slider("Number of ants", 5, 30, 10)
num_iterations = st.sidebar.slider("Iterations", 10, 150, 50)
evaporation_rate = st.sidebar.slider("Evaporation rate", 0.1, 0.9, 0.5)
alpha = st.sidebar.slider("Alpha (pheromone weight)", 0.5, 3.0, 1.0)
beta = st.sidebar.slider("Beta (distance weight)", 0.5, 4.0, 2.0)

run_button = st.sidebar.button("▶ Run Optimization", use_container_width=True, type="primary")

# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
st.title("🚛 Zero Waste Logistics — Routing Dashboard")
st.caption("Truck location → KD-Tree nearest-neighbor search → Distance matrix → Ant Colony Optimization → Live route map")
st.markdown("---")

filtered_df = locations_df[locations_df["amenity_type"].isin(amenity_filter)].reset_index(drop=True)
demand_df = simulate_demand(filtered_df)

if "result" not in st.session_state:
    st.session_state.result = None

if run_button or st.session_state.result is None:
    try:
        truck_location = get_truck_location(truck_source, filtered_df, **mysql_creds)
    except Exception as e:
        st.warning(f"Couldn't get truck location via '{truck_source}' ({e}). Falling back to fixed depot.")
        truck_location = CITY_CENTER

    stops_df = nearest_stops(filtered_df, truck_location, num_stops)

    route_coords = [truck_location] + stops_df[["latitude", "longitude"]].values.tolist()
    # Explicit str()/int() casts: pandas .tolist() on an object-dtype column gets
    # inferred by the checker as list[Any] (a huge Union of every possible pandas
    # scalar type), which is what was making amenity = ordered_types[i] look
    # unhashable a couple lines later at the .get(amenity, ...) calls. Casting
    # here narrows everything to plain str/int once, at the source.
    route_names: list[str] = ["Garbage Truck (Start)"] + [str(x) for x in stops_df["name"].tolist()]
    route_types: list[str] = ["other"] + [str(x) for x in stops_df["amenity_type"].tolist()]
    route_ids: list[int] = [-1] + [int(x) for x in stops_df["node_id"].tolist()]
    route_coords = np.array(route_coords, dtype=float)

    if distance_mode == "Real road network (accurate)":
        road_graph = load_road_graph()
        dist_mat = road_distance_matrix(route_coords, road_graph)
        dist_unit_label = "km (real road distance)"
    else:
        dist_mat = distance_matrix(route_coords, route_coords)  # degrees, straight-line
        dist_unit_label = "deg (straight-line)"

    with st.spinner("Ants searching for the optimal route..."):
        best_path, best_len, history = run_aco(
            dist_mat, num_ants=num_ants, num_iterations=num_iterations,
            evaporation_rate=evaporation_rate, alpha=alpha, beta=beta,
        )
    naive_len = naive_route_length(dist_mat)

    st.session_state.result = dict(
        stops_df=stops_df, route_coords=route_coords, route_names=route_names,
        route_types=route_types, route_ids=route_ids, dist_mat=dist_mat,
        best_path=best_path, best_len=best_len, history=history, naive_len=naive_len,
        dist_unit_label=dist_unit_label, truck_source=truck_source,
    )

res = st.session_state.result
route_coords: np.ndarray = res["route_coords"]
route_names: list[str] = res["route_names"]
route_types: list[str] = res["route_types"]
best_path, best_len, history, naive_len = res["best_path"], res["best_len"], res["history"], res["naive_len"]
dist_unit_label = res["dist_unit_label"]

# Road-network distances are already in km; straight-line ones are in raw
# lat/lon degrees and need the ~111 km/degree conversion to be meaningful.
KM_FACTOR = 1.0 if "road" in dist_unit_label else 111.0

ordered_coords = route_coords[best_path]
ordered_names = [route_names[i] for i in best_path]
ordered_types = [route_types[i] for i in best_path]

savings_pct = (1 - best_len / naive_len) * 100 if naive_len > 0 else 0
total_waste = demand_df["waste_kg_30d"].sum()
est_fuel_l = best_len * KM_FACTOR * 0.35  # rough: km * L/km for a waste truck

# --------------------------------------------------------------------------
# KPI ROW
# --------------------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Stops on route", f"{len(ordered_names) - 1}")
k2.metric("Optimized distance", f"{best_len*KM_FACTOR:.2f} km", help=f"Source: {dist_unit_label}")
k3.metric("Savings vs. naive route", f"{savings_pct:.1f}%", delta=f"-{(naive_len-best_len)*KM_FACTOR:.2f} km")
k4.metric("Est. waste collected (30d)", f"{total_waste:,.0f} kg")
st.caption(f"Truck location source: **{res['truck_source']}**")

st.markdown("---")

# --------------------------------------------------------------------------
# TABS
# --------------------------------------------------------------------------
tab_map, tab_analytics, tab_data, tab_about = st.tabs(
    ["🗺️ Live Map", "📊 Analytics", "📋 Data", "ℹ️ About"]
)

with tab_map:
    st.subheader("Optimal Collection Route")
    legend_html = "".join(
        f'<span class="route-pill">● {t}</span>' for t in sorted(set(ordered_types))
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    m = folium.Map(location=CITY_CENTER, zoom_start=15, tiles="CartoDB dark_matter")

    folium.Marker(
        ordered_coords[0].tolist(),
        popup="Garbage Truck (Start)",
        tooltip="Start",
        icon=folium.Icon(color="green", icon="truck", prefix="fa"),
    ).add_to(m)

    for i in range(1, len(ordered_coords)):
        amenity = ordered_types[i]
        folium.Marker(
            ordered_coords[i].tolist(),
            popup=f"Stop {i}: {ordered_names[i]} ({amenity})",
            tooltip=f"Stop {i}",
            icon=folium.Icon(color=AMENITY_COLORS.get(amenity, "gray"),
                              icon=AMENITY_ICONS.get(amenity, "map-marker"), prefix="fa"),
        ).add_to(m)

    folium.PolyLine(
        locations=ordered_coords.tolist(),
        color="#58a6ff", weight=5, opacity=0.85, tooltip="ACO Optimal Route",
    ).add_to(m)

    st_folium(m, width=None, height=600, use_container_width=True)

with tab_analytics:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("ACO Convergence")
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=history, mode="lines", line=dict(color="#58a6ff", width=3)))
        fig.update_layout(
            xaxis_title="Iteration", yaxis_title="Best route length (deg)",
            template="plotly_dark", height=350, margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Naive vs. ACO-Optimized Route")
        fig2 = go.Figure(go.Bar(
            x=["Nearest-Neighbor (naive)", "ACO Optimized"],
            y=[naive_len * KM_FACTOR, best_len * KM_FACTOR],
            marker_color=["#8b949e", "#58a6ff"],
        ))
        fig2.update_layout(yaxis_title="Distance (km)", template="plotly_dark",
                            height=350, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Demand mix by amenity type")
    merged = filtered_df.merge(demand_df, on="node_id")
    fig3 = px.sunburst(
        merged, path=["amenity_type", "name"], values="waste_kg_30d",
        color="amenity_type", color_discrete_map={
            "restaurant": "#f0883e", "hospital": "#f85149",
            "college": "#a371f7", "other": "#8b949e",
        },
    )
    fig3.update_layout(template="plotly_dark", height=450, margin=dict(t=10, b=10))
    st.plotly_chart(fig3, use_container_width=True)

with tab_data:
    st.subheader("Route order (as produced by ACO)")
    order_table = pd.DataFrame({
        "Stop #": range(len(ordered_names)),
        "Location": ordered_names,
        "Type": ordered_types,
        "Latitude": ordered_coords[:, 0],
        "Longitude": ordered_coords[:, 1],
    })
    st.dataframe(order_table, use_container_width=True, hide_index=True)

    st.subheader("All candidate locations (post-filter)")
    st.dataframe(
        filtered_df.merge(demand_df, on="node_id"),
        use_container_width=True, hide_index=True,
    )

with tab_about:
    st.markdown("""
    ### Pipeline
    1. **Data extraction** — restaurants, hospitals, and colleges pulled from OpenStreetMap via `osmnx`.
    2. **Storage** — cleaned point data loaded into a MySQL `location` table.
    3. **Truck location** — determined dynamically (fixed depot, simulated, or live GPS), never hardcoded.
    4. **Demand simulation** — synthetic historical pickup requests generated per location, weighted by amenity type.
    5. **Nearest-neighbor search** — a KD-Tree finds the closest pending pickups to the truck's current position.
    6. **Route optimization** — an Ant Colony Optimization (ACO) metaheuristic searches for the shortest tour across the selected stops, using either straight-line or real road-network distances.
    7. **Visualization** — this dashboard, rendering the live route, KPIs, and optimizer diagnostics.

    Use the sidebar to swap between the demo dataset and a live MySQL connection, choose how the
    truck's current location is determined, adjust which stops are considered, pick straight-line
    vs. real road-network distance, and tune the ACO hyperparameters to see how they affect convergence.
    """)

st.markdown("---")
st.caption("Zero Waste Logistics · ACO-based routing demo")