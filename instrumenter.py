"""
instrumenter.py
---------------
Parses a C/C++ source file and replaces each execution-block boundary
with a  LOG_FLAG("construct_N_filename")  call.

Flag naming:
    func1_main    – 1st function body in main.c
    if2_sensor    – 2nd if-block in sensor.c
    for3_motor    – 3rd for-loop in motor.c
    while1_utils  – 1st while-loop in utils.c
    switch1_main  – 1st switch in main.c
    case1_main    – 1st case-break in main.c  (inside switch)
    else1_main    – 1st else / else-if block
    do1_main      – 1st do-while body

Each flag point maps to  LOG_FLAG("name")  which appends one line to
coverage.log every time that line is executed.
"""

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

TOKEN_SPEC = [
    ("BLOCK_COMMENT",  r"/\*[\s\S]*?\*/"),
    ("LINE_COMMENT",   r"//[^\n]*"),
    ("STRING",         r'"(?:[^"\\]|\\.)*"'),
    ("CHAR_LIT",       r"'(?:[^'\\]|\\.)*'"),
    ("PREPROCESSOR",   r"^\s*#[^\n]*"),
    ("LBRACE",         r"\{"),
    ("RBRACE",         r"\}"),
    ("SEMICOLON",      r";"),
    ("COLON",          r":"),
    ("KEYWORD",        r"\b(?:if|else|while|for|do|switch|case|default|return|break|continue)\b"),
    ("LPAREN",         r"\("),
    ("RPAREN",         r"\)"),
    ("NEWLINE",        r"\n"),
    ("WHITESPACE",     r"[ \t]+"),
    ("OTHER",          r"."),
]

MASTER_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC),
    re.MULTILINE,
)


def tokenise(source: str) -> list[dict]:
    tokens = []
    for m in MASTER_RE.finditer(source):
        tokens.append({
            "type":  m.lastgroup,
            "value": m.group(),
            "start": m.start(),
            "end":   m.end(),
        })
    return tokens


# ---------------------------------------------------------------------------
# Edit helpers
# ---------------------------------------------------------------------------

def get_line_indent(source: str, pos: int) -> str:
    """Leading whitespace of the line containing char offset pos."""
    line_start = source.rfind("\n", 0, pos) + 1
    m = re.match(r"[ \t]*", source[line_start:])
    return m.group() if m else ""


def apply_edits(source: str, edits: list) -> str:
    """Apply all (pos, text) insertions, highest pos first so offsets stay valid."""
    for _, pos, text in sorted(edits, key=lambda e: e[1], reverse=True):
        source = source[:pos] + text + source[pos:]
    return source


# ---------------------------------------------------------------------------
# Analyser
# ---------------------------------------------------------------------------

class Analyser:
    """
    Walks the token stream, identifies execution blocks, and records
    (position, LOG_FLAG text) insertions.
    """

    def __init__(self, source: str, file_stem: str):
        self.source    = source
        self.stem      = file_stem          # e.g. "main", "sensor"
        self.tokens    = tokenise(source)
        self.idx       = 0
        self.edits: list = []

        # Per-construct counters for naming
        self._counters: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Counter / naming
    # ------------------------------------------------------------------ #

    def _next(self, construct: str) -> str:
        """Return next unique flag name for a construct, e.g. 'if3_sensor'."""
        n = self._counters.get(construct, 0) + 1
        self._counters[construct] = n
        return f"{construct}{n}_{self.stem}"

    # ------------------------------------------------------------------ #
    # Token navigation
    # ------------------------------------------------------------------ #

    def cur(self) -> dict | None:
        return self.tokens[self.idx] if self.idx < len(self.tokens) else None

    def adv(self) -> dict | None:
        t = self.cur()
        self.idx += 1
        return t

    def skip_trivia(self):
        """Skip whitespace, newlines, comments, preprocessor."""
        while self.cur() and self.cur()["type"] in (
            "WHITESPACE", "NEWLINE", "LINE_COMMENT", "BLOCK_COMMENT", "PREPROCESSOR"
        ):
            self.adv()

    def read_parens(self):
        """Consume balanced ( ... )."""
        assert self.cur() and self.cur()["type"] == "LPAREN"
        self.adv()
        depth = 1
        while self.cur() and depth > 0:
            if self.cur()["type"] == "LPAREN":
                depth += 1
            elif self.cur()["type"] == "RPAREN":
                depth -= 1
            self.adv()

    def consume_to_semicolon(self):
        while self.cur():
            if self.adv()["type"] == "SEMICOLON":
                return

    # ------------------------------------------------------------------ #
    # Flag insertion helpers
    # ------------------------------------------------------------------ #

    def _log_call(self, flag_name: str, indent: str) -> str:
        return f'{indent}LOG_FLAG("{flag_name}");\n'

    def insert_flag_before_pos(self, pos: int, flag_name: str):
        """
        Insert LOG_FLAG on its own line, just before the line that
        contains char offset *pos*.
        """
        line_start = self.source.rfind("\n", 0, pos) + 1
        indent = re.match(r"[ \t]*", self.source[line_start:]).group()
        self.edits.append(("insert", line_start, self._log_call(flag_name, indent)))

    def insert_flag_before_rbrace(self, rbrace_pos: int, flag_name: str):
        """
        Insert LOG_FLAG on the line just before the closing }.
        Indent matches the } line.
        """
        line_start = self.source.rfind("\n", 0, rbrace_pos) + 1
        indent = re.match(r"[ \t]*", self.source[line_start:]).group()
        self.edits.append(("insert", line_start, self._log_call(flag_name, indent)))

    # ------------------------------------------------------------------ #
    # Block parsers
    # ------------------------------------------------------------------ #

    def parse_braced_block(self, context: str) -> tuple[int, int]:
        """
        Parse { ... } for the given context.
        Recursively handles nested constructs.
        Returns (open_pos, close_pos).

        context values: "function" | "if" | "else" | "while" | "for" | "do" | "switch"
        """
        open_tok = self.cur()
        assert open_tok and open_tok["type"] == "LBRACE"
        open_pos = open_tok["start"]
        self.adv()   # consume {

        has_return = False   # only matters for function context

        while self.cur():
            t = self.cur()

            # ---- closing brace ----------------------------------------
            if t["type"] == "RBRACE":
                close_pos = t["start"]
                self.adv()   # consume }

                if context == "function":
                    # Only flag } when there is NO return in this body
                    # (void / fall-through functions).
                    if not has_return:
                        flag = self._next("func")
                        self.insert_flag_before_rbrace(close_pos, flag)

                elif context in ("if", "else", "while", "for", "do"):
                    flag = self._next(context)
                    self.insert_flag_before_rbrace(close_pos, flag)

                elif context == "switch":
                    flag = self._next("switch")
                    self.insert_flag_before_rbrace(close_pos, flag)

                return open_pos, close_pos

            # ---- nested { } -------------------------------------------
            elif t["type"] == "LBRACE":
                self.parse_braced_block("generic")

            # ---- keywords ---------------------------------------------
            elif t["type"] == "KEYWORD":
                kw = t["value"]
                self.adv()

                if kw == "if":
                    self.parse_if_chain()
                elif kw == "while":
                    self.parse_while()
                elif kw == "for":
                    self.parse_for()
                elif kw == "do":
                    self.parse_do_while()
                elif kw == "switch":
                    self.parse_switch()
                elif kw == "return":
                    if context == "function":
                        flag = self._next("func")
                        self.insert_flag_before_pos(t["start"], flag)
                        has_return = True
                    self.consume_to_semicolon()
                elif kw in ("break", "continue", "case", "default"):
                    self.consume_to_semicolon()
                # other keywords (type keywords that got through) — skip
            else:
                self.adv()

        raise SyntaxError(f"Unexpected EOF inside {context} block")

    # ---- if / else if / else ------------------------------------------

    def parse_if_chain(self):
        """'if' keyword already consumed."""
        self.skip_trivia()
        if not (self.cur() and self.cur()["type"] == "LPAREN"):
            return
        self.read_parens()
        self.skip_trivia()

        if self.cur() and self.cur()["type"] == "LBRACE":
            self.parse_braced_block("if")
        else:
            self.consume_to_semicolon()

        self._try_parse_else()

    def _try_parse_else(self):
        saved = self.idx
        self.skip_trivia()
        t = self.cur()
        if t and t["type"] == "KEYWORD" and t["value"] == "else":
            self.adv()   # consume 'else'
            self.skip_trivia()
            t2 = self.cur()
            if t2 and t2["type"] == "KEYWORD" and t2["value"] == "if":
                self.adv()   # consume 'if'
                self.parse_if_chain()
            elif t2 and t2["type"] == "LBRACE":
                self.parse_braced_block("else")
            else:
                self.consume_to_semicolon()
        else:
            self.idx = saved

    # ---- while --------------------------------------------------------

    def parse_while(self):
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LPAREN":
            self.read_parens()
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LBRACE":
            self.parse_braced_block("while")
        else:
            self.consume_to_semicolon()

    # ---- for ----------------------------------------------------------

    def parse_for(self):
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LPAREN":
            self.read_parens()
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LBRACE":
            self.parse_braced_block("for")
        else:
            self.consume_to_semicolon()

    # ---- do-while -----------------------------------------------------

    def parse_do_while(self):
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LBRACE":
            self.parse_braced_block("do")
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "KEYWORD" and self.cur()["value"] == "while":
            self.adv()
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LPAREN":
            self.read_parens()
        self.consume_to_semicolon()

    # ---- switch -------------------------------------------------------

    def parse_switch(self):
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LPAREN":
            self.read_parens()
        self.skip_trivia()
        if self.cur() and self.cur()["type"] == "LBRACE":
            self.parse_switch_body()

    def parse_switch_body(self):
        """
        Parse switch { ... }.
        Flag inserted:
          - before each break; (case exit)
          - before closing } of the switch
        """
        open_tok = self.cur()
        assert open_tok and open_tok["type"] == "LBRACE"
        open_pos = open_tok["start"]
        self.adv()   # consume {

        while self.cur():
            t = self.cur()

            if t["type"] == "RBRACE":
                close_pos = t["start"]
                self.adv()
                flag = self._next("switch")
                self.insert_flag_before_rbrace(close_pos, flag)
                return open_pos, close_pos

            elif t["type"] == "KEYWORD" and t["value"] in ("case", "default"):
                self.adv()
                # consume label value + colon
                while self.cur():
                    tok = self.adv()
                    if tok["type"] == "COLON" or tok["value"] == ":":
                        break

            elif t["type"] == "KEYWORD" and t["value"] == "break":
                flag = self._next("case")
                self.insert_flag_before_pos(t["start"], flag)
                self.consume_to_semicolon()

            elif t["type"] == "KEYWORD" and t["value"] == "return":
                flag = self._next("case")
                self.insert_flag_before_pos(t["start"], flag)
                self.consume_to_semicolon()

            elif t["type"] == "KEYWORD" and t["value"] == "switch":
                self.adv()
                self.parse_switch()

            elif t["type"] == "KEYWORD" and t["value"] == "if":
                self.adv()
                self.parse_if_chain()

            elif t["type"] == "KEYWORD" and t["value"] == "while":
                self.adv()
                self.parse_while()

            elif t["type"] == "KEYWORD" and t["value"] == "for":
                self.adv()
                self.parse_for()

            elif t["type"] == "LBRACE":
                self.parse_braced_block("generic")

            else:
                self.adv()

        raise SyntaxError("Unexpected EOF inside switch body")

    # ------------------------------------------------------------------ #
    # Top-level scan
    # ------------------------------------------------------------------ #

    def _looks_like_function_def(self) -> bool:
        """Heuristic: TYPE NAME ( params ) { → function definition."""
        i = self.idx
        paren_found = False
        while i < len(self.tokens):
            t = self.tokens[i]
            if t["type"] in ("WHITESPACE", "NEWLINE", "LINE_COMMENT",
                              "BLOCK_COMMENT", "PREPROCESSOR"):
                i += 1
                continue
            if t["type"] == "LPAREN":
                paren_found = True
                depth = 1
                i += 1
                while i < len(self.tokens) and depth > 0:
                    if self.tokens[i]["type"] == "LPAREN":
                        depth += 1
                    elif self.tokens[i]["type"] == "RPAREN":
                        depth -= 1
                    i += 1
                continue
            if paren_found and t["type"] == "LBRACE":
                return True
            if t["type"] == "SEMICOLON":
                return False
            i += 1
        return False

    def run(self):
        TYPE_KEYWORDS = {
            "void", "int", "char", "float", "double", "bool",
            "uint8_t", "uint16_t", "uint32_t", "uint64_t",
            "int8_t",  "int16_t",  "int32_t",  "int64_t",
            "static", "inline", "extern", "volatile", "const", "unsigned", "signed",
        }

        while self.cur():
            t = self.cur()

            if t["type"] in ("WHITESPACE", "NEWLINE", "LINE_COMMENT",
                              "BLOCK_COMMENT", "PREPROCESSOR"):
                self.adv()
                continue

            if t["type"] == "KEYWORD":
                kw = t["value"]
                self.adv()
                if kw == "if":
                    self.parse_if_chain()
                elif kw == "while":
                    self.parse_while()
                elif kw == "for":
                    self.parse_for()
                elif kw == "do":
                    self.parse_do_while()
                elif kw == "switch":
                    self.parse_switch()
                continue

            # Function definition detection
            if t["value"] in TYPE_KEYWORDS or t["type"] == "OTHER":
                if self._looks_like_function_def():
                    while self.cur() and self.cur()["type"] != "LBRACE":
                        self.adv()
                    if self.cur() and self.cur()["type"] == "LBRACE":
                        self.parse_braced_block("function")
                    continue

            self.adv()

    def get_instrumented(self) -> str:
        self.run()
        return apply_edits(self.source, self.edits)
