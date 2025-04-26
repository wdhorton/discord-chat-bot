import discord
from discord.ext import commands
import os
from webserver import keep_alive
from database import init_db, log_interaction, store_feedback
from wandb_logger import init_wandb, log_interaction as wandb_log_interaction

from vector_emb import llm_answer_question

# Initialize the database and wandb
init_db()
# --- Determine and Load Transcript File --- 
init_wandb()
# basic qa
###########################################
def discord_setup():
    intents = discord.Intents.default()
    intents.messages = True
    intents.message_content = True

    return discord.Client(intents=intents)

client = discord_setup()

@client.event
async def on_ready():
    # Send the message "hello" only to the general channel
    for guild in client.guilds:
        general_channel = discord.utils.get(guild.text_channels, name='random')
        if general_channel:
            await general_channel.send("Hello! I'm here to assist you with the workshop transcript. Ask me anything by mentioning me (@bot)!")

async def handle_feedback(message, thread_name):
    try:
        interaction_id = int(thread_name.split('-')[1]) if '-' in thread_name else None
        if not interaction_id:
            return
            
        feedback = message.content
        store_feedback(interaction_id, feedback)
        
        # Get the original bot response from the thread
        original_response = None
        async for msg in message.channel.history(limit=10):
            if msg.author == client.user and not msg.content.startswith(("Was this response helpful?", "Thank you for your feedback!")):
                original_response = msg.content
                break
        
        # Update W&B with feedback
        wandb_log_interaction(
            message.author.id,
            message.channel.id,
            "",  # No need to include question for feedback
            original_response,  # Include the original response
            message.channel.id,
            feedback
        )
        await message.channel.send("Thank you for your feedback!")
        await message.channel.edit(archived=True)
        return True
    except Exception as e:
        print(f"Error storing feedback: {e}")
        return False

async def create_and_handle_thread(message, question):
    try:
        thread = await message.create_thread(
            name=f"q-{message.id}",
            auto_archive_duration=60
        )
        
        async with thread.typing():
            #workshop_context = get_context(context_file)
            response =  llm_answer_question(question)
            await thread.send(response)
            
            # Log interaction to both database and wandb
            interaction_id = log_interaction(
                message.author.id,
                message.channel.id,
                question,
                response,
                thread.id
            )
            
            wandb_log_interaction(
                message.author.id,
                message.channel.id,
                question,
                response,
                thread.id
            )
            
            await thread.edit(name=f"question-{interaction_id}")
            await thread.send("Was this response helpful? (Please reply with Yes/No and optionally add more details)")
            
    except Exception as e:
        await message.channel.send(f"Error: {str(e)}")

def is_bot_mentioned(message, client):
    return client.user.mention in message.content

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # Check if it's a feedback response in a thread
    if isinstance(message.channel, discord.Thread) and message.channel.owner_id == client.user.id:
        feedback_handled = await handle_feedback(message, message.channel.name)
        if feedback_handled:
            return

    # Bot is mentioned or called
    if is_bot_mentioned(message, client):
        await create_and_handle_thread(message, message.content)

def run_discord_bot():
    discord_token = os.environ["DISCORD_BOT_TOKEN_HUGO"]
    if not discord_token:
        raise ValueError("DISCORD_TOKEN environment variable not set")
    print("Starting Discord bot...")
    client.run(discord_token)

if __name__ == "__main__":
    init_wandb()
    # Retrieve the token from the environment variable populated by the Modal secret
    keep_alive()  # Start the Flask server
    run_discord_bot()

