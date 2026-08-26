"""Fail-closed disposable-branch credential-file lifecycle.

This module owns no network, environment, CLI, or database behavior.  It turns
already captured sensitive token stdout into one exact local env file, validates
that file without logging its contents, and removes it at the end of a bounded
context.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat
from typing import Iterator
from urllib.parse import urlparse


BRANCH_URL_KEY = "TURSO_ISOLATED_DATABASE_URL"
BRANCH_TOKEN_KEY = "TURSO_ISOLATED_AUTH_TOKEN"
EXPECTED_KEYS = (BRANCH_URL_KEY, BRANCH_TOKEN_KEY)
DEFAULT_MAX_FILE_BYTES = 16_384
DEFAULT_MAX_TOKEN_BYTES = 12_288


class SecretFileError(ValueError):
    """Raised without including secret values or file content."""


@dataclass(frozen=True)
class BranchSecrets:
    branch_url: str
    branch_token: str


def _validate_target(directory: Path, filename: str) -> Path:
    if not isinstance(filename, str) or not filename or filename in {".", ".."}:
        raise SecretFileError("Secret filename is invalid.")
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise SecretFileError("Secret filename must be one plain basename.")
    root = directory.resolve(strict=True)
    if not root.is_dir():
        raise SecretFileError("Secret-file parent is not a directory.")
    return root / filename


def _normalize_branch_url(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SecretFileError("Branch URL is missing or malformed.")
    parsed = urlparse(value)
    if parsed.scheme not in {"libsql", "https"}:
        raise SecretFileError("Branch URL scheme is not allowed.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise SecretFileError("Branch URL must be credential-free.")
    if parsed.query or parsed.fragment:
        raise SecretFileError("Branch URL cannot contain query or fragment data.")
    return value.rstrip("/")


def _token_from_stdout(raw: bytes, *, max_token_bytes: int) -> str:
    if not isinstance(raw, bytes) or not raw or len(raw) > max_token_bytes:
        raise SecretFileError("Sensitive token stdout is empty or oversized.")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretFileError("Sensitive token stdout is not UTF-8.") from exc
    token = decoded.rstrip("\r\n")
    if not token or token != token.strip() or "\n" in token or "\r" in token:
        raise SecretFileError("Sensitive token stdout is not exactly one token line.")
    if any(ord(character) < 0x21 or ord(character) == 0x7F for character in token):
        raise SecretFileError("Sensitive token stdout contains a control character.")
    return token


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_branch_secret_file(
    directory: Path,
    filename: str,
    *,
    branch_url: str,
    token_stdout: bytes,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_token_bytes: int = DEFAULT_MAX_TOKEN_BYTES,
) -> Path:
    """Atomically publish one complete mode-600 secret file without replacement."""

    target = _validate_target(Path(directory), filename)
    url = _normalize_branch_url(branch_url)
    token = _token_from_stdout(token_stdout, max_token_bytes=max_token_bytes)
    payload = (
        f"{BRANCH_URL_KEY}={url}\n{BRANCH_TOKEN_KEY}={token}\n"
    ).encode("utf-8")
    if len(payload) > max_file_bytes:
        raise SecretFileError("Secret-file payload is oversized.")
    temporary = target.parent / f".{target.name}.{secrets.token_hex(12)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    published = False
    try:
        descriptor = os.open(temporary, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SecretFileError("Secret-file write did not make progress.")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(temporary, target, follow_symlinks=False)
        published = True
        os.unlink(temporary)
        _fsync_directory(target.parent)
        validate_branch_secret_file(
            target,
            expected_branch_url=url,
            max_file_bytes=max_file_bytes,
        )
        return target
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if temporary.exists() or temporary.is_symlink():
            os.unlink(temporary)
        if published and (target.exists() or target.is_symlink()):
            os.unlink(target)
            _fsync_directory(target.parent)
        raise


def _read_validated_bytes(
    path: Path,
    *,
    max_file_bytes: int,
    expected_uid: int,
) -> bytes:
    try:
        before = os.lstat(path)
    except FileNotFoundError as exc:
        raise SecretFileError("Secret file is absent.") from exc
    if not stat.S_ISREG(before.st_mode):
        raise SecretFileError("Secret file is not a regular file.")
    if before.st_nlink != 1:
        raise SecretFileError("Secret file has an unexpected hard link.")
    if stat.S_IMODE(before.st_mode) != 0o600:
        raise SecretFileError("Secret file mode is not exactly 0600.")
    if before.st_uid != expected_uid:
        raise SecretFileError("Secret file owner is not the current execution owner.")
    if before.st_size <= 0 or before.st_size > max_file_bytes:
        raise SecretFileError("Secret file is empty or oversized.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise SecretFileError("Secret file identity changed while opening.")
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != expected_uid
        ):
            raise SecretFileError("Secret file metadata changed while opening.")
        chunks: list[bytes] = []
        remaining = max_file_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_file_bytes:
            raise SecretFileError("Secret file is oversized.")
        return raw
    finally:
        os.close(descriptor)


def validate_branch_secret_file(
    path: Path,
    *,
    expected_branch_url: str,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    expected_uid: int | None = None,
) -> BranchSecrets:
    """Validate metadata and parse exactly the two governed keys."""

    owner = os.geteuid() if expected_uid is None else expected_uid
    raw = _read_validated_bytes(
        Path(path), max_file_bytes=max_file_bytes, expected_uid=owner
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretFileError("Secret file is not UTF-8.") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or "=" not in line:
            raise SecretFileError("Secret file contains a malformed line.")
        key, value = line.split("=", 1)
        if key in values:
            raise SecretFileError("Secret file contains a duplicate key.")
        if key not in EXPECTED_KEYS:
            raise SecretFileError("Secret file contains an unexpected key.")
        if not value:
            raise SecretFileError("Secret file contains an empty value.")
        values[key] = value
    if tuple(values) != EXPECTED_KEYS or set(values) != set(EXPECTED_KEYS):
        raise SecretFileError("Secret file key set or order is not exact.")
    url = _normalize_branch_url(values[BRANCH_URL_KEY])
    if url != _normalize_branch_url(expected_branch_url):
        raise SecretFileError("Secret file branch URL differs from the approved target.")
    token = _token_from_stdout(
        values[BRANCH_TOKEN_KEY].encode("utf-8"),
        max_token_bytes=DEFAULT_MAX_TOKEN_BYTES,
    )
    return BranchSecrets(url, token)


def verify_secret_file_absent(path: Path) -> None:
    if os.path.lexists(path):
        raise SecretFileError("Secret-file disposal could not be verified.")


def unlink_and_verify_secret_file(path: Path) -> None:
    try:
        os.unlink(path)
        _fsync_directory(Path(path).parent)
    except FileNotFoundError:
        pass
    verify_secret_file_absent(path)


@contextmanager
def branch_secret_file(
    directory: Path,
    filename: str,
    *,
    branch_url: str,
    token_stdout: bytes,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_token_bytes: int = DEFAULT_MAX_TOKEN_BYTES,
) -> Iterator[tuple[Path, BranchSecrets]]:
    """Yield validated branch secrets and always unlink the exact path."""

    path = create_branch_secret_file(
        directory,
        filename,
        branch_url=branch_url,
        token_stdout=token_stdout,
        max_file_bytes=max_file_bytes,
        max_token_bytes=max_token_bytes,
    )
    try:
        yield path, validate_branch_secret_file(
            path,
            expected_branch_url=branch_url,
            max_file_bytes=max_file_bytes,
        )
    finally:
        unlink_and_verify_secret_file(path)
