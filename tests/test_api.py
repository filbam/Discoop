import httpx
import pytest

from discoop.api import DiscordAPI
from discoop.errors import DiscoopError, ExitCode


def make_api(handler, **kwargs):
    sleeps: list[float] = []
    api = DiscordAPI("tok", transport=httpx.MockTransport(handler), sleep=sleeps.append, **kwargs)
    return api, sleeps


def test_get_me_sends_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "tok"
        assert request.url.path == "/api/v9/users/@me"
        return httpx.Response(200, json={"id": "1", "username": "someone"})

    api, _ = make_api(handler)
    assert api.get_me()["username"] == "someone"


def test_401_means_login_required():
    api, _ = make_api(lambda r: httpx.Response(401, json={"message": "401: Unauthorized"}))
    with pytest.raises(DiscoopError) as e:
        api.get_me()
    assert e.value.code == ExitCode.AUTH_REQUIRED


def test_429_waits_retry_after_then_retries():
    responses = iter(
        [httpx.Response(429, json={"retry_after": 1.5, "global": False}), httpx.Response(200, json={})]
    )
    api, sleeps = make_api(lambda r: next(responses))
    assert api.request("GET", "/x").status_code == 200
    assert sleeps == [1.5]


def test_long_rate_limit_aborts():
    api, _ = make_api(lambda r: httpx.Response(429, json={"retry_after": 600}))
    with pytest.raises(DiscoopError) as e:
        api.request("GET", "/x")
    assert e.value.code == ExitCode.RATE_LIMITED


def test_other_client_errors_are_returned():
    api, _ = make_api(lambda r: httpx.Response(403, json={"message": "Missing Access"}))
    assert api.request("GET", "/x").status_code == 403


def test_delay_paces_requests():
    now = [100.0]
    api, sleeps = make_api(lambda r: httpx.Response(200, json={}), delay=1.0, clock=lambda: now[0])
    api.request("GET", "/a")
    now[0] += 0.25
    api.request("GET", "/b")
    assert sleeps == [0.75]


@pytest.mark.parametrize(
    "path", ["https://cdn.discordapp.com/attachments/1/2/a.png", "//cdn.discordapp.com/x", "users/@me"]
)
def test_token_never_leaves_the_api(path):
    """The client with the token only takes API paths; files come from the CDN through another client."""
    api, _ = make_api(lambda r: pytest.fail(f"request sent to {r.url}"))
    with pytest.raises(ValueError):
        api.request("GET", path)
