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
import sqlite3
import datetime
from enum import Enum

import modal
from vector_emb import answer_question, SYSTEM_PROMPT, COMPLETION_MODEL
from database import log_interaction, init_db, get_db_path

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
    volumes={"/data/db": logs_db_storage}
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
    interaction_id = None
    message_id = None
    try:
        init_db() # Initialize DB within the function context
        message = await fetch_api.local(question)
        print(f"🤖 Got response from ChatGPT: {message[:100]}...")
        
        # Create a payload with the message and feedback buttons
        payload = {
            "content": message,
            "components": [
                {
                    "type": 1,  # Action Row
                    "components": [
                        {
                            "type": 2,  # Button
                            "style": 3,  # Success/Green
                            "custom_id": "feedback_positive",
                            "emoji": {"name": "👍"},
                            "label": "Helpful"
                        },
                        {
                            "type": 2,  # Button
                            "style": 4,  # Danger/Red
                            "custom_id": "feedback_negative",
                            "emoji": {"name": "👎"},
                            "label": "Not Helpful"
                        }
                    ]
                }
            ]
        }
        
        # Send the response to Discord
        import aiohttp
        interaction_url = f"https://discord.com/api/v10/webhooks/{app_id}/{interaction_token}/messages/@original"
        async with aiohttp.ClientSession() as session:
            async with session.patch(interaction_url, json=payload) as resp:
                response_text = await resp.text()
                print("🤖 Discord response: " + response_text)
                
                # Try to extract message_id from the response
                try:
                    response_data = json.loads(response_text)
                    message_id = response_data.get("id")
                    print(f"🤖 Message ID from Discord response: {message_id}")
                except:
                    print("🤖 Could not extract message ID from response")
        
        print("🤖 Successfully sent response with feedback buttons to Discord")
    except Exception as e:
        error_message = f"Sorry, there was an error processing your request: {str(e)}"
        print(f"🤖 Error in reply: {error_message}")
        await send_to_discord({"content": error_message}, app_id, interaction_token)
    finally:
        # Log the interaction in the database
        print("🤖 Logging interaction")
        # Ensure the volume is reloaded if needed for the write operation
        logs_db_storage.reload() 
        interaction_id = log_interaction(
            user_id=interaction_token, # timestamp is handled internally
            channel_id=app_id,
            question=question,
            response=message, # Use the potentially modified message
            feedback=None,
            thread_id=message_id if message_id else interaction_token  # Store message_id in thread_id field
        )
        print(f"🤖 Interaction logged with ID {interaction_id}, associated with message ID: {message_id}")
        # Persist changes made to the volume
        logs_db_storage.commit() 
        return interaction_id


@app.function(
    concurrency_limit=1,
    allow_concurrent_inputs=1000,
    volumes={"/data/db": logs_db_storage}
)
async def handle_feedback(app_id: str, interaction_token: str, feedback_value: str, message_id: str):
    """
    Process feedback from a button interaction and store it in the database.
    
    Args:
        app_id (str): Discord application ID
        interaction_token (str): Token for this specific interaction
        feedback_value (str): The feedback value ("positive" or "negative")
        message_id (str): The message ID that received feedback
    """
    from database import init_db, store_feedback
    import traceback
    
    print(f"🤖 Processing feedback: {feedback_value} for message {message_id}")
    try:
        init_db()
        logs_db_storage.reload()
        
        # Connect to the database
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        print(f"🤖 Using database at path: {get_db_path()}")
        
        # Dump the entire interactions table to debug (limit to 10 rows)
        cursor.execute('SELECT id, user_id, channel_id, thread_id FROM interactions ORDER BY id DESC LIMIT 10')
        all_interactions = cursor.fetchall()
        print(f"🤖 All recent interactions: {all_interactions}")
        
        # Try these different search strategies in order:
        # 1. Look for message_id in thread_id field
        cursor.execute('SELECT id FROM interactions WHERE thread_id = ?', (message_id,))
        result = cursor.fetchone()
        
        if result:
            interaction_id = result[0]
            print(f"🤖 Found interaction by thread_id: {interaction_id}")
        else:
            # 2. Look for interaction_token in user_id field
            cursor.execute('SELECT id FROM interactions WHERE user_id = ?', (interaction_token,))
            result = cursor.fetchone()
            
            if result:
                interaction_id = result[0]
                print(f"🤖 Found interaction by user_id (token): {interaction_id}")
            else:
                # 3. Look for original message_id in user_id field (some implementations store it there)
                cursor.execute('SELECT id FROM interactions WHERE user_id = ?', (message_id,))
                result = cursor.fetchone()
                
                if result:
                    interaction_id = result[0]
                    print(f"🤖 Found interaction by user_id (message): {interaction_id}")
                else:
                    # 4. Fallback to most recent interaction
                    cursor.execute('SELECT id FROM interactions ORDER BY id DESC LIMIT 1')
                    result = cursor.fetchone()
                    
                    if result:
                        interaction_id = result[0]
                        print(f"🤖 Using most recent interaction as fallback: {interaction_id}")
                    else:
                        # 5. If no interactions at all, create a new one
                        print("🤖 No interactions found, creating a new one for the feedback")
                        timestamp = datetime.datetime.now().isoformat()
                        cursor.execute('''
                            INSERT INTO interactions 
                            (timestamp, user_id, channel_id, question, response, feedback, thread_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (timestamp, str(interaction_token), str(app_id), 
                              "Feedback only", "No response - feedback only", 
                              None, str(message_id)))
                        conn.commit()
                        interaction_id = cursor.lastrowid
        
        feedback_text = "👍 Helpful" if feedback_value == "positive" else "👎 Not Helpful"
        
        # Store the feedback both in the database and in temporary storage
        print(f"🤖 Storing feedback '{feedback_text}' for interaction {interaction_id}")
        conn.close()  # Close the connection before calling store_feedback
        
        try:
            # Store feedback using the dedicated function
            store_feedback(interaction_id, feedback_text)
            print(f"🤖 Feedback stored successfully using store_feedback()")
        except Exception as store_error:
            # If store_feedback fails, try direct SQL
            print(f"🤖 Error using store_feedback: {store_error}")
            print(f"🤖 Trying direct SQL update")
            
            direct_conn = sqlite3.connect(get_db_path())
            direct_cursor = direct_conn.cursor()
            direct_cursor.execute(
                'UPDATE interactions SET feedback = ? WHERE id = ?', 
                (feedback_text, interaction_id)
            )
            direct_conn.commit()
            rows_affected = direct_cursor.rowcount
            print(f"🤖 Direct SQL update affected {rows_affected} rows")
            direct_conn.close()
        
        logs_db_storage.commit()
        
        # Verify that feedback was actually stored
        verify_conn = sqlite3.connect(get_db_path())
        verify_cursor = verify_conn.cursor()
        verify_cursor.execute('SELECT feedback FROM interactions WHERE id = ?', (interaction_id,))
        stored_feedback = verify_cursor.fetchone()
        verify_conn.close()
        print(f"🤖 Verification - stored feedback for interaction {interaction_id}: {stored_feedback}")
        
        # Send acknowledgement response to Discord
        acknowledge_message = "Thank you for your feedback!" + (" We're glad the response was helpful." if feedback_value == "positive" else " We'll work on improving our answers.")
        
        await send_to_discord(
            {"type": DiscordResponseType.CHANNEL_MESSAGE_WITH_SOURCE.value, "content": acknowledge_message},
            app_id,
            interaction_token
        )
        
    except Exception as e:
        error_message = f"Error processing feedback: {str(e)}\n{traceback.format_exc()}"
        print(f"🤖 {error_message}")
        await send_to_discord(
            {"type": DiscordResponseType.CHANNEL_MESSAGE_WITH_SOURCE.value, "content": "Sorry, there was an error processing your feedback."},
            app_id,
            interaction_token
        )


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
        
        # Handle button click interactions (for feedback)
        if data.get("type") == DiscordInteractionType.MESSAGE_COMPONENT.value:
            print("🤖: handling button interaction")
            app_id = data["application_id"]
            interaction_token = data["token"]
            custom_id = data["data"]["custom_id"]
            message_id = data["message"]["id"]
            
            if custom_id.startswith("feedback_"):
                feedback_value = custom_id.split("_")[1]  # Extract "positive" or "negative"
                
                # Handle feedback asynchronously
                handle_feedback.spawn(app_id, interaction_token, feedback_value, message_id)
                
                # Acknowledge the button click immediately
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
    MESSAGE_COMPONENT = 3  # button click or select menu interaction


class DiscordResponseType(Enum):
    """Enumeration of Discord response types we use."""
    PONG = 1  # hello back during auth check
    CHANNEL_MESSAGE_WITH_SOURCE = 4  # respond immediately with a message
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5  # we'll send a message later
    UPDATE_MESSAGE = 7  # update an existing message


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
