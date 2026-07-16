from __future__ import annotations

import time

from garfield_intents import (
    ActionRequest,
    PendingAction,
    RiskLevel,
    is_confirmation,
)


def make_pending(
    action_id: str = "recycle_bin.empty",
    token: str = "очистку корзины",
) -> PendingAction:
    return PendingAction(
        request=ActionRequest(
            action_id=action_id,
            arguments={},
            risk=RiskLevel.DESTRUCTIVE,
            display_name=token,
        ),
        created_at=time.monotonic(),
        confirmation_token=token,
    )


def test_plain_yes_does_not_confirm_destructive_action() -> None:
    assert not is_confirmation("да", make_pending(), ["да", "подтверждаю"])


def test_full_confirmation_token_confirms_action() -> None:
    assert is_confirmation(
        "подтверждаю очистку корзины",
        make_pending(),
        ["да", "подтверждаю"],
    )


def test_wrong_confirmation_token_is_rejected() -> None:
    assert not is_confirmation(
        "подтверждаю закрытие окна",
        make_pending(),
        ["да", "подтверждаю"],
    )


def test_pending_action_expires() -> None:
    pending = make_pending()
    pending.created_at -= 30
    assert pending.is_expired(20)
