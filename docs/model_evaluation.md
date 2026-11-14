# One-day archive-origin estimates: method and held-out evaluation

This document records how the dashboard's one-day estimates are produced and how they were evaluated. Every number below was computed from the bundled NASA POWER archive by `scripts/train_climate_models.py` and is stored in `models/climate_models.json` (built 2026-11-14, algorithm `standardized-ridge-plus-chronological-baselines-v1`).

These are **historical-data estimates, not operational weather forecasts**. No numerical weather prediction input, station observation, or disaster label is used.

## What is estimated

For each of the 12 archive locations and each of the four NASA POWER parameters, one model estimates the next daily value from that location's own archived history:

| Variable | Canonical unit | Annual aggregation used elsewhere in the app |
|---|---|---|
| `T2M` | °C | arithmetic mean of daily values |
| `RH2M` | % | arithmetic mean of daily values |
| `WS10M` | km/h (converted from m/s × 3.6) | arithmetic mean of daily values |
| `PRECTOTCORR` | mm/day | sum of valid daily values (mm/year) |

48 series are modelled and evaluated. Each series is modelled separately; nothing is pooled across locations.

## Features

All features come from the same variable at the same location and are strictly earlier than the target day:

- day-of-year sine and cosine (seasonal position),
- lags of 1, 2, 7, 14, 30, and 365 days,
- trailing 7-day and 30-day means.

Feature rows are dropped when a required lag is unavailable. Values are standardized on the training period only.

## Chronological split (no leakage)

| Split | Target dates | Purpose |
|---|---|---|
| Training | 1982-01-01 – 2019-12-31 | Fit ridge coefficients and standardization |
| Selection | 2020-01-01 – 2020-12-31 | Choose between ridge, persistence, and seasonal naive |
| Calibration | 2021-01-01 – 2022-12-31 | Fit the interval radius only |
| Held-out test | 2023-01-01 – 2025-12-31 | Final metrics; never used for fitting or selection |

The first training target is 1982 because the 365-day lag needs 1981 observations. For the seven locations whose archive starts in 2015, the training period is 2016–2019 (1,461 target days); the five original locations have 13,879 training targets. Every series has exactly **1,096 held-out test days** (2023–2025), and ridge, persistence, and seasonal naive are scored on **identical test dates**.

## Compared methods

- **Ridge regression** — standardized linear model with a fixed regularization strength (alpha 1.0). Alpha was not tuned per series, so no extra selection freedom is introduced.
- **Persistence** — tomorrow equals today.
- **Seasonal naive** — tomorrow equals the same calendar day one year earlier.

The method with the lowest selection-year MAE is used for that series. Selection happens before calibration and before the held-out test, so the test period never influences which method is shown.

## Prediction intervals

A symmetric interval is built from the absolute calibration-period residual quantile (2021–2022, 730 days), giving a nominal 90% interval. An interval is displayed **only if** it has at least 100 held-out test cases **and** its empirical held-out coverage falls between 85% and 95%. Otherwise the interface states that uncertainty is not reliably quantified for that series; no percentage is invented.

**Result: 47 of 48 series pass.** The single failure is **Nairobi precipitation (`PRECTOTCORR`)**, whose nominal 90% interval covered only **83.5%** of held-out days, below the 85% floor. Its estimate is still shown, but without an interval and with the text "uncertainty not reliably quantified".

Passing series show held-out coverage between 85.4% and 94.2%, with mean interval widths from 0.822 mm/day (Cairo precipitation) to 27.755 percentage points (Phoenix humidity). Coverage near the edges of the 85–95% band means the interval is approximately, not exactly, calibrated.

## Held-out results, all 48 series

MAE, RMSE, and R² are for the selected method on the 1,096 held-out days (2023-01-01 – 2025-12-31). The three baseline columns are MAE on the same dates for comparison. Interval coverage is empirical held-out coverage of the nominal 90% interval.

| Location | Variable | Unit | Selected method | MAE | RMSE | R² | Ridge MAE | Persistence MAE | Seasonal-naive MAE | 90% interval shown | Held-out coverage | Mean width |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Cairo, Egypt | PRECTOTCORR | mm/day | persistence | 0.373 | 2.541 | -0.225 | 0.417 | 0.373 | 0.648 | yes | 94.2% | 0.822 |
| Cairo, Egypt | RH2M | % | ridge | 5.159 | 6.865 | 0.734 | 5.159 | 5.637 | 8.826 | yes | 90.7% | 23.783 |
| Cairo, Egypt | T2M | °C | ridge | 0.953 | 1.312 | 0.964 | 0.953 | 1.043 | 2.297 | yes | 91.4% | 4.540 |
| Cairo, Egypt | WS10M | km/h | ridge | 2.359 | 3.045 | 0.274 | 2.359 | 2.710 | 3.705 | yes | 90.1% | 10.089 |
| Delhi, India | PRECTOTCORR | mm/day | persistence | 2.537 | 6.909 | -0.002 | 2.538 | 2.537 | 3.618 | yes | 90.3% | 9.697 |
| Delhi, India | RH2M | % | ridge | 4.695 | 6.683 | 0.900 | 4.695 | 4.889 | 12.990 | yes | 90.3% | 20.027 |
| Delhi, India | T2M | °C | ridge | 0.942 | 1.247 | 0.971 | 0.942 | 0.989 | 2.612 | yes | 91.5% | 4.099 |
| Delhi, India | WS10M | km/h | ridge | 2.363 | 3.057 | 0.357 | 2.363 | 2.656 | 3.887 | yes | 91.0% | 10.318 |
| Jakarta, Indonesia | PRECTOTCORR | mm/day | ridge | 4.459 | 7.579 | 0.233 | 4.459 | 4.841 | 6.374 | yes | 89.8% | 14.542 |
| Jakarta, Indonesia | RH2M | % | ridge | 2.204 | 2.806 | 0.641 | 2.204 | 2.436 | 4.516 | yes | 89.9% | 8.959 |
| Jakarta, Indonesia | T2M | °C | ridge | 0.313 | 0.400 | 0.744 | 0.313 | 0.347 | 0.811 | yes | 89.2% | 1.310 |
| Jakarta, Indonesia | WS10M | km/h | ridge | 2.118 | 2.684 | 0.489 | 2.118 | 2.282 | 4.180 | yes | 93.0% | 9.686 |
| London, United Kingdom | PRECTOTCORR | mm/day | ridge | 2.092 | 3.297 | 0.049 | 2.092 | 2.270 | 2.947 | yes | 88.2% | 5.606 |
| London, United Kingdom | RH2M | % | ridge | 3.357 | 4.377 | 0.747 | 3.357 | 3.957 | 5.739 | yes | 89.5% | 13.867 |
| London, United Kingdom | T2M | °C | ridge | 1.339 | 1.756 | 0.902 | 1.339 | 1.435 | 2.918 | yes | 88.0% | 5.190 |
| London, United Kingdom | WS10M | km/h | ridge | 5.010 | 6.436 | 0.286 | 5.010 | 5.734 | 8.325 | yes | 89.3% | 19.723 |
| Manila, Philippines | PRECTOTCORR | mm/day | ridge | 6.251 | 11.651 | 0.202 | 6.251 | 7.057 | 9.854 | yes | 88.9% | 19.170 |
| Manila, Philippines | RH2M | % | ridge | 2.399 | 3.185 | 0.747 | 2.399 | 2.647 | 4.869 | yes | 88.4% | 9.806 |
| Manila, Philippines | T2M | °C | ridge | 0.489 | 0.628 | 0.845 | 0.489 | 0.526 | 0.966 | yes | 87.8% | 1.960 |
| Manila, Philippines | WS10M | km/h | ridge | 1.776 | 2.452 | 0.608 | 1.776 | 1.960 | 3.565 | yes | 90.9% | 7.453 |
| Nairobi, Kenya | PRECTOTCORR | mm/day | ridge | 1.404 | 3.315 | 0.137 | 1.404 | 1.422 | 1.972 | **no** | 83.5% | 2.880 |
| Nairobi, Kenya | RH2M | % | ridge | 3.295 | 4.299 | 0.798 | 3.295 | 3.490 | 8.614 | yes | 91.8% | 14.994 |
| Nairobi, Kenya | T2M | °C | ridge | 0.474 | 0.610 | 0.789 | 0.474 | 0.493 | 1.083 | yes | 92.2% | 2.146 |
| Nairobi, Kenya | WS10M | km/h | ridge | 1.633 | 2.104 | 0.753 | 1.633 | 1.767 | 3.644 | yes | 90.5% | 7.047 |
| Phoenix, USA | PRECTOTCORR | mm/day | persistence | 0.927 | 2.982 | -0.458 | 1.019 | 0.927 | 1.188 | yes | 91.5% | 3.398 |
| Phoenix, USA | RH2M | % | ridge | 5.695 | 7.904 | 0.751 | 5.695 | 5.988 | 15.069 | yes | 91.9% | 27.755 |
| Phoenix, USA | T2M | °C | ridge | 1.218 | 1.574 | 0.970 | 1.218 | 1.329 | 3.381 | yes | 89.6% | 5.033 |
| Phoenix, USA | WS10M | km/h | ridge | 2.113 | 2.799 | 0.105 | 2.113 | 2.540 | 3.221 | yes | 88.8% | 8.510 |
| Reykjavík, Iceland | PRECTOTCORR | mm/day | ridge | 4.072 | 5.705 | 0.066 | 4.072 | 4.381 | 5.748 | yes | 89.5% | 11.669 |
| Reykjavík, Iceland | RH2M | % | ridge | 3.641 | 4.692 | 0.413 | 3.641 | 4.060 | 6.199 | yes | 90.4% | 15.000 |
| Reykjavík, Iceland | T2M | °C | ridge | 1.314 | 1.819 | 0.878 | 1.314 | 1.368 | 3.229 | yes | 89.8% | 5.693 |
| Reykjavík, Iceland | WS10M | km/h | ridge | 5.145 | 6.755 | 0.389 | 5.145 | 5.843 | 8.819 | yes | 90.2% | 21.851 |
| Sydney, Australia | PRECTOTCORR | mm/day | ridge | 2.865 | 6.350 | 0.011 | 2.865 | 2.906 | 4.256 | yes | 92.3% | 9.013 |
| Sydney, Australia | RH2M | % | ridge | 5.570 | 7.199 | 0.379 | 5.570 | 6.272 | 9.784 | yes | 87.8% | 21.872 |
| Sydney, Australia | T2M | °C | ridge | 1.054 | 1.414 | 0.846 | 1.054 | 1.142 | 1.922 | yes | 86.8% | 4.099 |
| Sydney, Australia | WS10M | km/h | ridge | 3.430 | 4.588 | 0.185 | 3.430 | 4.216 | 5.620 | yes | 90.3% | 14.796 |
| São Paulo, Brazil | PRECTOTCORR | mm/day | ridge | 2.915 | 4.688 | 0.166 | 2.915 | 2.808 | 3.961 | yes | 89.5% | 8.256 |
| São Paulo, Brazil | RH2M | % | ridge | 5.175 | 7.013 | 0.599 | 5.175 | 5.341 | 11.062 | yes | 88.7% | 20.578 |
| São Paulo, Brazil | T2M | °C | ridge | 1.184 | 1.589 | 0.793 | 1.184 | 1.270 | 2.792 | yes | 85.4% | 4.325 |
| São Paulo, Brazil | WS10M | km/h | ridge | 2.916 | 3.823 | 0.260 | 2.916 | 3.383 | 4.470 | yes | 91.0% | 11.710 |
| Tokyo, Japan | PRECTOTCORR | mm/day | ridge | 5.752 | 12.258 | 0.052 | 5.752 | 6.418 | 7.794 | yes | 91.2% | 17.016 |
| Tokyo, Japan | RH2M | % | ridge | 4.835 | 6.262 | 0.338 | 4.835 | 5.519 | 7.630 | yes | 87.9% | 19.424 |
| Tokyo, Japan | T2M | °C | ridge | 1.543 | 1.980 | 0.950 | 1.543 | 1.640 | 2.719 | yes | 89.7% | 6.255 |
| Tokyo, Japan | WS10M | km/h | ridge | 3.865 | 5.023 | 0.127 | 3.865 | 4.686 | 5.457 | yes | 91.5% | 14.947 |
| Toronto, Canada | PRECTOTCORR | mm/day | ridge | 1.796 | 2.615 | 0.021 | 1.796 | 1.915 | 2.167 | yes | 86.5% | 4.252 |
| Toronto, Canada | RH2M | % | ridge | 5.457 | 6.779 | 0.429 | 5.457 | 6.172 | 8.864 | yes | 91.3% | 23.047 |
| Toronto, Canada | T2M | °C | ridge | 1.549 | 2.008 | 0.952 | 1.549 | 1.615 | 3.118 | yes | 93.0% | 7.156 |
| Toronto, Canada | WS10M | km/h | ridge | 5.541 | 6.959 | 0.328 | 5.541 | 6.472 | 8.010 | yes | 92.7% | 23.956 |

## Reading the results honestly

- Ridge is selected for **45 of 48** series; persistence wins for **3** (Cairo, Delhi, and Phoenix precipitation). Precipitation is the hardest variable: R² is near zero or negative for most locations because daily rainfall is close to a coin flip at this resolution, and the best MAE is usually only slightly better than persistence.
- Temperature R² ranges from 0.744 (Jakarta) to 0.971 (Delhi). Wind and humidity sit in between; wind R² is low in several cities (0.105–0.489).
- A negative R² means the selected method does worse than predicting the test-period mean on those days. That is reported, not hidden.
- Held-out MAE is a retrospective accuracy measure for 2023–2025. It is not a guarantee for any future day, and it is not a forecast skill score against an operational model.
- None of these models predicts a disaster, an impact, or an official warning. They estimate one meteorological variable one day beyond the archive.

## Reproducing the results

```bash
python scripts/train_climate_models.py
```

The command reads `data/historical/earthscope_power.sqlite3`, rewrites `models/climate_models.json`, and prints the per-series summary. `python -m pytest tests/test_climate_model_suite.py -q` re-checks the interval gating and a real archive estimate.
