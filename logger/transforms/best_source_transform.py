#!/usr/bin/env python3

"""Select the best currently healthy source for each configured role."""

import logging
from typing import Union

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord


class BestSourceTransform(Transform):
    """Add best-source values and provenance to structured records."""

    def __init__(self, roles: dict, return_after: float = 30,
                 bad_flags: list | None = None, **kwargs):
        super().__init__(**kwargs)
        if return_after < 0:
            raise ValueError('return_after must not be negative')

        self.roles = roles
        for role, config in roles.items():
            sources = config.get('sources', [])
            timeout = config.get('timeout')
            if not sources:
                raise ValueError(f'{role} must configure at least one source')
            if timeout is None or timeout < 0:
                raise ValueError(f'{role} timeout must not be negative')

        self.return_after = return_after
        self.bad_flags = set(bad_flags if bad_flags is not None else [3, 4, 9])
        self.latest = {}
        self.selected = {role: None for role in roles}
        self.primary_healthy_since = {role: None for role in roles}
        self.primary_last_update = {role: None for role in roles}

    def transform(self, record: Union[DASRecord, dict]):
        """Add the selected value, source name, and age to *record*."""
        if not self.can_process_record(record):
            return self.digest_record(record)

        if isinstance(record, DASRecord):
            timestamp = record.timestamp
            fields = record.fields
        else:
            if 'timestamp' not in record or 'fields' not in record:
                raise ValueError('dict records require timestamp and fields')
            timestamp = record['timestamp']
            fields = record['fields']

        for config in self.roles.values():
            for source in config['sources']:
                if source in fields:
                    self.latest[source] = (fields[source], timestamp,
                                           fields.get(f'{source}_QC'))

        for role, config in self.roles.items():
            self._select(role, config, timestamp, fields)
        return record

    def _healthy(self, source, timestamp, timeout):
        latest = self.latest.get(source)
        return (latest is not None and
                timestamp - latest[1] <= timeout and
                latest[2] not in self.bad_flags)

    def _select(self, role, config, timestamp, fields):
        sources = config['sources']
        timeout = config['timeout']
        primary = sources[0]
        healthy = [source for source in sources
                   if self._healthy(source, timestamp, timeout)]
        previous = self.selected[role]

        if primary in healthy:
            healthy_since = self.primary_healthy_since[role]
            latest_timestamp = self.latest[primary][1]
            if (healthy_since is None or
                    (self.primary_last_update[role] is not None and
                     latest_timestamp - self.primary_last_update[role] > timeout)):
                self.primary_healthy_since[role] = latest_timestamp
            self.primary_last_update[role] = latest_timestamp
        else:
            self.primary_healthy_since[role] = None

        chosen = healthy[0] if healthy else None
        if previous and previous != primary and previous in healthy:
            healthy_since = self.primary_healthy_since[role]
            ready = (primary in healthy and healthy_since is not None and
                     timestamp - healthy_since >= self.return_after)
            if not ready:
                chosen = previous

        self.selected[role] = chosen
        if chosen is None:
            fields.pop(role, None)
            fields.pop(f'{role}_age', None)
            fields[f'{role}_source'] = 'none'
        else:
            value, source_timestamp, _ = self.latest[chosen]
            fields[role] = value
            fields[f'{role}_source'] = chosen
            fields[f'{role}_age'] = timestamp - source_timestamp

        if previous is not None and previous != chosen:
            age = timestamp - self.latest[previous][1]
            logging.warning('%s: switched from %s to %s (%s %.1f s old)',
                            role, previous, chosen or 'none', previous, age)
