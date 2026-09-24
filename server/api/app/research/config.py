"""Research configuration — frozen for reproducibility.

Every experiment must reference this config (or a frozen copy of it)
so that results can be reproduced exactly.
"""
from __future__ import annotations

from pathlib import Path

# --- Reproducibility ---
GLOBAL_SEED = 42
SPLIT_SEED = 42
MODEL_SEED = 42
SYNTHETIC_SEED = 42

# --- Versions ---
FEATURE_SCHEMA_VERSION = "fs-v1.0.0"
DATASET_SCHEMA_VERSION = "ds-v1.0.0"
BASELINE_MODEL_VERSION = "baseline-v1.0.0"

# --- Paths ---
RESEARCH_ROOT = Path(__file__).parent
ARTIFACTS_DIR = RESEARCH_ROOT / "artifacts"
DATASETS_DIR = RESEARCH_ROOT / "datasets"

# --- Split defaults ---
FACILITY_SPLIT_TEST_SIZE = 0.30  # 30% of facilities held out
TEMPORAL_SPLIT_TRAIN_FRACTION = 0.80  # first 80% of days for training

# --- Baseline hyperparameters (frozen — no tuning in E1) ---
RF_N_ESTIMATORS = 300
RF_MAX_DEPTH = 12
RF_MIN_SAMPLES_LEAF = 5
RF_MAX_FEATURES = "sqrt"

# B4 anomaly threshold (tuned on train fold only, reported)
B4_ZSCORE_THRESHOLDS = [2.0, 2.5, 3.0, 3.5, 4.0]
B4_MIN_HISTORY_DAYS = 14  # need at least 14 days of history for z-score
B4_MIN_HISTORY_OBS = 10   # and at least 10 observations

# --- Class definitions (10-way, matches production) ---
SOURCE_CLASSES = [
    "refinery", "steel", "gas_flare", "cement", "smelter",
    "waste_incineration", "power_plant", "chemical",
    "unknown_industrial", "natural_fire",
]

# Normality labels (anomaly task)
NORMALITY_CLASSES = ["normal", "abnormal"]

# --- Minimum reporting thresholds ---
MIN_CLASS_SUPPORT = 20  # classes with <20 test samples flagged as unreliable
