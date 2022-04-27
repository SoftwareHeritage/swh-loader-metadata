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
from swh.loader.metadata.github import GitHubMetadataFetcher
from swh.model.model import (
    MetadataAuthority,
    MetadataAuthorityType,
    MetadataFetcher,
    Origin,
    RawExtrinsicMetadata,
)

from .test_base import DummyLoader

ORIGIN = Origin("https://github.com/octocat/Hello-World")
FORKED_ORIGIN = Origin("https://github.com/octocat/linguist")
DOUBLE_FORKED_ORIGIN = Origin("https://github.com/jmarlena/linguist")

METADATA_AUTHORITY = MetadataAuthority(
    type=MetadataAuthorityType.FORGE, url="https://github.com"
)


def expected_metadata(dt, datadir):
    data_file_path = Path(datadir) / "https_api.github.com/repos_octocat_Hello-World"
    with data_file_path.open("rb") as fd:
        expected_metadata_bytes = fd.read()
    return RawExtrinsicMetadata(
        target=ORIGIN.swhid(),
        discovery_date=dt,
        authority=METADATA_AUTHORITY,
        fetcher=MetadataFetcher(name="swh.loader.metadata.github", version=__version__),
        format="application/vnd.github.v3+json",
        metadata=expected_metadata_bytes,
    )


def test_type() -> None:
    # check with mypy
    fetcher_cls: Type[MetadataFetcherProtocol]
    fetcher_cls = GitHubMetadataFetcher
    print(fetcher_cls)

    # check at runtime
    fetcher = GitHubMetadataFetcher(
        ORIGIN,
        credentials=None,
        lister_name="github",
        lister_instance_name="",
    )
    assert isinstance(fetcher, MetadataFetcherProtocol)


def test_github_metadata(datadir, requests_mock_datadir, mocker):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    mocker.patch("swh.loader.metadata.base.now", return_value=now)

    fetcher = GitHubMetadataFetcher(
        ORIGIN, credentials=None, lister_name="github", lister_instance_name=""
    )

    assert fetcher.get_origin_metadata() == [expected_metadata(now, datadir)]
    assert fetcher.get_parent_origins() == []


def test_github_metadata_fork(datadir, requests_mock_datadir, mocker):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    mocker.patch("swh.loader.metadata.base.now", return_value=now)

    fetcher = GitHubMetadataFetcher(
        FORKED_ORIGIN, credentials=None, lister_name="github", lister_instance_name=""
    )

    assert fetcher.get_parent_origins() == [
        Origin(url="https://github.com/github/linguist"),
    ]


def test_github_metadata_fork_of_fork(datadir, requests_mock_datadir, mocker):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    mocker.patch("swh.loader.metadata.base.now", return_value=now)

    fetcher = GitHubMetadataFetcher(
        DOUBLE_FORKED_ORIGIN,
        credentials=None,
        lister_name="github",
        lister_instance_name="",
    )

    assert fetcher.get_parent_origins() == [
        Origin(url="https://github.com/octocat/linguist"),
        Origin(url="https://github.com/github/linguist"),
    ]


def test_github_metadata_from_loader(
    swh_storage, mocker, datadir, requests_mock_datadir
):
    # Fail early if this package is not fully installed
    assert "github" in {
        entry_point.name
        for entry_point in pkg_resources.iter_entry_points("swh.loader.metadata")
    }

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    mocker.patch("swh.loader.metadata.base.now", return_value=now)

    loader = DummyLoader(
        storage=swh_storage,
        origin_url=ORIGIN.url,
        lister_name="github",
        lister_instance_name="",
    )
    loader.load()

    assert swh_storage.raw_extrinsic_metadata_get(
        ORIGIN.swhid(), METADATA_AUTHORITY
    ).results == [expected_metadata(now, datadir)]
