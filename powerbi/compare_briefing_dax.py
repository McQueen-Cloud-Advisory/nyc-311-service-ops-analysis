"""Compare actual Desktop briefing helper measures with independent reference cases."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

SCENARIOS = dict(zip('ABCDE', (
    'overall', 'brooklyn_dirty', 'queens_dirty', 'empty_borough',
    'activity_week_2026_11_09',
)))
REQUIRED_FIELDS = {
    'release_id', 'scenario', 'priority_label', 'priority_aged_count',
    'priority_aged_display', 'priority_open_count', 'priority_aged_share',
    'priority_within_segment_aged_rate', 'selected_aged_count',
    'selected_open_count', 'snapshot_open_30d_plus', 'oldest_open_age_days',
    'target_misses', 'complete_week_count', 'first_complete_week',
    'last_complete_week', 'nov16_trend_intake', 'nov16_trend_recorded_closures',
    'nov9_trend_intake', 'nov9_trend_recorded_closures',
    'worklist_unfiltered_age_row_count', 'worklist_age_7d_plus_row_count',
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=Path('powerbi/briefing-reference.json'))
    parser.add_argument('--dax-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding='utf-8'))
    expected = {row['scenario']: row for row in reference['scenarios']}
    checks = []
    hashes = {'reference': hashlib.sha256(args.reference.read_bytes()).hexdigest()}
    for section in 'ABCDE':
        file = args.dax_directory / f'{section}.json'
        hashes[section] = hashlib.sha256(file.read_bytes()).hexdigest()
        actual = json.loads(file.read_text(encoding='utf-8-sig'))
        if isinstance(actual, list):
            if len(actual) != 1:
                raise ValueError('Expected one scenario row per query')
            actual = actual[0]
        if set(actual) != REQUIRED_FIELDS:
            raise ValueError(f'{section}: unexpected or missing briefing fields')
        scenario = actual['scenario']
        if scenario != SCENARIOS[section]:
            raise ValueError(f'{section}: expected scenario {SCENARIOS[section]}')
        target = dict(expected[scenario], release_id=reference['release_id'])
        weekly = next(row for row in target['weekly'] if row['week_start'] == '2026-11-09')
        target['nov9_trend_intake'] = weekly['intake']
        target['nov9_trend_recorded_closures'] = weekly['recorded_closures']
        for field, observed in actual.items():
            if field == 'scenario':
                continue
            wanted = target[field]
            tolerance = 1e-6 if field == 'oldest_open_age_days' else 1e-12 if field in {'priority_aged_share', 'priority_within_segment_aged_rate'} else 0
            if isinstance(wanted, (int, float)) and isinstance(observed, (int, float)):
                difference = abs(wanted-observed)
                passed = difference <= tolerance
            else:
                difference = None
                passed = wanted == observed
            checks.append(dict(scenario=scenario, field=field, expected=wanted, actual=observed, difference=difference, tolerance=tolerance, passed=passed))
    result = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), release_id=reference['release_id'],
                  outcome='passed' if all(row['passed'] for row in checks) else 'failed',
                  scope='Executed Desktop DAX briefing measures versus independent Python reference over saved BigQuery release exports',
                  checks_compared=len(checks), checks=checks, input_sha256=hashes,
                  visual_inspection='separate Desktop check')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f"{result['outcome'].upper()}: {len(checks)} briefing comparisons")
    for check in checks:
        if not check['passed']:
            print(check)
    return 0 if result['outcome'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
