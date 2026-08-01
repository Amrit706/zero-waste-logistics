<div align="center">

# 🚛 Zero Waste Logistics — Smart Waste Collection Routing

</div>

![Python](https://img.shields.io/badge/python-3.13+-3776AB?style=flat-square&logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/-Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)
![Optimization](https://img.shields.io/badge/Optimization-Ant%20Colony-orange?style=flat-square)
![MySQL](https://img.shields.io/badge/-MySQL-4479A1?style=flat-square&logo=mysql&logoColor=white)

An end-to-end route optimization system that finds **near-optimal garbage collection routes** across a city using **real road-network distances** (not straight-line estimates) and an **Ant Colony Optimization** algorithm built from scratch — going beyond a fixed daily route into something that actually adapts to where the truck is and what's on the map.

**Business Impact:** Cut total route distance by roughly **5–20%** versus a naive nearest-neighbor ordering (varies by run/hyperparameters), while switching the underlying distance calculation from straight-line estimates to **real drivable road distances** via Dijkstra's shortest-path algorithm — meaning the optimized route is one a truck could actually drive, not just a theoretical shortcut through buildings.

🔗 **Live Demo:** [https://zero-waste-logistics.streamlit.app](https://zero-waste-logistics.streamlit.app)

---

## 🧠 What's Under the Hood

| Stage | What Happens | Tech |
|---|---|---|
| 🗺️ Data Extraction | Restaurants, hospitals & colleges pulled from OpenStreetMap | `osmnx` |
| 🗄️ Storage | Cleaned location data persisted to a relational database | `MySQL` |
| 🎲 Demand Simulation | Synthetic historical pickup-request patterns (dinner rushes, hospital frequency, etc.) | `NumPy` / `random` |
| 📍 Nearest-Neighbor Search | Instantly finds the closest pending pickups to the truck | `SciPy KD-Tree` |
| 🛣️ Real Road Distance | Locations snapped onto the actual drivable street graph, shortest paths computed with **Dijkstra's algorithm** | `NetworkX` + `osmnx` |
| 🐜 Route Optimization | Ant Colony Optimization, built from scratch — pheromone trails + distance heuristics converge on a short route | Custom Python |
| 📊 Live Dashboard | Interactive map, KPIs, and optimizer convergence charts | `Streamlit` + `Folium` + `Plotly` |

---

## ✨ Features

- 🚚 **Dynamic truck location** — simulated in real time, or pulled live from GPS telemetry, never hardcoded
- 🛰️ **Two distance modes** — instant straight-line estimate, or real road-network driving distance (Dijkstra on the actual street graph)
- 🐜 **Tunable ACO engine** — adjust ants, iterations, evaporation rate, and pheromone/distance weighting live from the sidebar
- 🗺️ **Live interactive map** — optimized route rendered stop-by-stop with amenity-specific markers
- 📈 **Optimizer analytics** — convergence curve + naive-route vs. optimized-route comparison
- 🔌 **MySQL-ready** — flip a toggle to pull real production data instead of the bundled demo dataset
- 🛡️ **Resilient by design** — gracefully falls back to demo data if a DB connection isn't available, instead of crashing

---

## 🏗️ Pipeline

```
OpenStreetMap ──▶ MySQL ──▶ KD-Tree (nearest pickups)
                                    │
                                    ▼
                  Road Network Graph + Dijkstra (real distances)
                                    │
                                    ▼
                      Ant Colony Optimization (best route)
                                    │
                                    ▼
                         Streamlit Live Dashboard
```

---

## 🎓 What This Project Demonstrates

- **Graph algorithms** — Dijkstra's shortest-path algorithm applied to a real 48,000+ node city road network, not a toy graph
- **Spatial data structures** — KD-Trees for fast geographic nearest-neighbor lookup
- **Combinatorial optimization** — Ant Colony Optimization implemented from first principles (not a library call), including pheromone evaporation/deposit and the alpha/beta exploration-vs-exploitation tradeoff
- **Real-world geospatial engineering** — the jump from naive straight-line distance to actual road-network shortest paths, which is the difference between a toy demo and something realistic
- **Data engineering fundamentals** — schema design, MySQL integration, and catching subtle type issues (e.g. `DECIMAL` columns returning as Python `Decimal` instead of `float`, which silently breaks downstream math if uncaught)
- **Production-minded habits** — no hardcoded secrets, no hardcoded "truck location," graceful fallbacks instead of crashes
- **Full-stack deployment** — from a Jupyter notebook prototype to a live, publicly deployed app on Streamlit Community Cloud, version-controlled on GitHub

---

## 🚀 Run It Yourself

```bash
git clone https://github.com/Amrit706/zero-waste-logistics.git
cd zero-waste-logistics
pip install -r requirements.txt
streamlit run app.py
```

Runs instantly on the bundled demo dataset — no database setup required. Flip the sidebar toggle to **"Connect to MySQL"** if you want to point it at your own `location` table.

---

## 📁 Project Structure

```
zero-waste-logistics/
├── app.py                          # Streamlit dashboard
├── main_updated.ipynb              # Full pipeline, built & tested step by step
├── requirements.txt                # Dependencies
├── prayagraj_drive_network.graphml # Cached road network (instant load, no re-download)
└── README.md
```

---

## 🛠️ Tech Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-4479A1?style=flat-square&logo=mysql&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-013243?style=flat-square&logo=numpy&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-150458?style=flat-square&logo=pandas&logoColor=white)
![SciPy](https://img.shields.io/badge/SciPy-8CAAE6?style=flat-square&logo=scipy&logoColor=white)
![Plotly](https://img.shields.io/badge/Plotly-3F4F75?style=flat-square&logo=plotly&logoColor=white)

**OSMnx** · **NetworkX** (Dijkstra's algorithm) · **Folium** · **Ant Colony Optimization** (custom implementation)

---

## 📌 Note on the Data

Location data (restaurants, hospitals, colleges) is real, pulled live from OpenStreetMap. Historical pickup-request volume is **synthetically simulated** — I didn't have access to real sensor/request logs, so demand patterns are generated with realistic assumptions (e.g. hospitals get picked up more frequently than colleges, restaurants spike during dinner hours).

---

<div align="center">

⭐ **If this project is useful or interesting to you, consider starring the repo!**

🔗 **[View the live app](https://zero-waste-logistics.streamlit.app)**

</div>
