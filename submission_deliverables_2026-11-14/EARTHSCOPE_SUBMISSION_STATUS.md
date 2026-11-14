# EarthScope Submission Status

**Status date:** 14 November 2026  
**Project folder:** `/home/ubuntu/EARTHSCOPE_working/merged`  
**Deliverable folder:** `/home/ubuntu/EARTHSCOPE_working/merged/submission_deliverables_2026-11-14`  
**Overall status:** NASA data audit, report, presentation and a compliant 30-second demo exist and have been checked. The submission is **not ready to send** because the public demo link, verified team details and the selected challenge title are still missing.

## What is in the package

| File | What it is | State |
| --- | --- | --- |
| `EARTHSCOPE_NASA_DATA_AUDIT.md` | Judge-ready data audit: sources, sample counts, sufficiency, storage, 2026 rules | Complete |
| `EarthScope_Final_Presentation.pptx` | Seven-slide editable PowerPoint, English | Complete and validated |
| `EarthScope_Final_Project_Report.docx` | Ten-page editable Word report with figures and clickable references | Complete and validated |
| `EarthScope_30s_Demo.mp4` | 28.5-second demo, 1920×1080, H.264 + AAC, synthetic narration disclosed | Complete and validated |
| `EARTHSCOPE_SUBMISSION_STATUS.md` | This status report | Complete |
| `assets/` | Screenshots, diagrams, credited NASA image, storyboard | Supporting files |

The original website source, its existing report and its screenshots were not modified. Everything new is inside the deliverable folder.

## Verified source position

One NASA integration is active: **NASA POWER Daily**, requested per coordinate for `T2M`, `RH2M`, `WS10M` and `PRECTOTCORR`, with explicit UTC and a 31-day request cap. The provider calls `power.larc.nasa.gov/api/temporal/daily/point` without a key, converts wind from m/s to km/h, and turns NASA fill values into nulls.

Everything else is either documentation or simulation. NOAA Climate Data Online is a candidate only, with no client, token or observation. NASA FIRMS, GPM IMERG, AppEEARS and Giovanni are not integrated. The map basemap is CARTO, not NASA. `mock_data.py` is legacy and unused by the active dashboard. The Blue Marble image in the deliverables is credited contextual imagery, not EarthScope data.

## Measured sample

| Item | Measured value |
| --- | --- |
| NASA raw JSON | 3 files, 19,649 bytes, 12 location payloads |
| NASA processed JSON | 3 files, 8,657 bytes, 17 stored rows |
| Unique NASA location-day keys | 12 (5 duplicate keys, no conflicting values) |
| Dates and locations covered | 2024-01-01, 2024-01-02, 2024-07-15; Cairo, Phoenix, Tokyo, Sydney, Manila |
| Non-null NASA values | 48 (four per unique record) |
| Simulated demo rows | 7 rows, 2026-11-13, one missing wind value |
| Total stored JSON | 31,063 bytes across 7 files |
| Live smoke check | 6 transient location-days, not persisted |

**Conclusion carried into every deliverable:** sufficient to demonstrate a transparent prototype; not sufficient for official warnings, forecasts, validated local risk, impact claims or climate trends. More data alone would not change that; a defined hazard, an independent reference set and event labels would.

## Storage

There is **no database**: no SQLite file, SQL schema, migration, seed script or database driver in the active path. Live observations live in process memory behind a ten-minute, 128-entry cache. Incident state is in memory, with optional JSON persistence disabled (`PERSIST_INCIDENTS=False`). The only durable data are static JSON files. No live record becomes a dataset.

## Demo video compliance

| Requirement | Result |
| --- | --- |
| Duration at or below 30 seconds | **28.500 s** measured with `ffprobe` |
| Playable container and codecs | MP4, H.264 video, AAC audio, 48 kHz mono, 30 fps, 1920×1080, 6.6 MB |
| Decode integrity | Full-file decode with FFmpeg produced no errors |
| Audio present and unclipped | Mean −19.6 dB, peak −1.9 dB |
| Content | Six beats: title, live NASA POWER request, four live charts, labelled simulated map, measured numbers, closing claim boundary |
| Honesty | No fabricated interface, no invented team identity, no claim of validation or deployment |
| AI disclosure, on screen | "AI-generated narration · synthetic voice" chip visible in every frame |
| AI disclosure, metadata | `comment`, `description` and `synopsis` tags state that the narration is AI-generated and that no imagery is AI-generated |
| Public hosting | **Not done.** The file is local only; a public link is required by the guide |

The video deliberately shows the real live dashboard capture, including the fact that its map pane stayed blank in the headless browser. The simulated map appears only with its SIMULATED labels. That choice keeps the demo truthful at the cost of one weaker visual.

## Checks performed

- **Presentation:** all seven slides passed the Slides tool validation before export; the exported file was reopened, parsed (7 slides, 3 embedded images) and rendered page by page. Slide text, tables, screenshots and page numbers were inspected; one crowded card and one unbalanced column were corrected before the final export.
- **Report:** reopened and rendered to 10 A4 pages. Headings, five tables, three figures, captions, footer page numbers and the 15 clickable references were inspected. Table rows were set not to split across pages after a first render showed a split.
- **Audit and status files:** every count and file size was produced by reading the repository, not from documentation.
- **Application:** 94 tests passed with one Starlette/httpx deprecation warning; Python byte-compilation and `node --check` passed; a live dashboard request returned HTTP 200 with six location-day slots.
- **Video:** `ffprobe` stream and duration checks, `volumedetect`, full decode, and frame extraction at 1.5, 5, 9, 14, 19, 25 and 28 seconds.

## Missing information

These were not present anywhere in the supplied project and were deliberately not invented:

1. **Team name** and **team-member names**.
2. **Selected challenge title** and challenge statement.
3. **Local Event time zone**, which determines the actual submission deadline for this team.
4. **A public hosting account or existing project URL** for the demo and the project page.
5. **A team photograph.** Not required by the current guide; noted only because it was checked.

Two naming facts should be settled before submission: the interface header reads **GEOSTORM** with "EarthScope · Environmental Data" beneath it, while the project and repository are called **EarthScope**. The deck and report use both consistently, but the submission page should pick one primary name.

## Remaining submission work

1. Insert the verified team name, member names and challenge title into slide 1 or 2 and into the submission page text.
2. Upload `EarthScope_30s_Demo.mp4` (or the exported deck PDF) to a host that allows public viewing without login, such as YouTube, Google Drive, OneDrive or Dropbox.
3. Open the public link in a private browser window and confirm it plays without a permission request.
4. Paste the English project description, the NASA data statement (NASA POWER Daily: `T2M`, `RH2M`, `WS10M`, `PRECTOTCORR`) and the AI-use disclosure into the submission form.
5. Confirm the team's Local Event deadline, then click "Submit for Judging" before it closes. Late entries are not judged.
6. Keep the audit, report and deck as supporting evidence; the portal accepts images but not documents or video.

## Risks to keep visible

- The hazard labels are prototype thresholds applied to gridded daily values. They are not forecasts, warnings or validated risk.
- A rendered live map was never captured; the live capture shows a blank map pane. Do not present a map image as live NASA data.
- The interface depends on public CDN assets; a blocked stylesheet was observed during capture, so restricted networks can degrade the display.
- Incident actions are unauthenticated and process-local. Any public deployment needs access control and a real store first.
- No deployment, judging outcome or scientific discovery is claimed anywhere in this package.

## References

[1]: https://power.larc.nasa.gov/docs/services/api/temporal/daily/ "NASA POWER Daily API documentation"
[2]: https://power.larc.nasa.gov/docs/tutorials/parameters/ "NASA POWER parameter dictionary"
[3]: https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/ "NASA POWER meteorology data sources and methodology"
[4]: https://power.larc.nasa.gov/docs/faqs/data/ "NASA POWER data FAQs"
[5]: https://www.spaceappschallenge.org/resources/project-submission-guide/ "NASA Space Apps Challenge 2026 project submission guide"
[6]: https://www.nasa.gov/nasa-brand-center/images-and-media/ "NASA images and media usage guidelines"
[7]: https://science.nasa.gov/earth/earth-observatory/the-blue-marble-true-color-global-imagery-at-1km-resolution/ "NASA Earth Observatory Blue Marble 2002"
[8]: https://wmo.int/publication-series/state-of-global-climate/state-of-global-climate-2025 "WMO State of the Global Climate 2025"
[9]: https://www.earthdata.nasa.gov/data/tools/firms "NASA Earthdata FIRMS"
[10]: https://gpm.nasa.gov/data/imerg "NASA Global Precipitation Measurement IMERG"
