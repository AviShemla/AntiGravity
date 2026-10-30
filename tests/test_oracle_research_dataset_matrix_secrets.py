import os
from pathlib import Path
import stat

import pytest

from scripts.oracle_research_dataset_matrix_secrets import (
    BRANCH_TOKEN_KEY,
    BRANCH_URL_KEY,
    SecretFileError,
    branch_secret_file,
    create_branch_secret_file,
    unlink_and_verify_secret_file,
    validate_branch_secret_file,
    verify_secret_file_absent,
)


URL = "libsql://theoracle-codex-oracle-rd-20260826t1700z-a1b2c3.turso.io"
TOKEN = b"secret-test-placeholder.token.value\n"


def _manual(path: Path, text: bytes, mode: int = 0o600) -> None:
    path.write_bytes(text)
    path.chmod(mode)


def test_atomic_create_is_exact_mode_regular_single_link_and_secret_free_stdout(tmp_path, capsys):
    path = create_branch_secret_file(
        tmp_path, "branch.env", branch_url=URL, token_stdout=TOKEN
    )
    metadata = os.lstat(path)
    assert stat.S_ISREG(metadata.st_mode)
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1
    values = validate_branch_secret_file(path, expected_branch_url=URL)
    assert values.branch_url == URL
    assert values.branch_token == TOKEN.decode().strip()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    unlink_and_verify_secret_file(path)


def test_atomic_create_never_replaces_existing_target_or_leaves_temp_file(tmp_path):
    target = tmp_path / "branch.env"
    target.write_text("do-not-replace", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_branch_secret_file(tmp_path, target.name, branch_url=URL, token_stdout=TOKEN)
    assert target.read_text(encoding="utf-8") == "do-not-replace"
    assert list(tmp_path.iterdir()) == [target]


def test_symlink_and_hardlink_are_rejected(tmp_path):
    real = tmp_path / "real.env"
    _manual(real, f"{BRANCH_URL_KEY}={URL}\n{BRANCH_TOKEN_KEY}=token\n".encode())
    symlink = tmp_path / "symlink.env"
    symlink.symlink_to(real)
    with pytest.raises(SecretFileError, match="regular"):
        validate_branch_secret_file(symlink, expected_branch_url=URL)
    hardlink = tmp_path / "hardlink.env"
    os.link(real, hardlink)
    with pytest.raises(SecretFileError, match="hard link"):
        validate_branch_secret_file(real, expected_branch_url=URL)


def test_wrong_mode_owner_and_oversized_content_are_rejected(tmp_path):
    path = tmp_path / "branch.env"
    content = f"{BRANCH_URL_KEY}={URL}\n{BRANCH_TOKEN_KEY}=token\n".encode()
    _manual(path, content, 0o640)
    with pytest.raises(SecretFileError, match="0600"):
        validate_branch_secret_file(path, expected_branch_url=URL)
    path.chmod(0o600)
    with pytest.raises(SecretFileError, match="owner"):
        validate_branch_secret_file(
            path, expected_branch_url=URL, expected_uid=os.geteuid() + 1
        )
    with pytest.raises(SecretFileError, match="oversized"):
        validate_branch_secret_file(
            path, expected_branch_url=URL, max_file_bytes=len(content) - 1
        )


@pytest.mark.parametrize(
    "text,match",
    [
        (f"{BRANCH_URL_KEY}={URL}\n", "key set"),
        (
            f"{BRANCH_URL_KEY}={URL}\n{BRANCH_TOKEN_KEY}=one\n{BRANCH_TOKEN_KEY}=two\n",
            "duplicate",
        ),
        (
            f"{BRANCH_URL_KEY}={URL}\n{BRANCH_TOKEN_KEY}=token\nEXTRA=value\n",
            "unexpected key",
        ),
        (f"{BRANCH_TOKEN_KEY}=token\n{BRANCH_URL_KEY}={URL}\n", "order"),
        (f"{BRANCH_URL_KEY}={URL}\n{BRANCH_TOKEN_KEY}=\n", "empty value"),
    ],
)
def test_parser_requires_exact_two_keys_once_in_canonical_order(tmp_path, text, match):
    path = tmp_path / "branch.env"
    _manual(path, text.encode())
    with pytest.raises(SecretFileError, match=match):
        validate_branch_secret_file(path, expected_branch_url=URL)


def test_url_is_exact_and_credential_free(tmp_path):
    path = tmp_path / "branch.env"
    _manual(path, f"{BRANCH_URL_KEY}={URL}\n{BRANCH_TOKEN_KEY}=token\n".encode())
    with pytest.raises(SecretFileError, match="differs"):
        validate_branch_secret_file(
            path, expected_branch_url="libsql://different.turso.io"
        )
    path.unlink()
    with pytest.raises(SecretFileError, match="credential-free"):
        create_branch_secret_file(
            tmp_path,
            "branch.env",
            branch_url="libsql://user:password@example.turso.io",
            token_stdout=TOKEN,
        )


@pytest.mark.parametrize(
    "token,match",
    [
        (b"", "empty or oversized"),
        (b"one\ntwo\n", "one token line"),
        (b" token\n", "one token line"),
        (b"bad\x00token\n", "control character"),
        (b"\xff", "UTF-8"),
    ],
)
def test_sensitive_stdout_must_be_one_bounded_token_line(tmp_path, token, match):
    with pytest.raises(SecretFileError, match=match):
        create_branch_secret_file(
            tmp_path, "branch.env", branch_url=URL, token_stdout=token
        )


class FatalSignal(BaseException):
    pass


def test_context_unlinks_and_independently_verifies_absence_after_base_exception(tmp_path):
    path = tmp_path / "branch.env"
    with pytest.raises(FatalSignal):
        with branch_secret_file(
            tmp_path, path.name, branch_url=URL, token_stdout=TOKEN
        ) as (observed_path, values):
            assert observed_path == path
            assert values.branch_token == TOKEN.decode().strip()
            raise FatalSignal()
    verify_secret_file_absent(path)


def test_context_unlinks_after_success_and_absence_check_rejects_residue(tmp_path):
    path = tmp_path / "branch.env"
    with branch_secret_file(
        tmp_path, path.name, branch_url=URL, token_stdout=TOKEN
    ):
        assert path.exists()
    verify_secret_file_absent(path)
    path.write_text("residue", encoding="utf-8")
    with pytest.raises(SecretFileError, match="could not be verified"):
        verify_secret_file_absent(path)
