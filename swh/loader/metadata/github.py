# Copyright (C) 2022 The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

"""Metadata fetcher for GitHub."""

import json
import re
from typing import List, Optional, Tuple
import urllib.parse

from swh.lister.github.utils import GitHubSession
from swh.model.model import Origin

from . import USER_AGENT
from .base import BaseMetadataFetcher, InvalidOrigin

HTTP_ACCEPT = "application/vnd.github.v3+json"
"""HTTP header sent on all API requests to GitHub."""

# The format is defined by a well-understood MIME type; we might as well use that.
METADATA_FORMAT = HTTP_ACCEPT
"""Value of the ``format`` field of produced
:class:`swh.model.model.RawExtrinsicMetadata` objects."""

_API_URL = "https://api.github.com/repos{path}"


class GitHubMetadataFetcher(BaseMetadataFetcher):
    FETCHER_NAME = "github"
    SUPPORTED_LISTERS = {"github"}

    _github_session: Optional[GitHubSession] = None

    def github_session(self) -> GitHubSession:
        if self._github_session is None:
            self._github_session = GitHubSession(
                user_agent=USER_AGENT, credentials=self.credentials
            )
        return self._github_session

    def _check_origin(self):
        (scheme, netloc, path, query, fragment) = urllib.parse.urlsplit(self.origin.url)
        if netloc != "github.com":
            # TODO: relax this check when we support self-hosted GitHub instances
            raise InvalidOrigin(f"netloc should be 'github.com', not '{netloc}'")

        if scheme != "https" or not re.match(r"/[^\s/]+/[^\s/]+", path):
            raise InvalidOrigin(f"Unsupported github.com URL: {self.origin.url}")

        if query != "" or fragment != "":
            raise InvalidOrigin(
                f"Unexpected end query or fragment in github.com URL: {self.origin.url}"
            )

    def _get_origin_metadata_bytes(self) -> List[Tuple[str, bytes]]:
        (scheme, netloc, path, query, fragment) = urllib.parse.urlsplit(self.origin.url)
        response = self.github_session().request(_API_URL.format(path=path))
        if response.status_code != 200:
            # TODO: retry
            return []

        metadata_bytes = response.content

        # TODO?: strip API hyperlinks from metadata_bytes to save space?
        # They take 10KB for every repo, or 1KB when compressed by the database server.
        # This means processing metadata_bytes and changing the format, instead of
        # archiving verbatim, though.

        return [(METADATA_FORMAT, metadata_bytes)]

    def get_parent_origins(self) -> List[Origin]:
        parents = []
        for metadata in self.get_origin_metadata():
            if metadata.format != METADATA_FORMAT:
                continue
            data = json.loads(metadata.metadata)
            parent = data.get("parent")
            source = data.get("source")
            if parent is not None:
                parents.append(Origin(url=parent["html_url"]))
                if source is not None and source["html_url"] != parent["html_url"]:
                    parents.append(Origin(url=source["html_url"]))

        return parents
