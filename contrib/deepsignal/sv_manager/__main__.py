"""Review a cast or write the reviewed product into an operator-selected folder."""
import argparse
import csv
import json
from datetime import datetime, timezone

from .files import export
from .ingest import ingest
from .profile import clean, extend, thin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('review', 'export'))
    parser.add_argument('cast', help='completed cast file')
    parser.add_argument('--mapping', help='column mapping YAML for delimited casts')
    parser.add_argument('--surface-salinity', type=float, help='measured surface salinity in PSU')
    parser.add_argument('--salinity-profile', help='reference CSV with depth_m,s_psu')
    parser.add_argument('--probe-sv', type=float, help='latest measured probe speed in m/s')
    parser.add_argument('--tsg-sv', type=float, help='latest thermosalinograph speed in m/s')
    parser.add_argument('--climatology', help='local reference CSV with depth_m,sv_ms')
    parser.add_argument('--spike-ms', type=float, default=5)
    parser.add_argument('--spike-dz-m', type=float, default=1)
    parser.add_argument('--bin-m', type=float, nargs=3, default=[1, 5, 25])
    parser.add_argument('--taper-m', type=float, default=200)
    parser.add_argument('--pressure-depth-m', type=float, default=1000)
    parser.add_argument('--max-points', type=int, default=1000)
    parser.add_argument('--fmt', choices=('asvp', 'csv', 'template'), default='asvp')
    parser.add_argument('--out-dir', help='existing local export directory')
    parser.add_argument('--template', help='template file for --fmt template')
    a = parser.parse_args()
    if a.action == 'export' and not a.out_dir:
        parser.error('Choose a local folder with --out-dir, for example --out-dir ./exports.')
    try:
        p = ingest(a.cast, mapping=a.mapping, surface_salinity=a.surface_salinity,
                   salinity_profile=a.salinity_profile)
        print(f'Cast {p.source["id"]} ({p.source["type"]}), {len(p.depth_m)} input rows.')
        utc = (datetime.fromtimestamp(p.time, timezone.utc).isoformat()
               if p.time is not None else None)
        print(f'UTC {utc or "missing"}, latitude {p.lat}, longitude {p.lon}.')
        if 'needs SV conversion' in p.reasons:
            parser.exit(1, 'Cast needs SV conversion. Check temperature, salinity and #112.\n')
        p = clean(p, probe_sv=a.probe_sv, tsg_sv=a.tsg_sv, spike_ms=a.spike_ms,
                  spike_dz_m=a.spike_dz_m, bin_m=a.bin_m)
        print(f'Measured to {p.max_cast_depth_m:g} m. Surface: {p.history[-1]["surface"]}.')
        print('Removed samples:', json.dumps(p.history[-1]['removed']))
        p = thin(extend(p, climatology=a.climatology, taper_m=a.taper_m,
                        pressure_depth_m=a.pressure_depth_m), max_points=a.max_points)
        print(f'Extension: {p.extended_from or "none needed"}. Quality {p.quality:.2f}/1.')
        print(f'{len(p.depth_m)} points. Maximum thinning error {p.thinning_error_ms:.6g} m/s.')
        if a.action == 'export':
            print(export(p, a.fmt, a.out_dir, template=a.template))
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f'Check the cast, settings and local folders: {exc}\n')


if __name__ == '__main__':
    main()
