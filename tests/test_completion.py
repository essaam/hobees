from prompt_toolkit.buffer import Buffer, CompletionState
from prompt_toolkit.completion import Completion
from prompt_toolkit.document import Document

from hobees.cli.completion import (
    FilePathCompleter,
    FilePathCompletion,
    accept_completion_or_submit,
)


def test_file_path_completer_lists_parent_and_matching_entries(tmp_path, monkeypatch):
    (tmp_path / "file.md").write_text("content")
    (tmp_path / "folder").mkdir()
    (tmp_path / "other.txt").write_text("content")
    monkeypatch.chdir(tmp_path)

    completions = list(
        FilePathCompleter().get_completions(Document("@fi"), complete_event=None)
    )

    assert [item.text for item in completions] == ["file.md", "../"]
    assert completions[0].display_meta[0][1] == "file"
    assert completions[1].display_meta[0][1] == "parent directory"

    folders = list(
        FilePathCompleter().get_completions(Document("@fo"), complete_event=None)
    )
    assert folders[0].text == "folder"
    assert folders[0].display_meta[0][1] == "folder"


def test_file_path_completer_browses_nested_folders_and_ignores_email(tmp_path, monkeypatch):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "inside.md").write_text("content")
    monkeypatch.chdir(tmp_path)
    completer = FilePathCompleter()

    nested = list(
        completer.get_completions(
            Document("@folder/in"), complete_event=None
        )
    )
    email = list(
        completer.get_completions(
            Document("user@fi"), complete_event=None
        )
    )

    assert [item.text for item in nested] == ["inside.md", "../"]
    assert email == []


def test_file_path_completer_closes_after_path_and_allows_normal_text(
    tmp_path, monkeypatch
):
    (tmp_path / "file.md").write_text("content")
    (tmp_path / "folder name").mkdir()
    (tmp_path / "folder name" / "inside.md").write_text("content")
    monkeypatch.chdir(tmp_path)
    completer = FilePathCompleter()

    after_path = list(
        completer.get_completions(
            Document("@file.md "), complete_event=None
        )
    )
    after_prose = list(
        completer.get_completions(
            Document("@file.md please summarize"), complete_event=None
        )
    )
    nested = list(
        completer.get_completions(
            Document("@folder name/in"), complete_event=None
        )
    )

    assert after_path == []
    assert after_prose == []
    assert [item.text for item in nested] == ["inside.md", "../"]


def test_enter_accepts_a_selected_path_without_submitting():
    accepted = []
    buffer = Buffer(accept_handler=lambda current: accepted.append(current.text))
    buffer.insert_text("@fi")
    buffer.complete_state = CompletionState(
        buffer.document,
        [FilePathCompletion("file.md", start_position=-2)],
    )

    accept_completion_or_submit(buffer)

    assert buffer.text == "@file.md"
    assert accepted == []


def test_enter_submits_when_no_path_completion_is_selected():
    accepted = []
    buffer = Buffer(accept_handler=lambda current: accepted.append(current.text))
    buffer.insert_text("hello")
    buffer.complete_state = CompletionState(
        buffer.document,
        [Completion("there", start_position=0)],
    )

    accept_completion_or_submit(buffer)

    assert accepted == ["hello"]
