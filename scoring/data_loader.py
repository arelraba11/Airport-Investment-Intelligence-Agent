from pathlib import Path

import pandas as pd

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "airports_dataset.csv"


def load_dataset(path: Path = DATASET_PATH) -> pd.DataFrame:
    """Load the unified airport dataset, indexed by IATA code."""
    return pd.read_csv(path).set_index("iata")
