"""Physics/context-informed ensemble. Stand-in for the trained XGBoost+PyG stack;
same feature contract, so swapping in model checkpoints changes nothing upstream."""
import math

CLASSES: list[str] = ["industrial", "persistent", "wildfire", "agricultural"]

HAZARD_BOOST = {"G-III": 0.12, "G-II": 0.06}
HAZARD_EXPOSURE = {"G-III": 0.9, "G-II": 0.6}


def _norm(v: float, mx: float) -> float:
    return min(1.0, max(0.0, v / mx))


def classify(f: dict) -> dict:
    prox = 0.0 if f.get("facility_distance_km") is None else math.exp(-f["facility_distance_km"] / 1.5)
    hz = HAZARD_BOOST.get(f.get("facility_hazard") or "", 0.0)
    pd_ = f["persist_days"]
    raw: dict[str, float] = {
        "industrial": 0.62 * prox + hz + 0.22 * _norm(f["frp"], 900) + 0.16 * f["night_ratio"],
        "persistent": (0.68 + 0.012 * min(pd_, 40) if pd_ >= 5 else 0.05 * pd_) + 0.28 * prox + 0.14 * (1 - f["diurnal_variance"]),
        "wildfire": 0.58 * f["forest_proxy"] + 0.30 * (1 - prox) + 0.22 * f["diurnal_variance"],
        "agricultural": 0.66 * f["agri_window"] + 0.24 * f["cluster_density"] + 0.10 * (1 - prox),
    }
    temp = 3.2
    exps = {k: math.exp(v * temp) for k, v in raw.items()}
    total = sum(exps.values())
    scores: dict[str, float] = {k: v / total for k, v in exps.items()}
    primary = max(scores, key=lambda k: scores[k])
    confidence = round(min(0.97, max(0.55, scores[primary] + 0.08)) * 100)
    return {"primary": primary, "scores": scores, "confidence": confidence}


def score_risk(f: dict, confidence: int) -> dict:
    intensity = _norm(f["frp"], 700)
    persistence = _norm(f["persist_days"], 20)
    exposure = HAZARD_EXPOSURE.get(f.get("facility_hazard") or "", 0.25)
    score = round(100 * (0.4 * intensity + 0.25 * persistence + 0.2 * exposure + 0.15 * confidence / 100))
    level = "critical" if score >= 75 else "high" if score >= 55 else "moderate" if score >= 35 else "low"
    drivers: list[str] = []
    if intensity > 0.45: drivers.append(f"FRP {round(f['frp'])} MW (elevated)")
    if f["persist_days"] >= 5: drivers.append(f"{f['persist_days']}-day persistence (STA rule)")
    if f.get("facility_hazard"): drivers.append(f"Proximity to {f['facility_hazard']} hazard facility")
    if f["night_ratio"] > 0.4: drivers.append("Night-time detection (uncontrolled-burn indicator)")
    return {"score": score, "level": level, "drivers": drivers or ["No aggravating factors"]}


def spread_rings(lat: float, lon: float, frp: float, primary: str,
                 wind_ms: float, wind_deg: float,
                 hours: tuple[int, ...] = (6, 12, 24)) -> list[dict]:
    """Anisotropic expansion preview (agent-based Monte-Carlo is the upgrade path)."""
    base = {"wildfire": 0.55, "agricultural": 0.35, "industrial": 0.08, "persistent": 0.05}[primary]
    rate = base * (0.6 + min(wind_ms, 15) / 12) * (0.7 + min(frp, 800) / 1600)
    wx, wy = math.sin(math.radians(wind_deg)), math.cos(math.radians(wind_deg))
    rings: list[dict] = []
    for h in hours:
        r = rate * h
        poly: list[list[float]] = []
        for i in range(32):
            a = 2 * math.pi * i / 32
            dx, dy = math.cos(a), math.sin(a)
            stretch = 1 + 0.8 * max(0.0, dx * wx + dy * wy)
            km = r * stretch
            dlat = (dy * km) / 111.0
            dlon = (dx * km) / (111.0 * max(0.2, math.cos(math.radians(lat))))
            poly.append([round(lon + dlon, 5), round(lat + dlat, 5)])
        poly.append(poly[0])
        rings.append({"hours": h, "radius_km": round(r, 2), "polygon": poly})
    return rings

