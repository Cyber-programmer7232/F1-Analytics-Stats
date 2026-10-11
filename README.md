# F1 Analytics Stats

A Streamlit app with one mode per F1 project idea, built one mode at a time.

| Mode | Data | Status |
|---|---|---|
| 1. Next race | jolpica-f1 | ✅ |
| 2. Standings | jolpica-f1 | ✅ |
| 3. Points race | jolpica-f1 | planned |
| 4. All-time stats | jolpica-f1 | planned |
| 5. Race lap times | FastF1 | planned |
| 6. Qualifying head-to-head | FastF1 | planned |
| 7. Tyre strategy | FastF1 | planned |
| 8. Season dashboard | both | planned |
| Player comparison (Poisson & regression) | both | planned |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

API responses are cached for an hour and requests are spaced out to respect
jolpica-f1's rate limits.
