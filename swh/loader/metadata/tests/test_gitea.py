# Copyright (C) 2022  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import datetime
from pathlib import Path
from typing import Type

import pkg_resources

from swh.loader.core.metadata_fetchers import MetadataFetcherProtocol
from swh.loader.metadata import __version__
from swh.loader.metadata.gitea import GiteaMetadataFetcher
from swh.model.model import (
    MetadataAuthority,
    MetadataAuthorityType,
    MetadataFetcher,
    Origin,
    RawExtrinsicMetadata,
)

from .test_base import DummyLoader

ORIGIN = Origin("https://codeberg.org/ForgeFed/ForgeFed")
FORKED_ORIGIN = Origin("https://codeberg.org/_ZN3val/ForgeFed")

METADATA_AUTHORITY = MetadataAuthority(
    type=MetadataAuthorityType.FORGE, url="https://codeberg.org"
)


def expected_metadata(dt, datadir):
    data_file_path = Path(datadir) / "https_codeberg.org/api_v1_repos_ForgeFed_ForgeFed"
    with data_file_path.open("rb") as fd:
        expected_metadata_bytes = fd.read()
    return RawExtrinsicMetadata(
        target=ORIGIN.swhid(),
        discovery_date=dt,
        authority=METADATA_AUTHORITY,
        fetcher=MetadataFetcher(name="swh.loader.metadata.gitea", version=__version__),
        format="gitea-repository-json",
        metadata=expected_metadata_bytes,
    )


def test_type() -> None:
    # check with mypy
    fetcher_cls: Type[MetadataFetcherProtocol]
    fetcher_cls = GiteaMetadataFetcher
    print(fetcher_cls)

    # check at runtime
    fetcher = GiteaMetadataFetcher(
        ORIGIN,
        credentials=None,
        lister_name="gitea",
        lister_instance_name="gitea",
    )
    assert isinstance(fetcher, MetadataFetcherProtocol)


def test_gitea_metadata(datadir, requests_mock_datadir, mocker):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    mocker.patch("swh.loader.metadata.base.now", return_value=now)

    fetcher = GiteaMetadataFetcher(
        ORIGIN, credentials=None, lister_name="gitea", lister_instance_name="gitea"
    )

    assert fetcher.get_origin_metadata()[0] == expected_metadata(now, datadir)
    assert fetcher.get_origin_metadata() == [expected_metadata(now, datadir)]
    assert fetcher.get_parent_origins() == []

    # Need to make sure '/' in the project ID was encoded as %2F; as
    # requests_mock_datadir does not tell the difference (because it uses urlunquote,
    # which decodes it)
    assert len(requests_mock_datadir.request_history) == 1
    assert (
        requests_mock_datadir.request_history[0].url
        == "https://codeberg.org/api/v1/repos/ForgeFed/ForgeFed"
    )


def test_gitea_metadata_fork(datadir, requests_mock_datadir, mocker):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    mocker.patch("swh.loader.metadata.base.now", return_value=now)

    fetcher = GiteaMetadataFetcher(
        FORKED_ORIGIN,
        credentials=None,
        lister_name="gitea",
        lister_instance_name="gitea",
    )

    assert fetcher.get_parent_origins() == [ORIGIN]


def test_gitea_metadata_from_loader(
    swh_storage, mocker, datadir, requests_mock_datadir
):
    # Fail early if this package is not fully installed
    assert "gitea" in {
        entry_point.name
        for entry_point in pkg_resources.iter_entry_points("swh.loader.metadata")
    }

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    mocker.patch("swh.loader.metadata.base.now", return_value=now)

    loader = DummyLoader(
        storage=swh_storage,
        origin_url=ORIGIN.url,
        lister_name="gitea",
        lister_instance_name="gitea",
    )
    loader.load()

    assert swh_storage.raw_extrinsic_metadata_get(
        ORIGIN.swhid(), METADATA_AUTHORITY
    ).results == [expected_metadata(now, datadir)]
