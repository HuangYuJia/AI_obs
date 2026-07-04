/**
 * OBS Virtual Try-On - Frontend Application
 * Handles OBS connection, drag-drop, image processing, and UI interactions.
 */

// ──────────────────────────────────────────────
// State & Configuration
// ──────────────────────────────────────────────
const state = {
    obsConnected: false,
    isLive: false,
    isGenerating: false,
    currentMode: 'vton',
    currentClothing: null,
    currentReferenceImage: null,
    ws: null,
    vtonWs: null,  // Lucy VTON real-time WebSocket
    obsPassword: localStorage.getItem('obsPassword') || 'a123456789',
};

const CONFIG = {
    WS_URL: `ws://${window.location.host}/ws`,
    VTON_WS_URL: `ws://${window.location.host}/ws/vton`,
    API_BASE: '',
};

// ──────────────────────────────────────────────
// DOM Elements
// ──────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const elements = {
    // Top bar
    liveIndicator: $('#liveIndicator'),

    // Left panel - image gallery
    imageGrid: $('#imageGrid'),
    btnAddLocal: $('#btnAddLocal'),
    localFileInput: $('#localFileInput'),

    // Center panel
    mainPreview: $('#mainPreview'),
    obsVideo: $('#obsVideo'),
    obsCanvas: $('#obsCanvas'),
    previewPlaceholder: $('#previewPlaceholder'),
    aiBadge: $('#aiBadge'),
    generatedOverlay: $('#generatedOverlay'),
    bottomPreviewImg: $('#bottomPreviewImg'),

    // Right panel - clothing
    clothingSection: $('#clothingSection'),
    clothingDropArea: $('#clothingDropArea'),
    clothingDropContent: $('#clothingDropContent'),
    clothingPreview: $('#clothingPreview'),
    clothingPreviewImg: $('#clothingPreviewImg'),
    clothingFileInput: $('#clothingFileInput'),
    btnClearClothing: $('#btnClearClothing'),

    // Right panel - reference image (transform mode)
    referenceSection: $('#referenceSection'),
    referenceDropArea: $('#referenceDropArea'),
    referenceDropContent: $('#referenceDropContent'),
    referencePreview: $('#referencePreview'),
    referencePreviewImg: $('#referencePreviewImg'),
    referenceFileInput: $('#referenceFileInput'),
    btnClearReference: $('#btnClearReference'),

    // Mode selector
    modeSelect: $('#modeSelect'),

    // Right panel - controls
    promptInput: $('#promptInput'),
    btnStart: $('#btnStart'),
    btnStop: $('#btnStop'),

    // Overlays
    toastContainer: $('#toastContainer'),
    loadingOverlay: $('#loadingOverlay'),
};

// ──────────────────────────────────────────────
// Toast Notifications
// ──────────────────────────────────────────────
function showToast(message, type = 'info', duration = 3000) {
    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        info: 'fas fa-info-circle',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `<i class="${icons[type]}"></i><span>${message}</span>`;
    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toast-out 0.3s ease-in forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ──────────────────────────────────────────────
// Loading Overlay
// ──────────────────────────────────────────────
function showLoading(message = 'AI生成中...') {
    elements.loadingOverlay.querySelector('p').textContent = message;
    elements.loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    elements.loadingOverlay.style.display = 'none';
}

// ──────────────────────────────────────────────
// WebSocket Connection
// ──────────────────────────────────────────────
function connectWebSocket() {
    try {
        state.ws = new WebSocket(CONFIG.WS_URL);

        state.ws.onopen = () => {
            console.log('WebSocket connected');
            showToast('已连接到服务器', 'success');
        };

        state.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            handleWSMessage(message);
        };

        state.ws.onclose = () => {
            console.log('WebSocket disconnected');
            setTimeout(connectWebSocket, 3000);
        };

        state.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    } catch (e) {
        console.error('Failed to connect WebSocket:', e);
        setTimeout(connectWebSocket, 3000);
    }
}

function handleWSMessage(message) {
    const { type, data } = message;

    switch (type) {
        case 'status':
            updateStatus(data);
            break;
        case 'obs_status':
            updateOBSStatus(data.connected);
            break;
        case 'live_status':
            updateLiveStatus(data.is_live);
            break;
        case 'clothing_updated':
            showToast('服装图片已更新', 'success');
            break;
        case 'generation_started':
            // Loading is handled by startGeneration function
            break;
        case 'generation_complete':
            hideLoading();
            showGeneratedImage(data.image);
            showToast('AI换装完成', 'success');
            break;
        case 'generation_error':
            hideLoading();
            showToast(`生成错误: ${data.error}`, 'error');
            break;
    }
}

function updateStatus(data) {
    updateOBSStatus(data.obs_connected);
    updateLiveStatus(data.is_live);
}

function updateOBSStatus(connected) {
    state.obsConnected = connected;
    elements.liveIndicator.classList.toggle('connected', connected);

    if (connected) {
        elements.previewPlaceholder.innerHTML = `
            <i class="fas fa-tv"></i>
            <p>OBS 直播画面已连接</p>
            <p class="small">正在获取画面...</p>
        `;
    } else {
        // Reset placeholder when disconnected
        elements.previewPlaceholder.innerHTML = `
            <i class="fas fa-tv"></i>
            <p>OBS直播画面将显示在这里</p>
            <p class="small">请连接OBS</p>
        `;
        elements.previewPlaceholder.style.display = 'flex';
        elements.obsCanvas.style.display = 'none';

        // Clear bottom preview
        elements.bottomPreviewImg.style.display = 'none';
        elements.bottomPreviewImg.src = '';
        const bottomPlaceholder = document.querySelector('.bottom-preview__placeholder');
        if (bottomPlaceholder) bottomPlaceholder.style.display = 'flex';

        // Clear AI generated overlay and badge
        if (elements.generatedOverlay) {
            elements.generatedOverlay.style.display = 'none';
            elements.generatedOverlay.src = '';
        }
        if (elements.aiBadge) {
            elements.aiBadge.style.display = 'none';
        }
    }

    // Update start button state
    updateStartButton();
}

function updateLiveStatus(isLive) {
    state.isLive = isLive;
    // LIVE is bright when either virtual camera is running OR OBS is connected
    const shouldShow = isLive || state.obsConnected;
    if (shouldShow) {
        elements.liveIndicator.classList.add('connected');
    } else {
        elements.liveIndicator.classList.remove('connected');
    }
}

// ──────────────────────────────────────────────
// OBS Connection
// ──────────────────────────────────────────────
async function connectOBS() {
    const password = state.obsPassword || 'a123456789';

    try {
        const response = await fetch(`/api/obs/connect?password=${encodeURIComponent(password)}`, {
            method: 'POST'
        });

        if (response.ok) {
            showToast('已连接OBS', 'success');
            updateOBSStatus(true);
            updateLiveStatus(true);
            startOBSStream();
            // Save password for auto-reconnect
            localStorage.setItem('obsPassword', password);
            state.obsPassword = password;
        } else {
            const error = await response.json().catch(() => ({}));
            showToast('OBS连接失败: ' + (error.detail || '请确认密码'), 'error');
        }
    } catch (e) {
        showToast('OBS连接错误: ' + e.message, 'error');
    }
}

async function disconnectOBS() {
    try {
        await fetch('/api/obs/disconnect', { method: 'POST' });
        stopOBSStream();
        updateOBSStatus(false);
        updateLiveStatus(false);
        // Clear saved password
        localStorage.removeItem('obsPassword');
        state.obsPassword = '';
        showToast('已断开OBS', 'info');
    } catch (e) {
        showToast('断开错误: ' + e.message, 'error');
    }
}

// ──────────────────────────────────────────────
// OBS Stream Capture
// ──────────────────────────────────────────────
let streamInterval = null;
let isOBSRendering = false;
let isRealTimeTryOn = false;
let lastClothingPath = null;
let frameCount = 0; // Track frame count for throttling

function startOBSStream() {
    if (streamInterval) return;
    isOBSRendering = true;
    frameCount = 0;

    // Use canvas to render frames
    const canvas = elements.obsCanvas;
    const ctx = canvas.getContext('2d');
    let isFetching = false;
    let lastFrameTime = 0;
    const targetFPS = 15; // Target 15 FPS
    const frameInterval = 1000 / targetFPS;

    function fetchFrame() {
        if (!isOBSRendering || !state.obsConnected) {
            stopOBSStream();
            return;
        }

        const now = Date.now();
        const elapsed = now - lastFrameTime;

        // Throttle to target FPS
        if (elapsed < frameInterval || isFetching) {
            requestAnimationFrame(fetchFrame);
            return;
        }

        // Reduce FPS during AI processing
        if (tryOnProcessing && frameCount % 5 !== 0) {
            frameCount++;
            requestAnimationFrame(fetchFrame);
            return;
        }

        isFetching = true;
        lastFrameTime = now;
        frameCount++;

        fetch('/api/obs/screenshot')
            .then(response => {
                if (response.ok) return response.json();
                throw new Error('Failed');
            })
            .then(data => {
                if (data.image && isOBSRendering) {
                    renderFrame(data.image);
                }
            })
            .catch(() => {})
            .finally(() => {
                isFetching = false;
                requestAnimationFrame(fetchFrame);
            });
    }

    // Start the frame loop
    requestAnimationFrame(fetchFrame);
}

function stopOBSStream() {
    isOBSRendering = false; // Stop rendering immediately

    // Clear main canvas and show placeholder
    const canvas = elements.obsCanvas;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    canvas.style.display = 'none';
    elements.previewPlaceholder.style.display = 'flex';
    elements.previewPlaceholder.innerHTML = `
        <i class="fas fa-tv"></i>
        <p>OBS直播画面将显示在这里</p>
        <p class="small">请连接OBS</p>
    `;

    // Clear bottom preview image
    elements.bottomPreviewImg.style.display = 'none';
    elements.bottomPreviewImg.src = '';
    const bottomPlaceholder = document.querySelector('.bottom-preview__placeholder');
    if (bottomPlaceholder) bottomPlaceholder.style.display = 'flex';

    // Clear AI generated overlay and badge
    if (elements.generatedOverlay) {
        elements.generatedOverlay.style.display = 'none';
        elements.generatedOverlay.src = '';
    }
    if (elements.aiBadge) {
        elements.aiBadge.style.display = 'none';
    }
}

function renderFrame(base64Image) {
    // Don't render if OBS is disconnected
    if (!isOBSRendering) return;

    const img = new Image();
    img.onload = () => {
        // Check again after image loaded
        if (!isOBSRendering) return;

        // Side preview: always show original OBS feed
        elements.bottomPreviewImg.src = `data:image/jpeg;base64,${base64Image}`;
        elements.bottomPreviewImg.style.display = 'block';
        const bottomPlaceholder2 = document.querySelector('.bottom-preview__placeholder');
        if (bottomPlaceholder2) bottomPlaceholder2.style.display = 'none';

        // Always show OBS feed in main canvas (background)
        elements.previewPlaceholder.style.display = 'none';
        elements.obsCanvas.style.display = 'block';
        const canvas = elements.obsCanvas;
        const ctx = canvas.getContext('2d');
        canvas.width = img.width;
        canvas.height = img.height;
        ctx.drawImage(img, 0, 0);

        // If real-time try-on is active, send frame for AI processing
        if (isRealTimeTryOn && state.currentClothing) {
            applyRealTimeTryOn(base64Image);
        }
    };
    img.src = `data:image/jpeg;base64,${base64Image}`;
}

// ──────────────────────────────────────────────
// Real-Time Try-On Processing
// ──────────────────────────────────────────────
let tryOnProcessing = false;
let isSwitchingState = false;
let lastProcessedClothing = null;
let vtonWsConnected = false;
let isTransformProcessing = false;

function connectVTONWebSocket() {
    // Prevent duplicate connections
    if (state.vtonWs && (state.vtonWs.readyState === WebSocket.OPEN || state.vtonWs.readyState === WebSocket.CONNECTING)) {
        console.log('[VTON] Already connected or connecting');
        return;
    }

    const wsUrl = CONFIG.VTON_WS_URL;
    console.log('[VTON] Connecting to', wsUrl);
    state.vtonWs = new WebSocket(wsUrl);

    state.vtonWs.onopen = () => {
        console.log('[VTON] WebSocket connected');
        // Send start message with clothing info and API key
        const userPrompt = elements.promptInput ? elements.promptInput.value.trim() : '';
        const prompt = userPrompt || 'try on';
        const apiKey = document.getElementById('decartApiKey') ? document.getElementById('decartApiKey').value : '';
        state.vtonWs.send(JSON.stringify({
            type: 'start',
            clothing: state.currentClothing,
            prompt: prompt,
            api_key: apiKey,
        }));
    };

    state.vtonWs.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleVTONMessage(data);
        } catch (e) {
            console.error('[VTON] Parse error:', e);
        }
    };

    state.vtonWs.onerror = (e) => {
        console.error('[VTON] WebSocket error:', e);
        vtonWsConnected = false;
        elements.aiBadge.textContent = 'AI 连接错误';
        elements.aiBadge.style.display = 'block';
    };

    state.vtonWs.onclose = () => {
        console.log('[VTON] WebSocket closed');
        vtonWsConnected = false;
        state.vtonWs = null;
    };
}

function handleVTONMessage(data) {
    switch (data.type) {
        case 'connected':
            console.log('[VTON] Session started:', data.message);
            vtonWsConnected = true;
            elements.aiBadge.textContent = 'AI 实时换装已连接';
            elements.aiBadge.style.display = 'block';
            break;
        case 'frame':
            // Received processed frame from Lucy VTON
            if (data.image) {
                // Restore canvas on first frame
                if (elements.previewPlaceholder.style.display !== 'none') {
                    elements.previewPlaceholder.style.display = 'none';
                    elements.obsCanvas.style.display = 'block';
                }
                elements.generatedOverlay.src = `data:image/jpeg;base64,${data.image}`;
                elements.generatedOverlay.style.display = 'block';
                elements.aiBadge.textContent = 'AI 实时换装中';
                elements.aiBadge.style.display = 'block';
                tryOnProcessing = false;
            }
            break;
        case 'updated':
            console.log('[VTON] Clothing updated:', data.message);
            break;
        case 'disconnected':
            console.log('[VTON] Session ended:', data.message);
            vtonWsConnected = false;
            break;
        case 'error':
            console.error('[VTON] Error:', data.message);
            vtonWsConnected = false;
            elements.aiBadge.textContent = 'AI 错误: ' + (data.message || '');
            elements.aiBadge.style.display = 'block';
            break;
    }
}

function disconnectVTONWebSocket() {
    if (state.vtonWs) {
        try {
            if (state.vtonWs.readyState === WebSocket.OPEN) {
                state.vtonWs.send(JSON.stringify({ type: 'stop' }));
            }
            state.vtonWs.close();
        } catch (e) {
            console.error('[VTON] Error closing WebSocket:', e);
        }
        state.vtonWs = null;
        vtonWsConnected = false;
    }
}

async function applyRealTimeTryOn(base64Frame) {
    if (!state.currentClothing) {
        return;
    }

    // Send frame via WebSocket if connected
    if (state.vtonWs && state.vtonWs.readyState === WebSocket.OPEN && vtonWsConnected) {
        state.vtonWs.send(JSON.stringify({
            type: 'frame',
            image: base64Frame,
        }));
    }
}

// ──────────────────────────────────────────────
// Generated Image Display
// ──────────────────────────────────────────────
function showGeneratedImage(base64Image) {
    // Save current OBS frame to bottom preview (original)
    const canvas = elements.obsCanvas;
    if (canvas.style.display !== 'none') {
        elements.bottomPreviewImg.src = canvas.toDataURL('image/png');
        elements.bottomPreviewImg.style.display = 'block';
    }

    // Show AI generated image in main preview
    elements.generatedOverlay.src = `data:image/png;base64,${base64Image}`;
    elements.generatedOverlay.style.display = 'block';
    elements.aiBadge.style.display = 'block';
    elements.previewPlaceholder.style.display = 'none';
}

// ──────────────────────────────────────────────
// Transform Mode (lucy-2.1 REST API)
// ──────────────────────────────────────────────
async function startTransformLoop() {
    if (!isTransformProcessing) return;

    if (elements.aiBadge) {
        elements.aiBadge.textContent = 'AI 人物变换中...';
        elements.aiBadge.style.display = 'block';
    }

    while (isTransformProcessing) {
        try {
            // Capture current OBS frame
            const canvas = elements.obsCanvas;
            if (canvas.width === 0 || canvas.height === 0) {
                await new Promise(r => setTimeout(r, 1000));
                continue;
            }

            const frameBase64 = canvas.toDataURL('image/jpeg', 0.7).split(',')[1];

            // Show processing state
            if (elements.aiBadge) {
                elements.aiBadge.textContent = 'AI 处理中...';
            }

            const prompt = elements.promptInput ? elements.promptInput.value.trim() : '';
            const response = await fetch('/api/lucy/process', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    frame: frameBase64,
                    clothing: state.currentReferenceImage,
                    prompt: prompt || 'Transform the person to match the reference image',
                }),
            });

            if (!isTransformProcessing) break;

            if (response.ok) {
                const data = await response.json();
                if (data.image) {
                    showGeneratedImage(data.image);
                    if (elements.aiBadge) {
                        elements.aiBadge.textContent = 'AI 人物变换';
                    }
                } else if (data.error) {
                    console.error('[Transform] Error:', data.error);
                    if (elements.aiBadge) {
                        elements.aiBadge.textContent = 'AI 处理错误';
                    }
                }
            } else {
                console.error('[Transform] HTTP error:', response.status);
                if (elements.aiBadge) {
                    elements.aiBadge.textContent = 'AI 请求错误';
                }
            }
        } catch (e) {
            if (!isTransformProcessing) break;
            console.error('[Transform] Error:', e);
            if (elements.aiBadge) {
                elements.aiBadge.textContent = 'AI 连接错误';
            }
        }

        // Wait before next frame (avoid overloading the API)
        if (isTransformProcessing) {
            await new Promise(r => setTimeout(r, 2000));
        }
    }
}

// ──────────────────────────────────────────────
// Clothing Drag & Drop
// ──────────────────────────────────────────────
function initClothingDragDrop() {
    const area = elements.clothingDropArea;
    const fileInput = elements.clothingFileInput;

    // Click to upload
    area.addEventListener('click', (e) => {
        if (e.target.closest('.btn--danger')) return;
        fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleClothingFile(e.target.files[0]);
        }
    });

    // Drag events
    area.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        area.classList.add('dragover');
    });

    area.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        area.classList.remove('dragover');
    });

    area.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        area.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleClothingFile(files[0]);
        }
    });

    // Clear button
    elements.btnClearClothing.addEventListener('click', (e) => {
        e.stopPropagation();
        clearClothing();
    });
}

async function handleClothingFile(file) {
    if (!file.type.startsWith('image/')) {
        showToast('请选择图片文件', 'error');
        return;
    }

    // Show preview
    const reader = new FileReader();
    reader.onload = (e) => {
        elements.clothingPreviewImg.src = e.target.result;
        elements.clothingDropContent.style.display = 'none';
        elements.clothingPreview.style.display = 'flex';
    };
    reader.readAsDataURL(file);

    // Upload to server
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/person/upload', {
            method: 'POST',
            body: formData,
        });

        if (response.ok) {
            const data = await response.json();
            state.currentClothing = data.path;
            lastClothingPath = null; // Reset to force refresh
            tryOnProcessing = false; // Reset processing flag
            showToast('服装图片已上传', 'success');
            updateStartButton();

            // Update VTON session if actively connected
            if (state.vtonWs && state.vtonWs.readyState === WebSocket.OPEN && vtonWsConnected) {
                state.vtonWs.send(JSON.stringify({
                    type: 'update',
                    clothing: data.path,
                }));
            }
        } else {
            showToast('上传失败', 'error');
        }
    } catch (e) {
        showToast('上传错误: ' + e.message, 'error');
    }
}

function clearClothing() {
    state.currentClothing = null;
    elements.clothingDropContent.style.display = '';
    elements.clothingPreview.style.display = 'none';
    elements.clothingPreviewImg.src = '';
    elements.clothingFileInput.value = '';
    updateStartButton();
}

// ──────────────────────────────────────────────
// Reference Image Drag & Drop (Transform Mode)
// ──────────────────────────────────────────────
function initReferenceDragDrop() {
    const area = elements.referenceDropArea;
    const fileInput = elements.referenceFileInput;
    if (!area || !fileInput) return;

    area.addEventListener('click', (e) => {
        if (e.target.closest('.btn--danger')) return;
        fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleReferenceFile(e.target.files[0]);
        }
    });

    area.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        area.classList.add('dragover');
    });

    area.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        area.classList.remove('dragover');
    });

    area.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        area.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleReferenceFile(files[0]);
        }
    });

    elements.btnClearReference.addEventListener('click', (e) => {
        e.stopPropagation();
        clearReference();
    });
}

async function handleReferenceFile(file) {
    if (!file.type.startsWith('image/')) {
        showToast('请选择图片文件', 'error');
        return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        elements.referencePreviewImg.src = e.target.result;
        elements.referenceDropContent.style.display = 'none';
        elements.referencePreview.style.display = 'flex';
    };
    reader.readAsDataURL(file);

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/person/upload', {
            method: 'POST',
            body: formData,
        });

        if (response.ok) {
            const data = await response.json();
            state.currentReferenceImage = data.path;
            showToast('参照画像をアップロードしました', 'success');
            updateStartButton();
        } else {
            showToast('上传失败', 'error');
        }
    } catch (e) {
        showToast('上传错误: ' + e.message, 'error');
    }
}

function clearReference() {
    state.currentReferenceImage = null;
    elements.referenceDropContent.style.display = '';
    elements.referencePreview.style.display = 'none';
    elements.referencePreviewImg.src = '';
    elements.referenceFileInput.value = '';
    updateStartButton();
}

// ──────────────────────────────────────────────
// Search Image Drag to Clothing
// ──────────────────────────────────────────────

async function handleClothingUrl(url) {
    try {
        // Fetch image and convert to file
        const response = await fetch(url);
        const blob = await response.blob();
        const file = new File([blob], 'clothing.jpg', { type: 'image/jpeg' });
        handleClothingFile(file);
    } catch (e) {
        showToast('图片获取失败', 'error');
    }
}

// ──────────────────────────────────────────────
// Mode Selection
// ──────────────────────────────────────────────
function initModeSelection() {
    const select = elements.modeSelect;
    if (!select) return;

    select.addEventListener('change', () => {
        state.currentMode = select.value;
        switchMode(state.currentMode);
    });

    state.currentMode = select.value || 'vton';
}

function switchMode(mode) {
    const isVton = mode === 'vton';
    const isTransform = mode === 'transform';

    // Toggle sections
    if (elements.clothingSection) elements.clothingSection.style.display = isVton ? '' : 'none';
    if (elements.referenceSection) elements.referenceSection.style.display = isTransform ? '' : 'none';

    // Toggle hints
    $$('.mode-hint-vton').forEach(el => el.style.display = isVton ? '' : 'none');
    $$('.mode-hint-transform').forEach(el => el.style.display = isTransform ? '' : 'none');

    // Update label
    const modeLabel = document.getElementById('modeLabel');
    if (modeLabel) modeLabel.textContent = '变换模式';

    updateStartButton();
}

// ──────────────────────────────────────────────
// Prompt Tags
// ──────────────────────────────────────────────
function initPromptTags() {
    $$('.prompt-tag').forEach(tag => {
        tag.addEventListener('click', () => {
            tag.classList.toggle('active');

            // Build prompt from active tags
            const activeTags = $$('.prompt-tag.active');
            if (activeTags.length > 0) {
                const tags = Array.from(activeTags).map(t => t.dataset.prompt);
                const currentPrompt = elements.promptInput.value;

                // Add tag to prompt if not already present
                tags.forEach(t => {
                    if (!currentPrompt.includes(t)) {
                        elements.promptInput.value = currentPrompt
                            ? `${currentPrompt}, ${t}`
                            : t;
                    }
                });
            }
        });
    });
}

// ──────────────────────────────────────────────
// Image Search & Gallery
// ──────────────────────────────────────────────
let localImages = []; // Track locally added images

function renderImageGrid() {
    const grid = elements.imageGrid;
    grid.innerHTML = '';
    localImages.forEach(img => {
        grid.appendChild(createImageCard(img.url, img.title, img.source, true));
    });
}

function createImageCard(src, title, source, isLocal = false) {
    const div = document.createElement('div');
    div.className = 'image-card';
    div.draggable = true;
    div.dataset.src = src;
    div.dataset.local = isLocal;

    div.innerHTML = `
        <img src="${src}" alt="${title}" loading="lazy">
        ${isLocal ? '<button class="image-card__delete" title="删除"><i class="fas fa-times"></i></button>' : ''}
    `;

    // Drag start
    div.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', src);
        e.dataTransfer.setData('application/x-image-url', src);
    });

    // Click to select as clothing
    div.addEventListener('click', (e) => {
        if (e.target.closest('.image-card__delete')) return;
        handleClothingUrl(src);
    });

    // Delete button for local images
    if (isLocal) {
        div.querySelector('.image-card__delete').addEventListener('click', (e) => {
            e.stopPropagation();
            if (!confirm('确定要删除这张图片吗？')) return;

            // Extract filename from src URL
            const filename = src.split('/').pop();
            fetch(`/api/clothing/${filename}`, { method: 'DELETE' })
                .then(res => {
                    if (res.ok) {
                        localImages = localImages.filter(img => img.url !== src);
                        div.remove();
                        showToast('图片已删除', 'success');
                    } else {
                        showToast('删除失败', 'error');
                    }
                })
                .catch(() => showToast('删除失败', 'error'));
        });
    }

    return div;
}

function addLocalImages(files) {
    Array.from(files).forEach(async (file) => {
        if (!file.type.startsWith('image/')) return;

        // Upload to clothing directory
        const formData = new FormData();
        formData.append('file', file);
        try {
            const response = await fetch('/api/clothing/upload', {
                method: 'POST',
                body: formData,
            });
            if (response.ok) {
                const data = await response.json();
                const src = `/api/image/clothing/${data.filename}`;
                const title = file.name.replace(/\.[^/.]+$/, '');
                localImages.push({ url: src, title: title, source: '本地' });
                renderImageGrid();
                showToast('图片已添加到图库', 'success');
            }
        } catch (e) {
            console.error('Upload error:', e);
        }
    });
}

function initImageGallery() {
    // Add local button
    elements.btnAddLocal.addEventListener('click', () => {
        elements.localFileInput.click();
    });

    // Local file input
    elements.localFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            addLocalImages(e.target.files);
            e.target.value = '';
        }
    });

    // Load local clothing
    loadLocalClothing();
}

async function loadLocalClothing() {
    try {
        const response = await fetch('/api/clothing/list');
        const data = await response.json();
        if (data.clothing && data.clothing.length > 0) {
            data.clothing.forEach(item => {
                const src = `/api/image/clothing/${item.filename}`;
                const title = item.filename.replace(/\.[^.]+$/, '');
                localImages.push({ url: src, title: title, source: '本地' });
            });
            renderImageGrid();
        }
    } catch (e) {
        console.error('Failed to load local clothing:', e);
    }
}

// ──────────────────────────────────────────────
// Generate (Virtual Try-On)
// ──────────────────────────────────────────────
function updateSteps() {
    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    if (!step1 || !step2) return;

    if (state.isGenerating) {
        // AI换装中：步骤2激活，步骤1未激活
        step1.className = 'step';
        step2.className = 'step active';
    } else {
        // 未换装：步骤1激活，步骤2未激活
        step1.className = 'step active';
        step2.className = 'step';
    }
}

function updateStartButton() {
    const isVton = state.currentMode === 'vton';
    const isTransform = state.currentMode === 'transform';

    let canStart = false;
    if (isVton) {
        canStart = state.currentClothing && state.obsConnected;
    } else if (isTransform) {
        canStart = state.currentReferenceImage && state.obsConnected;
    }

    elements.btnStart.disabled = !canStart;
    updateSteps();

    // Update button text
    const startLabel = elements.btnStart.querySelector('span') || elements.btnStart;
    if (isTransform) {
        elements.btnStart.innerHTML = '<i class="fas fa-play"></i> 连接并开始';
    } else {
        elements.btnStart.innerHTML = '<i class="fas fa-play"></i> 开始换装';
    }

    // Update tooltip
    if (isVton && !state.currentClothing) {
        elements.btnStart.title = '请先上传服装图片';
    } else if (isTransform && !state.currentReferenceImage) {
        elements.btnStart.title = '请先上传参照画像';
    } else if (!state.obsConnected) {
        elements.btnStart.title = '请先连接OBS';
    } else {
        elements.btnStart.title = isTransform ? '开始人物变换' : '开始实时换装';
    }
}

async function startGeneration() {
    if (isSwitchingState) return;

    const isVton = state.currentMode === 'vton';
    const isTransform = state.currentMode === 'transform';

    if (isVton && !state.currentClothing) {
        showToast('请先上传服装图片', 'error');
        return;
    }
    if (isTransform && !state.currentReferenceImage) {
        showToast('请先上传参照画像', 'error');
        return;
    }
    if (!state.obsConnected) {
        showToast('请先连接OBS', 'error');
        return;
    }

    isSwitchingState = true;
    elements.btnStart.disabled = true;
    elements.btnStop.disabled = true;

    if (elements.aiBadge) {
        elements.aiBadge.textContent = 'AI 连接中...';
        elements.aiBadge.style.display = 'block';
    }
    elements.generatedOverlay.style.display = 'none';
    elements.previewPlaceholder.style.display = 'flex';
    elements.previewPlaceholder.innerHTML = `
        <i class="fas fa-spinner fa-spin"></i>
        <p>${isTransform ? 'AI 人物变换连接中...' : 'AI 换装连接中...'}</p>
    `;

    state.isGenerating = true;
    elements.btnStart.style.display = 'none';
    elements.btnStop.style.display = '';
    updateSteps();

    if (isVton) {
        isRealTimeTryOn = true;
        lastProcessedClothing = null;
        tryOnProcessing = false;
        showToast('实时换装已开启', 'success');
        connectVTONWebSocket();
    } else if (isTransform) {
        isTransformProcessing = true;
        showToast('人物变换已开启', 'success');
        startTransformLoop();
    }

    setTimeout(() => {
        isSwitchingState = false;
        elements.btnStop.disabled = false;
    }, 500);
}

async function stopGeneration() {
    if (isSwitchingState) return;

    isSwitchingState = true;
    elements.btnStart.disabled = true;
    elements.btnStop.disabled = true;

    // Stop both modes
    isRealTimeTryOn = false;
    isTransformProcessing = false;
    state.isGenerating = false;
    tryOnProcessing = false;
    lastProcessedClothing = null;
    lastClothingPath = null;

    disconnectVTONWebSocket();

    elements.btnStart.style.display = '';
    elements.btnStop.style.display = 'none';
    updateSteps();

    if (elements.generatedOverlay) {
        elements.generatedOverlay.style.display = 'none';
        elements.generatedOverlay.src = '';
    }
    if (elements.aiBadge) {
        elements.aiBadge.style.display = 'none';
        elements.aiBadge.textContent = '';
    }

    elements.obsCanvas.style.display = 'block';
    elements.previewPlaceholder.style.display = 'none';

    if (isOBSRendering) {
        elements.obsCanvas.style.display = 'block';
    }

    showToast(state.currentMode === 'transform' ? '人物变换已停止' : '实时换装已停止', 'info');

    setTimeout(() => {
        isSwitchingState = false;
        updateStartButton();
    }, 500);
}

// ──────────────────────────────────────────────
// OBS Virtual Camera Controls
// ──────────────────────────────────────────────

// ──────────────────────────────────────────────
// Event Listeners
// ──────────────────────────────────────────────
function initEventListeners() {
    // Camera connection button (right panel)
    const btnConnectCamera = document.getElementById('btnConnectCamera');
    if (btnConnectCamera) {
        btnConnectCamera.addEventListener('click', () => {
            connectOBS();
        });
    }

    // Start/Stop buttons
    elements.btnStart.addEventListener('click', startGeneration);
    elements.btnStop.addEventListener('click', stopGeneration);
}

// ──────────────────────────────────────────────
// Drag & Drop Global (for search images to clothing)
// ──────────────────────────────────────────────
function initGlobalDragDrop() {
    // When dragging from search panel, show drop zone highlight
    document.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    document.addEventListener('drop', (e) => {
        e.preventDefault();
        // Remove all dragover highlights
        $$('.drag-drop-area').forEach(area => area.classList.remove('dragover'));
    });
}


// ──────────────────────────────────────────────
// Initialization
// ──────────────────────────────────────────────
function init() {
    console.log('OBS Virtual Try-On - Initializing...');

    // Initialize all modules
    initEventListeners();
    initClothingDragDrop();
    initReferenceDragDrop();
    initImageGallery();
    initModeSelection();
    initPromptTags();

    // Connect WebSocket
    connectWebSocket();

    // Try to fetch initial status
    fetch('/api/status')
        .then(res => res.json())
        .then(data => updateStatus(data))
        .catch(e => console.log('Could not fetch initial status'));

    // Auto-reconnect OBS with default password
    const defaultPassword = 'a123456789';
    state.obsPassword = defaultPassword;
    console.log('Auto-reconnecting OBS...');
    connectOBS();

    console.log('OBS Virtual Try-On - Ready');
}

// Start when DOM is ready
document.addEventListener('DOMContentLoaded', init);
