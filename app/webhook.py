import logging
import uuid
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError

from app import main as main_module
from app.config import settings
from app.crypto import verify_signature
from app.models import WebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    x_pseudogram_signature: str | None = Header(
        default=None, alias="X-PseudoGram-Signature"
    ),
):
    raw_body = await request.body()
    db = main_module.db
    rule_engine = main_module.rule_engine

    # 1. Verify HMAC signature if enabled
    if settings.VERIFY_WEBHOOK_SIGNATURE:
        if not x_pseudogram_signature or not verify_signature(
            raw_body, x_pseudogram_signature, settings.API_KEY
        ):
            logger.warning("Rejected webhook due to invalid signature.")
            raise HTTPException(
                status_code=401, detail="Invalid or missing signature"
            )

    # 2. Parse JSON payload
    try:
        payload_dict = await request.json()
        payload = WebhookPayload(**payload_dict)
    except (ValidationError, Exception) as exc:
        logger.warning("Malformed webhook payload: %s", exc)
        raise HTTPException(
            status_code=400, detail=f"Malformed webhook payload: {exc}"
        )

    # 3. Deduplicate event ID
    is_new_event = db.record_event_if_new(payload.event_id)
    if not is_new_event:
        logger.info("Ignoring duplicate event %s", payload.event_id)
        return {"status": "duplicate_event_ignored", "event_id": payload.event_id}

    # 4. Handle comment.deleted events
    if payload.event_type == "comment.deleted":
        comment_id = payload.data.comment_id
        logger.info(
            "Received comment.deleted for comment %s (logged for audit)",
            comment_id,
        )
        return {"status": "ok", "action": "comment_deleted_logged"}

    # 5. Handle comment.created events
    if payload.event_type == "comment.created":
        comment_data = payload.data
        text = comment_data.text or ""
        user_data = comment_data.from_user
        if not user_data or not user_data.user_id:
            return {"status": "ok", "action": "missing_user_id"}

        user_id = user_data.user_id
        comment_id = comment_data.comment_id

        matched_rules = rule_engine.match_rules(text)
        if not matched_rules:
            return {"status": "ok", "action": "no_matching_rules"}

        deliveries_created = 0
        for rule in matched_rules:
            rule_id = rule["rule_id"]
            dm_message = rule["dm_message"]
            idempotency_key = f"rule:{rule_id}:user:{user_id}"
            delivery_id = f"del_{uuid.uuid4().hex[:12]}"

            created = db.create_delivery(
                delivery_id=delivery_id,
                rule_id=rule_id,
                recipient_user_id=user_id,
                comment_id=comment_id,
                idempotency_key=idempotency_key,
                message=dm_message,
            )
            if created:
                deliveries_created += 1

        return {
            "status": "ok",
            "matched_rules": len(matched_rules),
            "deliveries_created": deliveries_created,
        }

    return {"status": "ok", "action": "unhandled_event_type"}
