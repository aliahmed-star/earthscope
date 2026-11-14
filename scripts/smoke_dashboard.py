"""Browser smoke test for the upgraded EarthScope dashboard.

Run against a locally served app, for example:
    python -m uvicorn api:app --host 127.0.0.1 --port 8011
    python scripts/smoke_dashboard.py --base-url http://127.0.0.1:8011

It checks the new panels render with real archive data and writes authentic
screenshots used by the submission assets. It fails loudly on JavaScript errors
or missing content.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = ROOT / "submission_deliverables_2026-11-14" / "assets" / "screenshots"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=args.headless, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1600, "height": 1200}, device_scale_factor=1)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" and "favicon" not in msg.text and "404" not in msg.text else None)

        page.goto(args.base_url, wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#coverageSummary')?.textContent.includes('stored rows')", timeout=60000)
        coverage = page.inner_text("#coverageSummary")
        print("coverage summary:", coverage)
        if "12/12 countries qualify" not in coverage:
            errors.append(f"unexpected coverage summary: {coverage}")
        rows = page.eval_on_selector_all("#coverageTable tbody tr", "els => els.length")
        print("coverage rows:", rows)
        if rows != 12:
            errors.append(f"expected 12 coverage rows, got {rows}")
        page.locator("#coveragePanel").screenshot(path=str(SHOTS / "archive_coverage_panel.png"))

        # Compare two countries on one shared range.
        page.fill("#compareStart", "2015-01-01")
        page.fill("#compareEnd", "2025-12-31")
        page.select_option("#compareVariable", "T2M")
        page.click("#compareRun")
        page.wait_for_function("document.querySelectorAll('#comparisonTable tbody tr').length >= 2", timeout=90000)
        page.wait_for_function("!document.querySelector('#compareRun').disabled", timeout=90000)
        insights = page.inner_text("#compareInsights")
        print("comparison insights:", insights[:300].replace("\n", " | "))
        if "all statistics calculated from stored observations" not in insights:
            errors.append("comparison insights did not confirm stored observations")
        page.locator("#comparisonPanel").screenshot(path=str(SHOTS / "country_comparison_panel.png"))
        page.locator("#trendsPanel").screenshot(path=str(SHOTS / "climate_trends_panel.png"))

        # Load one-day estimates for the selected countries.
        page.click("#loadEstimates")
        page.wait_for_function("document.querySelectorAll('#modelSuiteTable tbody tr').length >= 2", timeout=120000)
        page.wait_for_function("!document.querySelector('#loadEstimates').disabled", timeout=120000)
        status = page.inner_text("#modelSuiteStatus")
        print("model suite status:", status)
        if "model bundle" not in status:
            errors.append(f"unexpected model status: {status}")
        page.locator("#modelSuitePanel").screenshot(path=str(SHOTS / "model_suite_panel.png"))

        # Confirm the original dashboard is still present and functional.
        for selector in ("#map", "#c_temperature", "#c_humidity", "#c_wind", "#c_rainfall", "#tbody"):
            if page.locator(selector).count() == 0:
                errors.append(f"missing original dashboard element {selector}")

        page.screenshot(path=str(SHOTS / "dashboard_full_page.png"), full_page=True)
        browser.close()

    if errors:
        print("SMOKE FAILED")
        for item in errors:
            print(" -", item)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
