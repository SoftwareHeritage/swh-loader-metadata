# Copyright (C) 2023  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

# WARNING: do not import unnecessary things here to keep cli startup time under
# control
import click

from swh.core.cli import CONTEXT_SETTINGS
from swh.core.cli import swh as swh_cli_group


@swh_cli_group.group(name="metadata-loader", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--config-file",
    "-C",
    default=None,
    type=click.Path(
        exists=True,
        dir_okay=False,
    ),
    help="Configuration file.",
)
@click.pass_context
def metadata_loader_cli_group(ctx, config_file):
    """Software Heritage Metadata Loader.

    The Indexer is used to mine the content of the archive and extract derived
    information from archive source code artifacts.

    """
    from swh.core import config

    ctx.ensure_object(dict)
    conf = config.read(config_file)
    ctx.obj["config"] = conf


@metadata_loader_cli_group.command("journal-client")
@click.pass_context
@click.option(
    "--stop-after-objects",
    "-m",
    default=None,
    type=int,
    help="Maximum number of objects to replay. Default is to run forever.",
)
def journal_client(ctx, stop_after_objects: int) -> None:
    """Load metadata from origins not visited for a while.

    Required configuration keys:

    * ``scheduler``
    * ``journal``
    * ``storage``
    * ``reload_after_days``, the number of days such that, if there is already metadata
      less old than this, then metadata is not loaded again
    * ``metadata_fetcher_credentials``, in the same format as for loaders and listers,
      possibly empty
    """
    from swh.journal.client import get_journal_client
    from swh.loader.metadata.journal_client import JournalClient
    from swh.scheduler import get_scheduler
    from swh.storage import get_storage

    config = ctx.obj["config"]

    for key in ("scheduler", "journal", "storage", "reload_after_days"):
        if not config.get(key):
            raise ValueError(f"{key} not configured")
    for key in ("metadata_fetcher_credentials",):
        if key not in config:
            raise ValueError(f"{key} not configured")

    scheduler = get_scheduler(**config["scheduler"])
    storage = get_storage(**config["storage"])

    metadata_fetcher_credentials = config["metadata_fetcher_credentials"] or {}
    reload_after_days = int(config["reload_after_days"])

    journal_cfg = config["journal"]
    journal_cfg["stop_after_objects"] = stop_after_objects or journal_cfg.get(
        "stop_after_objects"
    )

    client = get_journal_client(
        cls="kafka",
        object_types=["origin"],
        **journal_cfg,
    )
    worker = JournalClient(
        scheduler=scheduler,
        storage=storage,
        metadata_fetcher_credentials=metadata_fetcher_credentials,
        reload_after_days=reload_after_days,
    )
    nb_messages = 0
    try:
        nb_messages = client.process(worker.process_journal_objects)
        print(f"Processed {nb_messages} message(s).")
    except KeyboardInterrupt:
        ctx.exit(0)
    else:
        print("Done.")
    finally:
        client.close()
