-- Golden cases: source wall-clock subtraction would incorrectly return 2 hours.
with examples as (
    select 'spring_forward' as example,
        timestamp(datetime '2026-03-08 01:30:00', 'America/New_York') as created_at,
        timestamp(datetime '2026-03-08 03:30:00', 'America/New_York') as closed_at,
        1.0 as expected_hours
    union all
    select 'fall_back',
        timestamp(datetime '2026-11-01 00:30:00', 'America/New_York'),
        timestamp(datetime '2026-11-01 02:30:00', 'America/New_York'),
        3.0
)
select * from examples
where abs(timestamp_diff(closed_at, created_at, microsecond) / 3600000000.0 - expected_hours) > 0.000001
