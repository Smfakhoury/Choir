"""The fstar prover profile (design note 12 §2.2, §3.3).

Covers F* and Pulse in one profile. Pulse is not a separate language
with its own files: a `#lang-pulse` pragma switches the *remainder of
an ordinary `.fst` file* into Pulse syntax, which F*'s lexer hands to
the Pulse syntax extension as a blob
(`src/parser/FStarC.Parser.Lexer.fst:312`, token `USE_LANG_BLOB`).
Since both halves share one file extension and one build, splitting
them into two profiles would mean two profiles claiming `.fst` — so
the declaration vocabulary below is the union, and Pulse's own
grammar agrees that this is the right union: its decl-boundary
predicate is literally F*'s list plus `fn`
(`pulse/src/syntax_extension/PulseSyntaxExtension.Grammar.fst:617`).

TRUST MODEL — F* needs both of Choir's layers, and the reason is
specific. `--report_assumes` is **use-site, not transitive**: with a
dependency's `.checked` cache populated, checking a module that calls
an admitted lemma in another module reports *nothing* (verified on
nightly-2026-08-26; a first test looked transitive only because the
missing cache forced the dependency to be re-elaborated). Separately,
it never reports `assume val` at all — neither the declaration nor its
uses. So:

- `trust_patterns` (source-level, drives the **blocking**
  `axiom-honesty` check) carries `assume`/`admit`/`magic` and the
  admit-flavoured options. This is the layer that catches a worker
  introducing an axiom.
- `trust_report_command` (the toolchain probe, informational only —
  `gate.provers.trust.collect_trust_report` is reached solely from
  `gate/verify/trust_report_cli.py`) inventories real use sites with
  locations for the overseer.

Clean-room rebuild is what makes the use-site probe project-complete:
the gate rebuilds from source with no warm cache, so every escape
hatch in the project is elaborated and therefore reported. The
residual gap is honest and documented rather than papered over — a
target proved by routing through a *pre-existing* admitted lemma is
not attributed to that target, unlike lean4's `#print axioms`, which
returns a transitive closure. `sorry-delta` would not flag it either
(delta zero; the admit was already at base). The inventory listing
every admit with its location is the mitigation.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from gate.provers.base import CommentSyntax, ProverProfile, TrustEntry
from gate.provers.decl_syntax import decl_line_regex_for, decl_prefix_fragment

# ---------------------------------------------------------------------------
# Declaration grammar.
# ---------------------------------------------------------------------------

# PROVENANCE: transcribed from F*'s own parser, not reconstructed from
# documentation or sample files. `start_of_next_decl_kinds`
# (`src/parser/FStarC.Parser.Grammar.fst:346-351`, FStarLang/FStar) is
# precisely F*'s internal answer to the question Choir's declaration
# scanner asks — "does a new declaration start here?" — so it is
# transcribed wholesale rather than guessed at. Spellings come from the
# lexer's keyword table (`src/parser/FStarC.Parser.Lexer.fst:69-145`).
#
# Excluded from that list on purpose: the qualifier tokens (they are
# `_DECL_MODIFIERS` below), the pragmas (`_CONTROL_FLAGS`), `EOF`, and
# the attribute brackets (`_ATTRIBUTE_SYNTAX`).
#
# `fn` is Pulse's declaration keyword
# (`PulseSyntaxExtension.Grammar.fst:99`, where the parser does
# `expect ps (KEYWORD "fn")`).
#
# The splice forms are spelled with their leading `%` — `lexer.fst:266`
# maps the string `"%splice"` to the token `SPLICE`, and `:267`
# `"%splice_t"` to `SPLICET`. Transcribing the *token* names instead
# would be wrong in both directions: bare `splice` is not a reserved
# word, so a line beginning with it as an ordinary application would
# invent a boundary, while the real `%splice[names] (tac)` form — a
# tactic that generates top-level declarations, so a trust surface —
# would not be recognised as one at all.
_DECL_KEYWORDS = (
    "class",
    "effect",
    "exception",
    "fn",
    "friend",
    "include",
    "instance",
    "let",
    "module",
    "new_effect",
    "open",
    "%splice",
    "%splice_t",
    "sub_effect",
    "type",
    "val",
)

# Declarations whose statement `extract_fstar_statement` can resolve.
# Narrower than `_DECL_KEYWORDS` because most of the rest are not
# proof-carrying at all: `open`/`include`/`friend`/`module` are
# directives, and the effect and splice forms have no statement/body
# split this extractor models. Being absent here is not a gap — a
# keyword outside `statement_keywords` is simply never asked for a
# statement.
_STATEMENT_KEYWORDS = (
    "val",
    "let",
    "fn",
    "type",
)

# Definition-bearing declarations, whose bodies are compared whole
# rather than allowed to be rewritten.
#
# This is the one genuinely awkward call in the profile, and it is
# deliberately made in the fail-closed direction. F* does not separate
# "theorem" from "definition" the way lean4 does: `let` introduces
# both a lemma (`let foo .. : Lemma (..) = <proof>`) and an ordinary
# value (`let n : int = 5`), and telling them apart needs the *type*,
# not the keyword. Leaving `let` out would mean a definition's body
# could be silently rewritten — fail-open, a real soundness hole.
# Including it means a proof-golfing edit to an existing F* proof
# reports CHANGED, which is a false block.
#
# A false block is recoverable and visible; a fail-open hole is
# neither. This also costs less than it appears: `base.py`'s
# placeholder escape means a `prove` task — where the base body is
# still `admit ()` — is compared statement-only, so the common case is
# unaffected. It is `golf`-shaped tasks that pay. isabelle sits in
# exactly this position for the same reason.
_DEFINITION_KEYWORDS = (
    "let",
    "fn",
    "type",
)

# PROVENANCE: `qualifier_kinds`, `FStarC.Parser.Grammar.fst:339-343`,
# plus Pulse's four `fn`-qualifiers — `ghost`, `atomic`,
# `unobservable`, `divergent` — each of which the Pulse grammar admits
# only when the next token is `fn`
# (`PulseSyntaxExtension.Grammar.fst:278-282`).
_DECL_MODIFIERS = (
    "assume",
    "atomic",
    "divergent",
    "ghost",
    "inline",
    "inline_for_extraction",
    "irreducible",
    "logic",
    "new",
    "noeq",
    "noextract",
    "opaque",
    "private",
    "reifiable",
    "reflectable",
    "total",
    "unfold",
    "unfoldable",
    "unobservable",
    "unopteq",
)

# `[@@ ...]` is the modern spelling and `[@ ...]` the legacy one; the
# lexer carries both (`LBRACK_AT_AT`/`LBRACK_AT`, listed in
# `start_of_next_decl_kinds`). `[@` is a prefix of `[@@`, so the
# shorter opener matches both.
_ATTRIBUTE_SYNTAX = ("[@", "]")

# PROVENANCE: `pragma_start_kinds`, `FStarC.Parser.Grammar.fst:333-337`.
# These may legally sit between declarations and before the
# declaration they govern, so the scanner has to step over them to
# find the real boundary. `#lang-pulse` is the Pulse switch
# (`FStarC.Parser.Lexer.fst:312`).
_CONTROL_FLAGS = (
    r"#push-options",
    r"#pop-options",
    r"#set-options",
    r"#reset-options",
    r"#restart-solver",
    r"#print-effects-graph",
    r"#lang-pulse",
)

# `%splice` attaches its generated-name list directly to the keyword
# with no whitespace — `%splice[name1; name2] (tac ())` — which
# `decl_line_regex`'s `KEYWORD\s+` cannot match, leaving the
# declaration unenumerated. `ProverProfile.decl_keyword_suffix` exists
# for exactly this shape (isabelle's `theorem%important`).
_DECL_KEYWORD_SUFFIX = r"\[[^\]]*\]"

_DECL_PREFIX = decl_prefix_fragment(
    _DECL_MODIFIERS, _ATTRIBUTE_SYNTAX, prefix_flags=_CONTROL_FLAGS
)

# ---------------------------------------------------------------------------
# Statement extraction.
# ---------------------------------------------------------------------------

_COMMENT_OPEN = "(*"
_COMMENT_CLOSE = "*)"
_LINE_COMMENT = "//"

# F* operator characters. A top-level `=` is a definition's body
# separator only when it is a lone `=`; adjoining any of these makes it
# part of a different operator (`==`, `=!=`, `==>`, `<==>`, `>=`, `:=`,
# `=>`), which must not be mistaken for the body split.
_OPERATOR_CHARS = set("=<>|&^+-*/%!:?~@$.")

_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = {")": "(", "]": "[", "}": "{"}

# `{|` and `|}` are SINGLE tokens in F*'s lexer
# (`src/parser/FStarC.Parser.Lexer.fst:213,218` — `LBRACE_BAR` and
# `BAR_RBRACE`), not a brace adjacent to a bar, and Pulse writes
# typeclass instance binders with them: `fn f (#a:Type) {| d: dict a |}`.
# They must be consumed as a pair *before* the single-character arms
# see them, because `fn`'s body separator is itself `{`: letting the
# `{` of `{|` be read as the body opener truncates the statement at the
# instance binder and silently reclassifies the whole
# `requires`/`ensures`/`returns` spec as rewritable body.
_TWO_CHAR_OPENER = "{|"
_TWO_CHAR_CLOSER = "|}"


def _body_separator_index(text: str, start: int, end: int, separator: str) -> int | None:
    """Index of the top-level `separator` in `text[start:end]`, or None.

    Comment-, string- and bracket-aware: F* has nesting `(* … *)` block
    comments (verified against the toolchain), `//` line comments, and
    `"…"` strings, and a separator inside any of them — or inside any
    bracket pair — is not the declaration's body split. A refinement
    like `x:int{x = 0}` keeps its `=` at depth one for exactly this
    reason.

    The separator is tested *before* bracket tracking, because Pulse's
    separator is itself an opener: `fn f () { … }` splits at a `{` that
    the bracket arm would otherwise consume as depth. Order does not
    affect the `=` case, which is not a bracket.

    Returns None when no top-level separator is found, which the caller
    turns into UNDETERMINED rather than a guess.
    """
    i = start
    depth = 0
    while i < end:
        ch = text[i]
        if text.startswith(_COMMENT_OPEN, i):
            nesting = 1
            i += len(_COMMENT_OPEN)
            while i < end and nesting:
                if text.startswith(_COMMENT_OPEN, i):
                    nesting += 1
                    i += len(_COMMENT_OPEN)
                elif text.startswith(_COMMENT_CLOSE, i):
                    nesting -= 1
                    i += len(_COMMENT_CLOSE)
                else:
                    i += 1
            continue
        if text.startswith(_LINE_COMMENT, i):
            newline = text.find("\n", i)
            i = end if newline == -1 or newline >= end else newline + 1
            continue
        if ch == '"':
            i += 1
            while i < end:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if text.startswith(_TWO_CHAR_OPENER, i):
            depth += 1
            i += len(_TWO_CHAR_OPENER)
            continue
        if text.startswith(_TWO_CHAR_CLOSER, i):
            if depth == 0:
                return None
            depth -= 1
            i += len(_TWO_CHAR_CLOSER)
            continue
        if depth == 0 and text.startswith(separator, i):
            if separator == "=":
                before = text[i - 1] if i > start else " "
                after = text[i + 1] if i + 1 < end else " "
                if before in _OPERATOR_CHARS or after in _OPERATOR_CHARS:
                    i += 1
                    continue
            return i
        if ch in _OPENERS:
            depth += 1
            i += 1
            continue
        if ch in _CLOSERS:
            # A closer at depth zero means the declaration's span was
            # mis-identified; stop rather than run past it.
            if depth == 0:
                return None
            depth -= 1
            i += 1
            continue
        i += 1
    return None


_DECL_LINE_RE_HOLDER: list[re.Pattern[str]] = []


def _decl_line_re() -> re.Pattern[str]:
    """The profile's own declaration-boundary regex, built once.

    Read off `FSTAR` via `decl_line_regex_for` so every prefix shape
    stays in step with the other `gate/` scanners; deferred because
    `FSTAR` is defined below this function.
    """
    if not _DECL_LINE_RE_HOLDER:
        _DECL_LINE_RE_HOLDER.append(decl_line_regex_for(FSTAR))
    return _DECL_LINE_RE_HOLDER[0]


def _next_decl_offset(text: str, after: int) -> int:
    """Offset of the next declaration line at or after `after`, else len(text).

    `decl_line_regex_for` builds a *line* matcher — it is anchored with
    `^` but carries no `MULTILINE` flag, and every other `gate/`
    consumer applies it per line with `.match(line)`. Scanning the
    whole buffer with `finditer` would therefore silently find only the
    match at offset zero, so this walks lines the same way the rest of
    the gate does.
    """
    decl_re = _decl_line_re()
    offset = text.find("\n", after)
    if offset == -1:
        return len(text)
    offset += 1
    while offset < len(text):
        end_of_line = text.find("\n", offset)
        line = text[offset:] if end_of_line == -1 else text[offset:end_of_line]
        if decl_re.match(line) is not None:
            return offset
        if end_of_line == -1:
            return len(text)
        offset = end_of_line + 1
    return len(text)


def extract_fstar_statement(text: str, decl_name: str) -> str | None:
    """Return `decl_name`'s statement, or None when undetermined.

    F* has no sentence terminator — no Rocq `.`, no `;;` — so a
    declaration ends exactly where the next one begins. The span is
    therefore found with the shared declaration-boundary regex, and the
    statement is carved out of it by keyword:

    - `val name : t` has no body at all; the whole span *is* the
      statement.
    - `let name .. : t = body` splits at the top-level `=`.
    - `fn name .. { body }` (Pulse) splits at the top-level `{`, which
      opens the function body.

    Anything that does not resolve cleanly returns None — UNDETERMINED,
    which passes and defers to review. Syntactic v0, the same maturity
    as the lean4 and rocq extractors.

    Declarations and boundaries are located in a COMMENT-BLANKED copy,
    never the raw text, matching `gate.verify.style.find_decl_spans`.
    Scanning raw lines would let a comment whose first token happens to
    be a declaration keyword (`let us recall that …`) read as the next
    declaration, truncating the statement before it and silently
    reclassifying its tail as rewritable body — and would equally let a
    declaration pasted inside a comment be matched as the real one.
    `strip_comments` overwrites comment characters with spaces, so
    offsets stay aligned and the returned slice is still taken from the
    raw text, preserving any comment that genuinely sits inside the
    statement.
    """
    # Imported here, not at module scope: `gate.inventory.scan` imports
    # `LEAN4` from `gate.provers`, so a module-level import would close
    # a cycle through this package's `__init__`.
    from gate.inventory.scan import strip_comments

    blanked = strip_comments(text, comment_syntax=FSTAR.comment_syntax)
    pattern = re.compile(
        rf"^{_DECL_PREFIX}(?P<kw>{'|'.join(_STATEMENT_KEYWORDS)})\s+"
        rf"(?:rec\s+)?(?P<name>{re.escape(decl_name)})\b",
        re.MULTILINE,
    )
    match = pattern.search(blanked)
    if match is None:
        return None

    start = match.start()
    end = _next_decl_offset(blanked, match.end())

    keyword = match.group("kw")
    if keyword == "val":
        return text[start:end].strip() or None

    separator = "{" if keyword == "fn" else "="
    split = _body_separator_index(blanked, match.end(), end, separator)
    if split is None:
        # A `fn` with no top-level `{` is a signature with no body —
        # the form Pulse interfaces (`.fsti`) use, where `fn` plays
        # exactly the role `val` plays in F*. Measured over the shipped
        # ulib and Pulse libraries, 497 of 581 interface `fn`
        # declarations take this shape, so treating "no body found" as
        # a parse failure would discard most of the Pulse interface
        # surface. The whole span is the statement, as for `val`.
        #
        # Deliberately not extended to `let`: a `let` with no top-level
        # `=` is malformed rather than body-less, and returning its
        # span as a statement would assert something the parse does not
        # support. That case stays UNDETERMINED.
        if keyword == "fn":
            return text[start:end].strip() or None
        return None
    return text[start:split].strip() or None


# ---------------------------------------------------------------------------
# Environment-level trust report.
# ---------------------------------------------------------------------------

# `--report_assumes warn` makes F* emit one warning per use of an
# escape hatch. Verified output shape (nightly-2026-08-26):
#
#     * Warning 335 at Mod.fst(2,22-2,27):
#       - Every use of Prims.admit triggers a warning
#       - Uses an axiom
#       - See also .../ulib/Prims.fst(431,0-431,38)
#
# and for the option form, which names no axiom:
#
#     * Warning 335 at Mod.fst(6,0-6,40):
#       - Every use of this option triggers a warning: admit_smt_queries
#
# Tactic-admitted goals arrive as Warning 296 ("Tactics admitted
# goal."), a different code, so both are matched.
_WARNING_HEADER_RE = re.compile(
    r"^\*\s+Warning\s+(?P<code>335|296)\s+at\s+(?P<loc>\S+?\([\d,\-]+\)):",
    re.MULTILINE,
)
_AXIOM_NAME_RE = re.compile(r"Every use of (?P<name>\S+) triggers a warning")
_OPTION_NAME_RE = re.compile(r"Every use of this option triggers a warning:\s*(?P<name>\S+)")
_TACTIC_ADMIT_RE = re.compile(r"Tactics admitted goal")


def fstar_trust_report_command(
    workspace: Path, targets: list[str], imports: list[str]
) -> list[str]:
    """Build the `--report_assumes` probe argv.

    `targets` are source files to check; `imports` are extra
    `--include` directories. No probe file is written — unlike rocq and
    isabelle, F* takes the request entirely on the command line, so
    there is nothing for `collect_trust_report` to clean up.

    Wrapped in `sh -c` for one specific reason: F* writes these
    warnings to **stderr** (verified by stream-splitting the probe),
    while the shared runner in `gate.provers.trust` captures
    `result.stdout`. Redirecting here keeps the fix inside this profile
    instead of changing a code path that lean4, isabelle and rocq all
    depend on and that their parsers were validated against.
    """
    argv = ["fstar.exe", "--report_assumes", "warn"]
    for include in imports:
        argv += ["--include", include]
    argv += list(targets)
    return ["sh", "-c", f"{shlex.join(argv)} 2>&1"]


def parse_fstar_trust_report(output: str) -> list[TrustEntry]:
    """Parse `--report_assumes` output into one entry per use site.

    Keyed by source location rather than by declaration name, because
    that is the granularity F* actually reports — it names the file,
    line and column of the use, never the enclosing declaration.
    Inventing a declaration attribution here would overstate what the
    probe knows; the location is what the overseer needs to find the
    hatch anyway.

    F* prints each warning twice (verified), so entries are
    de-duplicated.
    """
    entries: list[TrustEntry] = []
    seen: set[tuple[str, str]] = set()

    headers = list(_WARNING_HEADER_RE.finditer(output))
    for index, header in enumerate(headers):
        body_end = headers[index + 1].start() if index + 1 < len(headers) else len(output)
        body = output[header.end() : body_end]
        location = header.group("loc")

        axiom = _AXIOM_NAME_RE.search(body)
        option = _OPTION_NAME_RE.search(body)
        if option is not None:
            name = f"option:{option.group('name')}"
        elif axiom is not None:
            name = axiom.group("name")
        elif _TACTIC_ADMIT_RE.search(body):
            name = "tactic:admitted_goal"
        else:
            continue

        key = (location, name)
        if key in seen:
            continue
        seen.add(key)
        entries.append(TrustEntry(decl=location, assumptions=(name,), clean=False))

    return entries


def qualify_fstar_decl_names(text: str) -> dict[int, str]:
    """Each declaration line mapped to its declared name — a DISAMBIGUATION key.

    Not name resolution; see `gate.provers.decl_syntax.qualify_by_scope`
    for why that distinction matters. F* needs no scope path, and the
    reason is structural rather than an omission: a file *is* a module,
    and F* has no in-file scope block (no lean4 `namespace`, no rocq
    `Module`/`Section`) that two same-named declarations could hide in.
    Top-level names are unique within a module, so the surface name
    already answers the only question this key is asked — *which
    declaration does this placeholder belong to?*

    The enclosing `module M` prefix is deliberately NOT applied. It is
    constant across the file, so it adds no disambiguation, and
    including it would make renaming the module change every key in the
    file at once — churn with no benefit on a key that must be computed
    identically over base and head.

    Line numbers are 1-based, matching `qualify_by_scope`.
    """
    decl_re = _decl_line_re()
    named_re = re.compile(
        rf"^{_DECL_PREFIX}(?:{'|'.join(_DECL_KEYWORDS)})\s+(?:rec\s+)?"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)\b"
    )
    result: dict[int, str] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        if decl_re.match(line) is None:
            continue
        named = named_re.match(line)
        if named is not None:
            result[line_no] = named.group("name")
    return result


FSTAR = ProverProfile(
    name="fstar",
    file_extensions=(".fst", ".fsti"),
    # F* is the only supported prover with *both* comment forms: `//`
    # to end of line and nesting `(* … *)` (nesting verified against
    # the toolchain, not assumed). No cartouche-like verbatim bracket.
    comment_syntax=CommentSyntax(line=_LINE_COMMENT, block_open="(*", block_close="*)"),
    decl_keywords=_DECL_KEYWORDS,
    statement_keywords=_STATEMENT_KEYWORDS,
    definition_keywords=_DEFINITION_KEYWORDS,
    # `admit` and `magic` only. `assume` is deliberately *not* here:
    # it is a declaration qualifier (`assume val foo : t`) as much as a
    # proof hatch, and `placeholder_tokens` feeds the blocking
    # `sorry-delta` count, where ordinary vocabulary must not appear.
    # It is caught by `trust_patterns` below instead, which is the
    # layer built for axioms.
    placeholder_tokens=("admit", "magic"),
    trust_patterns=(
        ("assume", r"\bassume\b"),
        ("admit", r"\badmit\b"),
        ("magic", r"\bmagic\b"),
        # The tactic-level admits need their own alternation because
        # `\badmit\b` matches none of them: there is no word boundary
        # inside `tadmit`, nor after the `t` in `admit1`. Each one
        # closes any goal, and each one REMOVES the base `admit ()` it
        # replaces, so `sorry-delta` sees a decrease and reads the edit
        # as progress. Spellings from `FStar.Tactics.V2.Derived.fst`.
        ("tactic_admit", r"\b(?:admit_all|admit1|tadmit(?:_t)?)\b"),
        # Option-level hatches, which disable checking rather than
        # discharge a goal. `--lax` skips verification wholesale and
        # `--admit_except` admits everything but one name; neither is
        # reachable from the patterns above (`\badmit\b` does not match
        # `admit_except` — `_` is a word character). rocq's profile
        # already treats option-level hatches such as `Unset Universe
        # Checking` as in scope, so omitting these would be a gap
        # against the project's own standard.
        ("admit_option", r"\b(?:admit_smt_queries|admit_except)\b|--lax\b"),
    ),
    build_command=("make", "verify"),
    # F* pins no toolchain file of its own — there is no `lean-toolchain`
    # equivalent — so the version is pinned by the project's workflow.
    toolchain_file=None,
    protected_files=("Makefile", "*.mk", "fstar.config.json"),
    extra_audits=(),
    search_tooling_note=False,
    extract_statement=extract_fstar_statement,
    trust_report_command=fstar_trust_report_command,
    parse_trust_report=parse_fstar_trust_report,
    # One probe covers every target: F* checks whole files and reports
    # every use site in them, so there is nothing to gain from
    # per-declaration invocation (and, unlike rocq, no way to ask about
    # a single declaration in the first place).
    one_probe_per_decl=False,
    decl_modifiers=_DECL_MODIFIERS,
    attribute_syntax=_ATTRIBUTE_SYNTAX,
    decl_prefix_flags=_CONTROL_FLAGS,
    decl_keyword_suffix=_DECL_KEYWORD_SUFFIX,
    qualify_decl_names=qualify_fstar_decl_names,
)
