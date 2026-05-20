"""Long-term user memory storage and keyword retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserMemory

MAX_SEARCH_LIMIT = 5
MAX_KEYWORDS = 20

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{1,}", re.IGNORECASE)
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "but",
    "for",
    "from",
    "has",
    "have",
    "into",
    "that",
    "the",
    "this",
    "use",
    "with",
    "you",
    "your",
}


def extract_keywords(text: str) -> list[str]:
    """Extract lightweight retrieval keywords without external services."""

    keywords: list[str] = []
    normalized = text.lower()

    for token in _LATIN_TOKEN_RE.findall(normalized):
        cleaned = token.strip("._+-")
        if _is_useful_keyword(cleaned):
            keywords.append(cleaned)

    for token in _CJK_TOKEN_RE.findall(text):
        cleaned = token.strip()
        if cleaned:
            keywords.append(cleaned[:24])

    return _dedupe_keywords(keywords)


async def store_user_memory(
    session: AsyncSession,
    *,
    user_id: int,
    content: str,
    kind: str = "fact",
    keywords: Sequence[str] | None = None,
    source_conversation_id: int | None = None,
    source_message_id: int | None = None,
    enabled: bool = True,
) -> UserMemory:
    """Persist one long-term memory for a user."""

    cleaned_content = " ".join(content.split())
    if not cleaned_content:
        raise ValueError("memory content cannot be empty")

    memory = UserMemory(
        user_id=user_id,
        kind=kind,
        content=cleaned_content,
        keywords=_normalize_keywords(keywords) if keywords is not None else extract_keywords(content),
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        enabled=enabled,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def search_user_memories(
    session: AsyncSession,
    user_id: int,
    query: str,
    limit: int = MAX_SEARCH_LIMIT,
) -> list[UserMemory]:
    """Search enabled memories for one user with DB content/keyword contains matching."""

    terms = extract_keywords(query)
    if not terms:
        stripped = query.strip().lower()
        if stripped:
            terms = [stripped]
        else:
            return []

    effective_limit = _effective_limit(limit)
    keyword_text = cast(UserMemory.keywords, String)
    match_conditions = []
    for term in terms:
        pattern = f"%{_escape_like(term)}%"
        match_conditions.append(UserMemory.content.ilike(pattern, escape="\\"))
        match_conditions.append(keyword_text.ilike(pattern, escape="\\"))

    result = await session.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.enabled.is_(True),
            or_(*match_conditions),
        )
        .order_by(UserMemory.updated_at.desc(), UserMemory.created_at.desc())
        .limit(max(effective_limit * 10, effective_limit))
    )
    memories = list(result.scalars().all())
    ranked = sorted(
        memories,
        key=lambda memory: (_score_memory(memory, terms), _timestamp(memory)),
        reverse=True,
    )
    return ranked[:effective_limit]


def format_long_term_memory_context(memories: Sequence[UserMemory]) -> str:
    if not memories:
        return ""

    lines = ["长期记忆上下文："]
    for index, memory in enumerate(memories, start=1):
        lines.append(f"{index}. [{memory.kind}] {memory.content}")
        metadata = _format_source_metadata(memory)
        if metadata:
            lines.append(f"   来源：{metadata}")
        if memory.keywords:
            lines.append(f"   关键词：{', '.join(memory.keywords[:8])}")
    return "\n".join(lines)


def _normalize_keywords(keywords: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    for keyword in keywords:
        normalized.extend(extract_keywords(str(keyword)))
    return _dedupe_keywords(normalized)


def _dedupe_keywords(keywords: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for keyword in keywords:
        cleaned = keyword.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
        if len(result) >= MAX_KEYWORDS:
            break
    return result


def _is_useful_keyword(token: str) -> bool:
    return len(token) >= 2 and token not in _STOPWORDS and not token.isdigit()


def _effective_limit(limit: int) -> int:
    return min(max(int(limit), 1), MAX_SEARCH_LIMIT)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _score_memory(memory: UserMemory, terms: Sequence[str]) -> int:
    keyword_values = {str(item).lower() for item in (memory.keywords or [])}
    content = memory.content.lower()
    score = 0
    for term in terms:
        lowered = term.lower()
        if lowered in keyword_values:
            score += 3
        if lowered in content:
            score += 1
    return score


def _timestamp(memory: UserMemory) -> datetime:
    return memory.updated_at or memory.created_at or datetime.min


def _format_source_metadata(memory: UserMemory) -> str:
    parts: list[str] = []
    if memory.source_conversation_id is not None:
        parts.append(f"conversation_id={memory.source_conversation_id}")
    if memory.source_message_id is not None:
        parts.append(f"message_id={memory.source_message_id}")
    if memory.created_at is not None:
        parts.append(f"created_at={memory.created_at.isoformat()}")
    return "; ".join(parts)
