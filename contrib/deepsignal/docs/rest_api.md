# DeepSignal read-only REST API

This service exposes CachedDataServer fields without providing any write path. It has **no login or
authorization yet** and binds to localhost (`127.0.0.1:8770`) by default. Do not bind it to a ship LAN
or shore-facing interface until an authentication and authorization design has been selected.

Start it alongside a CachedDataServer on its default websocket port:

```sh
python3 -m contrib.deepsignal.rest_api.server
```

`--host`, `--port`, and `--cds` override the HTTP address, HTTP port, and CDS websocket URL. The API
limits a request to 20 fields, 86,400 seconds of history, and 20,000 returned points. Responses are
UTF-8 and carry `Cache-Control: no-store`.

## Examples

List fields and metadata, fetch current values, or fetch ten minutes of history:

```sh
curl http://127.0.0.1:8770/api/v1/fields
curl 'http://127.0.0.1:8770/api/v1/latest?fields=air_temp,wind_speed'
curl 'http://127.0.0.1:8770/api/v1/series?field=air_temp&seconds=600&max_points=2000'
curl 'http://127.0.0.1:8770/api/v1/series?field=air_temp&seconds=600&format=csv'
curl http://127.0.0.1:8770/api/v1/health
```

MATLAB can read the JSON endpoints directly:

```matlab
latest = webread('http://127.0.0.1:8770/api/v1/latest?fields=air_temp');
```

Python needs only its standard library:

```python
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8770/api/v1/series?field=air_temp&seconds=600") as response:
    series = json.load(response)
```

Series JSON contains `field`, the requested `seconds`, `points` as timestamp/value pairs, and
`decimated`. A value of 1 means no reduction; larger values give the sampling stride. CSV timestamps
are ISO 8601 UTC. Unknown fields return 404, invalid or over-budget queries return 400, and CDS
connection failures return 503.
