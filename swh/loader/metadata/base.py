# Copyright (C) 2020-2022 The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

"""Base module for all metadata fetchers, which are called by the Git loader
to get metadata from forges on origins being loaded."""

import datetime
import sys
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple, Type
import urllib.parse

import requests

from swh.model.model import (
    MetadataAuthority,
    MetadataAuthorityType,
    MetadataFetcher,
    Origin,
    RawExtrinsicMetadata,
)

CredentialsType = Optional[Dict[str, Dict[str, List[Dict[str, str]]]]]


class InvalidOrigin(Exception):
    pass


def now() -> datetime.datetime:
    # Used by tests for mocking
    return datetime.datetime.now(tz=datetime.timezone.utc)


class BaseMetadataFetcher:
    """The base class for a Software Heritage metadata fetchers

    Fetchers are hooks used by loader to retrieve extrinsic metadata from
    forges before archiving repositories.

    Each fetcher handles a specific type of forge (not VCS); each fetcher
    class generally matches a lister class, as they use the same APIs.

    Args:
      origin: the origin to retrieve metadata from
      credentials: This is the same format as for :class:`swh.lister.pattern.Lister`:
        dictionary of credentials for all fetchers. The first level
        identifies the fetcher's name, the second level the lister
        instance. The final level is a list of dicts containing the
        expected credentials for the given instance of that fetcher.
      session: optional HTTP session to use to send HTTP requests
    """

    FETCHER_NAME: str
    """The config-friendly name of this fetcher, used to retrieve the first
    level of credentials."""

    SUPPORTED_LISTERS: Set[str]
    """Set of forge types this metadata fetcher supports. The type names are the same
    as the names used by listers themselves.

    Generally, fetchers have a one-to-one matching with listers, in which case
    this is set of ``{FETCHER_NAME}``.
    """

    def __init__(
        self,
        origin: Origin,
        credentials: CredentialsType,
        lister_name: str,
        lister_instance_name: str,
    ):
        if self.FETCHER_NAME is None:
            raise NotImplementedError(f"{self.__class__.__name__}.FETCHER_NAME")
        self.origin = origin
        self._check_origin()
        self._origin_metadata_objects: Optional[List[RawExtrinsicMetadata]] = None
        self._session: Optional[requests.Session] = None

        # Both names do not *have* to match, but they all do for now.
        assert lister_name == self.FETCHER_NAME

        self.credentials = list(
            (credentials or {}).get(lister_name, {}).get(lister_instance_name, [])
        )

    def _make_session(self) -> requests.Session:
        session = requests.Session()
        fetcher = self._metadata_fetcher()
        user_agent = (
            f"Software Heritage Metadata Fetcher ({fetcher.name} {fetcher.version})"
        )
        session.headers["User-Agent"] = user_agent
        return session

    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._make_session()
        return self._session

    def _check_origin(self) -> bool:
        """Raise :exc:`InvalidOrigin` if the origin does not belong to the supported
        forge types of this fetcher."""
        raise NotImplementedError(f"{self.__class__.__name__}._check_origin")

    def _get_origin_metadata_bytes(self) -> List[Tuple[str, bytes]]:
        """Return pairs of ``(format, metadata)``, used to build
        :class:`swh.model.model.RawExtrinsicMetadata` objects."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.get_origin_metadata_bytes"
        )

    def _metadata_authority(self) -> MetadataAuthority:
        """Return information about the metadata authority that issued metadata
        we extract from the given origin"""
        (scheme, netloc, *_) = urllib.parse.urlsplit(self.origin.url)

        assert scheme and netloc, self.origin.url

        # A good default that should work for most, if not all, forges
        forge_url = urllib.parse.urlunsplit(("https", netloc, "", "", ""))
        return MetadataAuthority(
            url=forge_url,
            type=MetadataAuthorityType.FORGE,
        )

    @classmethod
    def _get_package_version(cls) -> str:
        """Return the version of the current loader."""
        module_name = cls.__module__ or ""
        module_name_parts = module_name.split(".")

        # Iterate rootward through the package hierarchy until we find a parent of this
        # loader's module with a __version__ attribute.
        for prefix_size in range(len(module_name_parts), 0, -1):
            package_name = ".".join(module_name_parts[0:prefix_size])
            module = sys.modules[package_name]
            if hasattr(module, "__version__"):
                return module.__version__

        # If this fetcher's class has no parent package with a __version__,
        # it should implement it itself.
        raise NotImplementedError(
            f"Could not dynamically find the version of {module_name}."
        )

    @classmethod
    def _metadata_fetcher(cls) -> MetadataFetcher:
        """Return information about this metadata fetcher"""
        return MetadataFetcher(
            name=cls.__module__,
            version=cls._get_package_version(),
        )

    def get_origin_metadata(self) -> List[RawExtrinsicMetadata]:
        """Return a list of metadata objects for the given origin."""
        if self._origin_metadata_objects is None:
            self._origin_metadata_objects = []
            for (format_, metadata_bytes) in self._get_origin_metadata_bytes():
                self._origin_metadata_objects.append(
                    RawExtrinsicMetadata(
                        target=self.origin.swhid(),
                        discovery_date=now(),
                        authority=self._metadata_authority(),
                        fetcher=self._metadata_fetcher(),
                        format=format_,
                        metadata=metadata_bytes,
                    )
                )

        return self._origin_metadata_objects

    def get_parent_origins(self) -> List[Origin]:
        """If the given origin is a "forge fork" (ie. created with the "Fork" button
        of GitHub-like forges), returns a list of origins it was forked from;
        closest parent first."""
        raise NotImplementedError(f"{self.__class__.__name__}.get_parent_origins")


if TYPE_CHECKING:
    # Makes mypy check BaseMetadataFetcher follows the MetadataFetcherProtocol
    def _f() -> None:
        from swh.loader.core.metadata_fetchers import MetadataFetcherProtocol

        base_metadata_fetcher: Type[MetadataFetcherProtocol]
        base_metadata_fetcher = BaseMetadataFetcher
        print(base_metadata_fetcher)

    del _f
