# F1 Analytics Stats

A Streamlit app with one mode per F1 project idea, built one mode at a time.

| Mode | Data | Status |
|---|---|---|
| 1. Next race | jolpica-f1 | ✅ |
| 2. Standings | jolpica-f1 | ✅ |
| 3. Points race | jolpica-f1 | ✅ |
| 4. All-time stats | jolpica-f1 | ✅ |
| 5. Race lap times | FastF1 | ✅ |
| 6. Qualifying head-to-head | FastF1 | ✅ |
| 7. Tyre strategy | FastF1 | ✅ |
| 8. Season dashboard | both | ✅ |
| Player comparison (Poisson & regression) | both | planned |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

FastF1 keeps downloaded timing data in `fastf1_cache/`, so a race loads fast the second time.
API responses are cached for an hour and requests are spaced out to respect
jolpica-f1's rate limits.
