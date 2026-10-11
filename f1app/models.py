"""Statistical models for the player comparison mode. Pure functions, no
Streamlit, so they are easy to test and reuse."""
import numpy as np
import pandas as pd
from scipy import stats


def poisson_rate(count: int, exposure: int, level: float = 0.95) -> tuple[float, float, float]:
    """Rate per race with an exact (Garwood) confidence interval for a Poisson count."""
    if exposure <= 0:
        return float("nan"), float("nan"), float("nan")
    alpha = 1 - level
    lo = stats.chi2.ppf(alpha / 2, 2 * count) / 2 if count > 0 else 0.0
    hi = stats.chi2.ppf(1 - alpha / 2, 2 * count + 2) / 2
    return count / exposure, lo / exposure, hi / exposure


def season_distribution(rate: float, races: int) -> pd.DataFrame:
    """P(k) for k = 0..races if the driver kept `rate` per race over a season.
    Uses a Poisson with mean rate * races, capped at the number of races."""
    mean = rate * races
    k = np.arange(0, races + 1)
    p = stats.poisson.pmf(k, mean)
    p[-1] += stats.poisson.sf(races, mean)  # can't win more races than there are
    return pd.DataFrame({"k": k, "p": p})


def compare_rates(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """Rate ratio of driver 1 to driver 2 and a two-sided p-value. Given the
    combined count, driver 1's share is Binomial(k1 + k2, n1 / (n1 + n2)) if
    both have the same underlying rate (the conditional test for two Poisson rates)."""
    if n1 <= 0 or n2 <= 0:
        return float("nan"), float("nan")
    ratio = (k1 / n1) / (k2 / n2) if k2 > 0 else float("inf") if k1 > 0 else float("nan")
    if k1 + k2 == 0:
        return ratio, 1.0
    p = stats.binomtest(k1, k1 + k2, n1 / (n1 + n2)).pvalue
    return ratio, float(p)


def career_fit(x: np.ndarray, y: np.ndarray) -> dict:
    """Fit y against career year. Returns the linear trend (slope per year, R²)
    and, with 3+ seasons, a quadratic curve for the career arc and its peak."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    out = {"n": len(x), "slope": np.nan, "r2": np.nan, "coef": None, "peak_x": np.nan, "peak_y": np.nan}
    if len(x) < 2 or np.ptp(x) == 0:
        return out
    lin = stats.linregress(x, y)
    out["slope"], out["r2"] = lin.slope, lin.rvalue**2
    deg = 2 if len(x) >= 3 else 1
    coef = np.polyfit(x, y, deg)
    out["coef"] = coef
    grid = np.linspace(x.min(), x.max(), 200)
    fitted = np.polyval(coef, grid)
    i = int(np.argmax(fitted))
    out["peak_x"], out["peak_y"] = grid[i], fitted[i]
    return out


def describe_p(p: float) -> str:
    if np.isnan(p):
        return "Not enough data"
    if p < 0.01:
        return "Very strong evidence of a real difference"
    if p < 0.05:
        return "Strong evidence of a real difference"
    if p < 0.10:
        return "Weak evidence of a difference"
    return "No clear difference (could be chance)"
