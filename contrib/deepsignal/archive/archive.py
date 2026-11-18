"""Compress closed logs and build deterministic shore-transfer bundles."""

from dataclasses import dataclass
import bz2
import datetime as dt
import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


MANIFEST = "MANIFEST.sha256"
SUFFIXES = {"gzip": ".gz", "xz": ".xz", "zstd": ".zst"}
LEVELS = {"gzip": 9, "xz": 9, "zstd": 19}


class VerificationError(RuntimeError):
    """Raised when archived bytes do not match their manifest."""


@dataclass(frozen=True)
class CompressedFile:
    source: Path
    output: Path
    codec: str


@dataclass(frozen=True)
class BundleFile:
    priority: int
    archive: Path
    manifest: Path


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _codec(codec):
    if codec not in ("auto", "gzip", "xz", "zstd"):
        raise ValueError(
            "codec setting saw %r; expected auto, zstd, xz, or gzip; example: xz" % codec)
    if codec == "auto":
        return "zstd" if shutil.which("zstd") else "xz"
    if codec == "zstd" and not shutil.which("zstd"):
        raise ValueError("codec setting saw 'zstd'; expected an installed zstd tool; example: xz")
    return codec


def _compress(data, codec, level=None):
    level = LEVELS[codec] if level is None else level
    if codec == "gzip":
        return gzip.compress(data, compresslevel=level, mtime=0)
    if codec == "xz":
        return lzma.compress(data, format=lzma.FORMAT_XZ, preset=level)
    process = subprocess.run(
        ["zstd", "-q", "--stdout", "--long=27", "-%d" % level], input=data,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if process.returncode:
        raise RuntimeError("zstd failed: %s" % process.stderr.decode("utf-8", "replace").strip())
    return process.stdout


def decompress(path):
    path = Path(path)
    data = path.read_bytes()
    try:
        if path.suffix == ".gz":
            return gzip.decompress(data)
        if path.suffix == ".xz":
            return lzma.decompress(data)
        if path.suffix == ".bz2":
            return bz2.decompress(data)
        if path.suffix == ".zst":
            process = subprocess.run(["zstd", "-q", "-d", "--stdout"], input=data,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if process.returncode:
                raise VerificationError(process.stderr.decode("utf-8", "replace").strip())
            return process.stdout
    except (OSError, EOFError, lzma.LZMAError) as error:
        raise VerificationError("cannot decompress %s: %s" % (path, error)) from error
    raise ValueError(
        "archive setting saw %s; expected .gz, .xz, or .zst; example: data.log.xz" % path)


def _version(codec):
    if codec == "zstd":
        result = subprocess.run(["zstd", "--version"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, check=False)
        return result.stdout.strip()
    return "Python %s" % os.sys.version.split()[0]


def _candidates(root, min_age_s, now=None):
    root = Path(root)
    now = dt.datetime.now(dt.timezone.utc) if now is None else now
    cutoff = now.timestamp() - min_age_s
    today = now.strftime("%Y-%m-%d")
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == MANIFEST or path.suffix in SUFFIXES.values():
            continue
        if today in path.name or path.stat().st_mtime > cutoff:
            continue
        yield path


def _append_manifest(directory, entry):
    with (directory / MANIFEST).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")


def compress_closed(root, codec="auto", level=None, min_age_s=3600,
                    delete_originals=False, out=None):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(
            "root setting saw %s; expected an existing directory; example: /data/raw" % root)
    codec = _codec(codec)
    level = LEVELS[codec] if level is None else level
    results = []
    for source in _candidates(root, min_age_s):
        relative = source.relative_to(root)
        target = ((Path(out).resolve() / relative) if out else source).with_name(
            source.name + SUFFIXES[codec])
        target.parent.mkdir(parents=True, exist_ok=True)
        original = source.read_bytes()
        compressed = _compress(original, codec, level)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(compressed)
        try:
            temporary.replace(target)
            if _sha(decompress(target)) != _sha(original):
                target.unlink(missing_ok=True)
                raise VerificationError("compressed copy does not match %s" % source)
            entry = {"original": source.name, "original_sha256": _sha(original),
                     "original_size": len(original), "compressed": target.name,
                     "compressed_sha256": _sha(compressed), "compressed_size": len(compressed),
                     "codec": codec, "level": level, "tool_version": _version(codec)}
            _append_manifest(target.parent, entry)
            if delete_originals:
                source.unlink()
            results.append(CompressedFile(source, target, codec))
        finally:
            temporary.unlink(missing_ok=True)
    return results


def verify(root):
    checked = 0
    for manifest in sorted(Path(root).rglob(MANIFEST)):
        for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            try:
                entry = json.loads(line)
                archive = manifest.parent / entry["compressed"]
                compressed = archive.read_bytes()
                if _sha(compressed) != entry["compressed_sha256"]:
                    raise VerificationError("compressed sha256 mismatch")
                raw = decompress(archive)
                if _sha(raw) != entry["original_sha256"] or len(raw) != entry["original_size"]:
                    raise VerificationError("original sha256 or size mismatch")
            except (KeyError, OSError, json.JSONDecodeError, VerificationError) as error:
                raise VerificationError("%s line %d: %s" % (manifest, number, error)) from error
            checked += 1
    for manifest in sorted(Path(root).rglob("*.manifest.json")):
        try:
            entry = json.loads(manifest.read_text(encoding="utf-8"))
            archive = manifest.parent / entry["archive"]
            if _sha(archive.read_bytes()) != entry["sha256"]:
                raise VerificationError("compressed sha256 mismatch")
            decompress(archive)
        except (KeyError, OSError, json.JSONDecodeError, VerificationError) as error:
            raise VerificationError("%s: %s" % (manifest, error)) from error
        checked += 1
    return checked


def plan(root, codec="auto", level=None, min_age_s=3600, out=None):
    codec = _codec(codec)
    for source in _candidates(Path(root).resolve(), min_age_s):
        relative = source.relative_to(Path(root).resolve())
        destination = (Path(out) / relative if out else source).with_name(
            source.name + SUFFIXES[codec])
        print("%s -> %s (%s level %s)" %
              (source, destination, codec, LEVELS[codec] if level is None else level))


def _tar_bytes(root, paths):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for path in paths:
            info = tar.gettarinfo(str(path), arcname=str(path.relative_to(root)))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with path.open("rb") as stream:
                tar.addfile(info, stream)
    return output.getvalue()


def bundle(spec, out, codec="auto", now=None):
    if not isinstance(spec, dict):
        raise ValueError(
            "spec setting saw a non-mapping; expected YAML mapping; example: cruise: NBP")
    root = Path(spec.get("root", ".")).resolve()
    cruise = spec.get("cruise")
    if not cruise:
        raise ValueError("cruise setting saw an empty value; expected a name; example: NBP1406")
    codec = _codec(codec)
    stamp = now or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    bundles = spec.get("bundles", [])
    for item in sorted(bundles, key=lambda value: value.get("priority", 99)):
        priority = item.get("priority")
        budget = item.get("budget")
        if priority not in range(1, 6):
            raise ValueError("priority setting saw %r; expected 1 through 5; example: 1" % priority)
        if not isinstance(budget, int) or budget <= 0:
            raise ValueError(
                "budget setting saw %r; expected positive bytes; example: 10485760" % budget)
        selected, used = [], 0
        for pattern in item.get("globs", []):
            for path in sorted(root.glob(pattern)):
                fits = used + path.stat().st_size <= budget
                if path.is_file() and path not in selected and fits:
                    selected.append(path)
                    used += path.stat().st_size
        if not selected:
            continue
        raw = _tar_bytes(root, selected)
        name = "bundle-%s-%s-p%d.tar%s" % (cruise, stamp, priority, SUFFIXES[codec])
        archive = out / name
        archive.write_bytes(_compress(raw, codec))
        manifest = out / (name + ".manifest.json")
        manifest.write_text(json.dumps({"archive": name, "codec": codec, "priority": priority,
                                        "sha256": _sha(archive.read_bytes()),
                                        "files": [str(path.relative_to(root))
                                                  for path in selected]},
                                       indent=2, sort_keys=True) + "\n", encoding="utf-8")
        results.append(BundleFile(priority, archive, manifest))
    return results
