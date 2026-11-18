# Component catalog

The DeepSignal component catalog turns the installed OpenRVDAS readers, writers,
and transforms into machine-readable forms. It walks the component package
folders rather than maintaining a second component list. Import failures are
reported as availability data, so an optional integration cannot prevent the
rest of the catalog from loading.

## Commands

```console
python -m contrib.deepsignal.catalog build > catalog.json
python -m contrib.deepsignal.catalog show UDPReader
python -m contrib.deepsignal.catalog check path/to/cruise.yaml
```

The Python facade exposes `catalog()`, `schema(class_name)`, and
`check_component(entry)`. These functions return JSON-serializable dictionaries
and do not print, prompt, or modify configuration. YAML configuration is loaded
only with `yaml.safe_load`.

## Coverage

| Kind | Package walked | Form content |
| --- | --- | --- |
| Reader | `logger.readers` | Constructor settings, defaults, descriptions, and required settings |
| Writer | `logger.writers` | Constructor settings, defaults, descriptions, and required settings |
| Transform | `logger.transforms` | Constructor settings, defaults, descriptions, and required settings |

Each catalog entry includes its class name, import module, kind, first
docstring paragraph, availability, constructor parameters, and JSON Schema.
Unknown annotations use a string form and say that the type was not declared.
`guided.yaml` adds technician-friendly labels and examples for common forms
without overriding signature validation.

## Integrity and errors

Checks do not alter input. Every finding names the setting, observed problem,
expectation, and an example. Unknown class and keyword names include a close
match when one exists. Missing optional imports remain visible with their exact
error instead of being guessed or suppressed.
