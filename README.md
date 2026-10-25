# UrbanPulse — Smart Rainfall Monitoring

UrbanPulse is a Python-based dashboard for exploring rainfall patterns using station observations and interactive visualizations. It was built around Bengaluru and Karnataka rainfall data, and it also works with other station-based rainfall CSVs.

## 🎯 Problem Statement
Rainfall data from many monitoring stations is hard to interpret and compare. UrbanPulse puts it in one place so it is easier to understand.

## 💡 Our Solution
UrbanPulse turns rainfall observations into visual summaries so users can explore patterns across stations and time.

## ✨ Features
- 📊 **Overview:** key numbers, a plain-English summary and a rainfall chart
- 🎯 **Station Screening:** flags unusually heavy latest readings and stale stations
- 🌦️ **Live Forecast:** Open-Meteo model estimates for up to 40 chosen stations
- 🗺️ **Station Map:** station locations coloured by maximum rainfall
- 📈 **Rainfall Trends:** rainfall over time, per station
- 🧾 **Raw Records:** sortable table with CSV download
- 🩺 **Data Health:** completeness checks with OK / Warning / Issue badges
- 📂 **Flexible CSV loading:** detects columns, separators and date formats automatically

## 🛠️ Technologies Used
Python, Streamlit (1.39 or newer), Pandas, Altair, PyDeck

## 📁 Project Structure
```
UrbanPulse/
├── dashboard.py
├── urbanpulse_requirements.txt
├── .streamlit/config.toml    (optional dark theme)
└── README.md
```

## 📄 Data Format
The dataset is **not** included in this repository. Obtain it from the [National Water Data Portal](https://nwdp.nwic.gov.in/en/dataset/rainfall-telemetry-hourly-karnataka-department) (dataset: *Rainfall (Telemetry - Hourly), Karnataka Department*), subject to its terms of use. Then either:
- place it at `data/processed/bengaluru_geo_filtered.csv`, or
- upload it from the dashboard sidebar.

**Tested file:** `rainfall_tel_hr_karnataka_ka_2021_2025.csv` (Karnataka telemetry rainfall, one row per station reading, about 683,000 rows, 686 stations, 8 Aug 2021 – 31 Dec 2025). Its exact columns are:

```
SlNo, Station, Agency, State LGD Code, State, District LGD Code, District, Tehsil, Block,
Village, River, Basin, Tributary, Subtributary, SubSubtributary, Local River,
Latitude, Longitude, Data Acquisition Time, Telemetry Hourly Rainfall (mm)
```

Dates look like `04-08-2023 17:00` (day-month-year).

**Other CSVs work too** if they have one row per reading and contain:

| Needed | Examples of accepted headers |
|---|---|
| Station name | `Station`, `site_name`, `station id`, `sensor` |
| Date and time | `Data Acquisition Time`, `timestamp`, `obs_time`, `date` |
| Rainfall (mm) | `Telemetry Hourly Rainfall (mm)`, `rainfall_mm`, `precip_mm` |
| Latitude / Longitude (optional, needed for the map and live forecast) | `Latitude`, `lat`, `Longitude`, `lon` |

Commas, semicolons, tabs and pipes are all accepted, and day-first, month-first and year-first dates are detected automatically. The sidebar box **"How your file was read"** shows which columns were used and how many rows were kept.

**Not supported yet:** wide monthly files (one row per year with a column for each month such as `JAN`, `FEB`, …).

## 🚀 How to Run

**First time:**
```
git clone https://github.com/AtharvKulshrestha-code/UrbanPulse.git
cd UrbanPulse
pip install -r urbanpulse_requirements.txt
pip install --upgrade streamlit
python -m streamlit run dashboard.py
```

**Next times:** don't clone again. Open the folder you already have and run:
```
cd UrbanPulse
git pull
python -m streamlit run dashboard.py
```

No Git? On GitHub choose **Code → Download ZIP**, unzip it, open a terminal in the unzipped folder and run the last two commands of the first-time steps.

Then open the address Streamlit prints (usually http://localhost:8501). The live forecast needs internet access. The historical pages work offline.

### Troubleshooting
- **You see an old version of the dashboard:** an old Streamlit process is still running. Close all terminals running Streamlit, or start on another port: `python -m streamlit run dashboard.py --server.port 8600`.
- **Menu icons or the dark theme look wrong:** make sure Streamlit is 1.39 or newer (`pip install --upgrade streamlit`).
- **Live Forecast is slow:** pick fewer stations. The page fetches each chosen station from Open-Meteo.

## 👥 Potential Users
- Students exploring rainfall data
- Researchers studying historical rainfall patterns
- Communities interested in local rainfall information
- Planners investigating environmental data

> UrbanPulse is an informational tool. It does not replace official weather warnings or emergency guidance.

## 🔮 Future Improvements
- Support wide monthly rainfall files
- Add more verified rainfall monitoring stations
- Improve rainfall comparisons across locations
- Evaluate potential alerts against reliable reference data

## 🙏 Credits
- Rainfall data: "Rainfall (Telemetry - Hourly), Karnataka Department", [National Water Data Portal (NWDP)](https://nwdp.nwic.gov.in/en/dataset/rainfall-telemetry-hourly-karnataka-department). Check the dataset page for its licence and terms of use.
- Weather forecasts: [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0; free for non-commercial use)
- Map: © [CARTO](https://carto.com/attributions), © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- Icons adapted from [Lucide](https://lucide.dev) (ISC licence)
- Fonts: Plus Jakarta Sans and JetBrains Mono (SIL Open Font License)

## 👨‍💻 Author
Atharv Kulshrestha · [AtharvKulshrestha-code](https://github.com/AtharvKulshrestha-code)
