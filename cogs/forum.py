import discord
from discord.commands import SlashCommandGroup
from discord.ext import commands

from db import get_forum_config, get_guild_setting
from cogs.permissions import can_use, check_permission


class ForumCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- Automatic Forum Events ---

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """Triggers when a forum post (thread) is created."""
        config = get_forum_config(thread.parent_id)
        if not config:
            return

        parent = thread.parent or await thread.guild.fetch_channel(thread.parent_id)
        if not isinstance(parent, discord.ForumChannel):
            return

        print(f"New forum post detected: '{thread.name}' (ID: {thread.id}) in configured channel '#{parent.name}'")

        existing_tags = list(thread.applied_tags)
        new_tags = list(existing_tags)
        tags_added = False

        for tag_id in config["auto_tag_ids"]:
            tag = parent.get_tag(tag_id)
            if tag and tag not in new_tags:
                new_tags.append(tag)
                tags_added = True

        if tags_added:
            try:
                # Discord maximum is 5 tags
                await thread.edit(applied_tags=new_tags[:5])
                print(f"Successfully auto-tagged post '{thread.name}'")
            except discord.Forbidden:
                print("Error: Lacking permissions to edit tags.")
            except Exception as e:
                print(f"Error updating tags: {e}")

    # --- Thread Management Slash Commands ---

    @discord.commands.slash_command(
        name="solve",
        description="Marks this forum post as solved: removes the unsolved tag, adds the solved tag, and locks the post.",
        checks=[check_permission("solve")],
    )
    async def solve(self, ctx: discord.ApplicationContext):
        thread = ctx.channel

        if not isinstance(thread, discord.Thread):
            await ctx.response.send_message(
                "❌ This command can only be used inside a forum post (thread)!",
                ephemeral=True
            )
            return

        config = get_forum_config(thread.parent_id)
        if not config:
            await ctx.response.send_message(
                "❌ This forum channel has not been configured yet. Ask an administrator to run `/settings` first!",
                ephemeral=True
            )
            return

        is_owner = thread.owner_id == ctx.user.id
        is_staff = ctx.user.guild_permissions.manage_threads

        if not (is_owner or is_staff):
            await ctx.response.send_message(
                "❌ Only the post author or staff members with 'Manage Threads' permission can solve this post!",
                ephemeral=True
            )
            return

        await ctx.response.defer()

        parent = thread.parent or await thread.guild.fetch_channel(thread.parent_id)
        existing_tags = list(thread.applied_tags)
        new_tags = []

        unsolved_tag_id = config["unsolved_tag_id"]
        solved_tag_id = config["solved_tag_id"]

        for tag in existing_tags:
            if unsolved_tag_id and tag.id == unsolved_tag_id:
                continue
            new_tags.append(tag)

        if solved_tag_id:
            solved_tag = parent.get_tag(solved_tag_id)
            if solved_tag and solved_tag not in new_tags:
                new_tags.append(solved_tag)

        new_tags = new_tags[:5]

        try:
            embed = discord.Embed(
                title="✅ Post Solved & Locked",
                description="This post has been marked as solved. It is now locked and archived to prevent further replies.",
                color=discord.Color.green()
            )
            embed.set_footer(
                text=f"Solved by {ctx.user.display_name}",
                icon_url=ctx.user.display_avatar.url
            )
            await ctx.followup.send(embed=embed)

            await thread.edit(
                applied_tags=new_tags,
                locked=True,
                archived=True,
                reason=f"Solved by {ctx.user}"
            )
            print(f"Post '{thread.name}' (ID: {thread.id}) marked as solved and locked by {ctx.user}")

        except discord.Forbidden:
            await ctx.followup.send(
                "❌ The bot lacks 'Manage Threads' or 'Send Messages' permission to execute this action.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error during /solve: {e}")
            await ctx.followup.send(
                f"❌ An error occurred while trying to solve the post: {e}",
                ephemeral=True
            )

    @discord.commands.slash_command(
        name="close",
        description="Closes and locks this forum post without changing any tags.",
        checks=[check_permission("close")],
    )
    async def close(self, ctx: discord.ApplicationContext):
        thread = ctx.channel

        if not isinstance(thread, discord.Thread):
            await ctx.response.send_message(
                "❌ This command can only be used inside a forum post (thread)!",
                ephemeral=True
            )
            return

        config = get_forum_config(thread.parent_id)
        if not config:
            await ctx.response.send_message(
                "❌ This forum channel has not been configured yet. Ask an administrator to run `/settings` first!",
                ephemeral=True
            )
            return

        is_owner = thread.owner_id == ctx.user.id
        is_staff = ctx.user.guild_permissions.manage_threads

        if not (is_owner or is_staff):
            await ctx.response.send_message(
                "❌ Only the post author or staff members with 'Manage Threads' permission can close this post!",
                ephemeral=True
            )
            return

        await ctx.response.defer()

        try:
            embed = discord.Embed(
                title="🔒 Post Closed & Locked",
                description="This post has been closed. It is now locked and archived to prevent further replies.",
                color=discord.Color.red()
            )
            embed.set_footer(
                text=f"Closed by {ctx.user.display_name}",
                icon_url=ctx.user.display_avatar.url
            )
            await ctx.followup.send(embed=embed)

            await thread.edit(
                locked=True,
                archived=True,
                reason=f"Closed by {ctx.user}"
            )
            print(f"Post '{thread.name}' (ID: {thread.id}) closed and locked by {ctx.user}")

        except discord.Forbidden:
            await ctx.followup.send(
                "❌ The bot lacks 'Manage Threads' or 'Send Messages' permission to execute this action.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error during /close: {e}")
            await ctx.followup.send(
                f"❌ An error occurred while trying to close the post: {e}",
                ephemeral=True
            )

    forum = SlashCommandGroup(name="forum", description="Forum helper commands.")

    @forum.command(
        name="help",
        description="Create a help post in a forum from your own text.",
        checks=[check_permission("forum help")],
    )
    @discord.commands.option("channel", discord.ForumChannel, description="Forum channel. Defaults to the one set in /settings, or the current forum.", required=False)
    @discord.commands.option("user", discord.User, description="Person who needs help — they'll be mentioned in the post.", required=False)
    @discord.commands.option("content", str, description="Text for the help post. The first line becomes the title.", required=False)
    async def forum_help(
        self,
        ctx: discord.ApplicationContext,
        channel: discord.ForumChannel = None,
        user: discord.User = None,
        content: str = None,
    ):
        target_forum = channel
        if target_forum is None:
            default_id = get_guild_setting(ctx.guild.id, "forum_help_channel")
            if default_id:
                default_forum = self.bot.get_channel(int(default_id))
                if isinstance(default_forum, discord.ForumChannel):
                    target_forum = default_forum
            if target_forum is None and isinstance(ctx.channel, discord.ForumChannel):
                target_forum = ctx.channel

        if target_forum is None:
            await ctx.response.send_message(
                "❌ No forum selected. Pass the `channel` option, set a default in `/settings`, or run this inside a forum channel.",
                ephemeral=True
            )
            return

        if not content or not content.strip():
            await ctx.response.send_message(
                "❌ Provide some `content` for the help post.",
                ephemeral=True
            )
            return

        await self._create_help_thread(ctx, target_forum, referenced=None, user=user, text=content, ephemeral=True)

    async def _create_help_thread(self, ctx: discord.ApplicationContext, target_forum, referenced=None, user=None, text=None, ephemeral: bool = False):
        """Deferred thread creation shared by /forum help and the context menu."""
        await ctx.response.defer(ephemeral=ephemeral)

        config = get_forum_config(target_forum.id)
        unsolved_tag = None
        if config and config["unsolved_tag_id"]:
            unsolved_tag = target_forum.get_tag(config["unsolved_tag_id"])

        if referenced is not None:
            title = (referenced.content or "").strip() or f"Message from {referenced.author.display_name}"
            body_lines = [
                f"**Referenced message** by {referenced.author.mention}:",
                referenced.content or "*[message has no text — see the link below]*",
                "",
                f"**Original message:** {referenced.jump_url}",
            ]
            if text:
                body_lines.extend(["", text])
        elif text:
            stripped = text.strip()
            lines = stripped.splitlines()
            title = lines[0] if lines else "New help post"
            body_lines = [stripped]
        else:
            await ctx.followup.send("❌ Provide a message link or some text.", ephemeral=True)
            return

        if len(title) > 100:
            title = title[:97] + "..."

        body_lines.append(f"**Opened by:** {ctx.user.mention}")
        if user:
            body_lines.append(f"**Helping:** {user.mention}")
        body = "\n".join(body_lines)

        mention_users = [ctx.user]
        if user and user.id != ctx.user.id:
            mention_users.append(user)
        applied_tags = [unsolved_tag] if unsolved_tag else None

        try:
            thread = await target_forum.create_thread(
                name=title,
                content=body,
                applied_tags=applied_tags,
                allowed_mentions=discord.AllowedMentions(users=mention_users),
            )
        except discord.Forbidden:
            await ctx.followup.send(
                "❌ The bot lacks permission to create posts in that forum.",
                ephemeral=True
            )
            return
        except Exception as e:
            print(f"Error creating forum post: {e}")
            await ctx.followup.send(
                f"❌ Failed to create the forum post: {e}",
                ephemeral=True
            )
            return

        msg = f"✅ Created help post: {thread.mention}"
        if not unsolved_tag:
            msg += "\n⚠️ This forum has no 'unsolved' tag configured — set one in `/settings`."
        try:
            await ctx.followup.send(msg, ephemeral=ephemeral)
        except Exception as e:
            print(f"Post created but failed to send confirmation: {e}")

    # --- Context menu (reply-to-message flow) ---

    @discord.commands.message_command(name="Create Help Post")
    async def forum_help_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        """Right-click a message -> Apps -> Create Help Post."""
        if not can_use(ctx, "forum help"):
            await ctx.response.send_message(
                "❌ You don't have permission to use this. Ask an admin to run `/settings`.",
                ephemeral=True
            )
            return

        if isinstance(ctx.channel, discord.ForumChannel):
            await self._create_help_thread(ctx, ctx.channel, message, None, ephemeral=True)
            return

        forums = [
            ch for ch in ctx.guild.channels
            if isinstance(ch, discord.ForumChannel) and get_forum_config(ch.id)
        ]
        if not forums:
            await ctx.response.send_message(
                "❌ No configured forum channel found. Run this inside a forum or configure one in `/settings`.",
                ephemeral=True
            )
            return
        if len(forums) == 1:
            await self._create_help_thread(ctx, forums[0], message, None, ephemeral=True)
            return

        await ctx.response.send_message(
            "Choose a forum to create the help post in:",
            view=ForumPickerView(self, message, forums),
            ephemeral=True
        )


class ForumPickerView(discord.ui.View):
    def __init__(self, cog, target_message, forums):
        super().__init__(timeout=120)
        self.cog = cog
        self.target_message = target_message
        self.select = discord.ui.Select(
            placeholder="Choose a forum channel...",
            options=[discord.SelectOption(label=f"#{ch.name}", value=str(ch.id)) for ch in forums[:25]],
        )
        self.select.callback = self._on_pick
        self.add_item(self.select)

    async def _on_pick(self, ctx: discord.ApplicationContext):
        forum = ctx.guild.get_channel(int(self.select.values[0]))
        self.stop()
        await self.cog._create_help_thread(ctx, forum, self.target_message, None, ephemeral=True)


def setup(bot):
    bot.add_cog(ForumCog(bot))
