"""
ErrorNormalizer - deterministic normalization of raw Alloy Analyzer errors.

Purpose:
    Convert raw Alloy error messages (syntax / type / name-resolution) into a
    stable, location-independent signature so that recurring errors can be
    reliably matched across iterations regardless of exact line/column.

This is the FIRST step in the post-analysis chain:
    ErrorNormalizer -> IssuePatternTracker -> ResolutionStatusTracker -> RepairPlateauDetector

It is fully deterministic (no LLM). Given an analyzer result and the model file
it produces a JSON-serializable dict that is stored on the current iteration's
regression-log entry.

Output schema (single primary error):
    {
      "issue_kind":            "syntax_error | type_error | name_resolution_error",
      "error_type":            "",
      "message_family":        "",
      "affected_symbol":       "",
      "affected_construct":    "",
      "model_region":          "",
      "nearby_token":          "",
      "expected_token_family": "",
      "normalized_signature":  "",
      "root_error_family":     "",
    }
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .alloy_executor import BLOCK_KEYWORDS, find_containing_block


# Ordered classification rules. First matching rule wins.
# Each rule: (compiled pattern, field-dict). Patterns are matched
# case-insensitively against the combined raw error text.
_RULES: List[Tuple[re.Pattern, Dict[str, str]]] = [
    # "There are N possible tokens that can appear here" -> block/delimiter structure
    (re.compile(r"there are\s+\d+\s+possible tokens that can appear here", re.IGNORECASE), {
        "issue_kind": "syntax_error",
        "error_type": "unexpected_token",
        "message_family": "possible_tokens_here",
        "root_error_family": "delimiter_or_block_structure_error",
    }),
    # "This must be an integer expression" -> operator used on non-ordered sig
    (re.compile(r"this must be an integer expression", re.IGNORECASE), {
        "issue_kind": "type_error",
        "error_type": "integer_expression_required",
        "message_family": "must_be_integer_expression",
        "root_error_family": "invalid_operator_for_signature_ordering",
    }),
    # 'The name "X" cannot be found' -> missing declaration / out of scope
    (re.compile(r'the name\s+"?[^"\n]+?"?\s+cannot be found', re.IGNORECASE), {
        "issue_kind": "name_resolution_error",
        "error_type": "name_not_found",
        "message_family": "name_cannot_be_found",
        "root_error_family": "missing_declaration_or_scope_error",
    }),
    # "has type X but ... expected Y" -> type mismatch
    (re.compile(r"has type\b.*\bbut\b.*\bexpect", re.IGNORECASE | re.DOTALL), {
        "issue_kind": "type_error",
        "error_type": "type_mismatch",
        "message_family": "has_type_but_expected",
        "root_error_family": "type_mismatch",
    }),
    # arity / invalid field join
    (re.compile(r"\b(arity mismatch|arity|invalid field join|cannot apply|this expression failed to be typechecked)\b",
                re.IGNORECASE), {
        "issue_kind": "type_error",
        "error_type": "arity_or_join_error",
        "message_family": "invalid_field_join",
        "root_error_family": "relation_arity_or_join_error",
    }),
    # redefinition / already declared
    (re.compile(r"\b(redefinition|redefined|already (defined|declared))\b", re.IGNORECASE), {
        "issue_kind": "name_resolution_error",
        "error_type": "redefinition",
        "message_family": "redefinition",
        "root_error_family": "missing_declaration_or_scope_error",
    }),
    # looser name-resolution fallback (keep AFTER the specific rules above)
    (re.compile(r"cannot be found", re.IGNORECASE), {
        "issue_kind": "name_resolution_error",
        "error_type": "name_not_found",
        "message_family": "name_cannot_be_found",
        "root_error_family": "missing_declaration_or_scope_error",
    }),
]

# Fallback classification when no content rule matches, keyed on whether Alloy
# reported a "Type error" or a "Syntax error".
_FALLBACK_TYPE = {
    "issue_kind": "type_error",
    "error_type": "type_error",
    "message_family": "generic_type_error",
    "root_error_family": "type_mismatch",
}
_FALLBACK_SYNTAX = {
    "issue_kind": "syntax_error",
    "error_type": "unexpected_token",
    "message_family": "generic_syntax_error",
    "root_error_family": "delimiter_or_block_structure_error",
}

# Constructs the normalizer recognizes (shared with the analyzer's block finder,
# which now includes `open`).
_BLOCK_KEYWORDS = BLOCK_KEYWORDS

# Region names by construct, for errors on the declaration line vs inside the body.
_DECL_REGION = {
    "sig": "signature_declaration", "fun": "function_declaration",
    "pred": "predicate_declaration", "fact": "fact_declaration",
    "assert": "assertion_declaration", "enum": "enum_declaration",
    "run": "command", "check": "command", "open": "import",
}
_BODY_REGION = {
    "sig": "signature_body", "fun": "function_body",
    "pred": "predicate_body", "fact": "fact_body",
    "assert": "assertion_body", "enum": "enum_body",
    "run": "command", "check": "command", "open": "import",
}

# Field order used to build the normalized signature. Matches the reference
# example: syntax_error:unexpected_token:fun:firstPendingFIFO:function_body:delimiter_or_block_structure
_SIGNATURE_FIELDS = [
    "issue_kind", "error_type", "affected_construct",
    "affected_symbol", "model_region", "root_error_family",
]


class ErrorNormalizer:
    """Deterministic workflow step that normalizes the primary Alloy error."""

    def __init__(self, logger=None):
        self.logger = logger

    def _log(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "log"):
            self.logger.log(message)

    def run(self, analysis: Dict[str, Any], model_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Normalize the primary syntax/type error in an analyzer result.

        Args:
            analysis: The `analysis` sub-dict of an analyzer result (contains
                      `syntax_errors`, a list of structured error dicts).
            model_path: Path to the .als model file for the current iteration
                        (used for backward search of the enclosing construct).

        Returns:
            Normalized error dict (see module docstring), or None if there is
            no syntax/type error to normalize.
        """
        try:
            syntax_errors = (analysis or {}).get("syntax_errors", []) or []
            if not syntax_errors:
                return None

            # Normalize the primary (first) error, consistent with how the
            # regression log already records syntax_error_context.
            error = syntax_errors[0]
            if not isinstance(error, dict):
                return None

            signature = self._normalize_single(error, model_path)
            self._log(
                f"[ERROR_NORMALIZER] signature={signature.get('normalized_signature')!r}"
            )
            return signature
        except Exception as exc:  # never break the workflow on normalization
            self._log(f"[ERROR_NORMALIZER] Failed to normalize error: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _normalize_single(self, error: Dict[str, Any], model_path: Optional[str]) -> Dict[str, Any]:
        message = error.get("message", "") or ""
        context = error.get("context", "") or ""
        full_text = error.get("full_text", "") or ""
        code_snippet = error.get("code_snippet", "") or ""
        line_num = error.get("line", 0) or 0
        col_num = error.get("column", 0) or 0

        raw_text = "\n".join(t for t in (full_text, context, message) if t)

        # 1) Classify issue_kind / error_type / message_family / root_error_family
        fields = self._classify(raw_text, message)

        # 2) Affected construct + symbol (+ block start line for region)
        construct, symbol, block_start = self._resolve_construct_symbol(code_snippet, model_path, line_num)

        # 3) Model region (declaration line vs body)
        region = self._resolve_region(construct, line_num, block_start)

        # 4) Nearby token at the error column + expected token family
        nearby_token = self._extract_token_at(model_path, line_num, col_num)
        expected_token_family = self._classify_expected_tokens(context, fields["message_family"])

        result: Dict[str, Any] = {
            "issue_kind": fields["issue_kind"],
            "error_type": fields["error_type"],
            "message_family": fields["message_family"],
            "affected_symbol": symbol,
            "affected_construct": construct,
            "model_region": region,
            "nearby_token": nearby_token,
            "expected_token_family": expected_token_family,
            "normalized_signature": "",  # filled below
            "root_error_family": fields["root_error_family"],
        }
        result["normalized_signature"] = self._build_signature(result)
        return result

    def _classify(self, raw_text: str, message: str) -> Dict[str, str]:
        for pattern, fields in _RULES:
            if pattern.search(raw_text):
                return dict(fields)
        # No content rule matched - fall back on the reported error kind.
        if "type error" in message.lower():
            return dict(_FALLBACK_TYPE)
        return dict(_FALLBACK_SYNTAX)

    def _resolve_construct_symbol(
        self, code_snippet: str, model_path: Optional[str], line_num: int
    ) -> Tuple[str, str, Optional[int]]:
        """
        Determine (affected_construct, affected_symbol, block_start_line).

        Prefer the block info already embedded by the analyzer in code_snippet
        ("CODE CONTEXT - COMPLETE BLOCK: <construct> <symbol> (lines A-B):").
        Fall back to a backward search over the model file.
        """
        # Preferred: parse the complete-block header from the code snippet.
        m = re.search(
            r"CODE CONTEXT - COMPLETE BLOCK:\s*(\w+)(?:\s+(\w+))?\s*\(lines\s+(\d+)-\d+\)",
            code_snippet,
        )
        if m:
            construct = m.group(1)
            symbol = m.group(2) or "unknown"
            block_start = int(m.group(3))
            if construct in _BLOCK_KEYWORDS:
                return construct, symbol, block_start

        # Fallback: reuse the shared block finder over the model file, extended
        # to also recognize `open` statements as enclosing declarations.
        if not model_path:
            return "unknown", "unknown", None
        block = find_containing_block(model_path, line_num)
        if not block:
            return "unknown", "unknown", None
        block_start, _, block_type = block
        # block_type is "<keyword> <name>" or just "<keyword>".
        parts = block_type.split(None, 1)
        construct = parts[0]
        symbol = parts[1].strip() if len(parts) > 1 else "unknown"
        return construct, symbol, block_start

    @staticmethod
    def _resolve_region(construct: str, line_num: int, block_start: Optional[int]) -> str:
        if construct not in _BODY_REGION:
            return "unknown"
        if block_start is not None and line_num <= block_start:
            return _DECL_REGION.get(construct, "unknown")
        return _BODY_REGION.get(construct, "unknown")

    @staticmethod
    def _extract_token_at(model_path: Optional[str], line_num: int, col_num: int) -> str:
        if not model_path or line_num < 1:
            return ""
        path = Path(model_path)
        if not path.exists():
            return ""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return ""
        if line_num > len(lines):
            return ""
        text = lines[line_num - 1]
        if not text:
            return ""
        # Column is 1-indexed; clamp into range.
        idx = max(0, min(col_num - 1, len(text) - 1))
        # If we're on a word char, expand to the whole word.
        if text[idx].isalnum() or text[idx] == "_":
            start = idx
            while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
                start -= 1
            end = idx
            while end < len(text) - 1 and (text[end + 1].isalnum() or text[end + 1] == "_"):
                end += 1
            return text[start:end + 1]
        # Otherwise return the single (non-space) symbol char.
        return text[idx].strip()

    @staticmethod
    def _classify_expected_tokens(context: str, message_family: str) -> str:
        if message_family != "possible_tokens_here" or not context:
            return ""
        # Find the token-list line that follows the "possible tokens" line.
        ctx_lines = [ln.strip() for ln in context.splitlines() if ln.strip()]
        token_line = ""
        for i, ln in enumerate(ctx_lines):
            if "possible tokens" in ln.lower():
                if i + 1 < len(ctx_lines):
                    token_line = ctx_lines[i + 1]
                break
        if not token_line:
            # Sometimes the tokens are on the same line after a colon.
            for ln in ctx_lines:
                if "possible tokens" in ln.lower() and ":" in ln:
                    token_line = ln.split(":", 1)[1].strip()
                    break
        if not token_line:
            return "mixed_tokens"
        if "{" in token_line or "}" in token_line:
            return "block_delimiter"
        if "(" in token_line or ")" in token_line:
            return "grouping_delimiter"
        if any(op in token_line for op in ["+", "-", "*", "/", "&", "=>", "->", "."]):
            return "expression_operator"
        return "declaration_or_name"

    @staticmethod
    def _build_signature(result: Dict[str, Any]) -> str:
        parts = []
        for key in _SIGNATURE_FIELDS:
            value = result.get(key) or "unknown"
            if key == "affected_symbol":
                # Preserve symbol casing; only strip whitespace/colons.
                value = str(value).strip().replace(":", "_") or "unknown"
            else:
                value = str(value).strip().lower().replace(" ", "_").replace(":", "_") or "unknown"
            parts.append(value)
        return ":".join(parts)


def normalize_error(analysis: Dict[str, Any], model_path: Optional[str] = None,
                    logger=None) -> Optional[Dict[str, Any]]:
    """Module-level convenience wrapper around ErrorNormalizer.run()."""
    return ErrorNormalizer(logger=logger).run(analysis, model_path)
