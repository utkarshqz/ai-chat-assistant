# 🤖 AI Chat Assistant

An intelligent chat interface with real-time streaming, conversation history, and tone control.

## Features
- 💬 **Real-time streaming** — character-by-character AI responses via SSE
- 🎛️ **Tone Toggle** — Professional, Casual, or Concise AI style
- 📁 **Conversation History** — stored in MongoDB, accessible in sidebar
- 🌙 **Dark UI** — modern glassmorphism design

## Tech Stack
- **Backend**: Python + FastAPI
- **AI**: OpenAI GPT-4o-mini (streaming)
- **Database**: MongoDB (pymongo)
- **Frontend**: Vanilla HTML/CSS/JS (single file)

## Setup

### 1. Install dependencies
```bash
pip install fastapi uvicorn "openai>=1.0.0" pymongo python-dotenv
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in your OPENAI_API_KEY and MONGO_URI
```

### 3. Run the server
```bash
uvicorn server:app --reload --port 8000
```

### 4. Open in browser
```
http://localhost:8000
```

## Environment Variables
| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `MONGO_URI` | MongoDB connection string (Atlas or local) |

## API Endpoints
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/chat` | Send message, get streaming response |
| GET | `/api/history` | List all conversations |
| GET | `/api/conversation/{id}` | Get full conversation |
| POST | `/api/conversation/new` | Create new conversation |
