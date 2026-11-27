#!/usr/bin/env python3
"""PreToolUse rewrite on Bash: every variable in a delete path is guarded, so a delete never stops on a prompt.

Claude Code asks before an ``rm`` whose path uses a variable that could be empty (``rm -rf $O/$n/renders`` reads as
``rm -rf //renders`` when both are unset), even in bypassPermissions mode, and tells the agent to write
``"${O:?}"/"${n:?}"/renders`` instead. This hook makes that rewrite itself: in the path arguments of an ``rm`` or
``rmdir`` (after its options, or everything after ``--``), each unguarded ``$NAME``, ``${NAME}`` or ``$1`` becomes
``${NAME:?}``, quoted, so the shell stops with "parameter null or not set" when it is empty and deletes nothing. The
rewritten command goes back as ``hookSpecificOutput.updatedInput``; Claude Code checks its permissions against that
input, not the one the agent sent, so the guarded delete runs with no prompt. No ``permissionDecision`` is given: a
hook's "allow" cannot approve such a removal anyway, and every other check still runs on the rewritten command.

What it never touches: any command that is no ``rm``/``rmdir``; options, redirections, single-quoted text, ``$(...)``
and backticks, ``${NAME:-x}`` and every other expansion with an operator, ``$@``/``$*``/``$?`` and the like, and
inline ``bash -c`` scripts. A literal glob or ``~`` stays unquoted, so it still expands: ``$D/*.png`` becomes
``"${D:?}"/*.png``. With every variable set, the guarded command deletes what the original would have, with one
difference: an unquoted variable that holds several space-separated paths is now one quoted path.

FAILURE POLICY: fail-open. A command it cannot read (an unterminated quote, an unknown shape) or a rewrite that
``bash -n`` would not parse is left exactly as sent: exit 0, no output.
"""

import json
import re
import shutil
import subprocess
import sys

_DELETES = {"rm", "rmdir"}
_WRAPPERS = {"sudo", "command", "builtin", "exec", "nohup", "nice", "env", "xargs", "timeout", "stdbuf", "ionice",
             "time"}
_RESERVED = {"!", "{", "}", "do", "then", "else", "elif", "if", "while", "until"}
_SEPARATORS = ("&&", "||", ";;", "|&", ";", "&", "|", "(", ")", "\n")
_REDIRECTS = ("<<<", "<<-", "<<", ">>", "&>>", "&>", "<&", ">&", ">|", "<>", "<", ">")
_METACHARS = set(" \t\n;&|()<>")
_SAFE = re.compile(r"[A-Za-z0-9_./,:@%+=-]")  # a literal char that means the same inside double quotes
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*\+?=")
_NAME = re.compile(r"[A-Za-z_]\w*|\d+")


class Unreadable(Exception):
    """The command has a shape this hook does not read; it is left as sent."""


def _closing(text, start, opener, closer):
    """The index just past the `closer` that matches the `opener` at text[start], quotes and escapes skipped."""
    depth, index = 0, start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "'" and opener != "{":
            end = text.find("'", index + 1)
            if end < 0:
                raise Unreadable("an unterminated quote")
            index = end + 1
            continue
        if char == '"' and opener != "{":
            index = _double_quoted_end(text, index)
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise Unreadable(f"an unclosed {opener}")


def _double_quoted_end(text, start):
    """The index just past the double-quoted string that opens at text[start]."""
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
        elif char == '"':
            return index + 1
        elif text.startswith("$(", index):
            index = _closing(text, index + 1, "(", ")")
        elif text.startswith("${", index):
            index = _closing(text, index + 1, "{", "}")
        elif char == "`":
            index = _backtick_end(text, index)
        else:
            index += 1
    raise Unreadable("an unterminated quote")


def _backtick_end(text, start):
    """The index just past the backtick substitution that opens at text[start]."""
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == "`":
            return index + 1
        else:
            index += 1
    raise Unreadable("an unterminated backtick")


def _dollar(text, index, quoted):
    """The piece a `$` at text[index] starts, as (kind, raw text, variable name or None), and where it ends."""
    rest = text[index + 1:index + 2]
    if rest == "(":
        end = _closing(text, index + 1, "(", ")")
        return ("opaque", text[index:end], None), end
    if rest == "{":
        end = _closing(text, index + 1, "{", "}")
        inner = text[index + 2:end - 1]
        return ("var" if _NAME.fullmatch(inner) else "opaque", text[index:end], inner), end
    if rest == "'" and not quoted:
        close = index + 2
        while close < len(text) and text[close] != "'":
            close += 2 if text[close] == "\\" else 1
        if close >= len(text):
            raise Unreadable("an unterminated quote")
        return ("opaque", text[index:close + 1], None), close + 1
    name = re.match(r"[A-Za-z_]\w*|\d", text[index + 1:])
    if name:
        end = index + 1 + name.end()
        return ("var", text[index:end], name.group()), end
    end = index + (2 if rest else 1)
    return ("opaque", text[index:end], None), end


def _double_quoted_pieces(text, start):
    """A double-quoted string's pieces (each tagged "dq"), and where the string ends."""
    pieces, index, literal = [], start + 1, start + 1
    while True:
        if index >= len(text):
            raise Unreadable("an unterminated quote")
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char not in '"$`':
            index += 1
            continue
        if index > literal:
            pieces.append(("dq-text", text[literal:index], None))
        if char == '"':
            return pieces, index + 1
        if char == "`":
            end = _backtick_end(text, index)
            pieces.append(("dq-opaque", text[index:end], None))
        else:
            (kind, raw, name), end = _dollar(text, index, quoted=True)
            pieces.append(("dq-" + kind, raw, name))
        index = literal = end


def _word(text, start):
    """The word that starts at text[start]: its pieces, as (kind, raw text, variable name), and where it ends."""
    pieces, index = [], start
    while index < len(text) and text[index] not in _METACHARS:
        char = text[index]
        if char == "'":
            end = text.find("'", index + 1)
            if end < 0:
                raise Unreadable("an unterminated quote")
            pieces.append(("opaque", text[index:end + 1], None))
            index = end + 1
        elif char == '"':
            inner, index = _double_quoted_pieces(text, index)
            pieces.extend(inner or [("dq-text", "", None)])
        elif char == "\\":
            pieces.append(("opaque", text[index:index + 2], None))
            index += 2
        elif char == "$":
            piece, index = _dollar(text, index, quoted=False)
            pieces.append(piece)
        elif char == "`":
            end = _backtick_end(text, index)
            pieces.append(("opaque", text[index:end], None))
            index = end
        else:
            pieces.append(("text", char, None))
            index += 1
    return pieces, index


def _heredoc_end(text, index, delimiter, strip_tabs):
    """Where a here-document's body that starts at text[index] ends (past its delimiter line)."""
    while index < len(text):
        line_end = text.find("\n", index)
        line_end = len(text) if line_end < 0 else line_end
        line = text[index:line_end]
        if (line.lstrip("\t") if strip_tabs else line) == delimiter:
            return line_end
        index = line_end + 1
    return len(text)


def simple_commands(text):
    """Every simple command's argument words, each as (start, end, pieces); redirections and their targets left out."""
    commands, words, index, pending_heredocs = [], [], 0, []
    redirect_target = None  # the redirect operator whose target word comes next
    while index < len(text):
        char = text[index]
        if char in " \t":
            index += 1
            continue
        if char == "\n" and pending_heredocs:
            for delimiter, strip_tabs in pending_heredocs:
                index = _heredoc_end(text, index + 1, delimiter, strip_tabs)
            pending_heredocs = []
            commands.append(words)
            words = []
            continue
        if char == "#" and not words:
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if text.startswith(("<(", ">("), index):
            end = _closing(text, index + 1, "(", ")")
            words.append((index, end, [("opaque", text[index:end], None)]))
            index = end
            continue
        redirect = next((op for op in _REDIRECTS if text.startswith(op, index)), None)
        if redirect:
            redirect_target = redirect
            index += len(redirect)
            continue
        separator = next((op for op in _SEPARATORS if text.startswith(op, index)), None)
        if separator:
            commands.append(words)
            words = []
            index += len(separator)
            continue
        pieces, end = _word(text, index)
        if redirect_target:
            if redirect_target.startswith("<<") and redirect_target != "<<<":
                delimiter = "".join(raw for _, raw, _ in pieces).strip("'\"").replace("\\", "")
                pending_heredocs.append((delimiter, redirect_target == "<<-"))
            redirect_target = None
        elif text[end:end + 1] in ("<", ">") and text[index:end].isdigit():
            pass  # a file descriptor number: part of the redirection that follows
        else:
            words.append((index, end, pieces))
        index = end
    commands.append(words)
    return commands


def _plain(pieces):
    """The word as plain text when it is only unquoted literal characters, else None."""
    return "".join(raw for _, raw, _ in pieces) if all(kind == "text" for kind, _, _ in pieces) else None


def delete_paths(words):
    """The words of this simple command that are an rm's or rmdir's path arguments ([] when it deletes nothing)."""
    position, after_wrapper = 0, False
    while position < len(words):
        plain = _plain(words[position][2])
        if plain is not None and (plain in _RESERVED or _ASSIGNMENT.match(plain)
                                  or (after_wrapper and re.fullmatch(r"-\S*|\d+(\.\d+)?[smhd]?", plain))):
            position += 1
            continue
        if plain is not None and plain.rsplit("/", 1)[-1] in _WRAPPERS:
            position, after_wrapper = position + 1, True
            continue
        break
    if position >= len(words):
        return []
    name = _plain(words[position][2]) or "".join(raw for _, raw, _ in words[position][2]).lstrip("\\")
    if name.rsplit("/", 1)[-1] not in _DELETES:
        return []
    paths, options_over = [], False
    for word in words[position + 1:]:
        plain = _plain(word[2])
        if not options_over and plain == "--":
            options_over = True
        elif options_over or not "".join(raw for _, raw, _ in word[2]).startswith("-"):
            paths.append(word)
    return paths


def guarded(pieces):
    """The word with every unguarded variable as a quoted ${NAME:?}; literal globs, ~ and escapes left outside the
    quotes so they mean what they meant."""
    out, run, waiting = [], [], []  # run: the open double-quoted text; waiting: safe literal chars not yet placed

    def close():
        if run:
            out.append('"' + "".join(run) + '"')
            run.clear()
    for kind, raw, name in pieces:
        if kind in ("var", "dq-var"):
            run.extend(waiting)
            waiting.clear()
            run.append("${" + name + ":?}")
        elif kind in ("dq-text", "dq-opaque"):
            run.extend(waiting)
            waiting.clear()
            run.append(raw)
        elif kind == "text" and _SAFE.fullmatch(raw):
            waiting.append(raw)
        else:
            close()
            out.extend(waiting)
            waiting.clear()
            out.append(raw)
    if run:
        run.extend(waiting)
        waiting.clear()
    close()
    return "".join(out + waiting)


def rewritten(command):
    """The command with every delete path's variables guarded, or None when nothing needed it."""
    edits = []
    for words in simple_commands(command):
        for start, end, pieces in delete_paths(words):
            if any(kind in ("var", "dq-var") for kind, _, _ in pieces):
                edits.append((start, end, guarded(pieces)))
    if not edits:
        return None
    for start, end, text in sorted(edits, reverse=True):
        command = command[:start] + text + command[end:]
    return command


def parses(command):
    """Whether bash reads the command without a syntax error (True when there is no bash to ask)."""
    bash = shutil.which("bash")
    if not bash:
        return True
    return subprocess.run([bash, "-n", "-c", command], capture_output=True, timeout=3).returncode == 0


def main():
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input") or {}
        command = tool_input.get("command")
        if payload.get("tool_name") != "Bash" or not isinstance(command, str):
            return
        new = rewritten(command)
        if new is None or new == command or not parses(new):
            return
    except Exception:  # fail-open: a broken rewrite must never wedge or change a tool call
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": {**tool_input, "command": new},
        "additionalContext": "rm_guard guarded the delete path's variables (empty stops it): " + new,
    }}))


if __name__ == "__main__":
    main()
