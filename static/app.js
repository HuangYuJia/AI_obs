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
    currentMode: 'tryon',
    currentClothing: null,
    ws: null,
    obsPassword: localStorage.getItem('obsPassword') || 'a123456789',
};

const CONFIG = {
    WS_URL: `ws://${window.location.host}/ws`,
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
    obsPassword: $('#obsPassword'),
    btnConnectOBS: $('#btnConnectOBS'),
    btnDisconnectOBS: $('#btnDisconnectOBS'),

    // Left panel - image gallery
    imageGrid: $('#imageGrid'),
    btnRefreshImages: $('#btnRefreshImages'),
    btnAddLocal: $('#btnAddLocal'),
    localFileInput: $('#localFileInput'),

    // Center panel
    mainPreview: $('#mainPreview'),
    obsVideo: $('#obsVideo'),
    obsCanvas: $('#obsCanvas'),
    previewPlaceholder: $('#previewPlaceholder'),
    aiBadge: $('#aiBadge'),
    generatedOverlay: $('#generatedOverlay'),
    btnVolume: $('#btnVolume'),
    bottomPreviewImg: $('#bottomPreviewImg'),
    bottomTimecode: $('#bottomTimecode'),

    // Right panel - clothing
    clothingDropArea: $('#clothingDropArea'),
    clothingDropContent: $('#clothingDropContent'),
    clothingPreview: $('#clothingPreview'),
    clothingPreviewImg: $('#clothingPreviewImg'),
    clothingFileInput: $('#clothingFileInput'),
    btnClearClothing: $('#btnClearClothing'),

    // Right panel - controls
    promptInput: $('#promptInput'),
    btnStart: $('#btnStart'),
    btnStop: $('#btnStop'),
    btnVolume: $('#btnVolume'),

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
    elements.btnConnectOBS.style.display = connected ? 'none' : '';
    elements.btnDisconnectOBS.style.display = connected ? '' : 'none';

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
    elements.liveIndicator.style.opacity = isLive ? '1' : '0.4';
    if (isLive) {
        // Live started
    } else {
        // Live stopped
    }
}

// ──────────────────────────────────────────────
// OBS Connection
// ──────────────────────────────────────────────
async function connectOBS() {
    const password = document.getElementById('obsPassword').value;

    try {
        const response = await fetch(`/api/obs/connect?password=${encodeURIComponent(password)}`, {
            method: 'POST'
        });

        if (response.ok) {
            showToast('已连接OBS', 'success');
            updateOBSStatus(true);
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
        stopOBSStream(); // Stop stream first to set flag
        updateOBSStatus(false);
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

        // Bottom preview: always show original OBS feed
        elements.bottomPreviewImg.src = `data:image/jpeg;base64,${base64Image}`;
        elements.bottomPreviewImg.style.display = 'block';
        const bottomPlaceholder = document.querySelector('.bottom-preview__placeholder');
        if (bottomPlaceholder) bottomPlaceholder.style.display = 'none';

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

async function applyRealTimeTryOn(base64Frame) {
    if (!state.currentClothing) {
        return;
    }

    // Skip if already processing
    if (tryOnProcessing) {
        return;
    }

    // Only process if clothing changed or first time
    if (lastProcessedClothing === state.currentClothing && elements.generatedOverlay.style.display !== 'none') {
        return;
    }

    tryOnProcessing = true;
    lastProcessedClothing = state.currentClothing;

    try {
        // Show processing indicator
        elements.aiBadge.textContent = 'AI 处理中...';
        elements.aiBadge.style.display = 'block';

        const response = await fetch('/api/realtime-tryon', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                frame: base64Frame,
                clothing: state.currentClothing,
            }),
        });

        if (response.ok) {
            const data = await response.json();
            if (data.image) {
                elements.generatedOverlay.src = `data:image/png;base64,${data.image}`;
                elements.generatedOverlay.style.display = 'block';
                elements.aiBadge.textContent = 'AI Generated';
                elements.aiBadge.style.display = 'block';
            } else {
                elements.aiBadge.textContent = 'AI 生成失败';
            }
        } else {
            elements.aiBadge.textContent = 'AI 错误';
        }
    } catch (e) {
        console.error('Try-on error:', e);
        elements.aiBadge.textContent = 'AI 错误';
    } finally {
        tryOnProcessing = false;
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
        const response = await fetch('/api/clothing/upload', {
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
// Search Image Drag to Clothing
// ──────────────────────────────────────────────
function initSearchDragToClothing() {
    // Make search result images draggable to clothing area
    $$('.image-card').forEach(card => {
        card.addEventListener('dragstart', (e) => {
            const imgSrc = card.querySelector('img').src;
            e.dataTransfer.setData('text/plain', imgSrc);
            e.dataTransfer.setData('application/x-image-url', imgSrc);
        });
    });

    // Handle drop from search to clothing area
    elements.clothingDropArea.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    elements.clothingDropArea.addEventListener('drop', (e) => {
        const imageUrl = e.dataTransfer.getData('text/plain') ||
                         e.dataTransfer.getData('application/x-image-url');

        if (imageUrl) {
            handleClothingUrl(imageUrl);
        }
    });
}

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
// Mode Selection (single mode now)
// ──────────────────────────────────────────────
function initModeSelection() {
    // Only one mode now, no need for selection logic
    state.currentMode = 'tryon';
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

async function searchImages(query = null) {
    if (!query) {
        query = 'COSPLAY cosplay';
    }

    try {
        const response = await fetch(`/api/search/images?query=${encodeURIComponent(query)}&count=8`);
        const data = await response.json();

        if (data.images && data.images.length > 0) {
            // Keep local images, add search results
            renderImageGrid(data.images, false);
        }

        // Show message if any (e.g., "请配置 BING_SEARCH_KEY")
        if (data.message) {
            showToast(data.message, 'info');
        }
    } catch (e) {
        console.error('Search error:', e);
        showToast('搜索失败: ' + e.message, 'error');
    }
}

function renderImageGrid(apiImages = [], append = false) {
    const grid = elements.imageGrid;

    if (!append) {
        // Clear only API images, keep local ones
        grid.innerHTML = '';
        // Re-add local images first
        localImages.forEach(img => {
            grid.appendChild(createImageCard(img.url, img.title, img.source, true));
        });
    }

    // Add API images
    apiImages.forEach(img => {
        grid.appendChild(createImageCard(img.thumbnail || img.url, img.title, img.source, false));
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
        <div class="image-card__info">
            <span class="image-card__title">${title}</span>
            <span class="image-card__source">${source}</span>
        </div>
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
            localImages = localImages.filter(img => img.url !== src);
            div.remove();
        });
    }

    return div;
}

function addLocalImages(files) {
    Array.from(files).forEach(file => {
        if (!file.type.startsWith('image/')) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            const url = e.target.result;
            const img = {
                url: url,
                title: file.name.replace(/\.[^/.]+$/, ''),
                source: '本地'
            };
            localImages.push(img);

            // Add to grid
            const card = createImageCard(url, img.title, img.source, true);
            elements.imageGrid.prepend(card);
        };
        reader.readAsDataURL(file);
    });
}

function initImageGallery() {
    // Refresh button
    elements.btnRefreshImages.addEventListener('click', () => {
        searchImages();
    });

    // Add local button
    elements.btnAddLocal.addEventListener('click', () => {
        elements.localFileInput.click();
    });

    // Local file input
    elements.localFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            addLocalImages(e.target.files);
            e.target.value = ''; // Reset input
        }
    });

    // Initial load
    searchImages();
}

// ──────────────────────────────────────────────
// Generate (Virtual Try-On)
// ──────────────────────────────────────────────
function updateStartButton() {
    // Both clothing image and OBS connection are required
    const canStart = state.currentClothing && state.obsConnected;
    elements.btnStart.disabled = !canStart;

    // Update tooltip
    if (!state.currentClothing) {
        elements.btnStart.title = '请先上传服装图片';
    } else if (!state.obsConnected) {
        elements.btnStart.title = '请先连接OBS';
    } else {
        elements.btnStart.title = '开始实时换装';
    }
}

async function startGeneration() {
    // Prevent rapid clicking
    if (isSwitchingState) return;

    if (!state.currentClothing) {
        showToast('请先上传服装图片', 'error');
        return;
    }

    if (!state.obsConnected) {
        showToast('请先连接OBS', 'error');
        return;
    }

    // Lock state
    isSwitchingState = true;
    elements.btnStart.disabled = true;
    elements.btnStop.disabled = true;

    // Enable real-time try-on mode
    isRealTimeTryOn = true;
    state.isGenerating = true;
    elements.btnStart.style.display = 'none';
    elements.btnStop.style.display = '';
    showToast('实时换装已开启', 'success');

    // Unlock after a short delay
    setTimeout(() => {
        isSwitchingState = false;
        elements.btnStop.disabled = false;
    }, 500);
}

async function stopGeneration() {
    // Prevent rapid clicking
    if (isSwitchingState) return;

    // Lock state
    isSwitchingState = true;
    elements.btnStart.disabled = true;
    elements.btnStop.disabled = true;

    // Stop real-time try-on mode
    isRealTimeTryOn = false;
    state.isGenerating = false;
    tryOnProcessing = false;
    lastProcessedClothing = null;  // Reset so next start will trigger new generation
    lastClothingPath = null;

    elements.btnStart.style.display = '';
    elements.btnStop.style.display = 'none';

    // Hide AI overlay and badge
    if (elements.generatedOverlay) {
        elements.generatedOverlay.style.display = 'none';
        elements.generatedOverlay.src = '';
    }
    if (elements.aiBadge) {
        elements.aiBadge.style.display = 'none';
    }

    // Show canvas again for OBS feed
    if (isOBSRendering) {
        elements.obsCanvas.style.display = 'block';
    }

    showToast('实时换装已停止', 'info');

    // Unlock after a short delay
    setTimeout(() => {
        isSwitchingState = false;
        updateStartButton();
    }, 500);
}

// ──────────────────────────────────────────────
// OBS Virtual Camera Controls
// ──────────────────────────────────────────────
async function startVirtualCamera() {
    try {
        const response = await fetch('/api/obs/start-virtual-cam', { method: 'POST' });
        if (response.ok) {
            updateLiveStatus(true);
            showToast('虚拟摄像头已启动', 'success');
        } else {
            showToast('虚拟摄像头启动失败', 'error');
        }
    } catch (e) {
        showToast('错误: ' + e.message, 'error');
    }
}

async function stopVirtualCamera() {
    try {
        const response = await fetch('/api/obs/stop-virtual-cam', { method: 'POST' });
        if (response.ok) {
            updateLiveStatus(false);
            showToast('バーチャルカメラを停止しました', 'info');
        }
    } catch (e) {
        showToast('错误: ' + e.message, 'error');
    }
}

// ──────────────────────────────────────────────
// Event Listeners
// ──────────────────────────────────────────────
function initEventListeners() {
    // OBS Connection
    elements.btnConnectOBS.addEventListener('click', connectOBS);
    elements.btnDisconnectOBS.addEventListener('click', disconnectOBS);

    // Start/Stop buttons
    elements.btnStart.addEventListener('click', startGeneration);
    elements.btnStop.addEventListener('click', stopGeneration);

    // Volume button (toggle)
    elements.btnVolume.addEventListener('click', () => {
        const icon = elements.btnVolume.querySelector('i');
        if (icon.classList.contains('fa-volume-up')) {
            icon.className = 'fas fa-volume-mute';
            elements.obsVideo.muted = true;
        } else {
            icon.className = 'fas fa-volume-up';
            elements.obsVideo.muted = false;
        }
    });
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
// Category Tabs
// ──────────────────────────────────────────────
function initCategoryTabs() {
    $$('.category-tabs .tab').forEach(tab => {
        tab.addEventListener('click', () => {
            $$('.category-tabs .tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
        });
    });
}

// ──────────────────────────────────────────────
// Search Box
// ──────────────────────────────────────────────
function initSearchBox() {
    const searchInput = $('#searchInput');
    const btnSearch = $('#btnSearch');

    btnSearch.addEventListener('click', () => {
        performSearch(searchInput.value);
    });

    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            performSearch(searchInput.value);
        }
    });
}

function performSearch(query) {
    if (!query.trim()) return;
    showToast(`搜索: ${query}`, 'info');
    // In production, this would call an API to search for images
}

// ──────────────────────────────────────────────
// Initialization
// ──────────────────────────────────────────────
function init() {
    console.log('OBS Virtual Try-On - Initializing...');

    // Initialize all modules
    initEventListeners();
    initClothingDragDrop();
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

    // Auto-reconnect OBS if password was saved
    if (state.obsPassword) {
        document.getElementById('obsPassword').value = state.obsPassword;
        console.log('Auto-reconnecting OBS...');
        connectOBS();
    }

    console.log('OBS Virtual Try-On - Ready');
}

// Start when DOM is ready
document.addEventListener('DOMContentLoaded', init);
