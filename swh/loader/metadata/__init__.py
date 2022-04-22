# Copyright (C) 2019-2022  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import pkg_resources

try:
    __version__ = pkg_resources.get_distribution("swh.loader.metadata").version
except pkg_resources.DistributionNotFound:
    __version__ = "devel"


USER_AGENT_TEMPLATE = "Software Heritage Metadata Loader (%s)"
USER_AGENT = USER_AGENT_TEMPLATE % __version__
