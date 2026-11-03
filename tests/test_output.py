import io

from discoop.errors import DiscoopError, ExitCode
from discoop.output import Output, detect_agent_mode


class FakeStream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_human_flag_wins_over_everything():
    assert detect_agent_mode(True, True, env={"DISCOOP_AGENT": "1"}, stdout=FakeStream(False)) is False


def test_agent_flag_and_env_select_agent_mode():
    assert detect_agent_mode(True, False, env={}, stdout=FakeStream(True)) is True
    assert detect_agent_mode(False, False, env={"DISCOOP_AGENT": "yes"}, stdout=FakeStream(True)) is True


def test_terminal_decides_when_nothing_is_set():
    assert detect_agent_mode(False, False, env={}, stdout=FakeStream(True)) is False
    assert detect_agent_mode(False, False, env={}, stdout=FakeStream(False)) is True


def test_agent_error_format(capsys):
    Output(agent=True).error(DiscoopError(ExitCode.AUTH_REQUIRED, "Not logged in.", "Run it."))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR AUTH_REQUIRED: Not logged in.\nHINT: Run it.\n"


def test_agent_fields_are_plain_key_value_lines(capsys):
    Output(agent=True).fields({"logged_in": "yes", "user": "@someone"}, title="ignored")
    assert capsys.readouterr().out == "logged_in: yes\nuser: @someone\n"


def test_agent_notes_need_verbose(capsys):
    Output(agent=True).note("hidden")
    Output(agent=True, verbose=True).note("shown")
    assert capsys.readouterr().err == "shown\n"
