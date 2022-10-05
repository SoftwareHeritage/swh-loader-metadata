# Copyright (C) 2022 The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import datetime

import pytest

from swh.loader.core.loader import BaseLoader
from swh.loader.metadata.base import BaseMetadataFetcher
from swh.model.model import (
    MetadataAuthority,
    MetadataAuthorityType,
    MetadataFetcher,
    Origin,
    RawExtrinsicMetadata,
)
import swh.storage.exc

ORIGIN = Origin(url="some-url")

METADATA_AUTHORITY = MetadataAuthority(
    type=MetadataAuthorityType.FORGE, url="http://example.org/"
)
REMD = RawExtrinsicMetadata(
    target=ORIGIN.swhid(),
    discovery_date=datetime.datetime.now(tz=datetime.timezone.utc),
    authority=METADATA_AUTHORITY,
    fetcher=MetadataFetcher(
        name="test fetcher",
        version="0.0.1",
    ),
    format="test-format",
    metadata=b'{"foo": "bar"}',
)


class DummyLoader(BaseLoader):
    """Base Loader to overload and simplify the base class (technical: to avoid repetition
    in other *Loader classes)"""

    visit_type = "git"

    def __init__(self, storage, *args, **kwargs):
        super().__init__(storage, *args, **kwargs)

    def cleanup(self):
        pass

    def prepare(self, *args, **kwargs):
        pass

    def fetch_data(self):
        pass

    def get_snapshot_id(self):
        return None

    def store_data(self):
        pass


class DummyMetadataFetcher(BaseMetadataFetcher):
    SUPPORTED_LISTERS = {"fake-lister"}
    FETCHER_NAME = "dummy"

    def __init__(self, origin, credentials, lister_name, lister_instance_name):
        pass

    def get_origin_metadata(self):
        return [REMD]

    def get_parent_origins(self):
        return []


def test_load(swh_storage, mocker):
    mocker.patch(
        "swh.loader.core.metadata_fetchers._fetchers",
        return_value=[DummyMetadataFetcher],
    )

    loader = DummyLoader(
        storage=swh_storage,
        origin_url=ORIGIN.url,
        lister_name="fake-lister",
        lister_instance_name="",
    )
    loader.load()

    assert swh_storage.raw_extrinsic_metadata_get(
        ORIGIN.swhid(), METADATA_AUTHORITY
    ).results == [REMD]


def test_load_unknown_lister(swh_storage, mocker):
    mocker.patch(
        "swh.loader.core.metadata_fetchers._fetchers",
        return_value=[DummyMetadataFetcher],
    )

    loader = DummyLoader(
        storage=swh_storage,
        origin_url=ORIGIN.url,
        lister_name="other-lister",
        lister_instance_name="",
    )
    loader.load()

    with pytest.raises(swh.storage.exc.StorageArgumentException):
        swh_storage.raw_extrinsic_metadata_get(ORIGIN.swhid(), METADATA_AUTHORITY)
