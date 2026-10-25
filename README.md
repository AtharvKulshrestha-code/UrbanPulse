# UrbanPulse — Smart Rainfall Monitoring

UrbanPulse is a Python-based dashboard for exploring rainfall patterns across the Bengaluru region using station observations and interactive visualizations.

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

## 📄 Data format
The dataset is **not** included in this repository. Obtain it from its original source, subject to its terms of use. Then either:
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

Commas, semicolons, tabs and pipes are all accepted, and day-first, month-first and year-first dates are detected automatically. The sidebar box "How your file was read" shows which columns were used.

**Not supported yet:** wide monthly files (one row per year, with a column for each month such as `JAN`, `FEB`, …), for example `Rainfall_Data_LL.csv`.

## 🚀 How to Run
1. Clone the repository
   ```
   git clone https://github.com/AtharvKulshrestha-code/UrbanPulse.git
   cd UrbanPulse
   ```
2. Install dependencies
   ```
   pip install -r urbanpulse_requirements.txt
   pip install --upgrade streamlit
   ```
3. Run the dashboard
   ```
   python -m streamlit run dashboard.py
   ```

The live forecast needs internet access. The historical pages work offline.

## 👥 Potential Users
Students, researchers, communities and planners who want to explore local rainfall data.

> UrbanPulse is an informational tool. It does not replace official weather warnings or emergency guidance.

## 🔮 Future Improvements
- Support wide monthly rainfall files
- Add more verified rainfall monitoring stations
- Improve rainfall comparisons across locations
- Evaluate potential alerts against reliable reference data

## 👨‍💻 Author
Atharv Kulshrestha · [AtharvKulshrestha-code](https://github.com/AtharvKulshrestha-code)
