from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Copenhagen")

def parse_feedback_received_dt(value: str):
    if not value:
        return None
    dt_naive = datetime.strptime(value, "%Y-%m-%d-%H-%M")
    return dt_naive.replace(tzinfo=TZ)
