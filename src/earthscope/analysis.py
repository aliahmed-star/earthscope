"""
analysis.py - explainable, rule-based hazard detection and risk scoring.

RESPONSIBILITY
    Take a validated observation (see data_loader.py) and answer:
      * Which hazards are present?            -> "hazards" / "primary_hazard"
      * How risky is it (Low..Critical)?      -> "risk_level"
      * Which numbers caused that?            -> "supporting_measurements"
      * Why, in plain language?               -> "reasons"
      * What could we NOT assess?             -> "missing_measurements", "limitations"

HOW IT WORKS (simple on purpose)
    1. Every hazard has a rule in config.HAZARD_RULES (thresholds per level).
    2. For each rule we find the highest level whose conditions ALL pass.
    3. The overall risk is the highest level among all hazards. If two hazards
       tie, the rule listed first in the config is "primary" (deterministic).
    4. No hazard reached -> "Low" with hazard type "None".

WHAT THIS MODULE DOES NOT DO
    * No loading or validation of raw data (data_loader.py).
    * No incident state (incidents.py) and no drawing (frontend).
    * No network access. The same input and config always give the same output.

LIMITATIONS
    Thresholds are prototype values, not official warning criteria. Missing
    measurements are never treated as zero: they are reported as limitations
    and can only prevent a hazard from being confirmed, never invent one.
"""

from . import config

# Symbols used when writing human-readable explanations.
_OPERATOR_SYMBOLS = {">=": "≥", "<=": "≤"}


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------
def _compare(value, operator, threshold):
    """Check one condition. Returns True, False, or None when the value is missing.

    Returning None (rather than False) lets the caller tell "definitely not
    reached" apart from "cannot tell because data is missing".
    """
    if value is None:
        return None
    if operator == ">=":
        return value >= threshold
    if operator == "<=":
        return value <= threshold
    raise ValueError(f"Unsupported operator in hazard rule: {operator!r}")


def _describe_condition(field, operator, threshold, value, level, hazard):
    """Build one human-readable sentence explaining a satisfied condition."""
    label, unit = config.MEASUREMENT_LABELS[field]
    symbol = _OPERATOR_SYMBOLS[operator]
    return (f"{label} {value:g} {unit} {symbol} {threshold:g} {unit} "
            f"(prototype {level} threshold for {hazard})")


def evaluate_rule(measurements, rule):
    """Evaluate ONE hazard rule against a measurements dict.

    Input : measurements - {"temperature_c": 44.0, "wind_speed_kmh": None, ...}
            rule         - one entry of config.HAZARD_RULES
    Output: {
              "hazard": str,
              "level": "Moderate"|"High"|"Critical"|None,   # None = not triggered
              "triggered_conditions": [(field, value), ...] # the measurements that matched
              "reasons": [str, ...],                        # one sentence per matched condition
              "undetermined_fields": [field, ...],          # missing data that blocked a higher level
            }
    """
    matched_level = None
    triggered, reasons = [], []
    undetermined = []

    # Check from the most severe level downwards; the first level whose
    # conditions all pass is the hazard's level.
    for level in reversed(config.RISK_LEVELS):
        conditions = rule["levels"].get(level)
        if not conditions:  # "Low" has no conditions by design
            continue
        results = [_compare(measurements.get(f), op, thr) for f, op, thr in conditions]

        if all(result is True for result in results):
            matched_level = level
            for field, operator, threshold in conditions:
                value = measurements[field]
                triggered.append((field, value))
                reasons.append(_describe_condition(field, operator, threshold, value, level, rule["hazard"]))
            break

        # This level failed. If NO condition was definitely false but some were
        # unknown, the level might have been reached - remember which data we lacked.
        if not any(result is False for result in results):
            for (field, _, _), result in zip(conditions, results):
                if result is None and field not in undetermined:
                    undetermined.append(field)

    return {
        "hazard": rule["hazard"],
        "level": matched_level,
        "triggered_conditions": triggered,
        "reasons": reasons,
        "undetermined_fields": undetermined,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def assess_observation(observation, rules=None):
    """Assess one validated observation and return a risk assessment dict.

    Input : an observation dict in the shared format (validate it first with
            data_loader.validate_observation). Missing measurements must be None.
    Output (stable contract for the frontend):
        {
          "location_id", "location_name", "latitude", "longitude",
          "observed_at", "data_source", "is_simulated",
          "status":       "assessed" | "insufficient_data",
          "risk_level":   "Low"|"Moderate"|"High"|"Critical"|None (None only if insufficient_data),
          "risk_rank":    0..3 (None if insufficient_data),
          "alert":        bool   # True when risk_level >= config.ALERT_MIN_LEVEL
          "primary_hazard": str  # hazard name, or "None"
          "summary":      short headline for lists, e.g. "Critical risk: Severe Wind"
          "hazards":      [{"hazard", "risk_level", "reasons"}, ...] most severe first
          "measurements": all four measurements (None where missing)
          "supporting_measurements": only the measurements that triggered a hazard
          "reasons":      [str, ...] plain-language explanation
          "missing_measurements": [field, ...]
          "limitations":  [str, ...]
          "threshold_set", "disclaimer"
        }
    """
    rules = config.HAZARD_RULES if rules is None else rules
    measurements = {field: observation.get(field) for field in config.MEASUREMENT_FIELDS}
    missing = [field for field, value in measurements.items() if value is None]

    result = {
        "location_id": observation.get("location_id"),
        "location_name": observation.get("location_name"),
        "latitude": observation.get("latitude"),
        "longitude": observation.get("longitude"),
        "observed_at": observation.get("observed_at"),
        "data_source": observation.get("data_source"),
        "source_metadata": observation.get("source_metadata"),
        "is_simulated": observation.get("is_simulated"),
        "measurements": measurements,
        "missing_measurements": missing,
        "threshold_set": config.THRESHOLD_SET_NAME,
        "disclaimer": config.PROTOTYPE_DISCLAIMER,
    }

    limitations = []
    # A simulated observation must always be labelled as such in the output.
    if observation.get("is_simulated"):
        limitations.append("This observation is simulated demonstration data, not a real measurement.")

    # --- Nothing measured at all: refuse to draw any conclusion --------------
    if len(missing) == len(config.MEASUREMENT_FIELDS):
        limitations.append("No measurements are available, so no risk can be assessed.")
        result.update({
            "status": "insufficient_data", "risk_level": None, "risk_rank": None, "alert": False,
            "primary_hazard": config.HAZARD_NONE, "summary": "Insufficient data - no risk assessed",
            "hazards": [], "supporting_measurements": {},
            "reasons": ["No measurements are available for this location."],
            "limitations": limitations,
        })
        return result

    # --- Evaluate every rule --------------------------------------------------
    evaluations = [evaluate_rule(measurements, rule) for rule in rules]

    # Report data gaps that prevented a hazard from being fully ruled in/out.
    for evaluation in evaluations:
        if evaluation["undetermined_fields"]:
            names = ", ".join(config.MEASUREMENT_LABELS[f][0] for f in evaluation["undetermined_fields"])
            limitations.append(f"{evaluation['hazard']} could not be fully evaluated: missing {names}.")
    if missing:
        names = ", ".join(config.MEASUREMENT_LABELS[f][0] for f in missing)
        limitations.append(f"Missing measurements: {names}. The result reflects only the available data.")

    # --- Keep triggered hazards, most severe first ---------------------------
    # sorted() is stable, so equal levels keep the config's rule order (the tie-break).
    triggered = [e for e in evaluations if e["level"] is not None]
    triggered.sort(key=lambda e: config.RISK_RANK[e["level"]], reverse=True)

    if not triggered:
        risk_level, primary = "Low", config.HAZARD_NONE
        reasons = ["No configured hazard threshold was reached by the available measurements."]
        supporting = {}
    else:
        risk_level, primary = triggered[0]["level"], triggered[0]["hazard"]
        reasons = [f"{e['hazard']} - {e['level']}: " + "; ".join(e["reasons"]) for e in triggered]
        # Collect every measurement that contributed to any triggered hazard.
        supporting = {}
        for e in triggered:
            for field, value in e["triggered_conditions"]:
                supporting[field] = value

    rank = config.RISK_RANK[risk_level]
    result.update({
        "status": "assessed",
        "risk_level": risk_level,
        "risk_rank": rank,
        "alert": rank >= config.RISK_RANK[config.ALERT_MIN_LEVEL],
        "primary_hazard": primary,
        "summary": f"{risk_level} risk: {primary}" if triggered else "Low risk: no hazard detected",
        "hazards": [{"hazard": e["hazard"], "risk_level": e["level"], "reasons": e["reasons"]} for e in triggered],
        "supporting_measurements": supporting,
        "reasons": reasons,
        "limitations": limitations,
    })
    return result


def assess_all(observations, rules=None):
    """Assess a list of observations, keeping the input order."""
    return [assess_observation(obs, rules) for obs in observations]


def get_alerts(assessments):
    """Return only assessments with alert=True, most severe first.

    Ties are ordered by location_id so the list is stable between refreshes.
    """
    alerts = [a for a in assessments if a.get("alert")]
    return sorted(alerts, key=lambda a: (-a["risk_rank"], a["location_id"] or ""))
