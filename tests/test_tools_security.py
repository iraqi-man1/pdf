"""Tests for the Security tools: Protect and Unlock."""

from __future__ import annotations

import pymupdf
import pytest

from pdfstudio.core.errors import PasswordRequiredError
from pdfstudio.gui import theme
from pdfstudio.gui.base import CATEGORIES, ToolPage
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.tools.security import TOOLS, ProtectTool, UnlockTool

OWNER_PASSWORD = "owner-only-pw"
USER_PASSWORD = "open-sesame"


def _noop(percent, message=""):
    return None


def _protect_options(password: str = "pass1234", **extra) -> dict:
    options = {"password": password, "allow_printing": True, "allow_copying": True}
    options.update(extra)
    return options


@pytest.fixture()
def locked_pdf(sample_pdf, tmp_path):
    """The sample PDF encrypted with USER_PASSWORD, so opening it needs that password."""
    path = tmp_path / "locked-source.pdf"
    doc = pymupdf.open(sample_pdf)
    doc.save(
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw=USER_PASSWORD,
        owner_pw=OWNER_PASSWORD,
    )
    doc.close()
    return path


def _open_locked(path, password: str):
    doc = pymupdf.open(path)
    assert doc.needs_pass
    assert doc.authenticate(password)
    return doc


def test_keys_are_unique_and_in_order():
    assert [cls.key for cls in TOOLS] == ["protect", "unlock"]


@pytest.mark.parametrize("tool_class", TOOLS, ids=lambda cls: cls.key)
def test_metadata_follows_the_tool_contract(tool_class):
    assert tool_class.category == "Security"
    assert tool_class.category in CATEGORIES
    assert tool_class.color == theme.CATEGORY_COLORS["Security"]
    assert tool_class.accepts == (".pdf",)
    assert tool_class.max_files == 1
    assert tool_class.title
    assert tool_class.action_text
    assert 0 < len(tool_class.description) <= 90


@pytest.mark.parametrize("tool_class", TOOLS, ids=lambda cls: cls.key)
def test_tool_page_builds_with_its_options(qapp, tool_class):
    page = ToolPage(tool_class(), AppSettings())
    assert not page.grab().isNull()


# --------------------------------------------------------------- protect


def test_protect_collects_matching_passwords_and_permissions(qapp):
    tool = ProtectTool()
    tool.build_options()
    tool._password.setText("pass1234")
    tool._confirm.setText("pass1234")
    tool._printing.setChecked(False)
    assert tool.collect_options() == {
        "password": "pass1234",
        "allow_printing": False,
        "allow_copying": True,
    }


def test_protect_rejects_mismatched_passwords_without_echoing_them(qapp):
    tool = ProtectTool()
    tool.build_options()
    tool._password.setText("secret-one")
    tool._confirm.setText("secret-two")
    with pytest.raises(ValueError, match="The two passwords do not match.") as info:
        tool.collect_options()
    assert "secret-one" not in str(info.value)
    assert "secret-two" not in str(info.value)


@pytest.mark.parametrize("password", ["", "abc"])
def test_protect_rejects_short_or_empty_passwords(qapp, password):
    tool = ProtectTool()
    tool.build_options()
    tool._password.setText(password)
    tool._confirm.setText(password)
    with pytest.raises(ValueError, match="at least 4 characters"):
        tool.collect_options()


def test_protect_show_passwords_toggles_both_fields(qapp):
    tool = ProtectTool()
    tool.build_options()
    tool._show.setChecked(True)
    assert tool._password.echoMode().name == "Normal"
    assert tool._confirm.echoMode().name == "Normal"
    tool._show.setChecked(False)
    assert tool._password.echoMode().name == "Password"
    assert tool._confirm.echoMode().name == "Password"


def test_protect_validate_needs_one_file(sample_pdf):
    tool = ProtectTool()
    assert tool.validate([sample_pdf], _protect_options()) is None
    assert tool.validate([], _protect_options()) == "Add a file first."


def test_protect_run_writes_an_encrypted_pdf_that_opens_with_the_password(sample_pdf, tmp_path):
    out_dir = tmp_path / "out"
    outputs = ProtectTool().run([sample_pdf], _protect_options("pass1234"), out_dir, _noop)
    assert outputs == [out_dir / "sample - protected.pdf"]

    doc = pymupdf.open(outputs[0])
    try:
        assert doc.needs_pass
        assert not doc.authenticate("definitely-wrong")
        assert doc.authenticate("pass1234")
        assert doc.page_count == 3
    finally:
        doc.close()


def test_protect_run_respects_the_printing_choice(sample_pdf, tmp_path):
    out_dir = tmp_path / "out"
    outputs = ProtectTool().run(
        [sample_pdf], _protect_options("pass1234", allow_printing=False), out_dir, _noop
    )
    doc = _open_locked(outputs[0], "pass1234")
    try:
        assert not doc.permissions & pymupdf.PDF_PERM_PRINT
    finally:
        doc.close()


def test_protect_summary_does_not_repeat_the_password(sample_pdf, tmp_path):
    tool = ProtectTool()
    outputs = tool.run([sample_pdf], _protect_options("pass1234"), tmp_path / "out", _noop)
    summary = tool.result_summary([sample_pdf], outputs)
    assert summary
    assert "pass1234" not in summary


# ---------------------------------------------------------------- unlock


def test_unlock_needs_a_password_typed(qapp):
    tool = UnlockTool()
    tool.build_options()
    with pytest.raises(ValueError, match="Type the password that opens this PDF."):
        tool.collect_options()


def test_unlock_collects_the_typed_password(qapp):
    tool = UnlockTool()
    tool.build_options()
    tool._password.setText(USER_PASSWORD)
    assert tool.collect_options() == {"password": USER_PASSWORD}


def test_unlock_show_password_toggles_the_field(qapp):
    tool = UnlockTool()
    tool.build_options()
    tool._show.setChecked(True)
    assert tool._password.echoMode().name == "Normal"
    tool._show.setChecked(False)
    assert tool._password.echoMode().name == "Password"


def test_unlock_run_with_the_right_password_writes_an_unencrypted_pdf(locked_pdf, tmp_path):
    out_dir = tmp_path / "out"
    outputs = UnlockTool().run([locked_pdf], {"password": USER_PASSWORD}, out_dir, _noop)
    assert outputs == [out_dir / "locked-source - unlocked.pdf"]

    doc = pymupdf.open(outputs[0])
    try:
        assert not doc.needs_pass
        assert not doc.is_encrypted
        assert doc.page_count == 3
    finally:
        doc.close()


def test_unlock_run_with_a_wrong_password_raises_password_required(locked_pdf, tmp_path):
    with pytest.raises(PasswordRequiredError):
        UnlockTool().run([locked_pdf], {"password": "not-the-password"}, tmp_path / "out", _noop)


def test_protect_then_unlock_round_trip(sample_pdf, tmp_path):
    protected = ProtectTool().run([sample_pdf], _protect_options("round-trip"), tmp_path / "a", _noop)[0]
    unlocked = UnlockTool().run([protected], {"password": "round-trip"}, tmp_path / "b", _noop)[0]
    doc = pymupdf.open(unlocked)
    try:
        assert not doc.needs_pass
        assert doc.page_count == 3
    finally:
        doc.close()
