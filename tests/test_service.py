"""How the feeder runs as a service: its settings, clients, logs and loop."""

import json
import logging
from pathlib import Path
from unittest import mock

import pytest

from feeder import JsonFormatter, Settings, chaptarr_client, serve, settings_from_env

ENV = {
    "CHAPTARR_URL": "http://chaptarr:8789/",
    "CHAPTARR_API_KEY": "test-chaptarr-key",
    "HARDCOVER_TOKEN": "Bearer test-hardcover-token",
}


def json_reply(body):
    reply = mock.MagicMock()
    reply.__enter__.return_value = reply
    reply.read.return_value = json.dumps(body).encode()
    return reply


class TestChaptarrClient:
    def test_when_getting_a_path_sends_the_api_key_to_that_url(self):
        get = chaptarr_client("http://chaptarr:8789/", "test-chaptarr-key")

        with mock.patch(
            "feeder.urllib.request.urlopen", return_value=json_reply([{"id": 1}])
        ) as urlopen:
            books = get("/api/v1/book")

        request = urlopen.call_args.args[0]
        assert request.full_url == "http://chaptarr:8789/api/v1/book"
        assert request.get_header("X-api-key") == "test-chaptarr-key"
        assert books == [{"id": 1}]


class TestSettingsFromEnv:
    def test_given_the_required_variables_uses_the_standard_paths(self):
        settings, config = settings_from_env(ENV)

        assert settings == Settings(
            library_db=Path("/calibre/library/metadata.db"),
            ingest_dir=Path("/calibre/ingest"),
            work_dir=Path("/calibre/feeder/work"),
            report_path=Path("/calibre/feeder/report.json"),
        )
        assert config["interval_seconds"] == 300

    def test_given_a_token_pasted_with_its_bearer_prefix_strips_it(self):
        _, config = settings_from_env(ENV)

        assert config["hardcover_token"] == "test-hardcover-token"

    def test_given_an_interval_uses_it(self):
        _, config = settings_from_env({**ENV, "FEED_INTERVAL_SECONDS": "60"})

        assert config["interval_seconds"] == 60

    def test_given_a_missing_variable_names_it(self):
        env = {key: value for key, value in ENV.items() if key != "CHAPTARR_API_KEY"}

        with pytest.raises(SystemExit, match="CHAPTARR_API_KEY"):
            settings_from_env(env)


class TestJsonFormatter:
    def test_when_formatting_writes_one_json_line_with_the_events_fields(self):
        record = logging.LogRecord(
            "cwa-feeder", logging.INFO, __file__, 1, "fed", None, None
        )
        record.fields = {"hardcover_id": "175780"}

        line = json.loads(JsonFormatter().format(record))

        assert line["level"] == "info"
        assert line["event"] == "fed"
        assert line["hardcover_id"] == "175780"
        assert "time" in line


class StopServing(Exception):
    pass


class TestServe:
    def test_when_a_run_fails_logs_it_and_runs_again_after_the_interval(self):
        runs = mock.Mock(side_effect=[OSError("chaptarr down"), {"held": []}])
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopServing

        with pytest.raises(StopServing):
            serve(runs, interval_seconds=300, sleep=sleep)

        assert runs.call_count == 2
        assert sleeps == [300, 300]
