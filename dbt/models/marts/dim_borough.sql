select '{{ var("release_id") }}' as release_id, borough as borough_key, borough
from unnest(['BRONX', 'BROOKLYN', 'MANHATTAN', 'QUEENS', 'STATEN ISLAND', 'UNKNOWN']) borough
