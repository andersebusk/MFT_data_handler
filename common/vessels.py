import pandas as pd
from config import VESSEL_EXCEL_FILE

_vessel_data_cache = None

def load_vessels():
    global _vessel_data_cache
    if _vessel_data_cache is None:
        df = pd.read_excel(VESSEL_EXCEL_FILE).fillna("")
        if "cylinders" in df.columns:
            df["cylinders"] = pd.to_numeric(df["cylinders"], errors="coerce").fillna(0).astype(int)
        else:
            df["cylinders"] = 0
        _vessel_data_cache = df.to_dict(orient="records")
    return _vessel_data_cache
