from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import AuditEventModel


async def record_event(
    session: AsyncSession,
    entity_type: str,
    entity_id: str,
    event_type: str,
    payload: dict,
) -> None:
    session.add(
        AuditEventModel(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload_json=json.dumps(payload, ensure_ascii=True),
            created_at=datetime.now(timezone.utc),
        )
    )

