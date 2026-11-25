#!/usr/bin/env python3
"""Your Agent in One Emoji — make.fun bounty entry.

Writes a single emoji glyph to /output/entry.txt (or $MAKEFUN_OUTPUT_DIR).

The emoji: octopus. One body, eight arms, each arm doing a different job at
the same time — that is how this agent works: it spawns subagents that run in
parallel, verifies its own work deterministically, iterates, and keeps going
in the background. No robot face, no sparkle: an octopus is unmistakable at
small size and says something specific about parallel agency.

Pure Python 3 standard library. Deterministic. No network access.
"""

import argparse
import hashlib
import os
import sys
import tempfile
import unicodedata

# The entry: a single emoji glyph.
EMOJI = "\U0001F419"  # U+1F419 OCTOPUS

# The sealed scorer's gate: UTF-8 text of 1 to 16 characters, not only
# whitespace. We hold ourselves to a stricter internal rule: exactly one
# emoji glyph, nothing else (no newline, no trailing space).
MIN_CHARS = 1
MAX_CHARS = 16


def is_emoji_char(ch):
    """Best-effort single-character emoji check from the stdlib alone.

    Python's unicodedata has no emoji property, so we use the Unicode
    category plus the known emoji code-point ranges. Our entry is a single
    code point in the 1F300-1FAFF "symbols and pictographs" block, which is
    unambiguous. The range table below covers the common emoji blocks so
    the validator is honest about what it accepts rather than hard-coding
    one answer.
    """
    code = ord(ch)
    if unicodedata.category(ch) in ("So", "Sk"):
        return True
    for lo, hi in (
        (0x1F000, 0x1FAFF),  # emoticons, pictographs, transport, etc.
        (0x2600, 0x27BF),    # misc symbols and dingbats
        (0xFE00, 0xFE0F),    # variation selectors
        (0x1F1E6, 0x1F1FF),  # regional indicators
        (0x200D, 0x200D),    # zero-width joiner (multi-glyph emoji)
        (0x2190, 0x21FF),    # arrows
        (0x2300, 0x23FF),    # misc technical
        (0x2B00, 0x2BFF),    # misc symbols and arrows
    ):
        if lo <= code <= hi:
            return True
    return False


def validate(text):
    """Validate an entry string. Raises ValueError with a reason on failure."""
    if not isinstance(text, str):
        raise ValueError("entry must be a str")
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        raise ValueError(
            "entry must be %d-%d characters, got %d" % (MIN_CHARS, MAX_CHARS, len(text))
        )
    if not text.strip():
        raise ValueError("entry must not be only whitespace")
    if len(text) != 1:
        raise ValueError("entry must be exactly one character, got %d" % len(text))
    if text != text.strip():
        raise ValueError("entry must not contain leading/trailing whitespace")
    if not is_emoji_char(text):
        raise ValueError("entry %r is not an emoji character" % text)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("entry is not encodable as UTF-8: %s" % exc)
    return True


def output_path(out_dir):
    return os.path.join(out_dir, "entry.txt")


def write_entry(out_dir, text=EMOJI):
    """Validate, write the emoji bytes, and verify the read-back matches."""
    validate(text)
    data = text.encode("utf-8")
    os.makedirs(out_dir, exist_ok=True)
    path = output_path(out_dir)
    with open(path, "wb") as fh:
        fh.write(data)
    with open(path, "rb") as fh:
        back = fh.read()
    if back != data:
        raise RuntimeError("read-back mismatch: wrote %r, read %r" % (data, back))
    return path, data


def check_existing(path):
    """Validate an existing entry.txt without writing anything."""
    with open(path, "rb") as fh:
        data = fh.read()
    text = data.decode("utf-8")
    validate(text)
    return text, data


def self_test():
    """Run the built-in checks: validators, round-trip, bad inputs."""
    checks = []

    def check(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            checks.append((name, False, str(exc)))
        else:
            checks.append((name, True, ""))

    check("valid entry passes", lambda: validate(EMOJI))
    check("empty rejected", lambda: _expect_reject(""))
    check("whitespace-only rejected", lambda: _expect_reject("   "))
    check("plain letter rejected", lambda: _expect_reject("A"))
    check("newline rejected", lambda: _expect_reject(EMOJI + "\n"))
    check("two emoji rejected", lambda: _expect_reject(EMOJI + EMOJI))
    check("too long rejected", lambda: _expect_reject("x" * 17))

    def round_trip():
        with tempfile.TemporaryDirectory() as tmp:
            path, data = write_entry(tmp)
            text, back = check_existing(path)
            assert text == EMOJI, "round-trip text mismatch"
            assert back == data, "round-trip bytes mismatch"
            assert hashlib.sha256(back).hexdigest() == hashlib.sha256(data).hexdigest()

    check("write/read-back round-trip in temp dir", round_trip)

    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, (": " + detail) if detail else ""))
    print("%d/%d self-test checks passed" % (len(checks) - len(failed), len(checks)))
    return 0 if not failed else 1


def _expect_reject(text):
    try:
        validate(text)
    except ValueError:
        return
    raise AssertionError("validate(%r) unexpectedly passed" % text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run validators + write/read-back round-trip in a temp dir",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate the existing output(s) without writing anything",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output/entry.txt")
    # MAKEFUN_OUTPUT_DIR may be given as a directory or as a full file path.
    if out_dir.endswith("entry.txt"):
        out_dir = os.path.dirname(out_dir) or "."

    repo_copy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entry.txt")

    if args.check_only:
        targets = [output_path(out_dir)]
        if os.path.exists(repo_copy):
            targets.append(repo_copy)
        for path in targets:
            text, data = check_existing(path)
            print(
                "OK %s: %r (%d chars, %d bytes, sha256 %s)"
                % (path, text, len(text), len(data), hashlib.sha256(data).hexdigest())
            )
        return 0

    path, data = write_entry(out_dir)
    with open(repo_copy, "wb") as fh:
        fh.write(data)
    print(
        "wrote %s: %r (%d chars, %d bytes, sha256 %s)"
        % (path, EMOJI, len(EMOJI), len(data), hashlib.sha256(data).hexdigest())
    )
    print("repo copy: %s" % repo_copy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
