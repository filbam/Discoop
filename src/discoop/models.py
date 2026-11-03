"""Plain data the commands work with: servers and channels as cached locally."""

from dataclasses import dataclass
from typing import Any

CHANNEL_TYPES = {
    0: "text",
    2: "voice",
    4: "category",
    5: "announcement",
    10: "announcement-thread",
    11: "thread",
    12: "private-thread",
    13: "stage",
    14: "directory",
    15: "forum",
    16: "media",
}
CATEGORY = 4
_VOICE_LIKE = {2, 13}
_HIDDEN_FLAG = 1 << 17


@dataclass(frozen=True)
class Server:
    id: str
    name: str
    member_count: int | None = None


@dataclass(frozen=True)
class Channel:
    id: str
    server_id: str
    name: str
    type: int
    parent_id: str | None = None
    position: int = 0
    topic: str | None = None

    @property
    def type_name(self) -> str:
        return CHANNEL_TYPES.get(self.type, f"type-{self.type}")

    def sort_key(self) -> tuple[int, int, int]:
        """Discord's sidebar order: text-like channels above voice ones, then position, then ID."""
        return (self.type in _VOICE_LIKE, self.position, int(self.id))


def server_from_api(data: dict[str, Any]) -> Server:
    return Server(id=data["id"], name=data.get("name") or "", member_count=data.get("approximate_member_count"))


def channel_from_api(data: dict[str, Any], server_id: str) -> Channel:
    return Channel(
        id=data["id"],
        server_id=server_id,
        name=data.get("name") or "",
        type=int(data.get("type", 0)),
        parent_id=data.get("parent_id"),
        position=int(data.get("position") or 0),
        topic=data.get("topic"),
    )


def is_hidden(data: dict[str, Any]) -> bool:
    """Channels the client gets obfuscated (docs/analyzy/discord-analyza.md, section 3)."""
    return data.get("name") == "___hidden___" or bool((data.get("flags") or 0) & _HIDDEN_FLAG)
