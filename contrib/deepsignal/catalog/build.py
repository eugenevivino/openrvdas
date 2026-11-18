"""Build and query the OpenRVDAS component catalog."""

import ast
import difflib
import importlib
import inspect
import json
import re
import sys
import types
from pathlib import Path

import yaml

_KINDS = {
    'reader': ('logger.readers', 'Reader'),
    'writer': ('logger.writers', 'Writer'),
    'transform': ('logger.transforms', 'Transform'),
}
_BASE_FILES = {'reader.py', 'writer.py', 'transform.py'}
_CACHE = None


def _module_files():
    root = Path(__file__).resolve().parents[3]
    result = []
    for kind, (package, _base) in _KINDS.items():
        directory = root.joinpath(*package.split('.'))
        for path in sorted(directory.glob('*.py')):
            if path.name != '__init__.py':
                result.append((kind, package + '.' + path.stem, path))
    return result


def _base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ''


def component_sources(module_files=None):
    """Return module names and public component classes found in source."""
    files = module_files or _module_files()
    parsed = {}
    roots = set(base for _package, base in _KINDS.values())
    component_names = set(roots)
    changed = True
    for kind, module, path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        parsed[(kind, module, path)] = tree
    while changed:
        changed = False
        for tree in parsed.values():
            for node in tree.body:
                if (isinstance(node, ast.ClassDef) and
                        any(_base_name(base) in component_names
                            for base in node.bases) and
                        node.name not in component_names):
                    component_names.add(node.name)
                    changed = True
    result = {}
    for (_kind, module, _path), tree in parsed.items():
        names = []
        for node in tree.body:
            if (isinstance(node, ast.ClassDef) and not node.name.startswith('_')
                    and node.name in component_names and node.name not in roots):
                names.append(node.name)
        result[module] = names
    return result


def _prepare_namespace(package):
    """Install a namespace package without executing its eager __init__.py."""
    if package in sys.modules and hasattr(sys.modules[package], '__path__'):
        return
    root = Path(__file__).resolve().parents[3]
    module = types.ModuleType(package)
    module.__path__ = [str(root.joinpath(*package.split('.')))]
    module.__package__ = package
    sys.modules[package] = module


def _import_component_module(module_name):
    package = module_name.rsplit('.', 1)[0]
    _prepare_namespace(package)
    return importlib.import_module(module_name)


def _json_default(value):
    if value is inspect.Parameter.empty:
        return None
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return repr(value)


def _annotation_text(annotation):
    if annotation is inspect.Parameter.empty:
        return ''
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace('typing.', '')


def _json_type(annotation, default):
    value = annotation if annotation is not inspect.Parameter.empty else type(default)
    origin = getattr(value, '__origin__', None)
    if value is bool:
        return 'boolean', None
    if value is int:
        return 'integer', None
    if value is float:
        return 'number', None
    if value is str:
        return 'string', None
    if value in (list, tuple) or origin in (list, tuple):
        return 'array', None
    if value is dict or origin is dict:
        return 'object', None
    if default is None or default is inspect.Parameter.empty:
        return 'string', 'Type is not declared; enter a string value.'
    if isinstance(default, bool):
        return 'boolean', None
    if isinstance(default, int):
        return 'integer', None
    if isinstance(default, float):
        return 'number', None
    if isinstance(default, (list, tuple)):
        return 'array', None
    if isinstance(default, dict):
        return 'object', None
    return 'string', None


def _doc_parts(cls_doc, init_doc=''):
    text = inspect.cleandoc(init_doc or cls_doc or '')
    paragraphs = re.split(r'\n\s*\n', text)
    summary = ' '.join(paragraphs[0].split()) if paragraphs else ''
    params = {}
    for line in text.splitlines():
        match = re.match(r'^\s*:param\s+(?:\S+\s+)?(\w+)\s*:\s*(.*)', line)
        if not match:
            match = re.match(r'^\s*(\w+)\s+(?:-|:)??\s{1,}(\S.*)', line)
        if match:
            params[match.group(1)] = ' '.join(match.group(2).split())
    return summary, params


def _required_parameter(name, parameter, description):
    if parameter.default is inspect.Parameter.empty:
        return True
    return (parameter.default is None and
            re.search(r'\bREQUIRED\b', description) is not None)


def _entry_from_class(cls, kind, module, available=True, error=''):
    class_doc = inspect.getdoc(cls) or ''
    init_doc = inspect.getdoc(cls.__init__) or ''
    summary, documented = _doc_parts(class_doc, init_doc)
    properties = {}
    parameters = []
    required = []
    try:
        signature = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        signature = inspect.Signature()
    for name, parameter in signature.parameters.items():
        if name == 'self' or parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD):
            continue
        description = documented.get(name, '')
        json_type, note = _json_type(parameter.annotation, parameter.default)
        if note:
            description = (description + ' ' + note).strip()
        prop = {'type': json_type, 'description': description}
        if parameter.default is not inspect.Parameter.empty:
            prop['default'] = _json_default(parameter.default)
        properties[name] = prop
        is_required = _required_parameter(name, parameter, description)
        if is_required:
            required.append(name)
        parameters.append({
            'name': name,
            'default': (_json_default(parameter.default)
                        if parameter.default is not inspect.Parameter.empty
                        else None),
            'has_default': parameter.default is not inspect.Parameter.empty,
            'type_hint': _annotation_text(parameter.annotation),
            'description': description,
            'required': is_required,
        })
    schema = {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'title': cls.__name__,
        'type': 'object',
        'properties': properties,
        'required': required,
        'additionalProperties': False,
    }
    return {
        'name': cls.__name__, 'module': module, 'kind': kind,
        'description': summary, 'parameters': parameters, 'schema': schema,
        'available': available, 'error': error,
    }


def _ast_default(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def _entry_from_ast(node, kind, module, error):
    init = next((item for item in node.body
                 if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and item.name == '__init__'), None)
    temp = type(node.name, (), {'__doc__': ast.get_docstring(node)})
    entry = _entry_from_class(temp, kind, module, False, error)
    if init:
        args = init.args.args[1:]
        defaults = [inspect.Parameter.empty] * (len(args) - len(init.args.defaults))
        defaults += [_ast_default(value) for value in init.args.defaults]
        props, params, required = {}, [], []
        _summary, documented = _doc_parts(ast.get_docstring(node),
                                          ast.get_docstring(init))
        for arg, default in zip(args, defaults):
            desc = documented.get(arg.arg, '')
            annotation = ast.unparse(arg.annotation) if arg.annotation else ''
            json_type, note = _json_type(inspect.Parameter.empty, default)
            if note:
                desc = (desc + ' ' + note).strip()
            prop = {'type': json_type, 'description': desc}
            if default is not inspect.Parameter.empty:
                prop['default'] = _json_default(default)
            props[arg.arg] = prop
            needed = default is inspect.Parameter.empty or (
                default is None and re.search(r'\bREQUIRED\b', desc))
            if needed:
                required.append(arg.arg)
            params.append({'name': arg.arg,
                           'default': None if default is inspect.Parameter.empty
                           else _json_default(default),
                           'has_default': default is not inspect.Parameter.empty,
                           'type_hint': annotation, 'description': desc,
                           'required': needed})
        entry['parameters'] = params
        entry['schema']['properties'] = props
        entry['schema']['required'] = required
    return entry


def build_catalog(module_files=None):
    """Import all component modules and return a JSON-safe catalog."""
    files = module_files or _module_files()
    sources = component_sources(files)
    components = {}
    modules = {}
    for kind, module_name, path in files:
        names = sources.get(module_name, [])
        try:
            module = _import_component_module(module_name)
            modules[module_name] = {'available': True, 'error': ''}
            for name in names:
                cls = getattr(module, name)
                components[name] = _entry_from_class(cls, kind, module_name)
        except Exception as exc:  # module errors are catalog data, not build errors
            error = '%s: %s' % (type(exc).__name__, exc)
            modules[module_name] = {'available': False, 'error': error}
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            nodes = {node.name: node for node in tree.body
                     if isinstance(node, ast.ClassDef)}
            for name in names:
                components[name] = _entry_from_ast(
                    nodes[name], kind, module_name, error)
    return {'components': dict(sorted(components.items())),
            'modules': dict(sorted(modules.items()))}


def catalog():
    """Return the process-cached component catalog."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build_catalog()
    return _CACHE


def schema(class_name):
    """Return the JSON Schema for one component class."""
    entry = catalog()['components'].get(class_name)
    if entry is None:
        raise KeyError('Unknown component class %s' % class_name)
    return entry['schema']


def _suggest(value, choices):
    match = difflib.get_close_matches(value, choices, n=1, cutoff=0.5)
    return match[0] if match else ''


def check_component(entry):
    """Check one untrusted component mapping and return plain findings."""
    findings = []
    if not isinstance(entry, dict):
        return {'valid': False, 'findings': [
            'Component setting saw %r; expected a mapping; example: '
            '{class: UDPReader, kwargs: {port: 6224}}.' % entry]}
    class_name = entry.get('class')
    components = catalog()['components']
    component = components.get(class_name)
    if component is None:
        suggestion = _suggest(str(class_name), components)
        hint = '; try %s' % suggestion if suggestion else ''
        findings.append("Class setting saw %r; expected a known component%s; "
                        "example: UDPReader." % (class_name, hint))
        return {'valid': False, 'findings': findings}
    module = entry.get('module')
    if module and module != component['module']:
        findings.append("Module setting for %s saw %r; expected %r; example: %s."
                        % (class_name, module, component['module'],
                           component['module']))
    if not component['available']:
        findings.append("Class setting saw %s; expected an available component; "
                        "install its optional dependency. Import error: %s."
                        % (class_name, component['error']))
    kwargs = entry.get('kwargs', {})
    if kwargs is None:
        kwargs = {}
    if not isinstance(kwargs, dict):
        findings.append("Kwargs setting for %s saw %r; expected a mapping; "
                        "example: {port: 6224}." % (class_name, kwargs))
        return {'valid': False, 'findings': findings}
    properties = component['schema']['properties']
    for name in kwargs:
        if name not in properties:
            suggestion = _suggest(str(name), properties)
            hint = '; try %s' % suggestion if suggestion else ''
            findings.append("Setting %s for %s saw an unknown name; expected one "
                            "of %s%s; example: %s."
                            % (name, class_name, ', '.join(properties), hint,
                               next(iter(properties), 'no kwargs')))
    for name in component['schema']['required']:
        if name not in kwargs:
            findings.append("Setting %s for %s saw no value; expected a value; "
                            "example: %s: %s." %
                            (name, class_name, name,
                             6224 if name == 'port' else 'value'))
    return {'valid': not findings, 'findings': findings}


def _component_entries(value):
    if isinstance(value, dict):
        if 'class' in value:
            yield value
        for child in value.values():
            yield from _component_entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from _component_entries(child)


def check_config(data):
    """Check every nested component in a parsed logger configuration."""
    findings = []
    checked = 0
    for entry in _component_entries(data):
        checked += 1
        findings.extend(check_component(entry)['findings'])
    return {'valid': not findings, 'checked': checked, 'findings': findings}


def check_config_file(path):
    """Safely load and check a YAML logger configuration file."""
    with open(path, encoding='utf-8') as stream:
        return check_config(yaml.safe_load(stream))


def write_outputs(directory):
    """Write catalog.json and one schema JSON file per component."""
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    result = catalog()
    (destination / 'catalog.json').write_text(
        json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    schema_dir = destination / 'schemas'
    schema_dir.mkdir(exist_ok=True)
    for name, entry in result['components'].items():
        (schema_dir / (name + '.json')).write_text(
            json.dumps(entry['schema'], indent=2, sort_keys=True) + '\n',
            encoding='utf-8')
    return result
