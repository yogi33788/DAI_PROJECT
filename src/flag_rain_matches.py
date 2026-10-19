#!/usr/bin/env python3
"""Create transparent metadata-based rain/revised-condition indicators.

Usage:
    python src/flag_rain_matches.py data/raw/ipl_male_json.zip data/processed

These are screening flags, not confirmed weather observations. Verify important
matches with scorecards/reliable reports before making causal claims.
"""
import csv
import json
import sys
import zipfile
from pathlib import Path


def event_name(event):
    return event.get("name", "") if isinstance(event, dict) else str(event or "")


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python src/flag_rain_matches.py INPUT.zip [OUTPUT_DIR]"
        )
    zip_path = Path(sys.argv[1]).expanduser()
    out_dir = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else Path("data/processed")
    if not zip_path.is_file():
        raise SystemExit(f"Input ZIP not found: {zip_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    flags = []
    with zipfile.ZipFile(zip_path) as archive:
        for filename in archive.namelist():
            if not filename.lower().endswith(".json"):
                continue
            try:
                data = json.loads(archive.read(filename))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            info = data.get("info", {})
            event = event_name(info.get("event"))
            if event and event != "Indian Premier League":
                continue

            outcome = info.get("outcome") or {}
            outcome_method = str(outcome.get("method", "")).strip()
            outcome_result = str(outcome.get("result", "")).strip().lower()
            scheduled_overs = to_float(info.get("overs")) or 20.0
            balls_per_over = int(info.get("balls_per_over", 6) or 6)

            innings = data.get("innings", [])
            target_methods = []
            target_overs_values = []
            first_innings_short = False

            for idx, inn in enumerate(innings):
                if inn.get("super_over", False):
                    continue
                target = inn.get("target") or {}
                method = str(target.get("method", "")).strip()
                if method:
                    target_methods.append(method)
                target_overs = to_float(target.get("overs"))
                if target_overs is not None and target_overs < scheduled_overs:
                    target_overs_values.append(target_overs)

                # A first innings shorter than the scheduled quota, not all out,
                # is a possible interruption indicator. It is only a heuristic.
                if idx == 0:
                    legal = 0
                    wickets = 0
                    for over in inn.get("overs", []):
                        for delivery in over.get("deliveries", []):
                            extras = delivery.get("extras") or {}
                            if "wides" not in extras and "noballs" not in extras:
                                legal += 1
                            wickets += len(delivery.get("wickets") or [])
                    quota = int(scheduled_overs * balls_per_over)
                    if legal < quota and wickets < 10 and legal > 0:
                        first_innings_short = True

            method_text = " ".join([outcome_method] + target_methods).lower()
            dls_flag = ("d/l" in method_text) or ("dls" in method_text) or ("duckworth" in method_text)
            revised_target_flag = bool(target_overs_values)
            no_result_flag = "no result" in outcome_result
            shortened_first_innings_flag = first_innings_short

            reasons = []
            if dls_flag:
                reasons.append("DLS/D-L method in metadata")
            if revised_target_flag:
                reasons.append("target overs below scheduled quota")
            if no_result_flag:
                reasons.append("no-result outcome (cause not confirmed)")
            if shortened_first_innings_flag:
                reasons.append("first innings ended below scheduled quota before 10 wickets (heuristic)")

            rain_indicator = bool(dls_flag or revised_target_flag or no_result_flag or shortened_first_innings_flag)
            if dls_flag or revised_target_flag:
                confidence = "strong revised-condition indicator; weather cause still verify"
            elif no_result_flag:
                confidence = "weak: no result does not prove rain"
            elif shortened_first_innings_flag:
                confidence = "weak heuristic: could have another explanation"
            else:
                confidence = "no metadata indicator detected"

            dates = info.get("dates") or []
            teams = info.get("teams") or []
            flags.append({
                "match_id": Path(filename).stem,
                "date": str(dates[0]) if dates else "",
                "season": str(info.get("season", "")),
                "team1": teams[0] if len(teams) > 0 else "",
                "team2": teams[1] if len(teams) > 1 else "",
                "winner": outcome.get("winner", ""),
                "outcome_method": outcome_method,
                "outcome_result": outcome.get("result", ""),
                "dls_method_flag": dls_flag,
                "revised_target_flag": revised_target_flag,
                "revised_target_overs": ";".join(map(str, target_overs_values)),
                "no_result_flag": no_result_flag,
                "shortened_first_innings_flag": shortened_first_innings_flag,
                "rain_indicator_flag": rain_indicator,
                "flag_reason": "; ".join(reasons),
                "confidence_note": confidence,
            })

    flags.sort(key=lambda r: (r["date"], r["match_id"]))
    flags_path = out_dir / "ipl_rain_flags.csv"
    write_csv(flags_path, flags)

    matches_path = out_dir / "ipl_matches.csv"
    if matches_path.exists():
        with matches_path.open(newline="", encoding="utf-8") as f:
            matches = list(csv.DictReader(f))
        flag_by_id = {r["match_id"]: r for r in flags}
        joined = []
        for match in matches:
            flag = flag_by_id.get(match["match_id"], {})
            merged = dict(match)
            for key in (
                "dls_method_flag", "revised_target_flag", "revised_target_overs",
                "no_result_flag", "shortened_first_innings_flag",
                "rain_indicator_flag", "flag_reason", "confidence_note"
            ):
                merged[key] = flag.get(key, "")
            joined.append(merged)
        write_csv(out_dir / "ipl_matches_with_rain_flags.csv", joined)

    print(f"Matches flagged/scanned: {len(flags)}")
    print(f"DLS/D-L method indicators: {sum(r['dls_method_flag'] for r in flags)}")
    print(f"Revised target overs indicators: {sum(r['revised_target_flag'] for r in flags)}")
    print(f"No-result outcomes: {sum(r['no_result_flag'] for r in flags)}")
    print(f"Any screening indicator: {sum(r['rain_indicator_flag'] for r in flags)}")
    print(f"Saved: {flags_path.resolve()}")
    if matches_path.exists():
        print(f"Saved: {(out_dir / 'ipl_matches_with_rain_flags.csv').resolve()}")


if __name__ == "__main__":
    main()
