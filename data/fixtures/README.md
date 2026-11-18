# Synthetic edge cases

`synthetic_a.json` and `synthetic_b.json` are **fabricated** inputs. They are never
evidence of a historical NYC backlog. They contain 13 fictional request keys and
fixed observation times, so replay does not substitute the current clock.

| Request suffix | Case |
| --- | --- |
| 0001 | Old open request in A; agency-recorded closure in B, on the same key |
| 0002 | Closed exactly at its 24-hour demo target |
| 0003 | Overdue open request |
| 0004 | Immature in A (1 hour) and B (49 hours), against a 72-hour target |
| 0005 | Unknown outcome |
| 0006 | Missing borough maps to UNKNOWN |
| 0007 | Missing creation date; open with unknown age |
| 0008 | Ambiguous New York fall-back timestamp |
| 0009 | Closure before creation |
| 0010 | Fictional category with no target |
| 0011 | Half-open target interval boundary; 48 elapsed hours across fall-back |
| 0012 | Closed status without a recorded closure date |
| 0013 | Recorded closure beyond the observation time |

Expected overall results: A has 6 observed open requests and 3 valid recorded
closures; B has 5 and 4. Both have a target numerator of 3 and denominator of 5.
P90 is 43.2 hours in A and 367.9 hours in B using inclusive linear interpolation.
These are fixture expectations, not public-data findings.

Regenerate from the repository root with
`python -m data.fixtures.build_fixtures`. The generator makes no network calls.
