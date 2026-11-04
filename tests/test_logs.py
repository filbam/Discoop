import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from discoop.api import DiscordAPI
from discoop.attachments import Downloader, FileJob
from discoop.logs import setup_logging, teardown_logging
from discoop.models import Attachment
from discoop.scrape import fetch_messages
from discoop.snowflake import Window


def test_leak_prevention(tmp_path: Path):
    """Token, signed URLs, message content and channel names must never leak into logs."""
    log_file = tmp_path / "leak.log"
    setup_logging(debug=True, log_file=log_file)
    try:
        secret_token = "FAKE.TOKEN.VALUE"
        secret_sig = "SECRETSIG"
        secret_filename = "f.png"
        secret_query = "ex=1"
        secret_msg = "SECRET MESSAGE TEXT"
        secret_channel = "secret-channel-name"
        secret_url = f"https://cdn.example/{secret_filename}?{secret_query}&is=2&hm={secret_sig}"

        # 1. API calls: 429 then 500 then 200 (with secret message text), then 403
        api_responses = [
            httpx.Response(429, json={"retry_after": 0.01, "global": False}),
            httpx.Response(500, json={"message": "Internal Server Error"}),
            httpx.Response(
                200,
                json=[
                    {
                        "id": "9876543210",
                        "type": 0,
                        "content": secret_msg,
                        "attachments": [
                            {
                                "id": "777888999",
                                "filename": secret_filename,
                                "size": 12,
                                "url": secret_url,
                            }
                        ],
                    }
                ],
            ),
            httpx.Response(403, json={"code": 50001, "message": "Missing Access"}),
        ]
        resp_iter = iter(api_responses)

        def api_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/attachments/refresh-urls"):
                return httpx.Response(
                    200,
                    json={"refreshed_urls": [{"original": secret_url, "refreshed": secret_url}]},
                )
            return next(resp_iter)

        sleeps: list[float] = []
        api = DiscordAPI(
            secret_token,
            transport=httpx.MockTransport(api_handler),
            sleep=sleeps.append,
            delay=0.0,
        )

        window = Window(None, datetime.now(timezone.utc))

        # Scrape channel messages
        fetched = fetch_messages(api, "12345678", window, label=secret_channel)
        assert len(fetched.messages) == 1

        # Call returning 403
        forbidden_resp = api.request("GET", "/channels/secret_forbidden")
        assert forbidden_resp.status_code == 403

        # 2. Downloader fetching attachment from CDN
        def cdn_handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "cdn.example"
            return httpx.Response(200, content=b"hello-secret")

        cdn_client = httpx.Client(transport=httpx.MockTransport(cdn_handler))
        downloader = Downloader(api, cdn_client, tmp_path / "export")
        job = FileJob(
            attachment=Attachment(
                id="777888999",
                filename=secret_filename,
                type="image/png",
                size=12,
                url=secret_url,
            ),
            message_id="9876543210",
            channel_id="12345678",
            path=f"files/{secret_channel}/777888999_{secret_filename}",
            url=secret_url,
        )
        downloader.run([job])
        cdn_client.close()
    finally:
        teardown_logging()

    log_content = log_file.read_text(encoding="utf-8")
    assert log_content, "Log file should not be empty"

    # Verify header
    assert "IDs in this log identify private servers and channels. Do not publish it." in log_content

    # Strict check: none of the sensitive strings must appear anywhere in the log
    forbidden_strings = [
        secret_token,
        secret_sig,
        secret_filename,
        secret_query,
        secret_msg,
        secret_channel,
    ]
    for forbidden in forbidden_strings:
        assert forbidden not in log_content, f"Leaked sensitive string: {forbidden!r}"

    # Verify that safe diagnostics WERE logged
    assert "status=200" in log_content
    assert "status=429" in log_content
    assert "status=500" in log_content
    assert "status=403" in log_content
    assert "host=cdn.example" in log_content
    assert "channel_id=12345678" in log_content


def test_without_setup_logging_nothing_written(tmp_path: Path, capsys: pytest.CaptureFixture):
    """When setup_logging is not called (or called with debug=False, log_file=None), nothing is logged."""
    teardown_logging()
    setup_logging(debug=False, log_file=None)

    discoop_logger = logging.getLogger("discoop")
    assert len(discoop_logger.handlers) == 0

    api = DiscordAPI(
        "tok",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
        sleep=lambda s: None,
    )
    api.request("GET", "/channels/123/messages")

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_teardown_removes_handlers_and_double_setup_no_duplicates(tmp_path: Path):
    """teardown_logging removes handlers; double setup/teardown is idempotent without duplicate handlers."""
    log_file = tmp_path / "double.log"

    # Setup once
    setup_logging(debug=True, log_file=log_file)
    discoop_logger = logging.getLogger("discoop")
    assert len(discoop_logger.handlers) == 2

    # Setup twice without teardown in-between: should not duplicate handlers
    setup_logging(debug=True, log_file=log_file)
    assert len(discoop_logger.handlers) == 2

    # Send a request to log
    api = DiscordAPI(
        "tok",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
        sleep=lambda s: None,
    )
    api.request("GET", "/channels/123/messages")

    # Teardown once
    teardown_logging()
    assert len(discoop_logger.handlers) == 0

    # Teardown twice (idempotence)
    teardown_logging()
    assert len(discoop_logger.handlers) == 0

    # Verify that the API request line appears exactly once in the file
    content = log_file.read_text(encoding="utf-8")
    api_request_lines = [
        line for line in content.splitlines() if "api request method=GET path=/channels/123/messages" in line
    ]
    assert len(api_request_lines) == 1, f"Expected 1 request line, found {len(api_request_lines)}"


def test_api_log_line_format(tmp_path: Path):
    """API request log line contains expected fields and query string is stripped from path."""
    log_file = tmp_path / "api_format.log"
    setup_logging(debug=True, log_file=log_file)
    try:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": "1"}, {"id": "2"}])

        api = DiscordAPI("tok", transport=httpx.MockTransport(handler), sleep=lambda s: None)
        api.request("GET", "/channels/999/messages?sensitive_query=hidden", params={"limit": 25, "before": "555"})
    finally:
        teardown_logging()

    content = log_file.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if "api request" in line]
    assert len(lines) == 1
    req_line = lines[0]

    # Required fields
    assert "status=200" in req_line
    assert "attempt=1" in req_line
    assert "ms=" in req_line
    assert "bytes=" in req_line
    assert "items=2" in req_line

    # Path check: must NOT have ? or sensitive_query
    assert "sensitive_query" not in req_line
    assert "path=/channels/999/messages" in req_line
    assert "?" not in req_line.split("path=")[1].split()[0]

    # Params check
    assert "params=limit,before" in req_line
    assert "limit=25" in req_line
    assert "before=555" in req_line
