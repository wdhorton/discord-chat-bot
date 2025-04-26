# ---
# deploy: true
# ---

"""
Discord Bot with ChatGPT Integration using Modal

This module implements a Discord bot that integrates with OpenAI's ChatGPT to provide 
question-answering capabilities through Discord slash commands. The bot is built using 
Modal for deployment and FastAPI for handling Discord interactions.

Key Features:
- Slash command integration (/api) for asking questions to ChatGPT
- Asynchronous request handling for better performance
- Discord interaction authentication
- OpenAI API integration with rate limiting and error handling

Requirements:
- Modal deployment setup with appropriate secrets:
  - discord-secret-2: Contains Discord bot credentials
  - openai-secret: Contains OpenAI API key
- Python packages: fastapi, pynacl, requests, openai

Usage:
1. Set up Discord application and bot in Discord Developer Portal
2. Configure Modal secrets for Discord and OpenAI
3. Deploy the application using Modal
4. Set up Discord interactions endpoint URL
5. Invite bot to your Discord server
6. Use /api command in Discord to interact with ChatGPT

For detailed setup instructions, see the documentation below.
"""

import json
from enum import Enum

import modal
from vector_emb import answer_question, SYSTEM_PROMPT, COMPLETION_MODEL
from database import log_interaction, init_db

image = (modal.Image.debian_slim(python_version="3.11").pip_install(
    "fastapi[standard]==0.115.9", "pynacl~=1.5.0", "requests~=2.32.3", "openai~=1.75.0",
    "tiktoken~=0.9.0", "chromadb~=1.0.6"
).add_local_dir("data", remote_path="/data", copy=True))

app = modal.App("example-discord-bot", image=image)

# Define persistent volume for logs - CORRECTED TYPO
logs_db_storage = modal.Volume.from_name("discord-logs", create_if_missing=True)

from openai import AsyncOpenAI

@app.function(secrets=[modal.Secret.from_name("openai-secret")])
@modal.concurrent(max_inputs=1000)
async def fetch_api(question: str) -> str:
    """
    Fetch a response from OpenAI's ChatGPT API for a given question.
    
    Args:
        question (str): The question to send to ChatGPT
        
    Returns:
        str: The response from ChatGPT, or an error message if the request fails
        
    Notes:
        - Uses GPT-3.5-turbo model with temperature 0.7 for varied responses
        - Limited to 500 tokens for concise answers
        - Handles API errors gracefully with formatted error messages
    """
    

    client = AsyncOpenAI()

    try:
        # Get context for the question
        context = answer_question(question)
        
        # Ensure context is a string to avoid NoneType errors
        if context is None:
            context = "No specific context found."
        
        # Make a single API call with both system prompt and context
        response = await client.chat.completions.create(
            model=COMPLETION_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Workshop Transcript Sections:\n{context}\n\nQuestion: {question}"}
            ],
            max_tokens=500,
            temperature=0
        )
        
        message = response.choices[0].message.content
    except Exception as e:
        message = f"# 🤖: Oops! {e}"

    return message

@app.local_entrypoint()
def test_fetch_api():
    result = fetch_api.remote("What is Modal?")  # Added test question
    if result.startswith("# 🤖: Oops! "):
        raise Exception(result)
    else:
        print(result)

async def send_to_discord(payload: dict, app_id: str, interaction_token: str):
    """
    Send a response back to Discord using their webhook API.
    
    Args:
        payload (dict): The message content to send to Discord
        app_id (str): The Discord application ID
        interaction_token (str): The interaction token for this specific response
        
    Notes:
        - Uses Discord's v10 API
        - Sends messages asynchronously using aiohttp
        - Updates the original interaction message
    """
    import aiohttp

    interaction_url = f"https://discord.com/api/v10/webhooks/{app_id}/{interaction_token}/messages/@original"

    async with aiohttp.ClientSession() as session:
        async with session.patch(interaction_url, json=payload) as resp:
            print("🤖 Discord response: " + await resp.text())


@app.function(
    concurrency_limit=1,
    allow_concurrent_inputs=1000,
    secrets=[modal.Secret.from_name("openai-secret")],
    volumes={"/data/db": logs_db_storage} # ADD THIS LINE TO MOUNT THE VOLUME
)
async def reply(app_id: str, interaction_token: str, question: str):
    """
    Handle the full flow of receiving a Discord command and responding with ChatGPT's answer.
    
    Args:
        app_id (str): Discord application ID
        interaction_token (str): Token for this specific interaction
        question (str): The user's question for ChatGPT
        
    Notes:
        - Concurrency limited to 1 instance but allows 1000 concurrent requests
        - Logs each step of the process for monitoring
        - Handles errors gracefully and sends error messages back to Discord
    """
    print(f"🤖 Getting ChatGPT response for question: {question}")
    message = "" # Initialize message to ensure it's defined in finally block
    try:
        init_db() # ADD THIS LINE TO INITIALIZE DB WITHIN THE FUNCTION CONTEXT
        message = await fetch_api.local(question)
        print(f"🤖 Got response from ChatGPT: {message[:100]}...")
        await send_to_discord({"content": message}, app_id, interaction_token)
        print("🤖 Successfully sent response to Discord")
    except Exception as e:
        error_message = f"Sorry, there was an error processing your request: {str(e)}"
        print(f"🤖 Error in reply: {error_message}")
        await send_to_discord({"content": error_message}, app_id, interaction_token)
    finally:
        # Log the interaction in the database
        print("🤖 Logging interaction")
        # Ensure the volume is reloaded if needed for the write operation
        logs_db_storage.reload() 
        log_interaction(
            user_id=interaction_token, # timestamp is handled internally
            channel_id=app_id,
            question=question,
            response=message, # Use the potentially modified message
            feedback=None,
            thread_id=None
        )
        # Persist changes made to the volume
        logs_db_storage.commit() 


# ## Set up a Discord app

# Now, we need to actually connect to Discord.
# We start by creating an application on the Discord Developer Portal.

# 1. Go to the
#    [Discord Developer Portal](https://discord.com/developers/applications) and
#    log in with your Discord account.
# 2. On the portal, go to **Applications** and create a new application by
#    clicking **New Application** in the top right next to your profile picture.
# 3. [Create a custom Modal Secret](https://modal.com/docs/guide/secrets) for your Discord bot.
#    On Modal's Secret creation page, select 'Discord'. Copy your Discord application’s
#    **Public Key** and **Application ID** (from the **General Information** tab in the Discord Developer Portal)
#    and paste them as the value of `DISCORD_PUBLIC_KEY` and `DISCORD_CLIENT_ID`.
#    Additionally, head to the **Bot** tab and use the **Reset Token** button to create a new bot token.
#    Paste this in the value of an additional key in the Secret, `DISCORD_BOT_TOKEN`.
#    Name this Secret `discord-secret`.

# We access that Secret in code like so:

discord_secret = modal.Secret.from_name(
    "discord-secret-2",
    required_keys=[  # included so we get nice error messages if we forgot a key
        "DISCORD_BOT_TOKEN",
        "DISCORD_CLIENT_ID",
        "DISCORD_PUBLIC_KEY",
    ],
)
@app.function(secrets=[discord_secret], image=image)
def create_slash_command(force: bool = False):
    """
    Register the /api slash command with Discord.
    
    Args:
        force (bool): If True, recreate the command even if it already exists
        
    Notes:
        - Creates a single 'api' command with a required 'question' parameter
        - Checks for existing commands to avoid duplicates
        - Requires Discord bot token and client ID from secrets
    """
    import os

    import requests

    BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bot {BOT_TOKEN}",
    }
    url = f"https://discord.com/api/v10/applications/{CLIENT_ID}/commands"

    command_description = {
        "name": "api",
        "description": "Ask ChatGPT a question",
        "options": [
            {
                "name": "question",
                "description": "The question you want to ask",
                "type": 3,  # STRING type
                "required": True
            }
        ]
    }

    # first, check if the command already exists
    response = requests.get(url, headers=headers)
    try:
        response.raise_for_status()
    except Exception as e:
        raise Exception("Failed to create slash command") from e

    commands = response.json()
    command_exists = any(
        command.get("name") == command_description["name"] for command in commands
    )

    # and only recreate it if the force flag is set
    if command_exists and not force:
        print(f"🤖: command {command_description['name']} exists")
        return

    response = requests.post(url, headers=headers, json=command_description)
    try:
        response.raise_for_status()
    except Exception as e:
        raise Exception("Failed to create slash command") from e
    print(f"🤖: command {command_description['name']} created")


@app.function(secrets=[discord_secret], min_containers=1)
@modal.concurrent(max_inputs=1000)
@modal.asgi_app()
def web_app():
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware

    web_app = FastAPI()

    # must allow requests from other domains, e.g. from Discord's servers
    web_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @web_app.post("/api")
    async def get_api(request: Request):
        body = await request.body()

        # confirm this is a request from Discord
        authenticate(request.headers, body)

        print("🤖: parsing request")
        data = json.loads(body.decode())
        if data.get("type") == DiscordInteractionType.PING.value:
            print("🤖: acking PING from Discord during auth check")
            return {"type": DiscordResponseType.PONG.value}

        if data.get("type") == DiscordInteractionType.APPLICATION_COMMAND.value:
            print("🤖: handling slash command")
            app_id = data["application_id"]
            interaction_token = data["token"]
            
            # Extract the question from the command data
            question = data["data"]["options"][0]["value"]

            # kick off request asynchronously, will respond when ready
            reply.spawn(app_id, interaction_token, question)

            # respond immediately with defer message
            return {
                "type": DiscordResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE.value
            }

        print(f"🤖: unable to parse request with type {data.get('type')}")
        raise HTTPException(status_code=400, detail="Bad request")

    return web_app


def authenticate(headers, body):
    """
    Verify that the incoming request is legitimately from Discord.
    
    Args:
        headers: The request headers containing Discord's signature
        body: The raw request body to verify
        
    Raises:
        HTTPException: If the request signature is invalid
        
    Notes:
        - Uses Discord's Ed25519 public key cryptography for verification
        - Required for Discord's security requirements
        - Handles both regular requests and Discord's security checks
    """
    import os

    from fastapi.exceptions import HTTPException
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey

    print("🤖: authenticating request")
    # verify the request is from Discord using their public key
    public_key = os.getenv("DISCORD_PUBLIC_KEY")
    verify_key = VerifyKey(bytes.fromhex(public_key))

    signature = headers.get("X-Signature-Ed25519")
    timestamp = headers.get("X-Signature-Timestamp")

    message = timestamp.encode() + body

    try:
        verify_key.verify(message, bytes.fromhex(signature))
    except BadSignatureError:
        # either an unauthorized request or Discord's "negative control" check
        raise HTTPException(status_code=401, detail="Invalid request")

class DiscordInteractionType(Enum):
    """Enumeration of Discord interaction types we handle."""
    PING = 1  # hello from Discord during auth check
    APPLICATION_COMMAND = 2  # an actual command


class DiscordResponseType(Enum):
    """Enumeration of Discord response types we use."""
    PONG = 1  # hello back during auth check
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5  # we'll send a message later


# ## Deploy on Modal

# You can deploy this app on Modal by running the following commands:

# ``` shell
# modal run discord_bot.py  # checks the API wrapper, little test
# modal run discord_bot.py::create_slash_command  # creates the slash command, if missing
# modal deploy discord_bot.py  # deploys the web app and the API wrapper
# ```

# Copy the Modal URL that is printed in the output and go back to the **General Information** section on the
# [Discord Developer Portal](https://discord.com/developers/applications).
# Paste the URL, making sure to append the path of your `POST` route (here, `/api`), in the
# **Interactions Endpoint URL** field, then click **Save Changes**. If your
# endpoint URL is incorrect or if authentication is incorrectly implemented,
# Discord will refuse to save the URL. Once it saves, you can start
# handling interactions!

# ## Finish setting up Discord bot

# To start using the Slash Command you just set up, you need to invite the bot to
# a Discord server. To do so, go to your application's **Installation** section on the
# [Discord Developer Portal](https://discord.com/developers/applications).
# Copy the **Discored Provided Link** and visit it to invite the bot to your bot to the server.

# Now you can open your Discord server and type `/api` in a channel to trigger the bot.
# You can see a working version [in our test Discord server](https://discord.gg/PmG7P47EPQ).
