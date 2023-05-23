# Copyright (C) 2023  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import dataclasses
import datetime
from typing import Any, Dict, Iterable, List, Type, TypeVar, cast
import uuid

from swh.core.api.classes import stream_results
from swh.core.statsd import Statsd
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


_TItem = TypeVar("_TItem")


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
        self.statsd = Statsd(namespace="swh_loader_metadata_journal_client")

    def statsd_timed(self, name: str, tags: Dict[str, Any] = {}):
        """
        Wrapper for :meth:`swh.core.statsd.Statsd.timed`, which uses the standard
        metric name and tag.
        """
        return self.statsd.timed(
            "operation_duration_seconds", tags={"operation": name, **tags}
        )

    def statsd_timing(self, name: str, value: float, tags: Dict[str, Any] = {}) -> None:
        """
        Wrapper for :meth:`swh.core.statsd.Statsd.timing`, which uses the standard
        metric name and tags for loaders.
        """
        self.statsd.timing(
            "operation_duration_seconds", value, tags={"operation": name, **tags}
        )

    def _get_lister(self, lister_id: uuid.UUID) -> Lister:
        if lister_id not in self._listers:
            with self.statsd_timed("get_listers_by_id"):
                (lister,) = self.scheduler.get_listers_by_id([str(lister_id)])
            self._listers[lister.id] = lister
        return self._listers[lister_id]

    def _add_metadata_fetchers(self, fetchers: Iterable[MetadataFetcher]) -> None:
        for fetcher in fetchers:
            if fetcher not in self._added_fetchers:
                self.storage.metadata_fetcher_add([fetcher])
                self._added_fetchers.add(fetcher)

    def _add_metadata_authorities(
        self, authorities: Iterable[MetadataAuthority]
    ) -> None:
        for authority in authorities:
            if authority not in self._added_authorities:
                self.storage.metadata_authority_add([authority])
                self._added_authorities.add(authority)

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
                self.statsd_timed("get_listed_origins")(
                    self.scheduler.get_listed_origins
                ),
                url=origin["url"],
            ):
                self._process_listed_origin(listed_origin)

        with self.statsd_timed("flush_storage"):
            self.storage.flush()

    def _process_listed_origin(
        self,
        listed_origin: ListedOrigin,
    ) -> List[RawExtrinsicMetadata]:
        origin = Origin(url=listed_origin.url)

        lister = self._get_lister(listed_origin.lister_id)

        tags = {
            "lister": lister.name,
            "lister_instance": lister.instance_name,
        }

        fetcher_classes = cast(
            List[Type[BaseMetadataFetcher]], get_fetchers_for_lister(lister.name)
        )
        self.statsd.histogram("metadata_fetchers", len(fetcher_classes), tags=tags)

        now = _now()

        metadata: List[RawExtrinsicMetadata] = []

        for cls in fetcher_classes:
            tags["fetcher"] = cls.FETCHER_NAME

            metadata_fetcher = cls(
                origin=origin,
                lister_name=lister.name,
                lister_instance_name=lister.instance_name,
                credentials=self.metadata_fetcher_credentials,
            )

            with self.statsd_timed("raw_extrinsic_metadata_get"):
                last_metadata = self.storage.raw_extrinsic_metadata_get(
                    target=origin.swhid(),
                    authority=metadata_fetcher.metadata_authority(),
                    after=now - datetime.timedelta(days=self.reload_after_days),
                    limit=1,
                )

            if last_metadata.results:
                # We already have recent metadata; don't load it again.
                self.statsd.increment(
                    "metadata_items_fetched_total",
                    len(last_metadata.results),
                    tags=tags,
                )

                continue

            with self.statsd_timed("get_origin_metadata", tags=tags):
                metadata = list(metadata_fetcher.get_origin_metadata())

            self.statsd.increment(
                "metadata_items_added_total", len(metadata), tags=tags
            )

            with self.statsd_timed("metadata_fetcher_add"):
                self._add_metadata_fetchers({m.fetcher for m in metadata})

            with self.statsd_timed("metadata_authority_add"):
                self._add_metadata_authorities({m.authority for m in metadata})

            with self.statsd_timed("raw_extrinsic_metadata_add"):
                self.storage.raw_extrinsic_metadata_add(metadata)

        return metadata
