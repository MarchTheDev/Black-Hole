import discord
from discord.ext import commands

from db import (
    set_notify_channel,
    remove_notify_channel,
    get_notify_channel,
    add_notify_mentions,
    remove_notify_mention,
    get_notify_mentions,
    get_forum_config,
    get_all_forum_configs,
    save_forum_config,
    delete_forum_config,
    set_command_roles,
    add_command_roles,
    remove_command_role,
    get_command_roles,
    get_all_command_roles,
    set_guild_setting,
    get_guild_setting,
    remove_guild_setting,
)
from cogs.permissions import KNOWN_COMMANDS, DEFAULT_PERMISSIONS, check_permission

HELP_FORUM_KEY = "forum_help_channel"


def _default_label(command_name: str) -> str:
    perms = DEFAULT_PERMISSIONS.get(command_name, ())
    if not perms:
        return "Everyone"
    return ", ".join(perm.replace("_", " ").title() for perm in perms)


def _resolve_tag(forum_channel, search_term):
    search_term = search_term.strip()
    if not search_term:
        return None
    for tag in forum_channel.available_tags:
        if tag.name.lower() == search_term.lower():
            return tag
    if search_term.isdigit():
        return forum_channel.get_tag(int(search_term))
    return None


def _tag_names(forum_channel, tag_ids):
    names = []
    for tid in tag_ids:
        tag = forum_channel.get_tag(tid) if forum_channel else None
        names.append(tag.name if tag else f"ID: {tid}")
    return ", ".join(names) if names else "None"


class EditTagsModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Forum Tag Settings")
        self.view = view
        forum = view.bot.get_channel(view.selected_forum_id)
        config = get_forum_config(view.selected_forum_id) or {}

        self.auto = discord.ui.TextInput(
            label="Auto-apply tags (comma separated)",
            required=False,
            value=_tag_names(forum, config.get("auto_tag_ids", [])),
        )
        self.unsolved = discord.ui.TextInput(
            label="Unsolved tag (name or ID)",
            required=False,
            value=str(forum.get_tag(config["unsolved_tag_id"]).name) if forum and config.get("unsolved_tag_id") else "",
        )
        self.solved = discord.ui.TextInput(
            label="Solved tag (name or ID)",
            required=False,
            value=str(forum.get_tag(config["solved_tag_id"]).name) if forum and config.get("solved_tag_id") else "",
        )
        self.add_item(self.auto)
        self.add_item(self.unsolved)
        self.add_item(self.solved)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        forum = view.bot.get_channel(view.selected_forum_id)
        if forum is None:
            await interaction.response.send_message("❌ That forum channel no longer exists.", ephemeral=True)
            return

        errors = []
        auto_ids, unresolved = [], []
        for part in self.auto.value.split(","):
            part = part.strip()
            if not part:
                continue
            tag = _resolve_tag(forum, part)
            if tag:
                auto_ids.append(tag.id)
            else:
                unresolved.append(part)

        unsolved_id = None
        if self.unsolved.value.strip():
            tag = _resolve_tag(forum, self.unsolved.value)
            if tag:
                unsolved_id = tag.id
            else:
                errors.append(f"Unsolved tag `{self.unsolved.value}` not found.")

        solved_id = None
        if self.solved.value.strip():
            tag = _resolve_tag(forum, self.solved.value)
            if tag:
                solved_id = tag.id
            else:
                errors.append(f"Solved tag `{self.solved.value}` not found.")

        if unresolved:
            errors.append(f"Could not find auto tags: `{', '.join(unresolved)}`")
        if errors:
            await interaction.response.send_message("❌ " + "\n".join(errors), ephemeral=True)
            return

        save_forum_config(
            forum.id,
            forum.name,
            ",".join(map(str, auto_ids)),
            unsolved_id,
            solved_id,
        )
        await interaction.response.send_message(f"✅ Saved settings for {forum.mention}.", ephemeral=True)
        view.state = "forum_edit"
        await view.message.edit(embed=view._render(), view=view)


class SettingsPanel(discord.ui.View):
    def __init__(self, bot, guild_id, operator_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.guild = bot.get_guild(guild_id)
        self.operator = operator_id
        self.message = None
        self.state = "main"
        self.selected_command = None
        self.selected_forum_id = None

    async def on_timeout(self):
        self.clear_items()
        try:
            await self.message.edit(view=None)
        except Exception:
            pass

    async def _require_operator(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.operator:
            await interaction.response.send_message(
                "❌ Only the user who opened this panel can use it.",
                ephemeral=True,
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction):
        embed = self._render()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await self.message.edit(embed=embed, view=self)

    # --- Buttons ---

    def _nav_button(self, label, emoji, style, state):
        btn = discord.ui.Button(label=label, emoji=emoji, style=style)

        async def callback(interaction):
            if not await self._require_operator(interaction):
                return
            self.state = state
            await self.refresh(interaction)

        btn.callback = callback
        return btn

    def _action_button(self, label, emoji, style, action=None, disabled=False):
        btn = discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled)

        async def callback(interaction):
            if not await self._require_operator(interaction):
                return
            if action:
                await action(interaction)

        btn.callback = callback
        return btn

    # --- Rendering ---

    def _render(self):
        self.clear_items()
        return getattr(self, f"_render_{self.state}")()

    def _render_main(self):
        notify_channel_id = get_notify_channel(self.guild_id)
        notify_channel = self.bot.get_channel(notify_channel_id) if notify_channel_id else None
        forums = get_all_forum_configs()
        overrides = get_all_command_roles(self.guild_id)
        mentions = get_notify_mentions(self.guild_id)

        embed = discord.Embed(
            title="⚙️ Black Hole Settings",
            description="Use the buttons below to view and change your settings.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🔔 Notifications",
            value=notify_channel.mention if notify_channel else "Not set",
            inline=False,
        )
        mention_summary = f"{len(mentions['role_ids'])} role(s), {len(mentions['user_ids'])} member(s)"
        embed.add_field(
            name="📣 Mention Targets",
            value=mention_summary if notify_channel else "Set a notification channel first",
            inline=False,
        )
        embed.add_field(
            name="🏷️ Forums",
            value=f"{len(forums)} configured" if forums else "None configured",
            inline=False,
        )
        embed.add_field(
            name="🔐 Permission Overrides",
            value=f"{len(overrides)} set" if overrides else "None",
            inline=False,
        )

        self.add_item(self._nav_button("Notifications", "🔔", discord.ButtonStyle.primary, "notifications"))
        self.add_item(self._nav_button("Forums", "🏷️", discord.ButtonStyle.primary, "forums"))
        self.add_item(self._nav_button("Permissions", "🔐", discord.ButtonStyle.primary, "permissions"))
        self.add_item(self._action_button("Close", "✖️", discord.ButtonStyle.danger, action=self._close))
        return embed

    async def _close(self, interaction):
        await interaction.response.edit_message(view=None)

    def _render_notifications(self):
        notify_channel_id = get_notify_channel(self.guild_id)
        channel = self.bot.get_channel(notify_channel_id) if notify_channel_id else None
        mentions = get_notify_mentions(self.guild_id)

        embed = discord.Embed(
            title="🔔 Notification Channel",
            description="Where Black Hole posts new cracks and Denuvo removals.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set", inline=False)
        embed.add_field(
            name="Sources",
            value="• voices38 cracks\n• Denuvo removals",
            inline=False,
        )
        embed.add_field(
            name="Mention Targets",
            value=f"{len(mentions['role_ids'])} role(s), {len(mentions['user_ids'])} member(s) get pinged. Use the 📣 Mentions button to change.",
            inline=False,
        )

        ch_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Choose the notification channel...",
        )

        async def on_channel(interaction):
            if not await self._require_operator(interaction):
                return
            target = ch_select.values[0]
            if target:
                set_notify_channel(self.guild_id, target.id)
            await self.refresh(interaction)

        ch_select.callback = on_channel
        self.add_item(ch_select)
        self.add_item(self._action_button(
            "Disable", "🗑️", discord.ButtonStyle.danger,
            action=self._disable_notify, disabled=channel is None,
        ))
        self.add_item(self._nav_button("Mentions", "📣", discord.ButtonStyle.primary, "mentions"))
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "main"))
        return embed

    async def _disable_notify(self, interaction):
        remove_notify_channel(self.guild_id)
        await self.refresh(interaction)

    def _render_mentions(self):
        mentions = get_notify_mentions(self.guild_id)
        role_ids = mentions["role_ids"]
        user_ids = mentions["user_ids"]

        embed = discord.Embed(
            title="📣 Notification Mentions",
            description="When a new voices38 crack or Denuvo removal is posted, these roles and members get pinged.",
            color=discord.Color.blurple(),
        )

        role_labels = []
        for rid in role_ids:
            role = self.guild.get_role(rid)
            role_labels.append(role.mention if role else f"<@&{rid}>")
        embed.add_field(
            name="Roles",
            value=", ".join(role_labels) if role_labels else "None",
            inline=False,
        )

        user_labels = []
        for uid in user_ids:
            user = self.bot.get_user(uid)
            user_labels.append(user.mention if user else f"<@{uid}>")
        embed.add_field(
            name="Members",
            value=", ".join(user_labels) if user_labels else "None",
            inline=False,
        )

        available_roles = self._selectable_roles(excluded_ids=set(role_ids))
        if available_roles:
            role_select = discord.ui.Select(
                placeholder="Add roles to ping...",
                options=[
                    discord.SelectOption(label=f"@{r.name}", value=str(r.id))
                    for r in available_roles
                ],
                max_values=min(len(available_roles), 25) or 1,
                disabled=not available_roles,
            )

            async def on_add_roles(interaction):
                if not await self._require_operator(interaction):
                    return
                add_notify_mentions(self.guild_id, [int(v) for v in role_select.values], [])
                await self.refresh(interaction)

            role_select.callback = on_add_roles
            self.add_item(role_select)

        user_select = discord.ui.UserSelect(
            placeholder="Add members to ping...",
            min_values=1,
            max_values=10,
        )

        async def on_add_users(interaction):
            if not await self._require_operator(interaction):
                return
            add_notify_mentions(self.guild_id, [], [u.id for u in user_select.values])
            await self.refresh(interaction)

        user_select.callback = on_add_users
        self.add_item(user_select)

        remove_options = []
        for rid in role_ids:
            role = self.guild.get_role(rid)
            remove_options.append(discord.SelectOption(
                label=f"@{role.name}" if role else f"Role {rid}",
                value=f"role:{rid}",
            ))
        for uid in user_ids:
            user = self.bot.get_user(uid)
            remove_options.append(discord.SelectOption(
                label=f"@{user.name}" if user else f"User {uid}",
                value=f"user:{uid}",
            ))

        remove_select = None
        if remove_options:
            remove_select = discord.ui.Select(
                placeholder="Remove a mention...",
                options=remove_options[:25],
                disabled=not remove_options,
            )

            async def on_remove(interaction):
                if not await self._require_operator(interaction):
                    return
                for v in remove_select.values:
                    target_type, _, sid = v.partition(":")
                    remove_notify_mention(self.guild_id, int(sid), target_type)
                await self.refresh(interaction)

            remove_select.callback = on_remove
            self.add_item(remove_select)
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "notifications"))
        return embed

    def _render_forums(self):
        configs = get_all_forum_configs()
        embed = discord.Embed(
            title="🏷️ Forum Channels",
            description="Pick a forum to view or change its tag settings.",
            color=discord.Color.blurple(),
        )
        if configs:
            for conf in configs:
                channel = self.bot.get_channel(conf["channel_id"])
                name = channel.name if channel else f"ID {conf['channel_id']}"
                info = f"**Auto Tags**: {_tag_names(channel, conf['auto_tag_ids'])}\n"
                info += f"**Unsolved**: {channel.get_tag(conf['unsolved_tag_id']).name if channel and conf.get('unsolved_tag_id') else 'None'}\n"
                info += f"**Solved**: {channel.get_tag(conf['solved_tag_id']).name if channel and conf.get('solved_tag_id') else 'None'}"
                embed.add_field(name=f"#{name}", value=info, inline=False)
        else:
            embed.add_field(name="Configured", value="None yet. Pick a forum below to configure it.", inline=False)

        default_id = get_guild_setting(self.guild_id, HELP_FORUM_KEY)
        default_forum = self.bot.get_channel(int(default_id)) if default_id else None
        embed.add_field(
            name="📍 Default Forum for /forum help",
            value=default_forum.mention if isinstance(default_forum, discord.ForumChannel) else "Not set",
            inline=False,
        )

        forum_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.forum],
            placeholder="Choose a forum channel to configure...",
        )

        async def on_forum(interaction):
            if not await self._require_operator(interaction):
                return
            self.selected_forum_id = forum_select.values[0].id
            self.state = "forum_edit"
            await self.refresh(interaction)

        forum_select.callback = on_forum
        self.add_item(forum_select)

        default_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.forum],
            placeholder="Set default forum for /forum help...",
        )

        async def on_default(interaction):
            if not await self._require_operator(interaction):
                return
            set_guild_setting(self.guild_id, HELP_FORUM_KEY, str(default_select.values[0].id))
            await self.refresh(interaction)

        default_select.callback = on_default
        self.add_item(default_select)

        self.add_item(self._action_button(
            "Clear Default", "🧹", discord.ButtonStyle.danger,
            action=self._clear_help_default,
            disabled=not isinstance(default_forum, discord.ForumChannel),
        ))
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "main"))
        return embed

    async def _clear_help_default(self, interaction):
        remove_guild_setting(self.guild_id, HELP_FORUM_KEY)
        await self.refresh(interaction)

    def _render_forum_edit(self):
        forum = self.bot.get_channel(self.selected_forum_id) if self.selected_forum_id else None
        if forum is None:
            embed = discord.Embed(title="🏷️ Forum", description="That forum channel no longer exists.", color=discord.Color.red())
            self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "forums"))
            return embed

        config = get_forum_config(forum.id)
        embed = discord.Embed(
            title=f"🏷️ #{forum.name}",
            description="Configure which tags the bot applies.",
            color=discord.Color.blurple(),
        )
        if config:
            embed.add_field(name="Auto Tags", value=_tag_names(forum, config["auto_tag_ids"]), inline=False)
            embed.add_field(name="Unsolved Tag", value=forum.get_tag(config["unsolved_tag_id"]).name if config.get("unsolved_tag_id") else "None", inline=False)
            embed.add_field(name="Solved Tag", value=forum.get_tag(config["solved_tag_id"]).name if config.get("solved_tag_id") else "None", inline=False)
        else:
            embed.description = "This forum is **not configured yet**. Click **Edit Tags** to set it up."

        self.add_item(self._action_button("Edit Tags", "✏️", discord.ButtonStyle.primary, action=self._edit_tags))
        self.add_item(self._action_button("Remove", "🗑️", discord.ButtonStyle.danger, action=self._remove_forum, disabled=not config))
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "forums"))
        return embed

    async def _edit_tags(self, interaction):
        await interaction.response.send_modal(EditTagsModal(self))

    async def _remove_forum(self, interaction):
        delete_forum_config(self.selected_forum_id)
        self.state = "forums"
        await self.refresh(interaction)

    def _role_line(self, command_name):
        role_ids = get_command_roles(self.guild_id, command_name)
        if not role_ids:
            return None
        mentions = []
        for rid in role_ids:
            role = self.guild.get_role(rid)
            mentions.append(role.mention if role else f"<@&{rid}>")
        return ", ".join(mentions)

    def _render_permissions(self):
        embed = discord.Embed(
            title="🔐 Command Permissions",
            description="Add roles to let them use a command. Admins are **always** allowed.\nDefault access applies when no roles are set.",
            color=discord.Color.blurple(),
        )
        for command_name in KNOWN_COMMANDS:
            overrides = self._role_line(command_name)
            if overrides:
                emoji = "🔒"
                value = f"**Default:** {_default_label(command_name)}\n**Allowed roles:** {overrides}"
            else:
                emoji = "✅"
                value = f"**Default access:** {_default_label(command_name)}"
            embed.add_field(name=f"{emoji} `/{command_name}`", value=value, inline=False)

        cmd_select = discord.ui.Select(
            placeholder="Pick a command to manage...",
            options=[
                discord.SelectOption(label=f"/{name}", value=name, description=_default_label(name))
                for name in KNOWN_COMMANDS
            ],
        )

        async def on_command(interaction):
            if not await self._require_operator(interaction):
                return
            self.selected_command = cmd_select.values[0]
            self.state = "command_perm"
            await self.refresh(interaction)

        cmd_select.callback = on_command
        self.add_item(cmd_select)
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "main"))
        return embed

    def _render_command_perm(self):
        command_name = self.selected_command
        role_ids = get_command_roles(self.guild_id, command_name)

        embed = discord.Embed(
            title=f"🔐 `/{command_name}`",
            description="Admins are always allowed. You can grant multiple roles.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Default Access", value=_default_label(command_name), inline=False)
        if role_ids:
            embed.add_field(name="Allowed Roles", value=self._role_line(command_name), inline=False)
        else:
            embed.add_field(name="Allowed Roles", value="None — default access applies.", inline=False)

        self.add_item(self._action_button("Add Roles", "➕", discord.ButtonStyle.primary, action=self._go_add_roles))
        self.add_item(self._action_button("Remove Roles", "➖", discord.ButtonStyle.danger, action=self._go_remove_roles, disabled=not role_ids))
        self.add_item(self._action_button("Clear All", "♻️", discord.ButtonStyle.danger, action=self._clear_override, disabled=not role_ids))
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "permissions"))
        return embed

    async def _go_add_roles(self, interaction):
        self.state = "add_roles"
        await self.refresh(interaction)

    async def _go_remove_roles(self, interaction):
        self.state = "remove_roles"
        await self.refresh(interaction)

    async def _clear_override(self, interaction):
        remove_command_role(self.guild_id, self.selected_command)
        await self.refresh(interaction)

    def _selectable_roles(self, excluded_ids=None):
        roles = [r for r in self.guild.roles if r.id != self.guild.id and not r.managed]
        if excluded_ids:
            roles = [r for r in roles if r.id not in excluded_ids]
        roles.sort(key=lambda r: r.position, reverse=True)
        return roles[:25]

    def _render_add_roles(self):
        command_name = self.selected_command
        current = set(get_command_roles(self.guild_id, command_name))
        roles = self._selectable_roles(excluded_ids=current)

        embed = discord.Embed(
            title=f"➕ Add Roles to `/{command_name}`",
            description="Pick one or more roles to allow. Shift-click to select multiple.",
            color=discord.Color.blurple(),
        )
        if not roles:
            embed.description = "No other roles available to add."

        if roles:
            role_select = discord.ui.Select(
                placeholder="Choose roles to allow...",
                options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in roles],
                max_values=min(len(roles), 25) or 1,
                disabled=not roles,
            )

            async def on_add(interaction):
                if not await self._require_operator(interaction):
                    return
                add_command_roles(self.guild_id, command_name, [int(v) for v in role_select.values])
                self.state = "command_perm"
                await self.refresh(interaction)

            role_select.callback = on_add
            self.add_item(role_select)
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "command_perm"))
        return embed

    def _render_remove_roles(self):
        command_name = self.selected_command
        roles = []
        for rid in get_command_roles(self.guild_id, command_name):
            role = self.guild.get_role(rid)
            if role:
                roles.append(role)
        roles.sort(key=lambda r: r.position, reverse=True)

        embed = discord.Embed(
            title=f"➖ Remove Roles from `/{command_name}`",
            description="Pick one or more roles to remove. Shift-click to select multiple.",
            color=discord.Color.blurple(),
        )
        if not roles:
            embed.description = "No allowed roles to remove."

        if roles:
            role_select = discord.ui.Select(
                placeholder="Choose roles to remove...",
                options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in roles],
                max_values=min(len(roles), 25) or 1,
                disabled=not roles,
            )

            async def on_remove(interaction):
                if not await self._require_operator(interaction):
                    return
                for v in role_select.values:
                    remove_command_role(self.guild_id, command_name, int(v))
                self.state = "command_perm"
                await self.refresh(interaction)

            role_select.callback = on_remove
            self.add_item(role_select)
        self.add_item(self._nav_button("Back", "🔙", discord.ButtonStyle.secondary, "command_perm"))
        return embed


class SettingsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.commands.slash_command(
        name="settings",
        description="Open the interactive Black Hole settings panel. (Admins Only)",
        checks=[check_permission("settings")],
    )
    async def settings(self, ctx: discord.ApplicationContext):
        view = SettingsPanel(self.bot, ctx.guild_id, ctx.user.id)
        embed = view._render()
        view.message = await ctx.respond(embed=embed, view=view, ephemeral=True)


def setup(bot):
    bot.add_cog(SettingsCog(bot))
