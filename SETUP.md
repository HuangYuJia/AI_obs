# OBS Virtual Try-On Setup Guide

## Overview

A web application that connects to OBS live streaming software and provides real-time AI virtual try-on using Lucy VTON (Decart) via WebRTC.

## Project Structure

```
test60/
├── server.py           # FastAPI backend with OBS WebSocket integration
├── lucy_api.py         # Lucy REST API client (batch mode)
├── lucy_realtime.py    # Lucy WebRTC real-time client
├── requirements.txt    # Python dependencies
├── .env               # Environment variables
├── start.bat          # Windows startup script
├── static/
│   ├── index.html     # Main HTML page
│   ├── style.css      # Dark theme styles
│   └── app.js         # Frontend JavaScript
├── uploads/           # Temporary uploads
├── clothing/          # Clothing image gallery
└── outputs/           # Generated result images
```

## Quick Start

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Decart API Key

Create or edit `.env` file:

```env
LUCY_API_KEY=dct_your_key_here
```

Get your API key from https://platform.decart.ai

### 3. Configure OBS WebSocket

1. Open OBS Studio
2. Go to **Tools > WebSocket Server Settings**
3. Enable WebSocket server
4. Set port to `4455` (default)
5. Set password (default used by app: `a123456789`)

### 4. Start the Server

```bash
# Windows
start.bat

# Or manually
python server.py
```

### 5. Open the Web Interface

```
http://localhost:8443
```

## Features

### Real-Time Virtual Try-On

Uses Lucy VTON (Decart) via WebRTC for live video processing at 30fps. OBS frames are pushed into the WebRTC stream, processed frames come back in real-time.

### OBS Integration

- Auto-connects to OBS on page load
- Captures live stream frames at ~15 FPS (throttled to ~3 FPS during AI processing)
- Virtual camera output support

### Clothing Gallery

- Left panel with local image management
- Upload via drag-and-drop or file picker
- Click to select, hover to delete
- Supports mid-session clothing switching

### Step-Based UI

- **STEP 1**: Camera confirmation (OBS Virtual Camera)
- **STEP 2**: Mode selection (lucy-vton-3)
- **STEP 3**: Start/Stop try-on session

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LUCY_API_KEY` | (required) | Decart API key (`dct_xxxxx`) |
| `OBS_HOST` | `localhost` | OBS WebSocket host |
| `OBS_PORT` | `4455` | OBS WebSocket port |
| `OBS_PASSWORD` | `""` | OBS WebSocket password |
| `SERVER_PORT` | `8443` | Web server port |
| `HTTP_PROXY` | (none) | HTTP proxy URL |
| `HTTPS_PROXY` | (none) | HTTPS proxy URL |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Get application status |
| POST | `/api/obs/connect` | Connect to OBS WebSocket |
| POST | `/api/obs/disconnect` | Disconnect from OBS |
| GET | `/api/obs/screenshot` | Capture OBS screenshot |
| POST | `/api/clothing/upload` | Upload clothing image |
| GET | `/api/clothing/list` | List clothing images |
| DELETE | `/api/clothing/{filename}` | Delete clothing image |
| GET | `/api/lucy/config` | Get Lucy API config |
| POST | `/api/lucy/process` | Single-frame VTON (REST) |
| GET | `/api/stream` | SSE streaming endpoint |
| WS | `/ws` | WebSocket status updates |
| WS | `/ws/vton` | WebSocket real-time VTON stream |

## WebSocket Protocol (`/ws/vton`)

### Client -> Server

| Type | Description | Payload |
|------|-------------|---------|
| `start` | Begin session | `clothing`, `prompt`, `api_key` |
| `frame` | Push OBS frame | `frame` (base64 JPEG) |
| `update` | Change clothing | `clothing` (path) |
| `stop` | End session | (none) |

### Server -> Client

| Type | Description |
|------|-------------|
| `connected` | Session started |
| `frame` | Processed frame (base64) |
| `error` | Error message |
| `stopped` | Session ended |

## Troubleshooting

### OBS Connection Failed

- Make sure OBS is running
- Check WebSocket is enabled in OBS settings
- Verify the port matches (default: 4455)
- Check password matches

### Real-Time Try-On Not Working

- Verify `LUCY_API_KEY` is set in `.env`
- Check network can reach Decart API
- Ensure clothing image is selected
- Confirm OBS is connected (LIVE indicator is pink)

### High Latency

- Check network quality
- Verify proxy settings if using proxy
- Consider lowering OBS output resolution

## Browser Compatibility

- Chrome 90+
- Firefox 88+
- Edge 90+
- Safari 14+
