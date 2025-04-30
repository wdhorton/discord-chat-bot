import modal
from pathlib import Path
import os

# Use hyphenated name to match the actual file (discord-answer-logs.db)
DB_FILE = "discord-answer-logs.db"
#DB_FILE = "logs.db"

#app = modal.App("discord-bot-datasette")
app = modal.App("discord-bot-logs-feed")


# Create an image with Datasette and its dependencies
image = modal.Image.debian_slim().pip_install(
    "datasette",
    "sqlite-utils",
)

# Use the same volume name as modal_discord_bot.py ("discord-logs")
db_storage = modal.Volume.from_name("discord-logs", create_if_missing=True)


# Mount the database directory at the same path as modal_discord_bot.py ("/data/db")
@app.function(
    image=image,
    volumes={"/data/db": db_storage},
    allow_concurrent_inputs=16,
)
@modal.asgi_app()
def ui():
    import asyncio

    from datasette.app import Datasette

    # Update path to match the mounted directory
    remote_db_path = Path("/data/db") / DB_FILE
    local_db_path = Path(".") / DB_FILE
    local_db_path.write_bytes(remote_db_path.read_bytes())

    ds = Datasette(files=[local_db_path], settings={"sql_time_limit_ms": 10000})
    asyncio.run(ds.invoke_startup())
    return ds.app()

