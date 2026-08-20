import discord

from db import get_command_roles


class PermissionDenied(discord.errors.CheckFailure):
    """Raised when a user lacks permission to use a command."""


# Default access per command, keyed by qualified name.
# Each value is a tuple of permission attribute names; ANY of them grants access.
# An empty tuple means everyone can use the command by default.
DEFAULT_PERMISSIONS = {
    "forum help": ("manage_channels", "administrator"),
    "settings": ("manage_guild", "administrator"),
    "solve": (),
    "close": (),
    "latest_cracks": (),
}

KNOWN_COMMANDS = tuple(DEFAULT_PERMISSIONS.keys())


def _member_can_use(member, guild_id: int, command_name: str) -> bool:
    """Pure decision logic: does this member pass the gate in this guild?"""
    if member.guild_permissions.administrator:
        return True

    role_ids = get_command_roles(guild_id, command_name)
    if role_ids:
        member_role_ids = {role.id for role in member.roles}
        return any(rid in member_role_ids for rid in role_ids)

    required = DEFAULT_PERMISSIONS.get(command_name, ())
    if not required:
        return True
    for perm_name in required:
        if getattr(member.guild_permissions, perm_name, False):
            return True
    return False


def can_use(interaction, command_name: str) -> bool:
    """Returns True if the user may use `command_name` in this server."""
    guild = interaction.guild
    if guild is None:
        return True
    member = interaction.user
    if not isinstance(member, discord.Member):
        return True
    return _member_can_use(member, guild.id, command_name)


def check_permission(command_name: str):
    """Returns a pycord command check that gates a command behind the override system."""
    async def predicate(ctx) -> bool:
        return can_use(ctx, command_name)
    return predicate
