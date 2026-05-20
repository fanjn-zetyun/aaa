from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole
from app.services.long_term_memory import (
    extract_keywords,
    format_long_term_memory_context,
    search_user_memories,
    store_user_memory,
)


def test_extract_keywords_normalizes_text():
    keywords = extract_keywords("Use PyTorch Lightning for Project-Alpha 2026 reproduction")

    assert "pytorch" in keywords
    assert "lightning" in keywords
    assert "project-alpha" in keywords
    assert "use" not in keywords
    assert "2026" not in keywords


@pytest.mark.asyncio
async def test_store_user_memory_persists_keywords(
    db_session: AsyncSession,
    test_user,
):
    memory = await store_user_memory(
        db_session,
        user_id=test_user.id,
        kind="preference",
        content="User prefers PyTorch Lightning for reproducible experiments.",
        source_conversation_id=None,
        source_message_id=None,
    )

    assert memory.id is not None
    assert memory.user_id == test_user.id
    assert memory.kind == "preference"
    assert memory.enabled is True
    assert "pytorch" in memory.keywords
    assert "lightning" in memory.keywords


@pytest.mark.asyncio
async def test_search_user_memories_isolates_by_user(
    db_session: AsyncSession,
    test_user,
):
    other_user = User(
        username="otheruser",
        password_hash="hashed",
        role=UserRole.USER,
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    own_memory = await store_user_memory(
        db_session,
        user_id=test_user.id,
        content="Default repository is lobster-lab/project-alpha.",
        keywords=["project-alpha"],
    )
    await store_user_memory(
        db_session,
        user_id=other_user.id,
        content="Other user's project-alpha memory must stay private.",
        keywords=["project-alpha"],
    )

    results = await search_user_memories(db_session, test_user.id, "project alpha", limit=5)

    assert [item.id for item in results] == [own_memory.id]


@pytest.mark.asyncio
async def test_search_user_memories_matches_keywords_and_content(
    db_session: AsyncSession,
    test_user,
):
    keyword_match = await store_user_memory(
        db_session,
        user_id=test_user.id,
        content="Use the stable environment for paper reproduction.",
        keywords=["cuda-12.6", "reproduce"],
    )
    content_match = await store_user_memory(
        db_session,
        user_id=test_user.id,
        content="The preferred report format is markdown with tables.",
        keywords=["report"],
    )
    await store_user_memory(
        db_session,
        user_id=test_user.id,
        content="Unrelated memory about account settings.",
        keywords=["settings"],
    )

    keyword_results = await search_user_memories(db_session, test_user.id, "cuda 12.6", limit=5)
    content_results = await search_user_memories(db_session, test_user.id, "markdown tables")

    assert [item.id for item in keyword_results] == [keyword_match.id]
    assert [item.id for item in content_results] == [content_match.id]


@pytest.mark.asyncio
async def test_search_user_memories_excludes_disabled(
    db_session: AsyncSession,
    test_user,
):
    await store_user_memory(
        db_session,
        user_id=test_user.id,
        content="Disabled GPU preference should not be recalled.",
        keywords=["gpu"],
        enabled=False,
    )

    results = await search_user_memories(db_session, test_user.id, "gpu")

    assert results == []


@pytest.mark.asyncio
async def test_search_user_memories_caps_limit_to_five(
    db_session: AsyncSession,
    test_user,
):
    for index in range(6):
        await store_user_memory(
            db_session,
            user_id=test_user.id,
            content=f"Memory {index} for shared keyword limit-check.",
            keywords=["limit-check"],
        )

    results = await search_user_memories(db_session, test_user.id, "limit-check", limit=10)

    assert len(results) == 5


@pytest.mark.asyncio
async def test_format_long_term_memory_context(
    db_session: AsyncSession,
    test_user,
):
    memory = await store_user_memory(
        db_session,
        user_id=test_user.id,
        kind="decision",
        content="User approved CPU-first reproduction before GPU training.",
        keywords=["cpu-first", "gpu"],
        source_conversation_id=None,
        source_message_id=None,
    )

    context = format_long_term_memory_context([memory])

    assert "长期记忆上下文" in context
    assert "[decision]" in context
    assert "CPU-first reproduction" in context
    assert "关键词" in context
    assert "cpu-first" in context
