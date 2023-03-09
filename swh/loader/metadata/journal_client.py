# Copyright (C) 2023  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import dataclasses
import datetime
from typing import Dict, Iterable, List, Type, cast
import uuid

from swh.core.api.classes import stream_results
from swh.loader.core.metadata_fetchers import CredentialsType, get_fetchers_for_lister
from swh.loader.metadata.base import BaseMetadataFetcher
from swh.model.model import (
    MetadataAuthority,
    MetadataFetcher,
    Origin,
    RawExtrinsicMetadata,
)
from swh.scheduler.interface import ListedOrigin, Lister, SchedulerInterface
from swh.storage.interface import StorageInterface


def _now() -> datetime.datetime:
    # Used by tests for mocking
    return datetime.datetime.now(tz=datetime.timezone.utc)


@dataclasses.dataclass
class JournalClient:
    scheduler: SchedulerInterface
    storage: StorageInterface
    metadata_fetcher_credentials: CredentialsType
    reload_after_days: int

    def __post_init__(self):
        self._listers = {}
        self._added_fetchers = set()
        self._added_authorities = set()

    def _get_lister(self, lister_id: uuid.UUID) -> Lister:
        if lister_id not in self._listers:
            (lister,) = self.scheduler.get_listers_by_id([str(lister_id)])
            self._listers[lister.id] = lister
        return self._listers[lister_id]

    def _add_metadata_fetchers(self, fetchers: Iterable[MetadataFetcher]) -> None:
        for fetcher in fetchers:
            if fetcher not in self._added_fetchers:
                self.storage.metadata_fetcher_add([fetcher])

    def _add_metadata_authorities(
        self, authorities: Iterable[MetadataAuthority]
    ) -> None:
        for authority in authorities:
            if authority not in self._added_authorities:
                self.storage.metadata_authority_add([authority])

    def process_journal_objects(self, messages: Dict[str, List[Dict]]) -> None:
        """Loads metadata for origins not recently loaded:

        1. reads messages from the origin journal topic
        2. queries the scheduler for a list of listers that produced this origin
           (to guess what type of forge it is)
        3. if it is a forge we can get extrinsic metadata from, check if we got any
           recently, using the storage
        4. if not, trigger a metadata load
        """

        assert set(messages) == {"origin"}, f"Unexpected message types: {set(messages)}"

        for origin in messages["origin"]:

            for listed_origin in stream_results(
                self.scheduler.get_listed_origins, url=origin["url"]
            ):
                self._process_listed_origin(listed_origin)

        self.storage.flush()

    def _process_listed_origin(
        self,
        listed_origin: ListedOrigin,
    ) -> List[RawExtrinsicMetadata]:
        origin = Origin(url=listed_origin.url)
        lister = self._get_lister(listed_origin.lister_id)

        fetcher_classes = cast(
            List[Type[BaseMetadataFetcher]], get_fetchers_for_lister(lister.name)
        )

        now = _now()

        metadata: List[RawExtrinsicMetadata] = []

        for cls in fetcher_classes:
            metadata_fetcher = cls(
                origin=origin,
                lister_name=lister.name,
                lister_instance_name=lister.instance_name,
                credentials=self.metadata_fetcher_credentials,
            )

            last_metadata = self.storage.raw_extrinsic_metadata_get(
                target=origin.swhid(),
                authority=metadata_fetcher.metadata_authority(),
                after=now - datetime.timedelta(days=self.reload_after_days),
                limit=1,
            )

            if last_metadata.results:
                # We already have recent metadata; don't load it again.
                continue

            metadata = list(metadata_fetcher.get_origin_metadata())
            self._add_metadata_fetchers({m.fetcher for m in metadata})
            self._add_metadata_authorities({m.authority for m in metadata})
            self.storage.raw_extrinsic_metadata_add(metadata)

        return metadata
