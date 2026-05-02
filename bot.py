from pyrogram import Client, filters
from pymongo import MongoClient
import os

@app.on_message(filters.command("start"))
def start(client, message):
    message.reply_text("Hello! 👋\nFile bhejo ya naam search karo 📁")
    
api_id = int(os.getenv("24332123"))
api_hash = os.getenv("abc2e4ec18e92c57c20e246410f8fb38")
bot_token = os.getenv("8654165456:AAFhEm3KFGKchPMK_MFJhMNy3zX_cmLtZQE")
MONGO_URL = os.getenv("mongodb+srv://botuser:Muneerrr%401122@cluster0.jbuj07n.mongodb.net/?appName=Cluster0")

app = Client("my_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

mongo_client = MongoClient(MONGO_URL)
db = mongo_client["telegram_bot"]
collection = db["files"]

@app.on_message(filters.document)
def save_file(client, message):
    file_name = message.document.file_name
    file_id = message.document.file_id

    collection.insert_one({
        "name": file_name,
        "file_id": file_id
    })

    message.reply_text("File save ho gayi ✅")

@app.on_message(filters.text)
def search_file(client, message):
    query = message.text

    result = collection.find_one({
        "name": {"$regex": query, "$options": "i"}
    })

    if result:
        message.reply_document(result["file_id"])
    else:
        message.reply_text("File nahi mili ❌")

print("Bot chal raha hai...")
app.run()
