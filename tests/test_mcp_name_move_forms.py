"""The forms an agent file may be written in, for the move of tool names.

A mapping of permissions written on the key's own line moves like the
block form, and a file keeps its line endings and its byte order mark."""

from __future__ import annotations

from app import mcp_name_move

MAPPING = {"read_file": "mcp__fs__read_file"}


def _file(body: str, line_end: str = "\n") -> str:
    lines = ["---", "name: reader", *body.split("\n"), "---", "Read what is asked."]
    return line_end.join(lines)


def test_a_permissions_mapping_on_one_line_moves_with_the_name_and_keeps_its_value():
    text = _file("permissions: {read_file: allow, write_file: ask}")
    moved = mcp_name_move.move_agent_file_text(text, MAPPING, set())
    assert moved is not None
    assert "permissions: {mcp__fs__read_file: allow, write_file: ask}" in moved


def test_a_name_that_stays_keeps_its_entry_and_gets_the_new_one_beside_it():
    text = _file("permissions: {read_file: deny}")
    moved = mcp_name_move.move_agent_file_text(text, MAPPING, {"read_file"})
    assert moved is not None
    assert "permissions: {read_file: deny, mcp__fs__read_file: deny}" in moved


def test_a_quoted_key_in_the_mapping_stays_quoted():
    text = _file("permissions: {'read_file': allow}")
    moved = mcp_name_move.move_agent_file_text(text, MAPPING, set())
    assert moved is not None
    assert "permissions: {'mcp__fs__read_file': allow}" in moved


def test_a_mapping_without_a_moved_name_is_left_alone():
    text = _file("permissions: {write_file: ask}")
    assert mcp_name_move.move_agent_file_text(text, MAPPING, set()) is None


def test_a_file_keeps_its_line_endings_and_its_byte_order_mark(tmp_path):
    text = _file("tools: [read_file, write_file]\npermissions: {read_file: allow}", "\r\n")
    path = tmp_path / "reader.md"
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    changed = mcp_name_move._move_agent_files(tmp_path, MAPPING, set())
    assert changed == 1
    written = path.read_bytes()
    assert written.startswith(b"\xef\xbb\xbf---")
    assert b"\n" not in written.replace(b"\r\n", b"")
    assert b"mcp__fs__read_file" in written
    assert written.count(b"\r\n") == text.count("\r\n")


def test_a_file_with_lf_endings_gets_no_carriage_return(tmp_path):
    path = tmp_path / "reader.md"
    path.write_bytes(_file("tools: [read_file]").encode("utf-8"))
    assert mcp_name_move._move_agent_files(tmp_path, MAPPING, set()) == 1
    assert b"\r" not in path.read_bytes()
