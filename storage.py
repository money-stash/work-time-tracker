import json
import os

DATA_FILE = "data.json"

DEFAULT_DATA = {
    "work_start_time": "14:00",
    "work_duration_minutes": 120,
    "session_minutes": 30,
    "break_minutes": 10,
    "warning_before_end_minutes": 3,
    "session": {
        "active": False,
        "completed_minutes": 0,
        "state": "idle"
    }
}

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        for key, value in DEFAULT_DATA.items():
            if key not in data:
                data[key] = value
        return data
    return DEFAULT_DATA.copy()

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_setting(key: str):
    return load_data()[key]

def set_setting(key: str, value):
    data = load_data()
    data[key] = value
    save_data(data)

def get_session() -> dict:
    return load_data()["session"]

def update_session(**kwargs):
    data = load_data()
    data["session"].update(kwargs)
    save_data(data)

def reset_session():
    data = load_data()
    data["session"] = {
        "active": False,
        "completed_minutes": 0,
        "state": "idle"
    }
    save_data(data)
