"""Passive OpenRVDAS cast notifications and record-time watch advice."""
import csv
import logging
import math
import re
from copy import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from logger.readers.reader import Reader
from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord

from .files import load_export
from .ingest import ingest, instant, load_mapping, reference
from .profile import Profile, clean, positive

Record = Union[DASRecord, dict, list, None]
LOG = logging.getLogger(__name__)
ROLES = dict(lat='Latitude', lon='Longitude', probe='SV_Probe', tsg='SV_TSG',
             alarm='SV_Alarm', depth='WaterDepth')
RECEIPT = re.compile(r'.+-[0-9a-f]{16}\.(?:asvp|csv|txt)\.json$')


def directory(key, value):
    if not isinstance(value, (str, Path)) or not Path(value).is_dir():
        raise ValueError(f'{key} is {value!r}. Choose an existing local folder, e.g. ./casts.')
    return Path(value)


class SVManagerReader(Reader):
    def __init__(self, drop_dir, follow=False, pattern='*', mapping=None,
                 surface_salinity=None, salinity_profile=None):
        super().__init__()
        self.folder = directory('drop_dir', drop_dir)
        if not isinstance(follow, bool):
            raise ValueError(f'follow is {follow!r}. Use true to watch or false to finish at EOF.')
        if not isinstance(pattern, str) or not pattern or '/' in pattern or '**' in pattern:
            raise ValueError(f'pattern is {pattern!r}. Use a filename pattern, e.g. *.cnv.')
        self.follow = follow
        self.pattern = pattern
        if mapping is not None:
            load_mapping(mapping)
        if surface_salinity is not None and salinity_profile is not None:
            raise ValueError('Choose one: surface_salinity (e.g. 35) or salinity_profile (CSV).')
        if surface_salinity is not None and reading(surface_salinity, 0, 50) is None:
            raise ValueError(f'surface_salinity is {surface_salinity!r}. Use 0 to 50 PSU, e.g. 35.')
        if salinity_profile is not None:
            reference(salinity_profile, 's_psu')
        self.kwargs = dict(mapping=mapping, surface_salinity=surface_salinity,
                           salinity_profile=salinity_profile)
        self.seen = {}
        self.errors = {}
        self.folder_error = None

    def read(self) -> Union[dict, str, None]:
        try:
            files = sorted(p for p in self.folder.iterdir() if p.match(self.pattern))
            self.folder_error = None
        except OSError as exc:
            if self.folder_error != str(exc):
                LOG.warning('Cannot read %s. Check the folder and its permissions: %s',
                            self.folder, exc)
                self.folder_error = str(exc)
            files = []
        for path in files:
            if path.suffix.lower() not in ('.cnv', '.edf', '.csv', '.svp', '.mvp', '.txt'):
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                st = path.stat()
                version = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
                if self.seen.get(path) == version:
                    continue
                p = ingest(path, **self.kwargs)
                after = path.stat()
                if version != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                    continue
            except (ValueError, OSError, csv.Error) as exc:
                if self.errors.get(path) != str(exc):
                    LOG.warning('Cannot read %s. Check the completed cast and retry: %s', path, exc)
                    self.errors[path] = str(exc)
                continue
            self.seen[path] = version
            self.errors.pop(path, None)
            return dict(timestamp=p.time, fields=dict(SVM_NewCast=1, SVM_CastId=p.source['id'],
                        SVM_CastFile=str(path), SVM_CastNotes=p.reasons))
        # An empty string keeps the core listener alive. None signals EOF.
        return '' if self.follow else None


def reading(value, low, high):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if math.isfinite(n) and low <= n <= high else None


def record_time(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    seconds = reading(value, -math.inf, math.inf)
    if seconds is None and isinstance(value, str):
        try:
            return instant(value)
        except ValueError:
            return None
    return seconds


def distance(lat, lon, dest_lat, dest_lon):
    a, b = math.radians(lat), math.radians(dest_lat)
    h = (math.sin((a-b)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon-dest_lon)/2)**2)
    return 12742 * math.asin(math.sqrt(min(1., max(0., h))))


class SVMonitorTransform(Transform):
    def __init__(self, profile=None, export_dir=None, age_h=12, distance_km=50,
                 surface_ms=2, duration_s=600, max_gap_s=120, fields=None):
        super().__init__()
        if profile is not None and export_dir is not None:
            raise ValueError('Choose profile (e.g. cast.csv) or export_dir (e.g. ./exports).')
        self.folder = directory('export_dir', export_dir) if export_dir is not None else None
        self.pinned = None
        self.active = None
        if isinstance(profile, Profile):
            self.active = profile
        elif profile is not None:
            if not isinstance(profile, (str, Path)):
                raise ValueError(f'profile is {profile!r}. Use a path, e.g. cast.asvp.json.')
            self.pinned = Path(profile)
        for key, n, example in [('age_h', age_h, 12), ('distance_km', distance_km, 50),
                                ('surface_ms', surface_ms, 2), ('duration_s', duration_s, 600),
                                ('max_gap_s', max_gap_s, 120)]:
            positive(key, n, example)
        self.age_h, self.km, self.ms = age_h, distance_km, surface_ms
        self.duration, self.gap = duration_s, max_gap_s
        if fields is None:
            fields = {}
        if not isinstance(fields, dict) or fields.keys() - ROLES.keys() or not all(
                isinstance(v, str) and v.strip() for v in fields.values()):
            raise ValueError(f'fields is {fields!r}. Map roles to field names, e.g. probe: BowSV.')
        self.roles = ROLES | fields
        self.version = self.last = self.since = self.last_surface = None
        self.samples = {}
        self.issue = ''
        self._refresh()

    def _refresh(self):
        if self.pinned is None and self.folder is None:
            return
        try:
            side = self.pinned
            if side is None:
                choices = ((f.stat().st_mtime_ns, f) for f in self.folder.iterdir()
                           if RECEIPT.fullmatch(f.name) and not f.is_symlink())
                side = max(choices, default=(0, None))[1]
            if side is None:
                self.active = self.version = None
                self.issue = 'Select a profile or complete a local export.'
                return
            version = (side, side.stat().st_mtime_ns)
            if self.version != version:
                self.active = (load_export(side) if side.suffix == '.json'
                               else clean(ingest(side)))
                self.version = version
                self.since = self.last_surface = None
            self.issue = ''
        except (OSError, ValueError, TypeError, KeyError, csv.Error) as exc:
            self.active = self.version = None
            issue = f'Check the selected receipt and its export: {exc}'
            if issue != self.issue:
                LOG.warning('%s', issue)
            self.issue = issue

    def _inputs(self, now, fields):
        limits = dict(lat=(-90, 90), lon=(-180, 180), depth=(0, 12000),
                      probe=(1400, 1650), tsg=(1400, 1650))
        if now is None or self.last is not None and now < self.last:
            self.samples.clear()
            self.since = self.last_surface = None
        self.last = now
        values, missing = {}, []
        for role, key in self.roles.items():
            if key in fields and now is not None:
                raw = fields[key]
                if role == 'alarm':
                    value = int(raw) if raw in (0, 1, '0', '1') else None
                else:
                    value = reading(raw, *limits[role])
                self.samples[role] = now, value
            if role not in self.samples:
                values[role] = None
                missing.append(f'{key} missing')
                continue
            stamp, value = self.samples[role]
            age = now - stamp
            if value is None:
                missing.append(f'{key} invalid {age:g} s ago')
            elif age > self.gap:
                unit = {'probe': 'm/s', 'tsg': 'm/s', 'lat': 'deg', 'lon': 'deg',
                        'depth': 'm', 'alarm': '(alarm state)'}[role]
                missing.append(f'{key} stale, last {value:g} {unit}, {age:g} s ago')
                value = None
            values[role] = value
        return values, missing

    def _advice(self, now, fields):
        self._refresh()
        v, missing = self._inputs(now, fields)
        p = self.active
        out = dict(SVM_Age_h=None, SVM_Distance_km=None, SVM_SurfaceDiff_ms=None,
                   SVM_Quality=p.quality if p else None, SVM_CastAdvice=0)
        if not p:
            out.update(SVM_CastAdvice=1, SVM_CastAdviceText='Active profile missing. ' +
                       (self.issue or 'Select a verified local export.'))
            return out
        reasons = []
        if now is not None and p.time is not None and now >= p.time:
            age = (now-p.time)/3600
            out['SVM_Age_h'] = age
            if age > self.age_h:
                reasons.append(f'profile is {age:.1f} h old (limit {self.age_h:g} h)')
        else:
            missing.append('valid record or cast time missing')
        if None not in (p.lat, p.lon, v['lat'], v['lon']):
            km = distance(p.lat, p.lon, v['lat'], v['lon'])
            out['SVM_Distance_km'] = km
            if km > self.km:
                reasons.append(f'ship is {km:.1f} km from cast (limit {self.km:g} km)')
        elif p.lat is None or p.lon is None:
            missing.append('cast position missing')
        role = 'probe' if v['probe'] is not None else 'tsg'
        if v[role] is not None and p.depth_m and p.depth_m[0] == 0 and p.sv_ms[0] is not None:
            diff = abs(v[role]-p.sv_ms[0])
            out['SVM_SurfaceDiff_ms'] = diff
            observed = self.samples[role][0]
            if diff <= self.ms:
                self.since = None
            elif self.since is None or not 0 <= observed-self.last_surface <= self.gap:
                self.since = observed
            self.last_surface = observed
            if self.since is not None and observed-self.since >= self.duration:
                reasons.append(f'surface sound speed has moved {diff:.1f} m/s '
                               f'(limit {self.ms:.1f} m/s for {self.duration/60:g} min)')
        else:
            self.since = self.last_surface = None
            if not p.depth_m or p.depth_m[0] != 0 or p.sv_ms[0] is None:
                missing.append('cast surface speed missing')
        if v['alarm'] == 1:
            reasons.append('sound-speed alarm active, check the probe and thermosalinograph')
        if (v['depth'] is not None and p.extended_from == 'climatology'
                and v['depth'] > p.max_cast_depth_m):
            reasons.append(f'water depth {v["depth"]:g} m exceeds cast depth '
                           f'{p.max_cast_depth_m:g} m, using climatology')
        text = 'New cast advised: ' + ' and '.join(reasons) if reasons else 'No cast trigger.'
        location = ''
        if p.lat is not None and p.lon is not None:
            location = (f' at {abs(p.lat):g} {"N" if p.lat >= 0 else "S"} '
                        f'{abs(p.lon):g} {"E" if p.lon >= 0 else "W"}')
        text += f' Last cast {p.source["id"]}{location}.'
        if missing:
            text += ' Check inputs: ' + ', '.join(missing) + '.'
        out.update(SVM_CastAdvice=int(bool(reasons)), SVM_CastAdviceText=text)
        return out

    def transform(self, record: Record) -> Record:
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        if isinstance(record, dict):
            fields = record.get('fields', {})
            advice = self._advice(record_time(record.get('timestamp')), fields)
            return record | {'fields': fields | advice}
        if isinstance(record, DASRecord):
            result = copy(record)
            advice = self._advice(record_time(record.timestamp), record.fields)
            result.fields = record.fields | advice
            return result
        raise ValueError('Provide a DASRecord or a dictionary with timestamp and fields.')
