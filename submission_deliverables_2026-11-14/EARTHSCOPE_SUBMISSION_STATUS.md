# EarthScope Submission Status

**Status date:** 14 November 2026  
**Project:** EarthScope dashboard with NASA POWER historical archive, country comparison, annual trends, and a 48-series one-day estimate suite  
**Technical status:** The existing dashboard was upgraded in place. Coverage, comparison, trend, and estimate panels are implemented and tested. The report, seven-slide deck, storyboard, narration, and video have been refreshed to the current project scope. No disaster-prediction capability is claimed.

## Verified project results

- SQLite schema v3 contains **446,364 daily-variable observations** for **12 city coordinates in 12 countries**: Cairo, Phoenix, Tokyo, Sydney, Manila, Delhi, Jakarta, London, Nairobi, Reykjavík, São Paulo, and Toronto.
- The five original locations cover 1981-01-01–2026-09-14 with **45 complete shared years**; the seven added locations cover 2015-01-01–2025-12-31 with **11 complete shared years**. Every one of the 48 series has zero missing normalized values. All 12 countries pass the rule of at least 10 shared complete calendar years with all four variables valid.
- **71 compressed source responses** are retained (1,995,885 bytes) and all 71 match their stored SHA-256 payload hashes. The SQLite file is 123,293,696 bytes. Database integrity and foreign-key checks pass.
- **48 one-day models** (12 locations × 4 variables) were trained with chronological splits: training through 2019, method selection on 2020, interval calibration on 2021–2022, and a held-out test on 2023–2025 with 1,096 target days per series. Ridge is selected for 45 series and persistence for 3.
- Cairo T2M, the original model, scores **MAE 0.953 °C, RMSE 1.312 °C, R² 0.964** on the held-out years; persistence scores 1.043 °C and seasonal naive 2.297 °C on the same dates.
- **47 of 48 series pass the interval display rule** (at least 100 held-out cases and 85–95% empirical coverage of the nominal 90% interval). Nairobi precipitation reaches 83.5% and is shown without an interval, labelled "uncertainty not reliably quantified".
- Country comparison uses one shared UTC window and reports annual and seasonal summaries, extrema with dates, completeness warnings, rankings, observed change, variability, and descriptive trend rates. Annual trends use **complete calendar years only**; Cairo T2M remains +0.093 °C/year for 2016–2025 and +0.032 °C/year for 1981–2025.
- The automated suite passed **138 tests** on the final rerun. Python compilation, inline JavaScript syntax and HTML ID checks, real-archive API checks, provenance hashes, and SQLite integrity checks also passed.
- The refreshed 30-second demo remains 1920×1080 at 30 fps, H.264 video with AAC audio, with synthetic-voice disclosure visible on screen and in metadata.

## Deliverables

| File | Description | Status |
|---|---|---|
| `EarthScope_Final_Presentation.pptx` | Seven-slide editable demo covering the 12-country archive, comparison, trends, model suite, and limits | Refreshed |
| `EarthScope_30s_Demo.mp4` | Short demo with archive coverage, comparison, trends, and held-out model results; synthetic narration disclosed | Refreshed |
| `EarthScope_Final_Project_Report.docx` | Project report with coverage, data quality, comparison/trend method, model suite metrics, and caveats | Refreshed |
| `EARTHSCOPE_NASA_DATA_AUDIT.md` | Current NASA archive, quality, and model audit | Updated |
| `EARTHSCOPE_SUBMISSION_STATUS.md` | This status file | Updated |
| `assets/storyboard.md` | Storyboard for the refreshed demo video | Updated |
| `assets/earthscope_video_narration.txt` | Verbatim narration script with synthetic-voice disclosure | Updated |
| `assets/earthscope_dataflow.mmd` and rendered `.png` | Dark architecture diagram including archive, comparison, trends, and model suite | Updated |
| `assets/earthscope_dataflow_light.mmd` and rendered `.png` | Light architecture diagram | Updated |
| `docs/model_evaluation.md` (project root) | Method and full 48-series held-out evaluation table | Added |
| `assets/screenshots/` | Authentic captures of the running dashboard | Curated |

The ZIP package is rebuilt from the enhanced project directory after final QA. It includes the SQLite archive, all 71 NASA source responses, the trained model bundle, tests, documentation, and the refreshed submission deliverables.

## Scope and limitations

The one-day estimates cover four meteorological variables at 12 city coordinates. They are historical-data estimates, not operational weather forecasts, and they do not predict disasters. The incident panel still applies deterministic prototype thresholds; it is not an AI disaster predictor and its levels are not official warnings. Historical trends are descriptive grid-cell summaries, not causal claims or station measurements. Seven locations have only 11 complete years, so their trend and comparison windows are shorter. The models have not been validated against independent station observations.

## Remaining submission items

The technical assets are complete. Before submission, the team still needs to supply the verified team name, member names, and selected challenge title if required; host the demo publicly and test the public link; and enter the project/NASA data statement and AI-use disclosure in the submission form. These facts were not present in the supplied project and have not been invented. No public deployment, judging result, or emergency-service connection is claimed.
