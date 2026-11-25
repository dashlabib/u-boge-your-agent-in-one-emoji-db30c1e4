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


# Emoji-presentation code points (Unicode Emoji_Presentation, approximated
# from the stdlib alone). A base character must be in one of these ranges
# to count as an emoji. Category So/Sk alone is NOT enough: it admits
# arrows, technical symbols and other marks that are not emoji at all.
EMOJI_PRESENTATION_RANGES = (
    (0x00A9, 0x00A9), (0x00AE, 0x00AE),  # (c) (r)
    (0x203C, 0x203C), (0x2049, 0x2049),  # !! !?
    (0x2122, 0x2122), (0x2139, 0x2139),  # TM i
    (0x2194, 0x2199), (0x21A9, 0x21AA),  # diagonal / hooked arrows
    (0x231A, 0x231B), (0x2328, 0x2328), (0x2388, 0x2388),
    (0x23CF, 0x23CF), (0x23E9, 0x23F3), (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x2604), (0x260E, 0x260E), (0x2611, 0x2611),
    (0x2614, 0x2615), (0x2618, 0x2618), (0x261D, 0x261D),
    (0x2620, 0x2620), (0x2622, 0x2623), (0x2626, 0x2626),
    (0x262A, 0x262A), (0x262E, 0x262F), (0x2638, 0x263A),
    (0x2640, 0x2640), (0x2642, 0x2642), (0x2648, 0x2653),
    (0x265F, 0x2660), (0x2663, 0x2663), (0x2665, 0x2666),
    (0x2668, 0x2668), (0x267B, 0x267B), (0x267E, 0x267F),
    (0x2692, 0x2697), (0x2699, 0x2699), (0x269B, 0x269C),
    (0x26A0, 0x26A1), (0x26A7, 0x26A7), (0x26AA, 0x26AB),
    (0x26B0, 0x26B1), (0x26BD, 0x26BE), (0x26C4, 0x26C5),
    (0x26C8, 0x26C8), (0x26CE, 0x26CF), (0x26D1, 0x26D1),
    (0x26D3, 0x26D4), (0x26E9, 0x26EA), (0x26F0, 0x26F5),
    (0x26F7, 0x26FA), (0x26FD, 0x26FD),
    (0x2702, 0x2702), (0x2705, 0x2705), (0x2708, 0x270D),
    (0x270F, 0x270F), (0x2712, 0x2712), (0x2714, 0x2714),
    (0x2716, 0x2716), (0x271D, 0x271D), (0x2721, 0x2721),
    (0x2728, 0x2728), (0x2733, 0x2734), (0x2744, 0x2744),
    (0x2747, 0x2747), (0x274C, 0x274C), (0x274E, 0x274E),
    (0x2753, 0x2755), (0x2757, 0x2757), (0x2763, 0x2764),
    (0x2795, 0x2797), (0x27A1, 0x27A1), (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2921, 0x2922),
    (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0x1F000, 0x1FAFF),  # emoticons, pictographs, transport, etc.
)


def is_emoji_presentation_char(ch):
    """True iff a single code point has emoji presentation by default."""
    code = ord(ch)
    for lo, hi in EMOJI_PRESENTATION_RANGES:
        if lo <= code <= hi:
            return True
    return False


def _is_regional_indicator(ch):
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def _is_variation_selector(ch):
    return 0xFE00 <= ord(ch) <= 0xFE0F


def _is_emoji_modifier(ch):
    return 0x1F3FB <= ord(ch) <= 0x1F3FF  # skin-tone modifiers


def grapheme_clusters(text):
    """Split text into extended grapheme clusters (simplified UAX #29).

    Handles the joins that matter for emoji: ZWJ sequences, variation
    selectors, emoji modifiers (skin tones), keycaps (U+20E3), combining
    marks, and regional-indicator pairs (flags). Anything else starts a
    new cluster. A lone code point is its own cluster, so this agrees
    with len() on plain text but counts a multi-code-point emoji as one.
    """
    clusters = []
    current = ""
    prev = ""
    ri_run = 0  # regional indicators at the end of the current cluster
    for ch in text:
        if not current:
            current = ch
            ri_run = 1 if _is_regional_indicator(ch) else 0
            prev = ch
            continue
        joins = (
            prev == "\u200d"  # char after a ZWJ joins the sequence
            or ch == "\u200d"
            or _is_variation_selector(ch)
            or _is_emoji_modifier(ch)
            or ch == "\u20e3"  # combining enclosing keycap
            or unicodedata.category(ch) in ("Mn", "Me")
            or (
                _is_regional_indicator(ch)
                and _is_regional_indicator(prev)
                and ri_run % 2 == 1  # second RI of a pair joins the flag
            )
        )
        if joins:
            current += ch
            ri_run = ri_run + 1 if _is_regional_indicator(ch) else 0
        else:
            clusters.append(current)
            current = ch
            ri_run = 1 if _is_regional_indicator(ch) else 0
        prev = ch
    if current:
        clusters.append(current)
    return clusters


def is_single_emoji(text):
    """True iff text is exactly one grapheme cluster forming one emoji.

    The cluster's base character must be an emoji-presentation character
    (a keycap sequence is the one exception: digit / # / * + U+20E3),
    and nothing else may hide inside the cluster: no whitespace, no
    letter, no second base character. A lone variation selector, ZWJ or
    combining mark is not an emoji, and two adjacent emoji are two
    clusters, so they fail here.
    """
    clusters = grapheme_clusters(text)
    if len(clusters) != 1:
        return False
    cluster = clusters[0]
    if not cluster:
        return False
    if "\u20e3" in cluster:  # keycap: e.g. "1" + VS16 + U+20E3
        return cluster[0] in "0123456789#*"
    if not is_emoji_presentation_char(cluster[0]):
        return False
    for ch in cluster:
        if ch.isspace() or unicodedata.category(ch).startswith("L"):
            return False
    return True


def validate(text):
    """Validate an entry string. Raises ValueError with a reason on failure.

    Enforces the competition gate exactly: 1-16 characters, not only
    whitespace, and exactly one emoji — a single grapheme cluster whose
    base character has emoji presentation. A second emoji, a letter, or
    whitespace anywhere in the text fails, as does any non-emoji symbol
    (an arrow or technical mark is not an emoji). A multi-code-point
    emoji that is genuinely one grapheme (a ZWJ sequence, a flag, a
    keycap) passes; that is the point of counting graphemes instead of
    code points.
    """
    if not isinstance(text, str):
        raise ValueError("entry must be a str")
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        raise ValueError(
            "entry must be %d-%d characters, got %d" % (MIN_CHARS, MAX_CHARS, len(text))
        )
    if not text.strip():
        raise ValueError("entry must not be only whitespace")
    if any(ch.isspace() for ch in text):
        raise ValueError("entry must not contain whitespace")
    if not is_single_emoji(text):
        raise ValueError("entry must be exactly one emoji, got %r" % text)
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
    check("17-char input rejected", lambda: _expect_reject(EMOJI * 17))
    check("16-char non-emoji rejected", lambda: _expect_reject("x" * 16))
    check("letter beside emoji rejected", lambda: _expect_reject("A" + EMOJI))
    check("emoji with trailing space rejected", lambda: _expect_reject(EMOJI + " "))
    check("arrow rejected (not emoji presentation)", lambda: _expect_reject("\u2190"))
    check("lone variation selector rejected", lambda: _expect_reject("\ufe0f"))
    check("lone ZWJ rejected", lambda: _expect_reject("\u200d"))
    check(
        "ZWJ family is one emoji",
        lambda: validate("\U0001F468\u200d\U0001F469\u200d\U0001F467"),
    )
    check("flag is one emoji", lambda: validate("\U0001F1FA\U0001F1F8"))
    check("keycap is one emoji", lambda: validate("1\ufe0f\u20e3"))

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
