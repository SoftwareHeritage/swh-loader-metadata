# Copyright (C) 2022  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

"""Metadata loader for Gitea and Gogs.

While both Gitea and Gogs currently return similar formats, they are implemented
as separate classes, to avoid losing provenance information in case they diverge
without notice in the future."""

import json
import logging
import random
import re
from typing import List, Optional, Tuple
import urllib.parse

import requests

from swh.model.model import Origin

from . import USER_AGENT
from .base import BaseMetadataFetcher, InvalidOrigin

HTTP_ACCEPT = "application/json"
"""HTTP header sent on all API requests to GitHub."""

logger = logging.getLogger(__name__)


class _BaseGiteaMetadataFetcher(BaseMetadataFetcher):
    _session: Optional[requests.Session] = None

    METADATA_FORMAT: str
    """Value of the ``format`` field of produced
    :class:`swh.model.model.RawExtrinsicMetadata` objects."""

    api_token: Optional[str]

    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            if len(self.credentials) > 0:
                cred = random.choice(self.credentials)
                username = cred.get("username")
                self.api_token = cred["password"]
                logger.info("Using authentication credentials from user %s", username)
            else:
                # Raises an error on Gogs, or a warning on Gitea
                self.on_anonymous_mode()
                self.api_token = None

            self._session = requests.Session()
            self._session.headers.update(
                {
                    "Accept": HTTP_ACCEPT,
                    "User-Agent": USER_AGENT,
                }
            )

            if self.api_token:
                self._session.headers["Authorization"] = f"token {self.api_token}"

        return self._session

    def on_anonymous_mode(self) -> None:
        raise NotImplementedError(f"{self.__class__.__name__}.on_anonymous_mode()")

    def _check_origin(self):
        (scheme, netloc, path, query, fragment) = urllib.parse.urlsplit(self.origin.url)

        if scheme not in ("http", "https") or not re.match(
            r"/[^\s/]+/[^\s/]+(\.git)?", path
        ):
            raise InvalidOrigin(f"Unsupported Gitea/Gogs URL: {self.origin.url}")

        if query != "" or fragment != "":
            raise InvalidOrigin(
                f"Unexpected end query or fragment in Gitea/Gogs URL: {self.origin.url}"
            )

    def _api_url(self):
        (scheme, netloc, path, query, fragment) = urllib.parse.urlsplit(self.origin.url)
        path = urllib.parse.unquote(path)

        # Normalize it, so only ``:namespace/:project`` is left
        path = path.strip("/")
        if path.endswith(".git"):
            path = path[0:-4]
        assert path.count("/") == 1, f"Unexpected number of / in {path}"

        api_path = f"/api/v1/repos/{path}"

        return urllib.parse.urlunsplit((scheme, netloc, api_path, "", ""))

    def _get_origin_metadata_bytes(self) -> List[Tuple[str, bytes]]:
        response = self.session().get(self._api_url())
        if response.status_code != 200:
            # TODO: retry
            return []

        metadata_bytes = response.content

        return [(self.METADATA_FORMAT, metadata_bytes)]

    def get_parent_origins(self) -> List[Origin]:
        parents = []
        for metadata in self.get_origin_metadata():
            if metadata.format != self.METADATA_FORMAT:
                continue
            data = json.loads(metadata.metadata)
            parent = data.get("parent")
            if parent is not None:
                parents.append(Origin(url=parent["html_url"]))

        return parents


class GiteaMetadataFetcher(_BaseGiteaMetadataFetcher):
    FETCHER_NAME = "gitea"
    SUPPORTED_LISTERS = {"gitea"}
    METADATA_FORMAT = "gitea-repository-json"

    def on_anonymous_mode(self):
        logger.warning(
            "No authentication token set in configuration, using anonymous mode"
        )


class GogsMetadataFetcher(_BaseGiteaMetadataFetcher):
    FETCHER_NAME = "gogs"
    SUPPORTED_LISTERS = {"gogs"}
    METADATA_FORMAT = "gogs-repository-json"

    def on_anonymous_mode(self):
        raise ValueError("No credentials or API token provided")
