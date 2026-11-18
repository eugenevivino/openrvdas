"""Sound-speed profile processing. Depth is metres positive down, SV is m/s."""
import heapq
import math
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from itertools import pairwise

BOTTOM = 12000
ARRAYS = ('depth_m', 'sv_ms', 't_c', 's_psu', 'pressure_dbar')


@dataclass
class Profile:
    source: dict
    time: float | None
    lat: float | None
    lon: float | None
    depth_m: list
    sv_ms: list
    t_c: list | None = None
    s_psu: list | None = None
    pressure_dbar: list | None = None
    quality: float = 1.0
    reasons: list = field(default_factory=list)
    max_cast_depth_m: float | None = None
    extended_from: str | None = None
    history: list = field(default_factory=list)
    thinning_error_ms: float = 0.0


def positive(name, value, example):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(f'{name} is {value!r}. Use a positive finite number, e.g. {example}.')


def select(p, indices):
    return replace(p, **{k: [getattr(p, k)[i] for i in indices]
                         for k in ARRAYS if getattr(p, k) is not None})


def clean(p, *, spike_ms=5, spike_dz_m=1, bin_m=(1, 5, 25), probe_sv=None, tsg_sv=None):
    if p.extended_from:
        raise ValueError('Clean the original cast before extending it.')
    positive('spike_ms', spike_ms, 5)
    positive('spike_dz_m', spike_dz_m, 1)
    if not isinstance(bin_m, (tuple, list)) or len(bin_m) != 3:
        raise ValueError(f'bin_m is {bin_m!r}. Supply three widths, for example [1, 5, 25].')
    for size in bin_m:
        positive('bin_m', size, 1)
    args = dict(spike_ms=spike_ms, spike_dz_m=spike_dz_m, bin_m=list(bin_m),
                probe_sv=probe_sv, tsg_sv=tsg_sv)
    counts = dict(depth=0, upcast=0, range=0, spike=0, binned=0)
    peak = -1
    accepted = []
    for i, (z, v) in enumerate(zip(p.depth_m, p.sv_ms, strict=True)):
        if z is None or not 0 <= z <= BOTTOM:
            counts['depth'] += 1
            continue
        if z <= peak:
            counts['upcast'] += 1
            continue
        peak = z
        if v is None or not 1400 <= v <= 1650:
            counts['range'] += 1
            continue
        if accepted:
            last = accepted[-1]
            if z - p.depth_m[last] <= spike_dz_m and abs(v - p.sv_ms[last]) > spike_ms:
                counts['spike'] += 1
                continue
        accepted.append(i)
    if not accepted:
        raise ValueError('No usable downcast sound speeds. Check the columns and SV conversion.')
    keep = []
    previous = None
    for i in accepted:
        z = p.depth_m[i]
        band = 0 if z < 100 else 1 if z < 1000 else 2
        key = (band, math.floor((z - (0, 100, 1000)[band]) / bin_m[band]))
        if key != previous or i == accepted[-1]:
            keep.append(i)
        previous = key
    counts['binned'] = len(accepted) - len(keep)
    q = select(p, keep)
    q.max_cast_depth_m = q.depth_m[-1]
    q.reasons = list(p.reasons)
    rejected = counts['range'] + counts['spike'] + counts['depth']
    if rejected:
        q.quality *= 1 - rejected / (len(accepted) + rejected)
        q.reasons.append(f'{rejected} invalid or spiking samples removed')
    surface = 'measured'
    if q.depth_m[0] > 0:
        surface = 'surface missing'
        for role, sv in [('probe', probe_sv), ('TSG', tsg_sv)]:
            if sv is None:
                continue
            if not isinstance(sv, (float, int)) or not 1400 <= sv <= 1650:
                raise ValueError(f'{role} surface SV is {sv!r}. Use 1400 to 1650 m/s.')
            q.depth_m.insert(0, 0.)
            q.sv_ms.insert(0, sv)
            for key in ARRAYS[2:]:
                if getattr(q, key) is not None:
                    getattr(q, key).insert(0, None)
            surface = f'surface filled from {role}'
            break
        else:
            q.reasons.append(surface)
            q.quality *= 0.9
    q.history = p.history + [dict(step='clean', args=args, removed=counts, surface=surface,
                                  range_ms=[1400, 1650], breaks_m=[100, 1000],
                                  downcast='new maximum depth', bin_sample='first plus endpoint')]
    return q


def ordered(depths):
    return bool(depths) and all(math.isfinite(z) for z in depths) and all(
        a < b for a, b in pairwise(depths))


def interpolate(z, depths, values):
    if not depths[0] <= z <= depths[-1]:
        raise ValueError(f'Reference profile does not cover {z:g} m. Supply a deeper profile.')
    i = max(0, bisect_right(depths, z) - 1)
    if z == depths[i]:
        return values[i]
    return values[i] + (values[i+1]-values[i]) * ((z-depths[i])/(depths[i+1]-depths[i]))


def extend(p, *, climatology=None, taper_m=200, pressure_depth_m=1000):
    from .ingest import reference

    positive('taper_m', taper_m, 200)
    positive('pressure_depth_m', pressure_depth_m, 1000)
    if p.extended_from or not ordered(p.depth_m) or p.max_cast_depth_m != p.depth_m[-1]:
        raise ValueError('Extend a cleaned, increasing cast at its measured endpoint.')
    z0, v0 = p.depth_m[-1], p.sv_ms[-1]
    if z0 == BOTTOM:
        return p
    targets = set(range((int(z0)//25+1)*25, BOTTOM+1, 25))
    args = dict(taper_m=taper_m, pressure_depth_m=pressure_depth_m)
    info = dict(step='extend', args=args, grid_m=25, bottom_m=BOTTOM, join_m=z0)
    quality = p.quality
    if climatology is not None:
        depths, values, source = reference(climatology, 'sv_ms')
        offset = v0 - interpolate(z0, depths, values)
        targets.update(z for z in depths if z0 < z <= BOTTOM)
        extra = sorted(targets)
        speeds = [interpolate(z, depths, values) + offset*math.exp(-(z-z0)/taper_m)
                  for z in extra]
        method = 'climatology'
        args['climatology'] = source['path']
        info.update(reference=source, offset_ms=offset)
    else:
        method = 'gradient then pressure'
        switch = max(z0, min(BOTTOM, pressure_depth_m))
        slope = 0.017
        synthetic_top = any(str(e.get('surface', '')).startswith('surface filled')
                            for e in p.history)
        if len(p.depth_m) - int(synthetic_top) >= 2:
            slope = (v0 - p.sv_ms[-2]) / (z0 - p.depth_m[-2])
        else:
            switch = z0
        if switch > z0:
            targets.add(switch)
        extra = sorted(targets)
        speeds = [v0 + slope*(min(z, switch)-z0) + 0.017*max(z-switch, 0) for z in extra]
        if not 1400 <= v0 + slope*(switch-z0) <= 1750:
            raise ValueError('Deepest gradient gives an implausible extension. Supply climatology.')
        quality *= 0.7
        info.update(deepest_gradient=slope, switch_m=switch, pressure_gradient=0.017)
    optional = {k: getattr(p, k) + [None]*len(extra) for k in ARRAYS[2:]
                if getattr(p, k) is not None}
    return replace(p, depth_m=p.depth_m+extra, sv_ms=p.sv_ms+speeds, extended_from=method,
                   quality=quality, reasons=p.reasons+[f'below {z0:g} m: {method}'],
                   history=p.history+[info], **optional)


def thin(p, *, max_points=1000):
    if type(max_points) is not int or max_points < 2:
        raise ValueError(f'max_points is {max_points!r}. Use an integer at least 2, e.g. 1000.')
    if not ordered(p.depth_m):
        raise ValueError('Clean the cast before thinning.')
    z, v = p.depth_m, p.sv_ms
    kept = {0, len(z)-1}
    if p.extended_from:
        kept.add(z.index(p.max_cast_depth_m))
    if len(kept) > max_points:
        raise ValueError('max_points must retain surface, join and bottom. Use at least 3.')
    queue = []

    def segment(a, b):
        if b - a < 2:
            return
        worst, split = -1., a
        for i in range(a+1, b):
            estimate = v[a] + (v[b]-v[a])*((z[i]-z[a])/(z[b]-z[a]))
            error = abs(v[i]-estimate)
            if error > worst:
                worst, split = error, i
        heapq.heappush(queue, (-worst, split, a, b))

    if len(z) <= max_points:
        kept.update(range(len(z)))
    else:
        for a, b in pairwise(sorted(kept)):
            segment(a, b)
        while queue and len(kept) < max_points and queue[0][0] < 0:
            _, i, a, b = heapq.heappop(queue)
            kept.add(i)
            segment(a, i)
            segment(i, b)
    q = select(p, sorted(kept))
    q.thinning_error_ms = abs(queue[0][0]) if queue else 0.
    q.history = p.history + [dict(step='thin', args=dict(max_points=max_points),
                                  method='largest vertical linear-interpolation error first',
                                  max_error_ms=q.thinning_error_ms)]
    return q
