import discord
from discord.ext import commands
import asyncio
from collections import defaultdict
import time

import os
BOT_TOKEN = os.environ.get("TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ── Config ────────────────────────────────────────────────────────────────────
# How many actions in how many seconds triggers anti-nuke
CHANNEL_DELETE_THRESHOLD = 3   # 3 channel deletes
CHANNEL_CREATE_THRESHOLD = 2   # 2 channel creates
BAN_THRESHOLD = 3              # 3 bans
KICK_THRESHOLD = 3             # 3 kicks
TIME_WINDOW = 5               # within 5 seconds

LOG_CHANNEL_NAME = "antinuke-log"  # bot will log alerts here

# ── Tracking ──────────────────────────────────────────────────────────────────
channel_deletes = defaultdict(list)
channel_creates = defaultdict(list)
bans = defaultdict(list)
kicks = defaultdict(list)
punished = set()  # avoid punishing same user twice


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_recent(action_list, window):
    now = time.time()
    return [t for t in action_list if now - t < window]


async def punish(guild, user, reason):
    if user.id in punished:
        return
    punished.add(user.id)

    # 1. Remove all roles
    try:
        await user.edit(roles=[], reason=f"Anti-Nuke: {reason}")
    except Exception:
        pass

    # 2. Lockdown server (@everyone can't send)
    for channel in guild.text_channels:
        try:
            await channel.set_permissions(guild.default_role, send_messages=False)
        except Exception:
            pass

    # 3. Ban the attacker
    try:
        await guild.ban(user, reason=f"Anti-Nuke: {reason}", delete_message_days=0)
    except Exception:
        pass

    # 4. Log it
    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if not log_channel:
        try:
            log_channel = await guild.create_text_channel(LOG_CHANNEL_NAME)
        except Exception:
            return

    await log_channel.send(
        f"🚨 **Anti-Nuke Triggered!**\n"
        f"**User:** {user} (`{user.id}`)\n"
        f"**Reason:** {reason}\n"
        f"**Actions taken:** Roles removed, server locked, user banned."
    )


# ── Events ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"[+] Anti-Nuke Bot logged in as {bot.user}")


@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        user = entry.user
        if user.bot or user.guild_permissions.administrator and user == bot.user:
            return
        channel_deletes[user.id].append(time.time())
        recent = get_recent(channel_deletes[user.id], TIME_WINDOW)
        channel_deletes[user.id] = recent
        if len(recent) >= CHANNEL_DELETE_THRESHOLD:
            await punish(guild, user, f"Mass channel delete ({len(recent)} in {TIME_WINDOW}s)")


@bot.event
async def on_guild_channel_create(channel):
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        user = entry.user
        if user.bot:
            return
        channel_creates[user.id].append(time.time())
        recent = get_recent(channel_creates[user.id], TIME_WINDOW)
        channel_creates[user.id] = recent
        if len(recent) >= CHANNEL_CREATE_THRESHOLD:
            await punish(guild, user, f"Mass channel create ({len(recent)} in {TIME_WINDOW}s)")


@bot.event
async def on_member_ban(guild, user):
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        moderator = entry.user
        if moderator.bot:
            return
        bans[moderator.id].append(time.time())
        recent = get_recent(bans[moderator.id], TIME_WINDOW)
        bans[moderator.id] = recent
        if len(recent) >= BAN_THRESHOLD:
            member = guild.get_member(moderator.id)
            if member:
                await punish(guild, member, f"Mass ban ({len(recent)} in {TIME_WINDOW}s)")


@bot.event
async def on_member_remove(member):
    guild = member.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        moderator = entry.user
        if moderator.bot:
            return
        kicks[moderator.id].append(time.time())
        recent = get_recent(kicks[moderator.id], TIME_WINDOW)
        kicks[moderator.id] = recent
        if len(recent) >= KICK_THRESHOLD:
            mod_member = guild.get_member(moderator.id)
            if mod_member:
                await punish(guild, mod_member, f"Mass kick ({len(recent)} in {TIME_WINDOW}s)")


# ── Commands ──────────────────────────────────────────────────────────────────
@bot.command(name="unlock")
@commands.has_permissions(administrator=True)
async def unlock(ctx):
    """Unlock all channels after a lockdown."""
    for channel in ctx.guild.text_channels:
        try:
            await channel.set_permissions(ctx.guild.default_role, send_messages=None)
        except Exception:
            pass
    await ctx.send("🔓 Server unlocked.")


@bot.command(name="resetpunished")
@commands.has_permissions(administrator=True)
async def reset_punished(ctx):
    """Clear the punished users list."""
    punished.clear()
    await ctx.send("✅ Punished list cleared.")


bot.run(BOT_TOKEN)
