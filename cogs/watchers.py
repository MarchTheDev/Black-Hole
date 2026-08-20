import asyncio
import html
import os
import re
from datetime import datetime, timezone

import discord
import feedparser
import requests
from bs4 import BeautifulSoup
from discord.ext import commands, tasks

from db import get_notify_configs, get_notify_mentions, has_seen_any, mark_seen
from cogs.permissions import check_permission

VOICES38_SOURCE = "v38"
DENUVO_SOURCE = "denuvo"

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://lhvknkrfhehcclzlabsl.supabase.co")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxodmtua3JmaGVoY2NsemxhYnNsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg4NzM0MTksImV4cCI6MjA5NDQ0OTQxOX0.B7YOW_hpn2zHxR-sfHgiNgqidpfESwJpixLrh-MevE8",
)
DENUVO_RSS_URL = "https://steamcommunity.com/groups/DenuvoWatch/rss/"
CRACKRELEASE_URL = "https://crackrelease.com/group/voices38/"

USER_AGENT = "BlackHoleBot/1.0"


def normalize_title(title: str) -> str:
    t = re.sub(r"[\W_]+", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip()


def _fmt_dmy(value):
    """Formats a date string or time.struct_time as DD/MM/YYYY. Falls back to the raw value."""
    if value is None:
        return ""
    if hasattr(value, "tm_year"):  # e.g. feedparser's published_parsed
        try:
            return datetime(value.tm_year, value.tm_mon, value.tm_mday).strftime("%d/%m/%Y")
        except (ValueError, OverflowError):
            return ""

    s = str(value).strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s


def fetch_voices38_supabase():
    """Primary voices38 source: isitcracked.com's public Supabase games table."""
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "User-Agent": USER_AGENT,
    }
    params = {
        "select": "id,title,slug,status,crack_date,scene_group,drm_protection",
        "scene_group": "eq.voices38",
        "order": "crack_date.desc.nullslast",
        "limit": "100",
    }
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/games",
        params=params,
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()

    games = []
    for g in resp.json():
        title = (g.get("title") or "").strip()
        status = (g.get("status") or "").lower()
        if not title or status not in ("cracked", "hypervisor"):
            continue
        slug = (g.get("slug") or "").strip()
        games.append({
            "key": normalize_title(title),
            "title": title,
            "status": g.get("status") or "Cracked",
            "crack_date": (g.get("crack_date") or "").strip(),
            "drm": (g.get("drm_protection") or "Denuvo").strip(),
            "url": f"https://isitcracked.com/game/{slug}" if slug else None,
        })
    return games


def fetch_voices38_crackrelease(max_pages=15):
    """Fallback voices38 source: crackrelease.com group page (server-rendered WordPress)."""
    games = []
    page = 1
    while page <= max_pages:
        url = CRACKRELEASE_URL if page == 1 else f"{CRACKRELEASE_URL}page/{page}/"
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        if resp.status_code != 200:
            break
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.p-wrap[data-pid]")
        if not cards:
            break

        for card in cards:
            link = card.select_one("h2.entry-title a.p-url")
            if not link:
                continue
            title = html.unescape(link.get_text(strip=True))
            badge = card.select_one("div.cw-card-badge")
            games.append({
                "key": normalize_title(title),
                "title": title,
                "status": badge.get_text(strip=True) if badge else "Cracked",
                "crack_date": "",
                "drm": "Denuvo",
                "url": link.get("href"),
            })

        if not soup.select_one("nav.pagination-wrap a.next.page-numbers"):
            break
        page += 1

    return games


def fetch_denuvo_rss():
    """Denuvo removal announcements from the Steam 'Denuvo Watch' group RSS feed."""
    resp = requests.get(DENUVO_RSS_URL, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    items = []
    for entry in feed.entries:
        guid = (entry.get("id") or entry.get("link") or "").strip()
        if not guid:
            continue
        desc = entry.get("description") or ""
        urls = re.findall(r'href="([^"]+)"', desc)
        clean = html.unescape(re.sub(r"<[^>]+>", " ", desc))
        clean = re.sub(r"\s+", " ", clean).strip()
        items.append({
            "guid": guid,
            "key": guid,
            "title": (entry.get("title") or "").strip(),
            "link": (entry.get("link") or "").strip(),
            "author": (entry.get("author") or "").strip(),
            "published": (entry.get("published") or "").strip(),
            "published_parsed": entry.get("published_parsed"),
            "description": clean,
            "urls": urls,
        })
    return items


class WatcherCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voices38_minutes = max(1, int(os.getenv("VOICES38_POLL_MINUTES", "30")))
        self.denuvo_minutes = max(5, int(os.getenv("DENUVO_POLL_MINUTES", "60")))

    async def cog_load(self):
        self.voices38_watcher.change_interval(minutes=self.voices38_minutes)
        self.denuvo_watcher.change_interval(minutes=self.denuvo_minutes)
        self.voices38_watcher.start()
        self.denuvo_watcher.start()

    async def cog_unload(self):
        self.voices38_watcher.cancel()
        self.denuvo_watcher.cancel()

    async def _broadcast(self, embed: discord.Embed):
        for target in get_notify_configs():
            channel = self.bot.get_channel(target["channel_id"])
            if channel is None:
                continue
            mentions = get_notify_mentions(target["guild_id"])
            role_ids = mentions["role_ids"]
            user_ids = mentions["user_ids"]
            content = None
            allowed = discord.AllowedMentions.none()
            if role_ids or user_ids:
                parts = [f"<@&{rid}>" for rid in role_ids] + [f"<@{uid}>" for uid in user_ids]
                content = " ".join(parts)
                allowed = discord.AllowedMentions(roles=role_ids, users=user_ids)
            try:
                await channel.send(content=content, embed=embed, allowed_mentions=allowed)
            except discord.Forbidden:
                print(f"[notify] Missing permissions to post in channel {target['channel_id']}")
            except Exception as e:
                print(f"[notify] Failed to post in channel {target['channel_id']}: {e}")

    def _fetch_voices38(self):
        try:
            games = fetch_voices38_supabase()
            if games:
                return games
            print("[voices38] Supabase returned no games; trying crackrelease fallback...")
        except Exception as e:
            print(f"[voices38] Supabase fetch failed ({e}); trying crackrelease fallback...")
        try:
            return fetch_voices38_crackrelease()
        except Exception as e:
            print(f"[voices38] crackrelease fetch failed: {e}")
        return []

    @discord.commands.slash_command(
        name="latest_cracks",
        description="Show the most recent voices38 cracks and Denuvo removals.",
        checks=[check_permission("latest_cracks")],
    )
    @discord.commands.option("amount", int, description="How many of each to show (default 10, max 25)", required=False)
    async def latest_cracks(self, ctx: discord.ApplicationContext, amount: int = 10):
        amount = max(1, min(amount, 25))
        await ctx.response.defer()

        games, items = [], []
        try:
            games = await asyncio.to_thread(fetch_voices38_supabase)
        except Exception as e:
            print(f"[latest_cracks] voices38 fetch failed: {e}")
        try:
            items = await asyncio.to_thread(fetch_denuvo_rss)
        except Exception as e:
            print(f"[latest_cracks] denuvo fetch failed: {e}")

        embed1 = discord.Embed(title="🔓 Latest voices38 Cracks", color=0x9B59B6)
        if games:
            lines = []
            for i, g in enumerate(games[:amount], 1):
                title = g["title"]
                link = g.get("url")
                name = f"[{title}]({link})" if link else title
                lines.append(f"{i}. **{name}** — {_fmt_dmy(g.get('crack_date')) or 'n/a'}")
            embed1.description = "\n".join(lines)
        else:
            embed1.description = "No voices38 cracks found (source unreachable?)."
        embed1.set_footer(text="Source: isitcracked.com / crackrelease.com")

        embed2 = discord.Embed(title="🟢 Latest Denuvo Removals", color=0x2ECC71)
        if items:
            lines = []
            for i, item in enumerate(items[:amount], 1):
                title = item["title"].replace("Denuvo removed from ", "", 1)
                link = item.get("link")
                name = f"[{title}]({link})" if link else title
                date = _fmt_dmy(item.get("published_parsed") or item.get("published"))
                lines.append(f"{i}. **{name}** — {date or 'n/a'}")
            embed2.description = "\n".join(lines)
        else:
            embed2.description = "No Denuvo removals found (source unreachable?)."
        embed2.set_footer(text="Source: Steam 'Denuvo Watch'")

        await ctx.followup.send(embeds=[embed1, embed2])

    @tasks.loop()
    async def voices38_watcher(self):
        await self.bot.wait_until_ready()
        try:
            games = await asyncio.to_thread(self._fetch_voices38)
            if not games:
                return

            first_poll = not has_seen_any(VOICES38_SOURCE)
            new_games = []
            for game in games:
                if first_poll:
                    mark_seen(VOICES38_SOURCE, game["key"])
                elif mark_seen(VOICES38_SOURCE, game["key"]):
                    new_games.append(game)

            if first_poll:
                print(f"[voices38] Seeded {len(games)} known releases. New cracks will be posted from now on.")
                return

            for game in new_games:
                print(f"[voices38] New crack detected: {game['title']}")
                await self._notify_voices38(game)
        except Exception as e:
            print(f"[voices38] Poll failed: {e}")

    async def _notify_voices38(self, game):
        embed = discord.Embed(
            title=f"🔓 {game['title']}",
            url=game.get("url"),
            description="**voices38** has released a crack for this title.",
            color=0x9B59B6,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Scene Group", value="voices38", inline=True)
        embed.add_field(name="Status", value=game.get("status") or "Cracked", inline=True)
        embed.add_field(name="DRM", value=game.get("drm") or "Unknown", inline=True)
        if game.get("crack_date"):
            embed.add_field(name="Crack Date", value=_fmt_dmy(game["crack_date"]), inline=True)
        embed.set_footer(text="Source: isitcracked.com / crackrelease.com")
        await self._broadcast(embed)

    @tasks.loop()
    async def denuvo_watcher(self):
        await self.bot.wait_until_ready()
        try:
            items = await asyncio.to_thread(fetch_denuvo_rss)
            if not items:
                return

            first_poll = not has_seen_any(DENUVO_SOURCE)
            new_items = []
            for item in items:
                if first_poll:
                    mark_seen(DENUVO_SOURCE, item["key"])
                elif mark_seen(DENUVO_SOURCE, item["key"]):
                    new_items.append(item)

            if first_poll:
                print(f"[denuvo] Seeded {len(items)} known announcements. New removals will be posted from now on.")
                return

            for item in new_items:
                print(f"[denuvo] New announcement: {item['title']}")
                await self._notify_denuvo(item)
        except Exception as e:
            print(f"[denuvo] Poll failed: {e}")

    async def _notify_denuvo(self, item):
        description = (item.get("description") or "")[:1024]
        embed = discord.Embed(
            title=item["title"],
            url=item.get("link"),
            description=description or None,
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc),
        )
        if item.get("author"):
            embed.add_field(name="Author", value=item["author"], inline=True)
        if item.get("published") or item.get("published_parsed"):
            embed.add_field(
                name="Posted",
                value=_fmt_dmy(item.get("published_parsed") or item.get("published")),
                inline=True,
            )
        if item.get("urls"):
            proof = "\n".join(f"[Proof link {i + 1}]({url})" for i, url in enumerate(item["urls"][:2]))
            embed.add_field(name="Proof", value=proof[:1024], inline=False)
        embed.set_footer(text="Source: Steam 'Denuvo Watch' group")
        await self._broadcast(embed)


def setup(bot):
    bot.add_cog(WatcherCog(bot))
