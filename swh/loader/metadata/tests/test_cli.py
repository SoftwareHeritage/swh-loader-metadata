# Copyright (C) 2020-2022  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import tempfile
from typing import List
from unittest.mock import MagicMock

from click.testing import CliRunner
from confluent_kafka import Producer
import yaml

from swh.journal.serializers import value_to_kafka
from swh.loader.metadata.cli import swh_cli_group
from swh.loader.metadata.journal_client import JournalClient


def invoke(
    args: List[str],
    storage=None,
    kafka_server=None,
    kafka_prefix=None,
    kafka_consumer_group=None,
    config=None,
):
    runner = CliRunner()

    config = dict(config or {})

    assert (
        (kafka_server is None)
        == (kafka_prefix is None)
        == (kafka_consumer_group is None)
    )
    if kafka_server:
        config["journal"] = dict(
            brokers=kafka_server,
            group_id=kafka_consumer_group,
            prefix=kafka_prefix,
            stop_on_eof=True,
        )

    with tempfile.NamedTemporaryFile("a", suffix=".yml") as config_fd:
        yaml.dump(config, config_fd)
        config_fd.seek(0)
        args = ["metadata-loader", "-C" + config_fd.name] + list(args)
        result = runner.invoke(swh_cli_group, args, catch_exceptions=False)
    return result


def test_journal_client(
    mocker,
    swh_storage,
    swh_storage_backend_config,
    swh_scheduler,
    swh_scheduler_config,
    kafka_server,
    kafka_prefix,
    kafka_consumer_group,
) -> None:
    origin_url = "http://example.org/repo.git"
    producer = Producer(
        {
            "bootstrap.servers": kafka_server,
            "client.id": "test metadata loader origin producer",
            "acks": "all",
        }
    )
    origin = {"url": origin_url}
    value = value_to_kafka(origin)
    topic = f"{kafka_prefix}.origin"
    producer.produce(topic=topic, key=b"bogus-origin", value=value)
    producer.flush()

    config = {
        "scheduler": swh_scheduler_config,
        "storage": swh_storage_backend_config,
        "metadata_fetcher_credentials": None,
        "reload_after_days": 42,
    }

    storage = MagicMock(wraps=swh_storage)
    mocker.patch("swh.storage.get_storage", return_value=storage)
    scheduler = MagicMock(wraps=swh_scheduler)
    mocker.patch("swh.scheduler.get_scheduler", return_value=scheduler)
    kwargs = dict(
        scheduler=scheduler,
        storage=storage,
        metadata_fetcher_credentials={},
        reload_after_days=42,
    )
    journal_client = JournalClient(**kwargs)  # type: ignore[arg-type]
    journal_client = MagicMock(wraps=journal_client)
    JournalClient_mock = mocker.patch(
        "swh.loader.metadata.journal_client.JournalClient", return_value=journal_client
    )
    result = invoke(
        ["journal-client"],
        kafka_server=kafka_server,
        kafka_prefix=kafka_prefix,
        kafka_consumer_group=kafka_consumer_group,
        config=config,
    )
    assert result.exit_code == 0, result.output
    assert result.output == "Processed 1 message(s).\nDone.\n"

    # Check the client was correctly initialized
    JournalClient_mock.assert_called_once_with(**kwargs)
    journal_client.process_journal_objects.assert_called_once_with(
        {"origin": [{"url": origin_url}]}
    )

    # Smoke check of the client's functionality
    scheduler.get_listed_origins.assert_called_once_with(
        url=origin_url, page_token=None
    )
