import os
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
from dotenv import load_dotenv

from db import init_db

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Fallback 1: Try common environment variable names
if not TOKEN:
    TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = os.getenv("TOKEN")

# Fallback 2: Manually read the .env or token.env file if load_dotenv() struggled in this environment
for env_file in [".env", "token.env"]:
    if not TOKEN and os.path.exists(env_file):
        try:
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        if key.strip() in ["DISCORD_TOKEN", "BOT_TOKEN", "TOKEN"]:
                            TOKEN = val.strip().strip('"').strip("'")  # Clean quotes
                            os.environ["DISCORD_TOKEN"] = TOKEN
                            break
        except Exception as e:
            print(f"Could not manually read {env_file} file: {e}")

# --- Lightweight Keep-Alive Web Server ---
# Render Free Tier Web Services require an open port and active web requests
# to prevent the bot from going to sleep after 15 minutes of inactivity.
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Bot is online and keeping alive!")

    def log_message(self, format, *args):
        pass

def run_web_server(port: int):
    try:
        server = ThreadingHTTPServer(('0.0.0.0', port), KeepAliveHandler)
        print(f"Keep-alive web server listening on port {port}...")
        server.serve_forever()
    except Exception as e:
        print(f"Failed to start keep-alive web server on port {port}: {e}")

def keep_alive():
    port = int(os.getenv("PORT", 8080))
    t = threading.Thread(target=run_web_server, args=(port,), daemon=True)
    t.start()
    print("Keep-alive thread initiated.")

keep_alive()

# Initialize database
init_db()


class BlackHoleBot(discord.Bot):
    def __init__(self):
        # Default intents means we don't request any Privileged Gateway Intents.
        intents = discord.Intents.default()
        intents.guilds = True  # Required for thread and channel events

        super().__init__(description="Black Hole — forum helper + crack notifications.", intents=intents)

        # pycord's load_extension/setup are synchronous.
        self.load_extension("cogs.forum")
        self.load_extension("cogs.watchers")
        self.load_extension("cogs.settings")
        print("Loaded extensions: cogs.forum, cogs.watchers, cogs.settings")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

        print("Syncing slash commands globally...")
        try:
            await self.sync_commands()
            print("Successfully synced slash commands globally.")
        except Exception as e:
            print(f"Failed to sync slash commands: {e}")
        print("Bot is ready and active!")


bot = BlackHoleBot()


@bot.event
async def on_application_command_error(interaction: discord.ApplicationContext, error: discord.ApplicationCommandError):
    command = interaction.command
    name = command.qualified_name if command else "this command"
    if isinstance(error, discord.errors.CheckFailure):
        message = (
            f"❌ You don't have permission to use `/{name}`.\n"
            "Ask an admin to run `/settings` and adjust who can use it."
        )
    else:
        print(f"[tree] Unhandled command error for /{name}: {error}")
        if interaction.response.is_done():
            # We already sent a response (e.g. post created); don't spam a second error.
            return
        message = f"❌ Something went wrong while running `/{name}`. Please try again."
    try:
        await interaction.response.send_message(message, ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(message, ephemeral=True)
    except Exception as e:
        print(f"[tree] Failed to send error message: {e}")


if __name__ == "__main__":
    if not TOKEN:
        print("\n❌ Error: DISCORD_TOKEN environment variable not set.")
        print("=== ⚙️ Startup Debugging Information ===")
        print(f"• Current Working Directory: {os.getcwd()}")
        try:
            files = os.listdir('.')
            print(f"• Files found in current directory: {files}")

            env_candidates = [f for f in files if 'env' in f.lower()]
            print(f"• Files containing 'env' in their name: {env_candidates}")

            for ec in env_candidates:
                size = os.path.getsize(ec)
                print(f"  - File '{ec}' size: {size} bytes")
                try:
                    with open(ec, 'r') as f:
                        keys_found = []
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            if '=' in line:
                                keys_found.append(line.split('=', 1)[0].strip())
                        print(f"  - Keys found in '{ec}': {keys_found}")
                except Exception as re:
                    print(f"  - Could not inspect '{ec}': {re}")
        except Exception as de:
            print(f"• Failed to list files: {de}")
        print("=======================================\n")
        print("Please review the debugging info above. It will show if your '.env' file is missing, empty, named incorrectly, or if the server is starting in a different folder.")
    else:
        bot.run(TOKEN)
