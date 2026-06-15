"""Admin DM alerts (COMPLETION.md §14).

A thin helper to DM the configured admin on important events (stuck games, sync failures, API cap,
role problems). Failures to DM are logged, never raised — an alert must not crash a scheduled task.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from tigrinho.logging import get_logger

log = get_logger("tigrinho.bot.alerts")


async def dm_admin(bot: commands.Bot, admin_user_id: int, message: str) -> None:
    """DM the admin; swallow + log any failure (a failed alert must not break the caller)."""
    try:
        user = await bot.fetch_user(admin_user_id)
        await user.send(message)
    except discord.HTTPException as exc:
        log.warning("admin_dm_failed", admin_user_id=admin_user_id, error=str(exc))
