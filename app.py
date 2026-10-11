"""F1 Analytics: one app, many modes. Run with `streamlit run app.py`."""
import streamlit as st

from f1app.modes import all_time, lap_times, next_race, points_race, standings

st.set_page_config(page_title="F1 Analytics", page_icon="🏎️", layout="wide")

# Each mode is (label, render function or None while it is still being built).
MODES = {
    "1. Next race": next_race.render,
    "2. Standings": standings.render,
    "3. Points race": points_race.render,
    "4. All-time stats": all_time.render,
    "5. Race lap times": lap_times.render,
    "6. Qualifying head-to-head": None,
    "7. Tyre strategy": None,
    "8. Season dashboard": None,
    "Player comparison (Poisson & regression)": None,
}

st.sidebar.title("🏎️ F1 Analytics")
mode = st.sidebar.radio("Mode", list(MODES))
st.sidebar.caption("Data: jolpica-f1 and FastF1. Unofficial, not affiliated with Formula 1.")

render = MODES[mode]
if render:
    render()
else:
    st.header(mode)
    st.info("Coming soon. This mode hasn't been built yet.")
