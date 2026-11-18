"""Publish recorded mast weather to a loopback-only demo cache."""

import argparse
import asyncio
import csv
from concurrent.futures import Future
from pathlib import Path
from time import sleep

import yaml
from websockets.legacy.server import serve

from server.cached_data_server import CachedDataServer


class LocalCachedDataServer(CachedDataServer):
    """Use the OpenRVDAS cache and protocol with a local-only listener."""

    def __init__(self, port, interval=1):
        self._started = Future()
        super().__init__(port=port, interval=interval, cleanup_interval=1)
        try:
            self._started.result()
        except Exception as error:
            self.quit_flag = True
            self.server_thread.join()
            self.event_loop.close()
            reason = str(error) or 'startup timed out'
            raise RuntimeError(f'Cannot open local cache on port {port}: {reason}') from error

    def _run_websocket_server(self):
        self.event_loop.run_until_complete(self._serve_local())

    async def _serve_local(self):
        # The upstream handler uses the legacy websockets (websocket, path) API.
        try:
            listener = serve(self._serve_websocket_data, '127.0.0.1', self.port)
            server = await asyncio.wait_for(listener, timeout=5)
        except Exception as error:
            self._started.set_exception(error)
            return

        self.port = server.sockets[0].getsockname()[1]
        self._stop = asyncio.Event()
        self._started.set_result(None)
        try:
            await self._stop.wait()
        finally:
            server.close()
            await server.wait_closed()

    def quit(self):
        self.quit_flag = True
        self.event_loop.call_soon_threadsafe(self._stop.set)
        self.server_thread.join()
        self.event_loop.close()


def weather_records(source):
    with source.open(encoding='utf-8') as records:
        messages = (line.partition(' ')[2] for line in records)
        for columns in csv.reader(messages):
            if columns and columns[0] == 'MET':
                yield {'MwxAirTemp': float(columns[3]), 'MwxAirRelHumid': float(columns[4])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path, help='path to console_demo_logger.yaml')
    args = parser.parse_args()
    try:
        config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            parser.error(f'{args.config} must contain a group of settings. Example: port: 18766')
        source = config.get('source')
        if not isinstance(source, str) or not Path(source).is_file():
            parser.error(f'source: saw {source!r}. Expected a path to the mast weather file. '
                         'Example: test/NBP1406/mwx1/raw/NBP1406_mwx1-2014-08-01')
        port = config.get('port', 18766)
        if type(port) is not int or not 1 <= port <= 65535:
            parser.error(f'port: saw {port!r}. Expected a port from 1 to 65535. '
                         'Example: port: 18766')
        cache = LocalCachedDataServer(port)
        try:
            print(f'Console demo cache listening at ws://127.0.0.1:{cache.port}', flush=True)
            for fields in weather_records(Path(source)):
                cache.cache_record({'fields': fields})
                sleep(1)
            print('The demo recording has ended. Run the same command to replay it.')
        finally:
            cache.quit()
    except KeyboardInterrupt:
        print('\nConsole demo stopped.')
    except (OSError, RuntimeError, ValueError, IndexError, yaml.YAMLError) as error:
        parser.exit(1, f'Could not run the console demo: {error}\n')


if __name__ == '__main__':
    main()
