# Copyright (C) 2019-2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("swh.loader.metadata")
except PackageNotFoundError:
    __version__ = "devel"


USER_AGENT_TEMPLATE = "Software Heritage Metadata Loader (%s)"
USER_AGENT = USER_AGENT_TEMPLATE % __version__
