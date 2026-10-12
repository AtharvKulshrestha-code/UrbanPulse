from pathlib import Path
import io
import json
import os
import urllib.error
import urllib.request

import altair as alt
import math
import pandas as pd
import pydeck as pdk
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

# UrbanPulse — Stitch-inspired dashboard using the real rainfall dataset.
# Rainfall observations are historical source data; no flood predictions are made.

st.set_page_config(
    page_title="UrbanPulse | Rainfall Intelligence",
    page_icon="🌧️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE = Path(__file__).resolve().parent
CANDIDATE_PATHS = [
    BASE / "data" / "processed" / "bengaluru_geo_filtered.csv",
    BASE / "data" / "processed" / "bengaluru_rainfall.csv",
    BASE / "data" / "rainfall_data.csv",
]
TIME_COL = "Data Acquisition Time"
STATION_COL = "Station"
RAIN_COL = "Telemetry Hourly Rainfall (mm)"
LAT_COL = "Latitude"
LON_COL = "Longitude"

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
    :root { --bg:#040810; --panel:#0d1726; --border:rgba(80,112,151,.32); --cyan:#00f0ff; --muted:#94a3b8; }
    html, body, [class*="css"] { font-family:'Plus Jakarta Sans',system-ui,sans-serif; }
    .stApp { background:radial-gradient(circle at 18% 8%,rgba(0,240,255,.075),transparent 32%),radial-gradient(circle at 88% 12%,rgba(59,130,246,.07),transparent 35%),#040810; color:#f0f6fc; }
    [data-testid="stHeader"] { background:rgba(4,8,16,.82); }
    [data-testid="stSidebar"] { background:rgba(6,12,22,.97); border-right:1px solid rgba(255,255,255,.07); }
    [data-testid="stSidebar"] * { color:#dbe7f4; }
    .block-container { padding-top:1.6rem; padding-bottom:3rem; max-width:1700px; }
    h1,h2,h3 { color:#fff !important; letter-spacing:-.5px; }
    .eyebrow { color:#00f0ff; font:700 10px 'JetBrains Mono',monospace; letter-spacing:2px; text-transform:uppercase; margin-bottom:7px; }
    .main-title { font-size:31px; font-weight:800; letter-spacing:-1px; line-height:1.2; color:white; }
    .sub-title { color:#94a3b8; font-size:12px; margin-top:5px; }
    .rule { border-bottom:1px solid rgba(255,255,255,.08); margin:18px 0 23px; }
    .panel { background:rgba(13,23,38,.83); border:1px solid var(--border); border-radius:15px; padding:19px 20px; box-shadow:0 15px 38px rgba(0,0,0,.2); margin-bottom:13px; }
    .metric-label { color:#94a3b8; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:1px; }
    .metric-value { font:800 27px 'JetBrains Mono',monospace; color:#f8fafc; margin:11px 0 5px; overflow-wrap:anywhere; }
    .metric-foot { color:#71839d; font-size:10px; line-height:1.45; }
    .panel-title { color:#f8fafc; font-size:16px; font-weight:750; }
    .panel-sub { color:#94a3b8; font-size:11px; margin-top:3px; }
    .pill { display:inline-block; border:1px solid rgba(0,240,255,.25); background:rgba(0,240,255,.07); color:#00f0ff; border-radius:5px; padding:4px 8px; font:600 9px 'JetBrains Mono',monospace; letter-spacing:.5px; }
    .notice { border:1px solid rgba(245,158,11,.28); border-left:3px solid #f59e0b; border-radius:9px; padding:12px; background:rgba(245,158,11,.06); color:#b6c4d8; font-size:11px; }
    .small-muted { color:#71839d; font-size:10px; }
    .stButton > button { border-radius:9px; border:1px solid rgba(0,240,255,.25); background:rgba(0,240,255,.09); color:#00f0ff; font-weight:700; }
    .stButton > button:hover { border-color:#00f0ff; color:#fff; }
    .stDownloadButton > button { border-radius:9px; }
    [data-testid="stDataFrame"] { border:1px solid rgba(80,112,151,.25); border-radius:10px; overflow:hidden; }
    [data-testid="stSlider"] label, [data-testid="stSelectbox"] label, [data-testid="stRadio"] label, [data-testid="stDateInput"] label { color:#aab9cc !important; }
    footer { visibility:hidden; }
    @media (max-width:900px) { .main-title {font-size:25px;} .metric-value {font-size:22px;} }
    </style>
    """,
    unsafe_allow_html=True,
)


def find_default_csv():
    for path in CANDIDATE_PATHS:
        if path.exists():
            return path
    return None


def load_rainfall(uploaded_file=None):
    """Load and normalize the actual rainfall dataset, tolerating common header variants."""
    source_label = "Uploaded CSV"
    if uploaded_file is not None:
        raw = pd.read_csv(uploaded_file, skip_blank_lines=True)
    else:
        path = find_default_csv()
        if path is None:
            raise FileNotFoundError(
                "No default rainfall CSV was found. Expected one of: "
                + ", ".join(str(p.relative_to(BASE)) for p in CANDIDATE_PATHS)
            )
        raw = pd.read_csv(path, skip_blank_lines=True)
        source_label = str(path.relative_to(BASE))

    raw.columns = [str(c).strip() for c in raw.columns]
    # Match column names case-insensitively after trimming whitespace.
    by_lower = {c.lower(): c for c in raw.columns}

    def find_col(candidates):
        for candidate in candidates:
            if candidate.lower() in by_lower:
                return by_lower[candidate.lower()]
        return None

    time_col = find_col([TIME_COL, "timestamp", "datetime", "date time", "date"])
    station_col = find_col([STATION_COL, "station_name", "sensor_id", "station id"])
    rain_col = find_col([RAIN_COL, "rainfall_mm", "rainfall (mm)", "rainfall", "hourly rainfall (mm)"])
    lat_col = find_col([LAT_COL, "latitude", "lat"])
    lon_col = find_col([LON_COL, "longitude", "lon", "long"])

    missing = []
    if time_col is None:
        missing.append(TIME_COL)
    if station_col is None:
        missing.append(STATION_COL)
    if rain_col is None:
        missing.append(RAIN_COL)
    if missing:
        raise ValueError(
            "CSV is missing required columns: "
            + ", ".join(missing)
            + ". The real dataset should contain station, timestamp, and rainfall columns."
        )

    rename = {time_col: "timestamp", station_col: "station", rain_col: "rainfall_mm"}
    if lat_col:
        rename[lat_col] = "latitude"
    if lon_col:
        rename[lon_col] = "longitude"
    df = raw.rename(columns=rename).copy()

    keep = ["timestamp", "station", "rainfall_mm"]
    if "latitude" in df.columns:
        keep.append("latitude")
    if "longitude" in df.columns:
        keep.append("longitude")
    df = df[keep].copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["station"] = df["station"].astype("string").str.strip()
    df["rainfall_mm"] = pd.to_numeric(df["rainfall_mm"], errors="coerce")
    if "latitude" in df.columns:
        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    if "longitude" in df.columns:
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    df = df.dropna(subset=["timestamp", "station", "rainfall_mm"])
    df = df[(df["station"] != "") & (df["rainfall_mm"] >= 0)].copy()
    df = df.sort_values(["station", "timestamp"]).reset_index(drop=True)
    if df.empty:
        raise ValueError("The CSV was loaded, but no valid rainfall records remain.")
    df["gap_hours"] = (
        df.groupby("station")["timestamp"].diff().dt.total_seconds() / 3600
    )
    return df, source_label



OPEN_METEO_API = "https://api.open-meteo.com/v1/forecast"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_open_meteo(locations):
    """Fetch Open-Meteo model estimates for a list of station-coordinate pairs.

    `locations` is a tuple of (station, latitude, longitude) tuples. Open-Meteo
    supports comma-separated coordinate lists and does not require sign-in for
    ordinary non-commercial use. Results are estimates for grid cells near each
    coordinate, not direct observations from the CSV's rain gauges.
    """
    if not locations:
        return [], "No station coordinates are available in the historical dataset.", pd.Timestamp.now(tz="UTC").isoformat()

    import urllib.parse

    latitudes = ",".join(f"{float(item[1]):.5f}" for item in locations)
    longitudes = ",".join(f"{float(item[2]):.5f}" for item in locations)
    params = {
        "latitude": latitudes,
        "longitude": longitudes,
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m,weather_code",
        "hourly": "precipitation,rain,precipitation_probability,temperature_2m",
        "forecast_days": 2,
        "timezone": "Asia/Kolkata",
    }
    url = OPEN_METEO_API + "?" + urllib.parse.urlencode(params)
    fetched_at = pd.Timestamp.now(tz="UTC").isoformat()
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "UrbanPulse/1.0 (student rainfall monitoring prototype)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            raw_text = response.read().decode("utf-8", errors="replace")
        if status < 200 or status >= 300:
            return [], f"Open-Meteo returned HTTP {status}.", fetched_at
        payload = json.loads(raw_text)
        if isinstance(payload, dict) and payload.get("error"):
            return [], str(payload.get("reason", "Open-Meteo reported an API error.")), fetched_at
        if isinstance(payload, dict):
            payloads = [payload]
        elif isinstance(payload, list):
            payloads = payload
        else:
            return [], f"Unexpected response type: {type(payload).__name__}.", fetched_at

        rows = []
        for idx, location in enumerate(locations):
            if idx >= len(payloads) or not isinstance(payloads[idx], dict):
                rows.append({"station": location[0], "latitude": location[1], "longitude": location[2], "error": "No response object for this coordinate."})
                continue
            item = payloads[idx]
            current = item.get("current") or {}
            hourly = item.get("hourly") or {}
            times = hourly.get("time") or []
            precip = hourly.get("precipitation") or []
            rain = hourly.get("rain") or []
            probability = hourly.get("precipitation_probability") or []
            temps = hourly.get("temperature_2m") or []
            current_time = current.get("time")
            # Forecast accumulation windows are based on hourly model values after current time.
            forecast_times = pd.to_datetime(pd.Series(times), errors="coerce")
            if current_time and len(forecast_times):
                now_naive = pd.to_datetime(current_time, errors="coerce")
                future_mask = forecast_times >= now_naive
            else:
                future_mask = pd.Series([True] * len(times))
            forecast_values = pd.to_numeric(pd.Series(precip), errors="coerce")
            future_values = forecast_values[future_mask.reset_index(drop=True)] if len(forecast_values) == len(future_mask) else forecast_values
            next_6h = float(future_values.head(6).sum()) if len(future_values.head(6).dropna()) else float("nan")
            next_24h = float(future_values.head(24).sum()) if len(future_values.head(24).dropna()) else float("nan")
            hourly_rows = []
            for j, timestamp in enumerate(times):
                hourly_rows.append({
                    "station": location[0], "latitude": location[1], "longitude": location[2],
                    "forecast_time": timestamp,
                    "forecast_precipitation_mm": precip[j] if j < len(precip) else None,
                    "forecast_rain_mm": rain[j] if j < len(rain) else None,
                    "precipitation_probability_percent": probability[j] if j < len(probability) else None,
                    "forecast_temperature_c": temps[j] if j < len(temps) else None,
                })
            rows.append({
                "station": location[0], "latitude": location[1], "longitude": location[2],
                "timezone": item.get("timezone", "Asia/Kolkata"),
                "current_time": current_time,
                "temperature_c": current.get("temperature_2m"),
                "relative_humidity_percent": current.get("relative_humidity_2m"),
                "current_precipitation_mm": current.get("precipitation"),
                "current_rain_mm": current.get("rain"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "weather_code": current.get("weather_code"),
                "next_6h_precipitation_mm": next_6h,
                "next_24h_precipitation_mm": next_24h,
                "hourly_forecast": hourly_rows,
                "model_elevation_m": item.get("elevation"),
                "error": "",
            })
        return rows, "", fetched_at
    except urllib.error.HTTPError as exc:
        return [], f"Open-Meteo returned HTTP {exc.code}.", fetched_at
    except urllib.error.URLError as exc:
        return [], f"Could not connect to Open-Meteo: {exc.reason}", fetched_at
    except TimeoutError:
        return [], "Open-Meteo request timed out after 20 seconds.", fetched_at
    except json.JSONDecodeError:
        return [], "Open-Meteo response was not valid JSON.", fetched_at
    except Exception as exc:
        return [], f"Live request failed: {type(exc).__name__}: {exc}", fetched_at


def weather_screening_flag(next_6h, next_24h):
    """Explainable prototype review thresholds; not official alerts or flood prediction."""
    if pd.isna(next_6h) or pd.isna(next_24h):
        return "Insufficient forecast data"
    if next_6h >= 30 or next_24h >= 75:
        return "High forecast rainfall — verify local conditions"
    if next_6h >= 15 or next_24h >= 35:
        return "Elevated forecast rainfall — review"
    return "No threshold flag from this simple screen"


def records_frame(records):
    """Convert source records to a display frame without renaming away original fields."""
    return pd.DataFrame(records) if records else pd.DataFrame()


def find_column(frame, candidates):
    by_lower = {str(c).strip().lower(): c for c in frame.columns}
    for candidate in candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None

def metric_card(label, value, foot):
    st.markdown(
        f'<div class="panel" style="min-height:130px">'
        f'<div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-foot">{foot}</div></div>',
        unsafe_allow_html=True,
    )


with st.sidebar:
    st.markdown(
        """<div style="display:flex;align-items:center;gap:10px">
        <div style="background:linear-gradient(135deg,#00f0ff,#2563eb);color:#03101e;border-radius:12px;padding:9px 11px;font-weight:900;font-size:18px">≋</div>
        <div><div style="font-weight:800;font-size:16px">UrbanPulse</div>
        <div style="color:#00f0ff;font:700 8px 'JetBrains Mono',monospace;letter-spacing:1.4px">RESILIENT CITY AI</div></div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='color:#71839d;font:700 9px JetBrains Mono,monospace;letter-spacing:1.5px;margin-top:32px;margin-bottom:8px'>RAINFALL INTELLIGENCE</div>",
        unsafe_allow_html=True,
    )
    page = st.radio(
        "Navigation",
        ["Mission Control", "Decision Engine", "Live Open-Meteo & Alerts", "Spatial Matrix", "Telemetry Trends", "Sensor Log Matrix", "Data Quality"],
        label_visibility="collapsed",
    )
    st.markdown(
        """<div style='margin-top:24px' class='notice'><b style='color:#fbbf24'>● Dual data mode</b><br>
        Historical CSV analysis is preserved. The Live Open-Meteo page shows weather-model estimates separately from historical gauge observations. UrbanPulse is not an official flood warning service.</div>""",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='small-muted' style='margin-top:18px'>URBANPULSE · DATA EXPLORER</div>", unsafe_allow_html=True)

st.markdown(
    '<div class="eyebrow">● MUNICIPAL HYDROLOGY NETWORK</div>'
    '<div class="main-title">Rainfall Intelligence & Historical Explorer</div>'
    '<div class="sub-title">Historical rainfall analysis plus Open-Meteo model estimates at station coordinates; not direct gauge telemetry.</div>',
    unsafe_allow_html=True,
)
header_a, header_b = st.columns([1.2, 2])
with header_a:
    st.markdown(
        '<div style="padding-top:12px;color:#34d399;font-size:11px">● Historical dataset mode</div>',
        unsafe_allow_html=True,
    )
with header_b:
    uploaded = st.file_uploader(
        "Import rainfall CSV", type=["csv"], label_visibility="collapsed", key="rainfall_upload"
    )
st.markdown('<div class="rule"></div>', unsafe_allow_html=True)

try:
    df, source_label = load_rainfall(uploaded)
except Exception as exc:
    st.error(f"Could not load rainfall data: {exc}")
    st.info(
        "For your current project, place bengaluru_geo_filtered.csv in "
        "data/processed/ beside the UrbanPulse project folder, or upload it above."
    )
    st.stop()

st.caption(f"Data source: `{source_label}` · {len(df):,} valid rainfall records")

stations = sorted(df["station"].dropna().unique().tolist())
min_date = df["timestamp"].min().date()
max_date = df["timestamp"].max().date()

with st.sidebar:
    st.markdown("<div style='font-weight:700;margin-top:18px;margin-bottom:8px'>Explorer Filters</div>", unsafe_allow_html=True)
    selected_stations = st.multiselect(
        "Stations",
        stations,
        default=stations,
        help="Select one or more stations to display.",
    )
    date_range = st.date_input(
        "Observation date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    gap_threshold = st.slider(
        "Flag reporting gaps longer than (hours)", min_value=6, max_value=168, value=24, step=6
    )

if not selected_stations:
    st.warning("Select at least one station in the sidebar.")
    st.stop()

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range

start_ts = pd.Timestamp(start_date)
end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
filtered = df[
    df["station"].isin(selected_stations)
    & df["timestamp"].between(start_ts, end_ts)
].copy()

if filtered.empty:
    st.warning("No records match these station and date filters.")
    st.stop()

# Recalculate intervals after filtering only for records visible in the selected date range.
filtered = filtered.sort_values(["station", "timestamp"])
filtered["gap_hours"] = (
    filtered.groupby("station")["timestamp"].diff().dt.total_seconds() / 3600
)

latest_timestamp = filtered["timestamp"].max()
median_gap = filtered["gap_hours"].median()
gaps_over_threshold = int((filtered["gap_hours"] > gap_threshold).sum())
max_rain = filtered["rainfall_mm"].max()
mean_rain = filtered["rainfall_mm"].mean()

if page == "Mission Control":
    cols = st.columns(4)
    metrics = [
        ("VALID OBSERVATIONS", f"{len(filtered):,}", "Records after current filters"),
        ("STATIONS SELECTED", f"{filtered['station'].nunique():,}", "Stations represented in view"),
        ("MAX RECORDED RAINFALL", f"{max_rain:.2f} mm", "Highest source-record value in view"),
        ("GAPS ABOVE THRESHOLD", f"{gaps_over_threshold:,}", f"Intervals longer than {gap_threshold} hours"),
    ]
    for col, (label, value, foot) in zip(cols, metrics):
        with col:
            metric_card(label, value, foot)

    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.markdown('<div class="panel-title">Recorded Rainfall Over Time</div><div class="panel-sub">Points show actual source records; missing intervals are not filled with zero.</div>', unsafe_allow_html=True)
        chart = (
            alt.Chart(filtered)
            .mark_circle(size=48, opacity=0.72)
            .encode(
                x=alt.X("timestamp:T", title="Observation time", axis=alt.Axis(labelColor="#94a3b8", gridColor="#172335")),
                y=alt.Y("rainfall_mm:Q", title="Rainfall per source record (mm)", axis=alt.Axis(labelColor="#94a3b8", gridColor="#172335")),
                color=alt.Color("station:N", title="Station"),
                tooltip=[
                    alt.Tooltip("station:N", title="Station"),
                    alt.Tooltip("timestamp:T", title="Timestamp"),
                    alt.Tooltip("rainfall_mm:Q", title="Rainfall (mm)", format=".2f"),
                ],
            )
            .properties(height=330, background="#0d1726")
            .configure_view(strokeOpacity=0)
            .configure_axis(titleColor="#94a3b8", labelColor="#94a3b8")
            .configure_legend(labelColor="#cbd5e1", titleColor="#cbd5e1")
        )
        st.altair_chart(chart, use_container_width=True)
    with right:
        st.markdown('<div class="panel-title">Rainfall Snapshot</div><div class="panel-sub">Summary of the selected observations</div>', unsafe_allow_html=True)
        summary = filtered["rainfall_mm"].describe().rename("rainfall_mm").to_frame()
        summary.index = ["Count", "Mean", "Std. deviation", "Minimum", "25th percentile", "Median", "75th percentile", "Maximum"]
        summary["rainfall_mm"] = summary["rainfall_mm"].round(2)
        st.dataframe(summary, use_container_width=True)
        st.markdown(
            f'<div class="notice">Latest observation in the filtered view: <b>{latest_timestamp}</b>. '
            f'Median interval between visible consecutive readings: <b>{median_gap:.2f} hours</b> (where available).</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="margin:23px 0 14px"><div class="panel-title">Station Summary</div><div class="panel-sub">Readings and reporting-gap indicators for the current filters</div></div>', unsafe_allow_html=True)
    station_summary = filtered.groupby("station").agg(
        readings=("rainfall_mm", "size"),
        mean_rainfall_mm=("rainfall_mm", "mean"),
        max_rainfall_mm=("rainfall_mm", "max"),
        median_gap_hours=("gap_hours", "median"),
        gaps_over_threshold=("gap_hours", lambda x: int((x > gap_threshold).sum())),
        first_observation=("timestamp", "min"),
        last_observation=("timestamp", "max"),
    ).reset_index()
    station_summary[["mean_rainfall_mm", "max_rainfall_mm", "median_gap_hours"]] = station_summary[
        ["mean_rainfall_mm", "max_rainfall_mm", "median_gap_hours"]
    ].round(2)
    st.dataframe(station_summary, use_container_width=True, hide_index=True)

elif page == "Decision Engine":
    st.markdown('<div class="panel-title">UrbanPulse Decision Engine</div><div class="panel-sub">Historical, explainable station screening — not a live flood forecast or official warning</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class=\"notice\"><b>How to read this page:</b> UrbanPulse compares each station's latest observation on or before the selected assessment date with that station's own historical rainfall distribution. It also checks how old the observation is. Results are screening signals only; they do not prove flooding or sensor failure.</div>",
        unsafe_allow_html=True,
    )

    control_a, control_b, control_c = st.columns(3)
    with control_a:
        baseline_days = st.selectbox("Historical baseline window", [30, 60, 90, 180, 365], index=2, help="Number of days before the assessment date used to estimate station-specific rainfall percentiles.")
    with control_b:
        high_percentile = st.selectbox("Unusual rainfall threshold", [90, 95, 97.5, 99], index=1, help="Latest reading at or above this station-specific percentile is flagged as unusually high.")
    with control_c:
        freshness_hours = st.selectbox("Stale observation after", [6, 12, 24, 48, 72], index=2, help="A reporting-freshness threshold for this historical replay, not an official service-level target.")

    assessment_time = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    history = df[(df["station"].isin(selected_stations)) & (df["timestamp"] <= assessment_time)].copy()
    if history.empty:
        st.warning("No observations exist on or before the selected assessment date.")
    else:
        baseline_start = assessment_time - pd.Timedelta(days=int(baseline_days))
        rows = []
        for station_name in selected_stations:
            station_all = history[history["station"] == station_name].sort_values("timestamp")
            if station_all.empty:
                rows.append({
                    "Station": station_name, "Latest observation": pd.NaT,
                    "Latest rainfall (mm per source record)": float("nan"),
                    "Historical baseline readings": 0, "P90 threshold (mm)": float("nan"),
                    f"P{high_percentile:g} threshold (mm)": float("nan"),
                    "Rainfall signal": "Insufficient evidence", "Observation age (hours)": float("nan"),
                    "Data freshness": "No observation by assessment date", "Confidence": "Low",
                    "Recommended next check": "Check station data availability and telemetry history",
                })
                continue
            latest = station_all.iloc[-1]
            prior_records = station_all[station_all["timestamp"] < latest["timestamp"]]
            baseline = prior_records[prior_records["timestamp"] >= baseline_start]["rainfall_mm"]
            # Exclude the latest observation from its own baseline to avoid self-influencing the threshold.
            if len(baseline) < 10:
                baseline = prior_records["rainfall_mm"]
            q90 = float(baseline.quantile(0.90)) if len(baseline) else float("nan")
            qhigh = float(baseline.quantile(float(high_percentile) / 100.0)) if len(baseline) else float("nan")
            latest_rain = float(latest["rainfall_mm"])
            age_hours = max(0.0, (assessment_time - latest["timestamp"]).total_seconds() / 3600.0)
            if len(baseline) < 10 or pd.isna(qhigh):
                signal = "Insufficient baseline"
            elif latest_rain >= qhigh:
                signal = f"Unusually high (≥P{high_percentile:g})"
            elif latest_rain >= q90:
                signal = "Elevated (≥P90)"
            else:
                signal = "No percentile anomaly"

            if age_hours <= 6:
                freshness = "Recent (≤6h)"
            elif age_hours <= freshness_hours:
                freshness = "Aging"
            else:
                freshness = "Stale for selected threshold"

            if len(baseline) >= 30 and age_hours <= freshness_hours:
                confidence = "Higher data support"
            elif len(baseline) >= 10:
                confidence = "Moderate data support" if age_hours <= freshness_hours else "Reduced — stale data"
            else:
                confidence = "Low — limited baseline"

            if age_hours > freshness_hours:
                action = "Verify reporting continuity before interpreting conditions"
            elif signal.startswith("Unusually high"):
                action = "Verify the reading and check local rainfall / drainage conditions"
            elif signal == "Elevated (≥P90)":
                action = "Review nearby stations and continue observation"
            elif signal == "Insufficient baseline":
                action = "Collect more valid observations before classifying this station"
            else:
                action = "Continue routine monitoring; no station-specific anomaly detected"

            rows.append({
                "Station": station_name,
                "Latest observation": latest["timestamp"],
                "Latest rainfall (mm per source record)": latest_rain,
                "Historical baseline readings": int(len(baseline)),
                "P90 threshold (mm)": q90,
                f"P{high_percentile:g} threshold (mm)": qhigh,
                "Rainfall signal": signal,
                "Observation age (hours)": age_hours,
                "Data freshness": freshness,
                "Confidence": confidence,
                "Recommended next check": action,
            })

        decision_df = pd.DataFrame(rows)
        # Sort by high rainfall signal first, then stale-data concerns, then observation magnitude.
        decision_df["_priority"] = decision_df["Rainfall signal"].map({
            f"Unusually high (≥P{high_percentile:g})": 0,
            "Elevated (≥P90)": 1,
            "Insufficient baseline": 2,
            "No percentile anomaly": 3,
            "Insufficient evidence": 4,
        }).fillna(5)
        decision_df = decision_df.sort_values(["_priority", "Observation age (hours)"], ascending=[True, False], na_position="last")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            metric_card("STATIONS ASSESSED", f"{len(decision_df):,}", "Selected stations with a result row")
        with c2:
            unusual_count = int(decision_df["Rainfall signal"].astype(str).str.startswith("Unusually high").sum())
            metric_card("UNUSUAL LATEST READINGS", f"{unusual_count:,}", f"At or above station P{high_percentile:g}")
        with c3:
            stale_count = int(decision_df["Data freshness"].astype(str).str.startswith("Stale").sum())
            metric_card("STALE OBSERVATIONS", f"{stale_count:,}", f"Older than {freshness_hours} hours at assessment time")
        with c4:
            insufficient_count = int(decision_df["Rainfall signal"].astype(str).str.contains("Insufficient").sum())
            metric_card("LIMITED EVIDENCE", f"{insufficient_count:,}", "Stations needing more data or baseline")

        st.markdown(f"**Assessment as of:** {assessment_time}  ·  **Baseline:** {baseline_days} days before assessment where available")
        display_cols = [
            "Station", "Latest observation", "Latest rainfall (mm per source record)",
            "Historical baseline readings", "P90 threshold (mm)", f"P{high_percentile:g} threshold (mm)",
            "Rainfall signal", "Observation age (hours)", "Data freshness", "Confidence", "Recommended next check",
        ]
        display_df = decision_df[display_cols].copy()
        for col in ["Latest rainfall (mm per source record)", "P90 threshold (mm)", f"P{high_percentile:g} threshold (mm)", "Observation age (hours)"]:
            display_df[col] = pd.to_numeric(display_df[col], errors="coerce").round(2)
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        report = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download decision report (CSV)",
            data=report,
            file_name=f"urbanpulse_decision_report_{end_date}.csv",
            mime="text/csv",
        )
        st.markdown("**Why this is different:** the signal is station-specific, every flag has a numeric threshold, and data freshness is shown separately so a stale reading is not mistaken for a current condition.")
        st.caption("Percentile flags describe a reading relative to the station's available historical values. They are not calibrated flood-risk levels. The source field is labelled hourly rainfall, but observation intervals may be irregular; values are therefore described as rainfall per source record. The assessment date is historical replay time, not the current time.")

elif page == "Live Open-Meteo & Alerts":
    st.markdown('<div class="panel-title">Live Open-Meteo & Rainfall Screening</div><div class="panel-sub">Weather-model estimates for your station coordinates · refreshes every 5 minutes</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="notice"><b>Source distinction:</b> Open-Meteo returns weather-model estimates for grid cells near the coordinates in your historical CSV. These are not measurements from your named rain gauges. Current conditions and hourly forecasts are displayed separately from historical sensor records. Threshold flags are prototype screening prompts, not official warnings or validated flood predictions.</div>',
        unsafe_allow_html=True,
    )
    refresh_col, status_col = st.columns([1, 2])
    with refresh_col:
        if st.button("↻ Refresh weather data now", key="refresh_open_meteo"):
            fetch_open_meteo.clear()
            st.rerun()
    auto_refresh_available = st_autorefresh is not None
    if auto_refresh_available:
        st_autorefresh(interval=300_000, limit=None, key="urbanpulse_open_meteo_auto_refresh")
    with status_col:
        if auto_refresh_available:
            st.caption("Auto-refresh: every 5 minutes · API responses cached for 5 minutes")
        else:
            st.caption("API cache: 5 minutes · Manual refresh available. Install streamlit-autorefresh for automatic page refresh.")

    if not {"latitude", "longitude"}.issubset(df.columns):
        st.error("Your historical CSV does not contain latitude and longitude columns. Open-Meteo requires coordinates; the historical pages will still work.")
    else:
        station_locations = (
            df[df["station"].isin(selected_stations)]
            .dropna(subset=["latitude", "longitude"])
            .sort_values("timestamp")
            .groupby("station", as_index=False)
            .agg(latitude=("latitude", "first"), longitude=("longitude", "first"))
        )
        station_locations = station_locations[
            station_locations["latitude"].between(-90, 90) & station_locations["longitude"].between(-180, 180)
        ]
        locations = tuple((str(row.station), float(row.latitude), float(row.longitude)) for row in station_locations.itertuples(index=False))
        if not locations:
            st.warning("No valid station coordinates are available for the selected stations.")
        else:
            with st.spinner(f"Fetching Open-Meteo estimates for {len(locations)} selected station coordinates…"):
                live_rows, live_error, fetched_at = fetch_open_meteo(locations)
            valid_rows = [r for r in live_rows if not r.get("error")]
            failed_rows = [r for r in live_rows if r.get("error")]
            live_df = pd.DataFrame([{k: v for k, v in row.items() if k != "hourly_forecast"} for row in valid_rows])
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                metric_card("COORDINATES REQUESTED", f"{len(locations):,}", "From selected historical stations")
            with m2:
                metric_card("LOCATIONS WITH DATA", f"{len(valid_rows):,}", "Open-Meteo response objects received")
            with m3:
                high_flags = sum(weather_screening_flag(r.get("next_6h_precipitation_mm", float("nan")), r.get("next_24h_precipitation_mm", float("nan"))).startswith(("High", "Elevated")) for r in valid_rows)
                metric_card("FORECAST REVIEW FLAGS", f"{high_flags:,}", "Prototype thresholds; not official warnings")
            with m4:
                metric_card("REFRESH INTERVAL", "5 min", "Model data may update less frequently")
            st.caption(f"Fetch time (UTC): {fetched_at}. Forecast/current timestamps are provided by Open-Meteo in Asia/Kolkata time. Refreshing the dashboard does not mean the underlying weather model updates every five minutes.")

            if live_error:
                st.error(live_error)
            if failed_rows:
                st.warning(f"{len(failed_rows)} coordinate(s) did not return a usable forecast object.")
                st.dataframe(pd.DataFrame(failed_rows).drop(columns=["hourly_forecast"], errors="ignore"), use_container_width=True, hide_index=True)

            if not live_df.empty:
                st.success(f"Open-Meteo API connected successfully · {len(valid_rows)} of {len(locations)} selected coordinates returned data.")
                st.markdown(
                    "<div class='panel-title'>Live forecast map</div><div class='panel-sub'>Markers are weather-model estimates at the coordinates in your CSV, not readings from the physical gauges.</div>",
                    unsafe_allow_html=True,
                )
                map_df = pd.DataFrame(valid_rows).copy()
                for numeric in ["latitude", "longitude", "next_6h_precipitation_mm", "next_24h_precipitation_mm"]:
                    if numeric in map_df.columns:
                        map_df[numeric] = pd.to_numeric(map_df[numeric], errors="coerce")
                map_df = map_df.dropna(subset=["latitude", "longitude"])
                map_df["next_6h_precipitation_mm"] = map_df["next_6h_precipitation_mm"].fillna(0)
                def forecast_marker_color(value):
                    if value >= 30:
                        return [255, 76, 76, 230]
                    if value >= 15:
                        return [255, 173, 51, 225]
                    if value > 0:
                        return [255, 220, 70, 215]
                    return [0, 220, 235, 205]
                map_df["marker_color"] = map_df["next_6h_precipitation_mm"].apply(forecast_marker_color)
                map_df["marker_radius"] = map_df["next_6h_precipitation_mm"].apply(lambda v: 260 if v >= 30 else 210 if v >= 15 else 160 if v > 0 else 120)
                if not map_df.empty:
                    center_lat = float((map_df["latitude"].min() + map_df["latitude"].max()) / 2)
                    center_lon = float((map_df["longitude"].min() + map_df["longitude"].max()) / 2)
                    span = max(float(map_df["latitude"].max() - map_df["latitude"].min()), float(map_df["longitude"].max() - map_df["longitude"].min()), 0.05)
                    zoom = max(7.0, min(11.0, 8.5 - math.log2(span / 0.5)))
                    forecast_layer = pdk.Layer(
                        "ScatterplotLayer", data=map_df, get_position="[longitude, latitude]",
                        get_fill_color="marker_color", get_line_color=[235, 245, 255, 230],
                        get_radius="marker_radius", radius_min_pixels=5, radius_max_pixels=18,
                        stroked=True, line_width_min_pixels=1, pickable=True, auto_highlight=True,
                    )
                    forecast_deck = pdk.Deck(
                        layers=[forecast_layer],
                        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0),
                        tooltip={"html": "<b>{station}</b><br/>Forecast precipitation next 6h: {next_6h_precipitation_mm} mm<br/>Forecast precipitation next 24h: {next_24h_precipitation_mm} mm", "style": {"backgroundColor": "#0d1726", "color": "white", "border": "1px solid #00ddeb", "borderRadius": "8px"}},
                        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
                    )
                    st.pydeck_chart(forecast_deck, use_container_width=True, height=430)
                    st.caption("Map colors: cyan = no forecast precipitation; yellow = some precipitation; orange = elevated prototype screening; red = high prototype screening. Thresholds are review prompts, not official warnings.")
                live_df["UrbanPulse screening flag"] = live_df.apply(
                    lambda r: weather_screening_flag(r.get("next_6h_precipitation_mm"), r.get("next_24h_precipitation_mm")), axis=1
                )
                live_df = live_df.rename(columns={
                    "station": "Historical station label (coordinate lookup)",
                    "latitude": "Latitude", "longitude": "Longitude",
                    "current_time": "Open-Meteo current timestamp (local)",
                    "temperature_c": "Temperature (°C)",
                    "relative_humidity_percent": "Relative humidity (%)",
                    "current_precipitation_mm": "Current precipitation (mm/model interval)",
                    "current_rain_mm": "Current rain (mm/model interval)",
                    "wind_speed_kmh": "Wind speed (km/h)",
                    "next_6h_precipitation_mm": "Forecast precipitation next 6h (mm)",
                    "next_24h_precipitation_mm": "Forecast precipitation next 24h (mm)",
                    "model_elevation_m": "Model elevation (m)",
                })
                display_cols = [c for c in [
                    "Historical station label (coordinate lookup)", "Latitude", "Longitude",
                    "Open-Meteo current timestamp (local)", "Temperature (°C)", "Relative humidity (%)",
                    "Current precipitation (mm/model interval)", "Current rain (mm/model interval)",
                    "Wind speed (km/h)", "Forecast precipitation next 6h (mm)",
                    "Forecast precipitation next 24h (mm)", "UrbanPulse screening flag", "Model elevation (m)",
                ] if c in live_df.columns]
                numeric_cols = [c for c in display_cols if c in live_df.columns and c not in ["Historical station label (coordinate lookup)", "Open-Meteo current timestamp (local)", "UrbanPulse screening flag"]]
                for col in numeric_cols:
                    live_df[col] = pd.to_numeric(live_df[col], errors="coerce").round(2)
                sorted_live = live_df.sort_values("Forecast precipitation next 6h (mm)", ascending=False, na_position="last") if "Forecast precipitation next 6h (mm)" in live_df.columns else live_df
                st.markdown('<div style="margin:22px 0 10px"><div class="panel-title">Current conditions and forecast review</div><div class="panel-sub">One model-grid estimate per selected station coordinate</div></div>', unsafe_allow_html=True)
                st.dataframe(sorted_live[display_cols], use_container_width=True, hide_index=True)
                st.download_button(
                    "Download live estimates and screening flags (CSV)",
                    data=sorted_live[display_cols].to_csv(index=False).encode("utf-8"),
                    file_name=f"urbanpulse_open_meteo_{pd.Timestamp.now().date()}.csv",
                    mime="text/csv",
                )

                forecast_frames = []
                for row in valid_rows:
                    hourly_rows = row.get("hourly_forecast", [])
                    if hourly_rows:
                        hourly_df = pd.DataFrame(hourly_rows)
                        hourly_df["forecast_time"] = pd.to_datetime(hourly_df["forecast_time"], errors="coerce")
                        hourly_frames = hourly_df[hourly_df["forecast_time"] >= pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)]
                        if not hourly_frames.empty:
                            forecast_frames.append(hourly_frames.head(24))
                if forecast_frames:
                    forecast_all = pd.concat(forecast_frames, ignore_index=True)
                    st.markdown('<div style="margin:22px 0 10px"><div class="panel-title">Hourly precipitation forecast</div><div class="panel-sub">Forecast values are model estimates in millimetres per hour</div></div>', unsafe_allow_html=True)
                    forecast_chart = alt.Chart(forecast_all).mark_line(point=True).encode(
                        x=alt.X("forecast_time:T", title="Forecast time (Asia/Kolkata)"),
                        y=alt.Y("forecast_precipitation_mm:Q", title="Forecast precipitation (mm/hour)"),
                        color=alt.Color("station:N", title="Coordinate label"),
                        tooltip=["station:N", alt.Tooltip("forecast_time:T", title="Time"), alt.Tooltip("forecast_precipitation_mm:Q", title="Precipitation (mm)", format=".2f"), alt.Tooltip("precipitation_probability_percent:Q", title="Precipitation probability (%)")],
                    ).properties(height=360, background="#0d1726").configure_view(strokeOpacity=0).configure_axis(titleColor="#94a3b8", labelColor="#94a3b8", gridColor="#172335").configure_legend(labelColor="#cbd5e1", titleColor="#cbd5e1")
                    st.altair_chart(forecast_chart, use_container_width=True)
                st.caption("Screening thresholds used by this prototype: elevated if forecast precipitation is ≥15 mm over 6 hours or ≥35 mm over 24 hours; high if ≥30 mm over 6 hours or ≥75 mm over 24 hours. These are review prompts chosen for the prototype, not official IMD thresholds, a calibrated flood model, or a guarantee of local impacts.")
            else:
                st.warning(live_error or "Open-Meteo returned no usable location data. Historical pages remain available; check your internet connection and coordinate columns.")

    st.markdown('<div style="margin:22px 0 10px"><div class="panel-title">Data source and limitations</div></div>', unsafe_allow_html=True)
    st.write("Open-Meteo provides weather-model data at requested coordinates. Station names shown here are labels inherited from your CSV; they do not mean Open-Meteo is reading those physical gauges. Model output can be spatially smoothed and may differ from local sensor observations.")
    st.markdown("Source: [Open-Meteo API documentation](https://open-meteo.com/en/docs) · [Open-Meteo service](https://open-meteo.com/)")
    st.caption("The live panel needs internet access but no account, sign-in, API token, or extra authentication. Open-Meteo data attribution is required under CC BY 4.0. This is a monitoring prototype, not an official flood warning service.")

elif page == "Spatial Matrix":
    st.markdown('<div class="panel-title">Spatial Matrix</div><div class="panel-sub">Station positions from coordinates included in the source dataset</div>', unsafe_allow_html=True)
    if not {"latitude", "longitude"}.issubset(filtered.columns):
        st.warning("The loaded CSV does not contain latitude and longitude columns, so a station map cannot be drawn.")
    else:
        loc = filtered.dropna(subset=["latitude", "longitude"]).groupby("station").agg(
            latitude=("latitude", "first"),
            longitude=("longitude", "first"),
            readings=("rainfall_mm", "size"),
            mean_rainfall_mm=("rainfall_mm", "mean"),
            max_rainfall_mm=("rainfall_mm", "max"),
        ).reset_index()
        if loc.empty:
            st.warning("No usable station coordinates are available in the filtered records.")
        else:
            # Validate coordinates before plotting; keep flagged records visible in the audit table.
            loc["coordinate_valid"] = (
                loc["latitude"].between(12, 14)
                & loc["longitude"].between(77, 78)
            )
            loc["max_rainfall_mm"] = pd.to_numeric(
                loc["max_rainfall_mm"], errors="coerce"
            ).fillna(0)

            # Color markers by maximum observed rainfall in the currently filtered records.
            # These colors describe historical observations, not live flood risk.
            def rainfall_color(value):
                if value >= 75:
                    return [255, 76, 76, 220]
                if value >= 50:
                    return [255, 153, 51, 220]
                if value >= 25:
                    return [255, 210, 70, 220]
                return [0, 220, 235, 210]

            loc["marker_color"] = loc["max_rainfall_mm"].apply(rainfall_color)
            loc["marker_radius"] = loc["max_rainfall_mm"].apply(
                lambda value: 240 if value >= 75 else 200 if value >= 50 else 165 if value >= 25 else 135
            )

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=loc,
                get_position="[longitude, latitude]",
                get_fill_color="marker_color",
                get_line_color=[235, 245, 255, 230],
                get_radius="marker_radius",
                radius_min_pixels=5,
                radius_max_pixels=18,
                stroked=True,
                line_width_min_pixels=1,
                pickable=True,
                auto_highlight=True,
            )

            # Frame the map around the station spread instead of relying on one fixed center.
            center_lat = float((loc["latitude"].min() + loc["latitude"].max()) / 2)
            center_lon = float((loc["longitude"].min() + loc["longitude"].max()) / 2)
            span = max(
                float(loc["latitude"].max() - loc["latitude"].min()),
                float(loc["longitude"].max() - loc["longitude"].min()),
                0.05,
            )
            zoom = max(7.0, min(10.0, 8.5 - math.log2(span / 0.5)))

            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=pdk.ViewState(
                    latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0
                ),
                tooltip={
                    "html": (
                        "<b>{station}</b><br/>"
                        "Readings: {readings}<br/>"
                        "Mean rainfall: {mean_rainfall_mm} mm<br/>"
                        "Max recorded rainfall: {max_rainfall_mm} mm<br/>"
                        "Coordinate range check: {coordinate_valid}"
                    ),
                    "style": {
                        "backgroundColor": "#0d1726",
                        "color": "white",
                        "border": "1px solid #00ddeb",
                        "borderRadius": "8px",
                    },
                },
                map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
            )
            st.pydeck_chart(deck, use_container_width=True, height=550)

            st.markdown(
                "<div style='display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 12px;'>"
                "<span>🔹 <b>Under 25 mm</b></span>"
                "<span>🟡 <b>25–49.99 mm</b></span>"
                "<span>🟠 <b>50–74.99 mm</b></span>"
                "<span>🔴 <b>75 mm or more</b></span>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.caption(
                "Marker color and size represent maximum recorded rainfall in the current filters; "
                "they are historical summaries, not live alerts. Coordinate checks use broad regional bounds."
            )
            st.dataframe(
                loc[["station", "latitude", "longitude", "coordinate_valid", "readings",
                    "mean_rainfall_mm", "max_rainfall_mm"]].round(4),
                use_container_width=True,
                hide_index=True,
            )
    st.caption("Map points use source coordinates. A geographic filter is not the same as an official city boundary.")

elif page == "Telemetry Trends":
    st.markdown('<div class="panel-title">Telemetry Trends</div><div class="panel-sub">Explore rainfall over time without inventing values for missing periods.</div>', unsafe_allow_html=True)
    chart_style = st.radio("View", ["Recorded observations", "Daily mean (observed days only)"], horizontal=True)
    if chart_style == "Daily mean (observed days only)":
        plot_df = filtered.copy()
        plot_df["date"] = plot_df["timestamp"].dt.floor("D")
        plot_df = plot_df.groupby(["date", "station"], as_index=False)["rainfall_mm"].mean()
        x_col = "date"
        y_title = "Mean recorded rainfall (mm per source record)"
    else:
        plot_df = filtered
        x_col = "timestamp"
        y_title = "Rainfall per source record (mm)"
    trend = alt.Chart(plot_df).mark_line(point=alt.OverlayMarkDef(size=35), strokeWidth=2).encode(
        x=alt.X(f"{x_col}:T", title="Date/time"),
        y=alt.Y("rainfall_mm:Q", title=y_title),
        color=alt.Color("station:N", title="Station"),
        tooltip=["station:N", alt.Tooltip(f"{x_col}:T", title="Time"), alt.Tooltip("rainfall_mm:Q", format=".2f")],
    ).properties(height=430, background="#0d1726").configure_view(strokeOpacity=0).configure_axis(
        titleColor="#94a3b8", labelColor="#94a3b8", gridColor="#172335"
    ).configure_legend(labelColor="#cbd5e1", titleColor="#cbd5e1")
    st.altair_chart(trend, use_container_width=True)
    st.caption("Daily means summarize available readings only; they are not complete daily rainfall totals.")

elif page == "Sensor Log Matrix":
    st.markdown('<div class="panel-title">Sensor Log Matrix</div><div class="panel-sub">Filtered source records with calculated reporting intervals</div>', unsafe_allow_html=True)
    table = filtered.copy()
    table["gap_hours"] = table["gap_hours"].round(2)
    table = table.rename(columns={
        "timestamp": "OBSERVATION TIME",
        "station": "STATION",
        "rainfall_mm": "RAINFALL (mm per source record)",
        "latitude": "LATITUDE",
        "longitude": "LONGITUDE",
        "gap_hours": "GAP SINCE PREVIOUS READING (hours)",
    })
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.download_button(
        "Download filtered rainfall CSV",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name="urbanpulse_filtered_rainfall.csv",
        mime="text/csv",
    )

else:
    st.markdown('<div class="panel-title">Data Quality</div><div class="panel-sub">Checks calculated from the selected station and date filters</div>', unsafe_allow_html=True)
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        metric_card("MISSING REQUIRED VALUES", "0", "Rows with invalid timestamp/station/rainfall are removed during loading")
    with q2:
        metric_card("ZERO RAINFALL READINGS", f"{int((filtered['rainfall_mm'] == 0).sum()):,}", "Measured zero values in this filtered dataset")
    with q3:
        metric_card("NEGATIVE VALUES", f"{int((filtered['rainfall_mm'] < 0).sum()):,}", "Negative values are excluded during loading")
    with q4:
        metric_card("GAPS OVER THRESHOLD", f"{gaps_over_threshold:,}", f"Visible consecutive-reading intervals over {gap_threshold} hours")
    gap_df = filtered[filtered["gap_hours"] > gap_threshold].copy()
    st.markdown('<div style="margin:23px 0 14px"><div class="panel-title">Long Reporting Gaps</div><div class="panel-sub">Intervals between consecutive visible observations</div></div>', unsafe_allow_html=True)
    if gap_df.empty:
        st.success("No reporting gaps exceed the selected threshold in this filtered view.")
    else:
        gap_df = gap_df[["station", "timestamp", "gap_hours"]].rename(columns={
            "station": "STATION",
            "timestamp": "LATER OBSERVATION TIME",
            "gap_hours": "GAP (hours)",
        })
        gap_df["GAP (hours)"] = gap_df["GAP (hours)"].round(2)
        st.dataframe(gap_df.sort_values("GAP (hours)", ascending=False), use_container_width=True, hide_index=True)
    st.markdown(
        '<div class="notice"><b>Interpretation:</b> a reporting gap means there is no observation in that interval. '
        'It does not mean rainfall was zero. These checks do not establish sensor uptime, measurement accuracy, '
        'or flood risk.</div>',
        unsafe_allow_html=True,
    )

st.markdown(
    '<div style="text-align:center;color:#52627a;font-size:9px;letter-spacing:1px;margin-top:30px">'
    'URBANPULSE RAINFALL INTELLIGENCE · HISTORICAL ANALYSIS + OPEN-METEO MODEL ESTIMATES · NOT A FLOOD WARNING SERVICE</div>',
    unsafe_allow_html=True,
)
