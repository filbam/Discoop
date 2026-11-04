import pytest

from discoop.errors import DiscoopError, ExitCode
from discoop.models import Channel, Server
from discoop.resolve import NotFoundError, normalize, resolve_many, resolve_one

SERVERS = [Server("461541385204400138", "VUT FIT"), Server("2", "IZP – cvičenia"), Server("3", "Gaming")]
CHANNELS = [
    Channel("10", "461541385204400138", "aeu-private🔒", 0),
    Channel("11", "461541385204400138", "isc-public", 0),
    Channel("12", "461541385204400138", "isc-private🔒", 0),
    Channel("13", "461541385204400138", "General", 0),
    Channel("14", "2", "general", 0),
]


def describe(item):
    return f"{item.name} ({item.id})"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aeu-private🔒", "aeu-private"),
        ("VUT  FIT", "vut fit"),
        ("Bakalářka – státnice", "bakalarka statnice"),
        ("𝒻𝒾𝒻𝒾𝓃𝓀𝑜", "fifinko"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_resolve_by_id_exact_and_normalized_name():
    assert resolve_one("461541385204400138", SERVERS, "server", describe).name == "VUT FIT"
    assert resolve_one("VUT FIT", SERVERS, "server", describe).id == "461541385204400138"
    assert resolve_one("vut fit", SERVERS, "server", describe).id == "461541385204400138"
    assert resolve_one("izp cvicenia", SERVERS, "server", describe).id == "2"
    assert resolve_one("aeu-private", CHANNELS, "channel", describe).id == "10"


def test_exact_name_beats_normalized_duplicates():
    assert resolve_one("General", CHANNELS, "channel", describe).id == "13"


def test_ambiguous_names_list_candidates():
    with pytest.raises(DiscoopError) as e:
        resolve_one("GENERAL", CHANNELS, "channel", describe)
    assert e.value.code == ExitCode.AMBIGUOUS
    assert "General (13)" in e.value.message and "general (14)" in e.value.message


def test_not_found():
    with pytest.raises(NotFoundError) as e:
        resolve_one("nope", SERVERS, "server", describe)
    assert e.value.code == ExitCode.NOT_FOUND
    with pytest.raises(NotFoundError):
        resolve_one("999", SERVERS, "server", describe)


def test_patterns_match_normalized_names():
    assert [c.id for c in resolve_many("isc-*", CHANNELS, "channel", describe)] == ["11", "12"]
    assert [c.id for c in resolve_many("*-private", CHANNELS, "channel", describe)] == ["10", "12"]
    assert [c.id for c in resolve_many("isc-public", CHANNELS, "channel", describe)] == ["11"]
    with pytest.raises(NotFoundError):
        resolve_many("xyz-*", CHANNELS, "channel", describe)


def test_typo_suggests_did_you_mean():
    with pytest.raises(NotFoundError) as e:
        resolve_one("vut fot", SERVERS, "server", describe)
    assert e.value.hint == "Did you mean: VUT FIT?"


def test_typo_suggests_multiple_candidates_without_duplicates():
    with pytest.raises(NotFoundError) as e:
        resolve_one("generla", CHANNELS, "channel", describe)
    assert e.value.hint == "Did you mean: General, general?"


def test_completely_different_word_has_no_suggestion():
    with pytest.raises(NotFoundError) as e:
        resolve_one("completelyunrelated", SERVERS, "server", describe)
    assert e.value.hint is None


def test_digit_query_has_no_suggestion():
    with pytest.raises(NotFoundError) as e:
        resolve_one("999", SERVERS, "server", describe)
    assert e.value.hint is None


def test_resolve_many_glob_suggestions():
    # Glob pattern with no close matches has hint is None
    with pytest.raises(NotFoundError) as e:
        resolve_many("completelyunrelated*", CHANNELS, "channel", describe)
    assert e.value.hint is None

    # Glob pattern with typo suggests close match
    with pytest.raises(NotFoundError) as e:
        resolve_many("isc-publc*", CHANNELS, "channel", describe)
    assert e.value.hint == "Did you mean: isc-public?"

