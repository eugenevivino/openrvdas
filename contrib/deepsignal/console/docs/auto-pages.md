# Automatic pages

The `auto-pages` module builds useful Bridge, Science, and All fields pages from the fields the ship's cache publishes.

## Turn it on

The console discovers this module automatically; no page file or module setting is needed. Leave the page list empty to show every known page:

```yaml
pages: []
```

To replace an automatic page, save a page file with the same id, for example `public/pages/bridge-auto.yaml`:

```yaml
title: My bridge
tiles:
  - type: number
    label: Heading
    field: S330HeadingTrue
    unit: deg
```

## See it working

Connect the console to the ship's cache and look for **Bridge (auto)**, **Science (auto)**, and **All fields (auto)** in the page tabs. Bridge appears only when a heading or wind field is recognized. Each page says that it was built from published fields, and All fields groups its numeric tiles by logger.

## Limits

The module does not change, rename, or calculate fields. It does not override a ship page or preset with the same id. All fields shows at most 200 numeric fields and reports how many were omitted. Recognition uses field names and cache metadata, so unusual names without useful units or descriptions may not be classified.
