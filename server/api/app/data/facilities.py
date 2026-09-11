"""OSM-extracted industrial registry seed (Overpass extraction schema)."""
FACILITIES: list[dict] = [
    {"id": "F-001", "name": "Jamnagar Refinery Complex", "subtype": "refinery", "lat": 22.47, "lon": 70.06, "hazard": "G-III"},
    {"id": "F-002", "name": "Bathinda Refinery (GGSR)", "subtype": "refinery", "lat": 30.21, "lon": 74.94, "hazard": "G-III"},
    {"id": "F-003", "name": "Haldia Petrochemicals", "subtype": "refinery", "lat": 22.03, "lon": 88.06, "hazard": "G-III"},
    {"id": "F-004", "name": "Tata Steel Jamshedpur", "subtype": "steel", "lat": 22.80, "lon": 86.20, "hazard": "G-III"},
    {"id": "F-005", "name": "Bokaro Steel Plant", "subtype": "steel", "lat": 23.66, "lon": 85.96, "hazard": "G-III"},
    {"id": "F-006", "name": "KG Basin Flare Cluster", "subtype": "gas_flare", "lat": 16.95, "lon": 82.25, "hazard": "G-III"},
    {"id": "F-007", "name": "Vapi Chemical Zone", "subtype": "chemical", "lat": 20.37, "lon": 72.90, "hazard": "G-III"},
    {"id": "F-008", "name": "Dahej SEZ Chemical Hub", "subtype": "chemical", "lat": 21.72, "lon": 72.57, "hazard": "G-III"},
    {"id": "F-009", "name": "Ankleshwar GIDC Estate", "subtype": "chemical", "lat": 21.62, "lon": 73.02, "hazard": "G-II"},
    {"id": "F-010", "name": "Satna Cement Works", "subtype": "cement", "lat": 24.60, "lon": 80.83, "hazard": "G-II"},
    {"id": "F-011", "name": "Gulbarga Cement Unit", "subtype": "cement", "lat": 17.33, "lon": 76.83, "hazard": "G-II"},
    {"id": "F-012", "name": "Nalco Angul Smelter", "subtype": "smelter", "lat": 20.85, "lon": 85.10, "hazard": "G-III"},
    {"id": "F-013", "name": "Singrauli NTPC Station", "subtype": "power_plant", "lat": 24.05, "lon": 82.70, "hazard": "G-II"},
    {"id": "F-014", "name": "Chandrapur Thermal PS", "subtype": "power_plant", "lat": 19.85, "lon": 79.30, "hazard": "G-II"},
]
