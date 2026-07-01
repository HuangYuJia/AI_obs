# OBS Virtual Try-On Setup Guide

## Overview
A web application that connects to OBS live streaming software, displays the live stream in the browser, and allows drag-and-drop virtual clothing try-on using AI.

## Project Structure
```
test60/
├── server.py           # FastAPI backend with OBS WebSocket integration
├── requirements.txt    # Python dependencies
├── start.bat          # Windows startup script
├── static/
│   ├── index.html     # Main HTML page (3-panel layout)
│   ├── style.css      # Dark theme styles
│   └── app.js         # Frontend JavaScript
├── uploads/           # Uploaded person images
├── outputs/           # Generated result images
└── clothing/          # Uploaded clothing images
```

## Quick Start

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure OBS WebSocket
1. Open OBS Studio
2. Go to **Tools > WebSocket Server Settings**
3. Enable WebSocket server
4. Set port to `4455` (default)
5. Set a password (optional, leave empty for no auth)

### 3. Start the Server
**Windows:**
```bash
start.bat
```

**Or manually:**
```bash
python server.py
```

### 4. Open the Web Interface
Open your browser and go to:
```
http://localhost:8443
```

## Features

### 3-Panel Layout
- **Left Panel**: Search gallery for finding costume/outfit images
- **Center Panel**: OBS live stream preview with AI-generated overlay
- **Right Panel**: Virtual try-on controls

### OBS Integration
- Connect to OBS via WebSocket
- Capture live stream frames
- Display in real-time in the browser
- Virtual camera output control

### Virtual Try-On
- Drag & drop clothing images
- Upload person (full-body) images
- AI-powered clothing swap
- Real-time generation with progress feedback

### UI Features
- Dark theme matching reference design
- Live indicator with pulsing animation
- Timecode display
- Thumbnail grid management
- Prompt input with preset tags
- Mode selection (Try-on, Swap, Generate)

## OBS Setup for Virtual Camera

### Option 1: OBS Virtual Camera
1. In OBS, click **Start Virtual Camera**
2. In the web UI, click **OBS接続** to connect
3. The live stream will appear in the center panel

### Option 2: Browser Source
1. In OBS, add a **Browser Source**
2. Set URL to `http://localhost:8443`
3. Set width/height to match your stream resolution

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main HTML page |
| GET | `/api/status` | Get application status |
| POST | `/api/obs/connect` | Connect to OBS WebSocket |
| POST | `/api/obs/disconnect` | Disconnect from OBS |
| GET | `/api/obs/screenshot` | Capture OBS screenshot |
| POST | `/api/clothing/upload` | Upload clothing image |
| POST | `/api/person/upload` | Upload person image |
| POST | `/api/generate` | Generate virtual try-on |
| POST | `/api/obs/start-virtual-cam` | Start virtual camera |
| POST | `/api/obs/stop-virtual-cam` | Stop virtual camera |
| WS | `/ws` | WebSocket for real-time updates |

## Configuration

### Environment Variables
```bash
OBS_HOST=localhost      # OBS WebSocket host
OBS_PORT=4455          # OBS WebSocket port
OBS_PASSWORD=          # OBS WebSocket password (empty = no auth)
SERVER_PORT=8443       # Web server port
```

### Custom VTON Model
To use a real VTON model (e.g., IDM-VTON, OOTDiffusion):

1. Install the model dependencies:
```bash
pip install torch torchvision diffusers transformers
```

2. Edit `server.py`, in the `VTONProcessor` class:
```python
def load_model(self, model_name="lucy-vton-3"):
    from diffusers import StableDiffusionPipeline
    self.model = StableDiffusionPipeline.from_pretrained("idm-vton/lucy-vton-3")
    self.model.to(self.device)
```

3. Update the `process()` method with actual inference code.

## Troubleshooting

### OBS Connection Failed
- Make sure OBS is running
- Check WebSocket is enabled in OBS settings
- Verify the port matches (default: 4455)
- Check firewall settings

### No Video Stream
- Ensure OBS Virtual Camera is started
- Check the browser console for errors
- Try refreshing the page

### Generation Errors
- Ensure both person and clothing images are uploaded
- Check the server logs for detailed error messages
- Verify the VTON model is properly loaded

## Browser Compatibility
- Chrome 90+
- Firefox 88+
- Edge 90+
- Safari 14+

## Notes
- The left panel (search gallery) is for demonstration only and does not connect to external search APIs
- The AI virtual try-on uses a placeholder implementation by default; replace with actual VTON model for production use
- For best results, use high-resolution full-body person images
