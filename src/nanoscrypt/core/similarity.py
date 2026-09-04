import re
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class EvolutionCandidate:
    tool_name: str
    base_version: int
    similarity_score: float
    matched_purpose: str
    missing_parameters: list[str]
    overlap_parameters: list[str]


class SimilarityMatcher:
    """Calculates semantic purpose overlap and parameter schema overlap
    to identify whether a user prompt represents an evolution of an existing tool."""

    STOPWORDS = {
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "and", "or", "is", "are", "was", "were", "be", "been", "that", "this", "it",
        "tool", "create", "make", "build", "write", "generate", "code", "run", "please",
        "can", "you", "also", "now", "want", "need", "should", "using", "using",
    }

    @classmethod
    def _stem(cls, word: str) -> str:
        """Basic lightweight stemmer for matching word variants."""
        w = word.lower()
        if w.endswith("extractor"):
            w = w[:-9] + "extract"
        elif w.endswith("ing"):
            w = w[:-3]
        elif w.endswith("ed"):
            w = w[:-2]
        elif w.endswith("es"):
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        return w

    @classmethod
    def tokenize(cls, text: str) -> set[str]:
        """Extracts normalized alphanumeric token set excluding common stopwords."""
        words = re.findall(r"[a-zA-Z0-9]+", text.lower())
        tokens = set()
        for w in words:
            if w not in cls.STOPWORDS and len(w) > 1:
                tokens.add(w)
                stemmed = cls._stem(w)
                if len(stemmed) > 1:
                    tokens.add(stemmed)
        return tokens

    @classmethod
    def compute_jaccard_similarity(cls, text_a: str, text_b: str) -> float:
        """Calculates Jaccard token overlap between two strings."""
        tokens_a = cls.tokenize(text_a)
        tokens_b = cls.tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a.intersection(tokens_b)
        union = tokens_a.union(tokens_b)
        return len(intersection) / len(union)

    @classmethod
    def extract_potential_params(cls, prompt: str) -> set[str]:
        """Heuristically extracts potential input argument names from prompt text."""
        tokens = cls.tokenize(prompt)
        candidates = set()
        for token in tokens:
            if any(term in token for term in ["path", "file", "url", "text", "query", "format", "dir", "name", "id", "num", "count", "mode"]):
                candidates.add(token)
        return candidates

    @classmethod
    def find_candidate(
        cls,
        user_prompt: str,
        registered_tools: list[dict[str, Any]],
        min_threshold: float = 0.35,
        reuse_threshold: float = 0.95,
    ) -> EvolutionCandidate | None:
        """Evaluates registered tools and returns an EvolutionCandidate if similarity
        falls within the evolution window [min_threshold, reuse_threshold)."""
        best_candidate: EvolutionCandidate | None = None
        best_score = 0.0

        prompt_params = cls.extract_potential_params(user_prompt)

        prompt_tokens = cls.tokenize(user_prompt)

        for tool in registered_tools:
            tool_name = tool.get("name", "")
            purpose = tool.get("purpose", "") or tool_name.replace("_", " ")
            input_schema = tool.get("input_schema", {}) or {}

            # 1. Purpose semantic overlap
            name_text = tool_name.replace("_", " ")
            purpose_sim = cls.compute_jaccard_similarity(user_prompt, f"{name_text} {purpose}")

            # Direct name mention bonus (e.g. "update word_analyzer to ...")
            name_bonus = 0.0
            if tool_name.lower() in user_prompt.lower() or name_text.lower() in user_prompt.lower():
                name_bonus = 0.40

            # 2. Schema parameter overlap (check if existing parameter name or parts appear in prompt)
            existing_params = set(input_schema.keys())
            matched_params = set()
            for p in existing_params:
                p_parts = cls.tokenize(p)
                if p_parts and p_parts.issubset(prompt_tokens):
                    matched_params.add(p)
                elif any(part in prompt_tokens for part in p_parts):
                    matched_params.add(p)

            schema_sim = (len(matched_params) / max(len(existing_params), 1)) if existing_params else 0.0

            # Combined weighted score with name mention bonus
            combined_score = round(min(1.0, 0.50 * purpose_sim + 0.30 * schema_sim + name_bonus), 3)

            # Missing parameters indicated in prompt that tool doesn't have
            missing = list(prompt_params - existing_params)

            if combined_score > best_score:
                best_score = combined_score
                curr_version = tool.get("current_version", 1)
                best_candidate = EvolutionCandidate(
                    tool_name=tool_name,
                    base_version=curr_version,
                    similarity_score=combined_score,
                    matched_purpose=purpose,
                    missing_parameters=missing,
                    overlap_parameters=list(matched_params),
                )

        if best_candidate and (min_threshold <= best_candidate.similarity_score < reuse_threshold):
            logger.info(
                "similarity_matcher_candidate_found",
                tool_name=best_candidate.tool_name,
                score=best_candidate.similarity_score,
                base_version=best_candidate.base_version,
            )
            return best_candidate

        return None
