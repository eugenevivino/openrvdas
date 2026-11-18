# BestSourceTransform

`BestSourceTransform` selects the first healthy sensor for each configured
role, while retaining a backup after failover until the primary has remained
healthy for `return_after` seconds. It uses record timestamps rather than wall
clock time. A source is unhealthy when it is older than its role's `timeout`
or its accompanying `<source>_QC` value is listed in `bad_flags`.

```yaml
class: BestSourceTransform
kwargs:
  roles:
    latitude: {sources: [s330Latitude, gp02Latitude], timeout: 10}
    longitude: {sources: [s330Longitude, gp02Longitude], timeout: 10}
  return_after: 30
  bad_flags: [3, 4, 9]
```

For every role, the transform adds `<role>`, `<role>_source`, and `<role>_age`
to the input record. If no source is healthy it omits the role value and age,
and sets `<role>_source` to `none`. All other fields pass through unchanged.
