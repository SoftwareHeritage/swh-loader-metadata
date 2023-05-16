# Copyright (C) 2023  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import datetime
from unittest.mock import MagicMock

import pytest

from swh.loader.metadata import __version__
from swh.loader.metadata.journal_client import JournalClient
from swh.model.model import (
    MetadataAuthority,
    MetadataAuthorityType,
    MetadataFetcher,
    Origin,
    RawExtrinsicMetadata,
)
from swh.scheduler.interface import ListedOrigin, SchedulerInterface
from swh.storage.interface import StorageInterface

NOW = datetime.datetime(2023, 1, 13, 16, 59, 47, tzinfo=datetime.timezone.utc)
RELOAD_AFTER_DAYS = 42
AGE_THRESHOLD = datetime.datetime(2022, 12, 2, 16, 59, 47, tzinfo=datetime.timezone.utc)


def test_origin_no_lister(
    swh_storage: StorageInterface, swh_scheduler: SchedulerInterface
):
    origin_url = "https://example.org/repo.git"
    storage = MagicMock(wraps=swh_storage)
    scheduler = MagicMock(wraps=swh_scheduler)

    journal_client = JournalClient(
        scheduler=scheduler,
        storage=storage,
        metadata_fetcher_credentials={},
        reload_after_days=42,
    )

    journal_client.process_journal_objects({"origin": [{"url": origin_url}]})

    scheduler.get_listed_origins.assert_called_once_with(
        url=origin_url, page_token=None
    )
    scheduler.get_listers_by_id.assert_not_called()
    storage.raw_extrinsic_metadata_get.assert_not_called()
    storage.raw_extrinsic_metadata_add.assert_not_called()


def test_origin_no_known_lister(
    swh_storage: StorageInterface, swh_scheduler: SchedulerInterface
):
    origin_url = "https://example.org/repo.git"
    storage = MagicMock(wraps=swh_storage)
    scheduler = MagicMock(wraps=swh_scheduler)

    journal_client = JournalClient(
        scheduler=scheduler,
        storage=storage,
        metadata_fetcher_credentials={},
        reload_after_days=42,
    )

    lister = swh_scheduler.get_or_create_lister(name="foo", instance_name="bar")
    assert lister.id is not None
    swh_scheduler.record_listed_origins(
        [ListedOrigin(lister_id=lister.id, url=origin_url, visit_type="git")]
    )

    journal_client.process_journal_objects({"origin": [{"url": origin_url}]})

    scheduler.get_listed_origins.assert_called_once_with(
        url=origin_url, page_token=None
    )
    scheduler.get_listers_by_id.assert_called_once_with([str(lister.id)])
    storage.raw_extrinsic_metadata_get.assert_not_called()
    storage.raw_extrinsic_metadata_add.assert_not_called()


def _run_journal_client_github_origin(
    origin_url: str, storage: StorageInterface, scheduler: SchedulerInterface, mocker
):
    origin = Origin(origin_url)
    mocker.patch("swh.loader.metadata.journal_client._now", return_value=NOW)
    mocker.patch("swh.loader.metadata.base._now", return_value=NOW)

    journal_client = JournalClient(
        scheduler=scheduler,
        storage=storage,
        metadata_fetcher_credentials={},
        reload_after_days=RELOAD_AFTER_DAYS,
    )

    lister = scheduler.get_or_create_lister(name="github", instance_name="github")
    assert lister.id is not None
    scheduler.record_listed_origins(
        [ListedOrigin(lister_id=lister.id, url=origin_url, visit_type="git")]
    )

    journal_client.process_journal_objects({"origin": [{"url": origin_url}]})

    scheduler.get_listed_origins.assert_called_once_with(  # type: ignore
        url=origin_url, page_token=None
    )
    scheduler.get_listers_by_id.assert_called_once_with(  # type: ignore
        [str(lister.id)]
    )

    storage.raw_extrinsic_metadata_get.assert_called_once_with(  # type: ignore
        target=origin.swhid(),
        authority=MetadataAuthority(MetadataAuthorityType.FORGE, "https://github.com"),
        after=AGE_THRESHOLD,
        limit=1,
    )


@pytest.mark.parametrize(
    "known_authority,known_fetcher",
    [(True, True), (False, True), (True, False), (False, False)],
)
def test_github_origin__first_time(
    swh_storage: StorageInterface,
    swh_scheduler: SchedulerInterface,
    requests_mock,
    mocker,
    known_authority: bool,
    known_fetcher: bool,
):

    origin_url = "https://github.com/example/test"
    origin = Origin(origin_url)
    storage = MagicMock(wraps=swh_storage)
    scheduler = MagicMock(wraps=swh_scheduler)

    requests_mock.get(
        "https://api.github.com/repos/example/test", text='{"key": "value"}'
    )

    authority = MetadataAuthority(
        type=MetadataAuthorityType.FORGE, url="https://github.com"
    )
    fetcher = MetadataFetcher(name="swh.loader.metadata.github", version=__version__)
    if known_authority:
        swh_storage.metadata_authority_add([authority])
    if known_fetcher:
        swh_storage.metadata_fetcher_add([fetcher])
    _run_journal_client_github_origin(origin_url, storage, scheduler, mocker)

    storage.raw_extrinsic_metadata_add.assert_called_once_with(
        [
            RawExtrinsicMetadata(
                target=origin.swhid(),
                discovery_date=NOW,
                authority=authority,
                fetcher=fetcher,
                format="application/vnd.github.v3+json",
                metadata=b'{"key": "value"}',
            )
        ]
    )


def test_github_origin__after_outdated(
    swh_storage: StorageInterface,
    swh_scheduler: SchedulerInterface,
    requests_mock,
    mocker,
):
    origin_url = "https://github.com/example/test"
    origin = Origin(origin_url)
    storage = MagicMock(wraps=swh_storage)
    scheduler = MagicMock(wraps=swh_scheduler)

    requests_mock.get(
        "https://api.github.com/repos/example/test", text='{"key": "value"}'
    )

    authority = MetadataAuthority(
        type=MetadataAuthorityType.FORGE, url="https://github.com"
    )
    fetcher = MetadataFetcher(name="swh.loader.metadata.github", version=__version__)
    swh_storage.metadata_authority_add([authority])
    swh_storage.metadata_fetcher_add([fetcher])
    swh_storage.raw_extrinsic_metadata_add(
        [
            RawExtrinsicMetadata(
                target=origin.swhid(),
                discovery_date=datetime.datetime(
                    2021, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
                ),
                authority=authority,
                fetcher=fetcher,
                format="application/vnd.github.v3+json",
                metadata=b'{"key": "old value"}',
            )
        ]
    )

    _run_journal_client_github_origin(origin_url, storage, scheduler, mocker)

    storage.raw_extrinsic_metadata_add.assert_called_once_with(
        [
            RawExtrinsicMetadata(
                target=origin.swhid(),
                discovery_date=NOW,
                authority=authority,
                fetcher=fetcher,
                format="application/vnd.github.v3+json",
                metadata=b'{"key": "value"}',
            )
        ]
    )


def test_github_origin__after_recent(
    swh_storage: StorageInterface,
    swh_scheduler: SchedulerInterface,
    requests_mock,
    mocker,
):
    origin_url = "https://github.com/example/test"
    origin = Origin(origin_url)
    storage = MagicMock(wraps=swh_storage)
    scheduler = MagicMock(wraps=swh_scheduler)

    requests_mock.get(
        "https://api.github.com/repos/example/test", text='{"key": "value"}'
    )

    authority = MetadataAuthority(
        type=MetadataAuthorityType.FORGE, url="https://github.com"
    )
    fetcher = MetadataFetcher(name="swh.loader.metadata.github", version=__version__)
    swh_storage.metadata_authority_add([authority])
    swh_storage.metadata_fetcher_add([fetcher])
    swh_storage.raw_extrinsic_metadata_add(
        [
            RawExtrinsicMetadata(
                target=origin.swhid(),
                discovery_date=datetime.datetime(
                    2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
                ),
                authority=authority,
                fetcher=fetcher,
                format="application/vnd.github.v3+json",
                metadata=b'{"key": "old value"}',
            )
        ]
    )

    _run_journal_client_github_origin(origin_url, storage, scheduler, mocker)

    storage.raw_extrinsic_metadata_add.assert_not_called()
