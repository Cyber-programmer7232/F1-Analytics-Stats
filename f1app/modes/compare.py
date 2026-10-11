"""Player comparison: compare a favourite driver with their era or with the
all-time greats using a Poisson model (wins, podiums, poles per race) and
regression (career arc of points share or championship position)."""
from datetime import datetime, timezone

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from f1app import jolpica, models
from f1app.modes.standings import FIRST_SEASON

STATS = {"Wins": "wins", "Podiums": "podiums", "Pole starts": "poles"}
MAX_COMPARE = 5


@st.cache_data(ttl=86400, show_spinner=False)
def season_table() -> pd.DataFrame:
    """One row per driver per season: Season, DriverId, Name, Points, Wins,
    Position, Share (% of all points scored that season), CareerYear."""
    rows = []
    last = datetime.now(timezone.utc).year
    for season in range(FIRST_SEASON, last + 1):
        lst = jolpica.standings(str(season), "driver")
        if lst is None:
            continue
        for e in lst["DriverStandings"]:
            d = e["Driver"]
            rows.append(
                {
                    "Season": season,
                    "DriverId": d["driverId"],
                    "Name": f"{d['givenName']} {d['familyName']}",
                    "Points": float(e["points"]),
                    "Wins": int(e["wins"]),
                    "Position": float(e["position"]) if "position" in e else np.nan,
                }
            )
    df = pd.DataFrame(rows)
    total = df.groupby("Season")["Points"].transform("sum")
    df["Share"] = np.where(total > 0, 100 * df["Points"] / total, 0.0)
    df["CareerYear"] = df["Season"] - df.groupby("DriverId")["Season"].transform("min") + 1
    # Tell apart drivers who share a name by adding their first season.
    first = df.groupby("DriverId")["Season"].transform("min")
    shared = df.groupby("Name")["DriverId"].transform("nunique") > 1
    df.loc[shared, "Name"] = df.loc[shared, "Name"] + " (" + first[shared].astype(str) + ")"
    return df


@st.cache_data(ttl=86400, show_spinner=False)
def career(driver_id: str) -> pd.DataFrame:
    """Season, Round, Grid, Position for every race the driver took part in."""
    rows = []
    for race in jolpica.driver_results(driver_id):
        for r in race.get("Results", []):
            rows.append(
                {
                    "Season": int(race["season"]),
                    "Round": int(race["round"]),
                    "Grid": pd.to_numeric(r.get("grid"), errors="coerce"),
                    "Position": pd.to_numeric(r.get("position"), errors="coerce"),
                }
            )
    return pd.DataFrame(rows, columns=["Season", "Round", "Grid", "Position"])


def counts(df: pd.DataFrame) -> dict:
    return {
        "starts": len(df),
        "wins": int((df["Position"] == 1).sum()),
        "podiums": int((df["Position"] <= 3).sum()),
        "poles": int((df["Grid"] == 1).sum()),
    }


def candidates(seasons: pd.DataFrame, focus: str, scope: str) -> list[str]:
    """Drivers to offer for comparison, best first."""
    if scope == "Their era":
        span = seasons[seasons["DriverId"] == focus]["Season"]
        pool = seasons[seasons["Season"].between(span.min(), span.max())]
        ranked = pool.groupby("DriverId")["Share"].sum()
    else:
        ranked = seasons.groupby("DriverId")["Wins"].sum()
    ranked = ranked.drop(focus, errors="ignore").sort_values(ascending=False)
    return ranked.head(40).index.tolist()


def poisson_tab(focus: str, chosen: list[str], names: dict, data: dict):
    stat_label = st.radio("Count", list(STATS), horizontal=True, key="cmp_stat")
    key = STATS[stat_label]

    rows = []
    for d in [focus] + chosen:
        c = data[d]
        rate, lo, hi = models.poisson_rate(c[key], c["starts"])
        rows.append({"Driver": names[d], "Starts": c["starts"], stat_label: c[key], "Rate": rate, "Low": lo, "High": hi})
    table = pd.DataFrame(rows)
    season_len = st.slider("Season length for the projections (races)", 7, 25, 22, key="cmp_len")

    st.markdown(f"**{stat_label} per race, with 95% range**")
    order = table.sort_values("Rate", ascending=False)["Driver"].tolist()
    base = alt.Chart(table).encode(y=alt.Y("Driver:N", sort=order, title=None))
    chart = (
        base.mark_rule(strokeWidth=3).encode(x=alt.X("Low:Q", title=f"{stat_label} per race", axis=alt.Axis(format="%")), x2="High:Q")
        + base.mark_point(filled=True, size=120).encode(
            x="Rate:Q",
            color=alt.Color("Driver:N", sort=[names[focus]] + [names[d] for d in chosen], legend=None),
            tooltip=["Driver", "Starts", stat_label,
                     alt.Tooltip("Rate:Q", format=".1%"), alt.Tooltip("Low:Q", format=".1%"), alt.Tooltip("High:Q", format=".1%")],
        )
    ).properties(height=max(140, 48 * len(table)))
    st.altair_chart(chart, width="stretch")

    shown = table.copy()
    shown["Per race"] = shown["Rate"].map("{:.1%}".format)
    shown["95% range"] = shown.apply(lambda r: f"{r['Low']:.1%} to {r['High']:.1%}", axis=1)
    shown[f"Expected in a {season_len}-race season"] = shown.apply(
        lambda r: f"{r['Rate'] * season_len:.1f} ({r['Low'] * season_len:.1f} to {r['High'] * season_len:.1f})", axis=1
    )
    st.dataframe(shown.drop(columns=["Rate", "Low", "High"]), hide_index=True, width="stretch")

    st.markdown(f"**Chance of each {stat_label.lower()} total in a {season_len}-race season**")
    dist = pd.concat(
        [models.season_distribution(r.Rate, season_len).assign(Driver=r.Driver) for r in table.itertuples() if not np.isnan(r.Rate)]
    )
    cutoff = dist[dist["p"] > 0.002]["k"].max()
    dist = dist[dist["k"] <= max(cutoff, 3)]
    st.altair_chart(
        alt.Chart(dist)
        .mark_bar()
        .encode(
            x=alt.X("k:O", title=f"{stat_label} in the season"),
            xOffset=alt.XOffset("Driver:N", sort=[names[focus]] + [names[d] for d in chosen]),
            y=alt.Y("p:Q", title="Chance", axis=alt.Axis(format="%")),
            color=alt.Color("Driver:N", sort=[names[focus]] + [names[d] for d in chosen], title=None),
            tooltip=["Driver", alt.Tooltip("k:O", title=stat_label), alt.Tooltip("p:Q", title="Chance", format=".1%")],
        )
        .properties(height=320),
        width="stretch",
    )

    st.markdown(f"**Is {names[focus]} really different?**")
    f = data[focus]
    tests = []
    for d in chosen:
        o = data[d]
        ratio, p = models.compare_rates(f[key], f["starts"], o[key], o["starts"])
        tests.append(
            {
                "Against": names[d],
                f"{names[focus]}'s rate vs theirs": "∞" if np.isinf(ratio) else ("–" if np.isnan(ratio) else f"{ratio:.2f}×"),
                "p-value": "–" if np.isnan(p) else f"{p:.3f}",
                "Verdict": models.describe_p(p),
            }
        )
    st.dataframe(pd.DataFrame(tests), hide_index=True, width="stretch")
    st.caption(
        "The Poisson model treats each start as a fresh chance at the same rate across the whole career. "
        "It doesn't know about car quality or teammates, so a great car makes any driver look better. "
        "The p-value is the chance of seeing a gap this big if both drivers really had the same rate."
    )


def regression_tab(focus: str, chosen: list[str], names: dict, seasons: pd.DataFrame):
    metric = st.radio("Measure", ["Points share", "Championship position"], horizontal=True, key="cmp_metric")
    field = "Share" if metric == "Points share" else "Position"
    ids = [focus] + chosen
    df = seasons[seasons["DriverId"].isin(ids)].dropna(subset=[field]).copy()
    df["Driver"] = df["DriverId"].map(names)
    order = [names[d] for d in ids]

    fits, curves = [], []
    for d in ids:
        g = df[df["DriverId"] == d]
        fit = models.career_fit(g["CareerYear"], g[field])
        if fit["coef"] is not None:
            xs = np.linspace(g["CareerYear"].min(), g["CareerYear"].max(), 60)
            curves.append(pd.DataFrame({"CareerYear": xs, field: np.polyval(fit["coef"], xs), "Driver": names[d]}))
        best = fit["peak_y"] if field == "Share" else np.nan
        if field == "Position" and fit["coef"] is not None:  # best position = lowest point of the curve
            xs = np.linspace(g["CareerYear"].min(), g["CareerYear"].max(), 200)
            ys = np.polyval(fit["coef"], xs)
            i = int(np.argmin(ys))
            fit["peak_x"], best = xs[i], ys[i]
        first = g["Season"].min() if not g.empty else np.nan
        fits.append(
            {
                "Driver": names[d],
                "Seasons": fit["n"],
                "Peak career year": "–" if np.isnan(fit["peak_x"]) else f"{fit['peak_x']:.0f} ({first + round(fit['peak_x']) - 1:.0f})",
                "Peak (fitted)": "–" if np.isnan(best) else (f"{best:.1f}%" if field == "Share" else f"P{max(best, 1):.1f}"),
                "Trend per year": "–" if np.isnan(fit["slope"]) else (f"{fit['slope']:+.2f} pts of share" if field == "Share" else f"{-fit['slope']:+.2f} places gained"),
                "R²": "–" if np.isnan(fit["r2"]) else f"{fit['r2']:.2f}",
            }
        )

    y_title = "Share of all points that season (%)" if field == "Share" else "Championship position"
    y_scale = alt.Scale(reverse=True, zero=False) if field == "Position" else alt.Scale(zero=True)
    color = alt.Color("Driver:N", sort=order, title=None)
    points = alt.Chart(df).mark_circle(size=70, opacity=0.8).encode(
        x=alt.X("CareerYear:Q", title="Career year (1 = debut season)", axis=alt.Axis(tickMinStep=1)),
        y=alt.Y(f"{field}:Q", title=y_title, scale=y_scale),
        color=color,
        tooltip=["Driver", "Season", "CareerYear", alt.Tooltip("Share:Q", format=".1f"), "Position", "Points", "Wins"],
    )
    layers = points
    if curves:
        layers = layers + alt.Chart(pd.concat(curves)).mark_line(strokeWidth=2.5).encode(x="CareerYear:Q", y=f"{field}:Q", color=color)
    st.altair_chart(layers.properties(height=420), width="stretch")
    st.dataframe(pd.DataFrame(fits), hide_index=True, width="stretch")
    st.caption(
        "Dots are seasons; lines are curved (quadratic) fits showing each career's rise, peak and decline. "
        "Points share divides a driver's points by every point scored that season, so different points systems and calendar lengths compare fairly. "
        "Trend per year is the straight-line slope; R² near 1 means the line explains the seasons well, near 0 means a lot of up and down."
    )


def render():
    st.header("🧮 Player comparison")
    try:
        with st.spinner("Loading every season's standings since 1950. The first time takes about half a minute."):
            seasons = season_table()
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return

    totals = seasons.groupby(["DriverId", "Name"]).agg(Wins=("Wins", "sum"), Share=("Share", "sum")).reset_index()
    totals = totals.sort_values(["Wins", "Share"], ascending=False)
    names = dict(zip(totals["DriverId"], totals["Name"]))
    ids = totals["DriverId"].tolist()
    default = ids.index("hamilton") if "hamilton" in ids else 0

    c1, c2 = st.columns([2, 1])
    focus = c1.selectbox("Your driver", ids, index=default, format_func=names.get, key="cmp_focus")
    scope = c2.radio("Compare with", ["Their era", "All time"], horizontal=True, key="cmp_scope")
    pool = candidates(seasons, focus, scope)
    chosen = st.multiselect(
        f"Drivers to compare (up to {MAX_COMPARE})", pool, default=pool[:3], format_func=names.get,
        max_selections=MAX_COMPARE, key=f"cmp_with_{focus}_{scope}",
    )
    if not chosen:
        st.info("Pick at least one driver to compare with.")
        return

    try:
        with st.spinner("Loading race-by-race careers…"):
            data = {d: counts(career(d)) for d in [focus] + chosen}
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return

    f = data[focus]
    span = seasons[seasons["DriverId"] == focus]["Season"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Seasons", f"{span.min()}–{span.max()}", f"{span.nunique()} seasons", delta_color="off")
    m2.metric("Starts", f["starts"])
    m3.metric("Wins", f["wins"], f"{f['wins'] / f['starts']:.1%} of starts" if f["starts"] else None, delta_color="off")
    m4.metric("Podiums", f["podiums"], f"{f['poles']} pole starts", delta_color="off")

    tab_p, tab_r = st.tabs(["Poisson: rates per race", "Regression: career arcs"])
    with tab_p:
        poisson_tab(focus, chosen, names, data)
    with tab_r:
        regression_tab(focus, chosen, names, seasons)
