from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from dotenv import load_dotenv
import os, json, uuid

load_dotenv()

app = FastAPI(title="AI Chat Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── OpenAI client (v1+) ───────────────────────────────────────
from openai import OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── MongoDB (optional fallback to in-memory) ─────────────────
MONGO_URI = os.getenv("MONGO_URI", "")
db_mode = "memory"
conversations_col = None
in_memory_store = {}   # fallback: { id: {title, messages, tone, created_at, updated_at} }

if MONGO_URI and "placeholder" not in MONGO_URI:
    try:
        from pymongo import MongoClient
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        mongo_client.admin.command("ping")
        db = mongo_client["ai_chat"]
        conversations_col = db["conversations"]
        db_mode = "mongo"
        print("[OK] MongoDB connected")
    except Exception as e:
        print(f"[WARN] MongoDB unavailable ({e}), using in-memory store")
else:
    print("[WARN] No valid MONGO_URI - using in-memory store (history won't persist across restarts)")

# ── Tone instructions ─────────────────────────────────────────
TONE_INSTRUCTIONS = {
    "professional": "You are a formal, professional AI assistant. Use structured, precise, and polished language. Avoid slang or casual expressions.",
    "casual":       "You are a friendly, casual AI assistant. Be conversational, warm, and relaxed. Use everyday language and feel free to use light humor.",
    "concise":      "You are a concise AI assistant. Keep ALL responses under 3 sentences. Be direct and to the point. No fluff.",
}

# ── Models ────────────────────────────────────────────────────
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    tone: str = "professional"
    history: Optional[List[Message]] = []

class NewConversationRequest(BaseModel):
    title: Optional[str] = "New Conversation"

# ── DB helpers ────────────────────────────────────────────────
def db_insert_conversation(doc: dict) -> str:
    if db_mode == "mongo":
        from bson import ObjectId
        result = conversations_col.insert_one(doc)
        return str(result.inserted_id)
    else:
        cid = str(uuid.uuid4())
        in_memory_store[cid] = {**doc, "_id": cid}
        return cid

def db_get_conversation(cid: str) -> Optional[dict]:
    if db_mode == "mongo":
        from bson import ObjectId
        try:
            doc = conversations_col.find_one({"_id": ObjectId(cid)})
            if doc:
                doc["_id"] = str(doc["_id"])
                for k in ("created_at", "updated_at"):
                    if k in doc and hasattr(doc[k], "isoformat"):
                        doc[k] = doc[k].isoformat()
            return doc
        except Exception:
            return None
    else:
        return in_memory_store.get(cid)

def db_update_conversation(cid: str, push_msgs: list, tone: str):
    if db_mode == "mongo":
        from bson import ObjectId
        try:
            conversations_col.update_one(
                {"_id": ObjectId(cid)},
                {
                    "$push": {"messages": {"$each": push_msgs}},
                    "$set": {"tone": tone, "updated_at": datetime.now(timezone.utc)},
                }
            )
        except Exception as e:
            print("Mongo update error:", e)
    else:
        if cid in in_memory_store:
            in_memory_store[cid]["messages"].extend(push_msgs)
            in_memory_store[cid]["tone"] = tone
            in_memory_store[cid]["updated_at"] = datetime.now(timezone.utc).isoformat()

def db_list_conversations(limit=30) -> list:
    if db_mode == "mongo":
        docs = list(
            conversations_col
            .find({}, {"_id": 1, "title": 1, "updated_at": 1})
            .sort("updated_at", -1)
            .limit(limit)
        )
        for d in docs:
            d["_id"] = str(d["_id"])
            if "updated_at" in d and hasattr(d["updated_at"], "isoformat"):
                d["updated_at"] = d["updated_at"].isoformat()
        return docs
    else:
        docs = [
            {"_id": k, "title": v.get("title", "Conversation"), "updated_at": v.get("updated_at", "")}
            for k, v in in_memory_store.items()
        ]
        docs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return docs[:limit]

# ── Routes ────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("public/index.html")

@app.post("/api/conversation/new")
def new_conversation(req: NewConversationRequest):
    now = datetime.now(timezone.utc).isoformat()
    doc = {"title": req.title, "messages": [], "tone": "professional", "created_at": now, "updated_at": now}
    cid = db_insert_conversation(doc)
    return {"conversation_id": cid, "title": req.title}

@app.get("/api/history")
def get_history():
    return db_list_conversations()

@app.get("/api/conversation/{conv_id}")
def get_conversation(conv_id: str):
    doc = db_get_conversation(conv_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc

@app.post("/api/chat")
def chat(req: ChatRequest):
    tone_instruction = TONE_INSTRUCTIONS.get(req.tone.lower(), TONE_INSTRUCTIONS["professional"])

    messages_for_api = [{"role": "system", "content": tone_instruction}]
    for m in (req.history or []):
        messages_for_api.append({"role": m.role, "content": m.content})
    messages_for_api.append({"role": "user", "content": req.message})

    def stream_generator():
        full_response = ""
        try:
            stream = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages_for_api,
                stream=True,
                max_tokens=1024,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_response += delta
                    yield f"data: {json.dumps({'delta': delta})}\n\n"

            # Persist to DB
            now_iso = datetime.now(timezone.utc).isoformat()
            user_msg = {"role": "user",      "content": req.message,    "timestamp": now_iso}
            ai_msg   = {"role": "assistant", "content": full_response,  "timestamp": now_iso}

            conv_id = req.conversation_id
            if conv_id and db_get_conversation(conv_id):
                db_update_conversation(conv_id, [user_msg, ai_msg], req.tone)
            else:
                title = req.message[:50] + ("..." if len(req.message) > 50 else "")
                doc = {
                    "title": title,
                    "messages": [user_msg, ai_msg],
                    "tone": req.tone,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
                conv_id = db_insert_conversation(doc)

            yield f"data: {json.dumps({'done': True, 'conversation_id': str(conv_id)})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


# Serve static files last
app.mount("/static", StaticFiles(directory="public"), name="static")
