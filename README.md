# UrbanPulse — Smart Rainfall Monitoring

UrbanPulse is a Python-based dashboard for exploring rainfall patterns across the Bengaluru region using station observations and interactive visualizations.

## 🎯 Problem Statement
Rainfall data from many monitoring stations is hard to interpret and compare. UrbanPulse puts it in one place so it is easier to understand.

## 💡 Our Solution
UrbanPulse turns rainfall observations into visual summaries so users can explore patterns across stations and time.

## ✨ Features
- 📊 **Overview:** key numbers, a plain-English summary and a rainfall chart
- 🎯 **Station Screening:** flags unusually heavy latest readings and stale stations
- 🌦️ **Live Forecast:** Open-Meteo model estimates at station coordinates
- 🗺️ **Station Map:** station locations coloured by maximum rainfall
- 📈 **Rainfall Trends:** rainfall over time, per station
- 🧾 **Raw Records:** sortable table with CSV download
- 🩺 **Data Health:** completeness checks with OK / Warning / Issue badges
- 🌙 Dark, responsive interface with filters and a one-click "Reset filters"

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

The dataset is not included in this repository. Obtain it from its original source, subject to its terms of use, and either place it at `data/processed/bengaluru_geo_filtered.csv` or upload it from the dashboard sidebar.

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
- Add more verified rainfall monitoring stations
- Improve rainfall comparisons across locations
- Evaluate potential alerts against reliable reference data

## 👨‍💻 Author
Atharv Kulshrestha · [AtharvKulshrestha-code](https://github.com/AtharvKulshrestha-code)
