/**
 * News Video Generator - Frontend Application
 */

let currentJobId = null;
let pollInterval = null;
let previewAudio = null;

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// === Voice Preview ===
async function previewVoice() {
    const voiceId = document.getElementById('voiceSelect').value;
    const btn = document.getElementById('btnPreview');
    
    // Stop if already playing
    if (previewAudio && !previewAudio.paused) {
        previewAudio.pause();
        previewAudio.currentTime = 0;
        btn.textContent = '\uD83D\uDD0A';
        return;
    }
    
    btn.textContent = '\u23F3';
    btn.disabled = true;
    
    try {
        previewAudio = new Audio(`/api/preview-voice/${voiceId}?t=${Date.now()}`);
        previewAudio.addEventListener('ended', () => {
            btn.textContent = '\uD83D\uDD0A';
        });
        previewAudio.addEventListener('error', () => {
            btn.textContent = '\u274C';
            setTimeout(() => { btn.textContent = '\uD83D\uDD0A'; }, 2000);
        });
        await previewAudio.play();
        btn.textContent = '\u23F9';
    } catch(e) {
        console.error('Preview error:', e);
        btn.textContent = '\u274C';
        setTimeout(() => { btn.textContent = '\uD83D\uDD0A'; }, 2000);
    } finally {
        btn.disabled = false;
    }
}

// === Check Gemini TTS Quota ===
async function checkGeminiTtsQuota() {
    const btn = document.getElementById('btnCheckTtsQuota');
    const statusDiv = document.getElementById('ttsQuotaStatus');
    if (!btn || !statusDiv) return;

    btn.textContent = '⏳ Проверка...';
    btn.disabled = true;
    statusDiv.style.display = 'block';
    statusDiv.style.background = 'rgba(255, 255, 255, 0.05)';
    statusDiv.style.color = '#ccc';
    statusDiv.innerHTML = 'Тестирование моделей Gemini TTS через активные ключи...';

    try {
        const resp = await fetch('/api/gemini/tts-status');
        const data = await resp.json();
        
        if (data.available) {
            statusDiv.style.background = 'rgba(46, 213, 115, 0.15)';
            statusDiv.style.border = '1px solid rgba(46, 213, 115, 0.4)';
            statusDiv.style.color = '#2ed573';
            statusDiv.innerHTML = `<strong>${data.summary}</strong><br>` +
                `<span style="opacity:0.85">Активные модели: ${data.active_models.join(', ')}</span><br>` +
                `<span style="opacity:0.85">Ролики будут озвучены выбранным голосом Gemini AI!</span>`;
        } else {
            statusDiv.style.background = 'rgba(255, 177, 66, 0.15)';
            statusDiv.style.border = '1px solid rgba(255, 177, 66, 0.4)';
            statusDiv.style.color = '#eccc68';
            statusDiv.innerHTML = `<strong>${data.summary}</strong><br>` +
                `<span style="opacity:0.85">При генерации видео движок автоматически переключится на чистый голос Edge-TTS (Conrad/Dmitry).</span>`;
        }
    } catch (e) {
        statusDiv.style.background = 'rgba(255, 71, 87, 0.15)';
        statusDiv.style.border = '1px solid rgba(255, 71, 87, 0.4)';
        statusDiv.style.color = '#ff4757';
        statusDiv.innerHTML = `Ошибка проверки квоты: ${e.message}`;
    } finally {
        btn.textContent = '⚡ Квота Gemini';
        btn.disabled = false;
    }
}

// === DOM Elements ===
const topicInput = document.getElementById('topicInput');
const voiceSelect = document.getElementById('voiceSelect');
const themeSelect = document.getElementById('themeSelect');
const rateSlider = document.getElementById('rateSlider');
const rateValue = document.getElementById('rateValue');
const lengthSlider = document.getElementById('lengthSlider');
const lengthValue = document.getElementById('lengthValue');
const skipAnalysis = document.getElementById('skipAnalysis');
const isPreviewMode = document.getElementById('isPreviewMode');
const kenBurnsMode = document.getElementById('kenBurnsMode');
const transitionsMode = document.getElementById('transitionsMode');
const btnGenerate = document.getElementById('btnGenerate');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');

const generatorPanel = document.getElementById('generatorPanel');
const progressPanel = document.getElementById('progressPanel');
const resultsPanel = document.getElementById('resultsPanel');
const errorPanel = document.getElementById('errorPanel');
const historyPanel = document.getElementById('historyPanel');

// === Slider Updates ===
rateSlider.addEventListener('input', () => {
    const val = parseInt(rateSlider.value);
    rateValue.textContent = (val >= 0 ? '+' : '') + val + '%';
});

lengthSlider.addEventListener('input', () => {
    const val = parseInt(lengthSlider.value);
    const approxMin = Math.round(val / 850);
    lengthValue.textContent = val.toLocaleString('ru-RU');
    const timeEl = document.getElementById('approxTime');
    if (timeEl) {
        timeEl.textContent = `~${approxMin}-${approxMin + 2} мин`;
    }
});

// === Quick Topics ===
document.querySelectorAll('.quick-topic').forEach(el => {
    el.addEventListener('click', () => {
        topicInput.value = el.dataset.topic;
        topicInput.focus();
        if (el.dataset.voice && voiceSelect) {
            voiceSelect.value = el.dataset.voice;
        }
        if (el.dataset.theme && themeSelect) {
            themeSelect.value = el.dataset.theme;
        }
        
        // Visual feedback
        el.style.transform = 'scale(0.95)';
        setTimeout(() => el.style.transform = '', 150);
    });
});

// === Topic Mode Switching ===
let currentTopicMode = 'single';

function setTopicMode(mode) {
    currentTopicMode = mode;
    const singleTab = document.getElementById('modeSingleTab');
    const batchTab = document.getElementById('modeBatchTab');
    const singleWrapper = document.getElementById('singleTopicWrapper');
    const batchWrapper = document.getElementById('batchTopicWrapper');
    const btnText = btnGenerate.querySelector('.btn-text');

    if (mode === 'batch') {
        if (singleTab) singleTab.classList.remove('active');
        if (batchTab) batchTab.classList.add('active');
        if (singleWrapper) singleWrapper.style.display = 'none';
        if (batchWrapper) batchWrapper.style.display = 'block';
        updateBatchCounter();
    } else {
        if (batchTab) batchTab.classList.remove('active');
        if (singleTab) singleTab.classList.add('active');
        if (batchWrapper) batchWrapper.style.display = 'none';
        if (singleWrapper) singleWrapper.style.display = 'block';
        if (btnText) btnText.textContent = 'Сгенерировать ролик';
    }
}

function updateBatchCounter() {
    const textarea = document.getElementById('batchTopicsInput');
    const counter = document.getElementById('batchCounter');
    const btnText = btnGenerate.querySelector('.btn-text');
    if (!textarea || !counter) return;

    const lines = textarea.value.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    counter.textContent = `📝 Тем в очереди: ${lines.length}`;
    if (currentTopicMode === 'batch') {
        if (lines.length > 0) {
            btnText.textContent = `🚀 Запустить пакет (${lines.length} тем)`;
        } else {
            btnText.textContent = '🚀 Запустить пакетную генерацию';
        }
    }
}

const batchTopicsInput = document.getElementById('batchTopicsInput');
if (batchTopicsInput) {
    batchTopicsInput.addEventListener('input', updateBatchCounter);
}

// === Enter key support ===
topicInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') startGeneration();
});

// === Start Generation ===
async function startGeneration() {
    let topicsList = [];
    const isBatch = (currentTopicMode === 'batch');

    if (isBatch) {
        const text = batchTopicsInput ? batchTopicsInput.value : '';
        topicsList = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        if (topicsList.length === 0) {
            if (batchTopicsInput) {
                batchTopicsInput.focus();
                batchTopicsInput.style.borderColor = 'var(--error)';
                setTimeout(() => batchTopicsInput.style.borderColor = '', 1500);
            }
            return;
        }
    } else {
        const topic = topicInput.value.trim();
        if (!topic) {
            topicInput.focus();
            topicInput.style.borderColor = 'var(--error)';
            setTimeout(() => topicInput.style.borderColor = '', 1500);
            return;
        }
        topicsList = [topic];
    }
    
    const rate = parseInt(rateSlider.value);
    const rateStr = (rate >= 0 ? '+' : '') + rate + '%';
    
    try {
        btnGenerate.disabled = true;
        btnGenerate.querySelector('.btn-text').textContent = 'Запускаем...';
        
        let response, data;
        const payloadCommon = {
            language: voiceSelect.value.split('-')[0],
            voice_id: voiceSelect.value,
            theme: themeSelect.value,
            voice_rate: rateStr,
            target_length: parseInt(lengthSlider.value),
            skip_image_analysis: skipAnalysis.checked,
            is_preview: isPreviewMode ? isPreviewMode.checked : false,
            ken_burns: kenBurnsMode ? kenBurnsMode.checked : false,
            transitions: transitionsMode ? transitionsMode.checked : true,
            review_slides: document.getElementById('reviewSlidesMode') ? document.getElementById('reviewSlidesMode').checked : false,
            acute_angle_id: selectedAcuteAngleId || '',
        };

        if (isBatch) {
            response = await fetch('/api/generate-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topics: topicsList,
                    ...payloadCommon
                }),
            });
            data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Server error');
            currentJobId = data.first_job_id;
        } else {
            response = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic: topicsList[0],
                    ...payloadCommon
                }),
            });
            data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Server error');
            currentJobId = data.job_id;
        }
        
        localStorage.setItem('active_news_job_id', currentJobId);
        
        // Reset banner states
        document.getElementById('titleBannerCard').style.display = 'none';
        document.getElementById('liveActivityBox').style.display = 'none';
        
        // Show progress panel
        showPanel('progress');
        document.getElementById('jobTopic').textContent = isBatch 
            ? `Пакетная генерация: 1 из ${topicsList.length} — ${topicsList[0]}`
            : topicsList[0];
        
        // Set status
        setStatus('busy', 'Генерация...');
        
        // Start polling
        startPolling();
        
    } catch (error) {
        showError(error.message);
    } finally {
        btnGenerate.disabled = false;
        if (isBatch) {
            updateBatchCounter();
        } else {
            btnGenerate.querySelector('.btn-text').textContent = 'Сгенерировать ролик';
        }
    }
}

// === Polling ===
function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(checkStatus, 1500);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function checkStatus() {
    if (!currentJobId) return;
    
    try {
        const response = await fetch(`/api/status/${currentJobId}`);
        if (!response.ok) {
            if (response.status === 404) {
                stopPolling();
                showError('Задача не найдена (сервер был перезапущен). Нажмите кнопку «Попробовать снова» и запустите ролик.');
                return;
            }
            throw new Error(`Ошибка ответа сервера (${response.status})`);
        }
        
        const job = await response.json();
        if (!job || typeof job.progress === 'undefined') {
            return;
        }
        
        updateProgress(job);
        await updateQueueBox();
        
        if (job.status === 'completed') {
            stopPolling();
            addToHistory(job);
            showResults(job);
            setStatus('ready', 'Готов к работе');
            
            // Check queue and show beautiful completion modal
            handleJobCompleted(job);
        } else if (job.status === 'failed') {
            stopPolling();
            showError(job.error || 'Ошибка при генерации');
            setStatus('error', 'Ошибка');
        } else if (job.status === 'awaiting_slide_review') {
            setStatus('busy', '⏸️ Ожидание проверки слайдов');
        }
    } catch (error) {
        console.error('Poll error:', error);
    }
}

async function updateQueueBox() {
    try {
        const res = await fetch('/api/queue');
        if (!res.ok) return;
        const qData = await res.json();
        const box = document.getElementById('queueStatusBox');
        const countEl = document.getElementById('queueCount');
        const listEl = document.getElementById('queueItemsList');
        if (!box || !countEl || !listEl) return;

        const total = qData.count || 0;
        if (total > 1) {
            box.style.display = 'block';
            countEl.textContent = total;
            listEl.innerHTML = qData.queue.map((item, idx) => {
                const isActive = (item.id === currentJobId);
                const isRunning = (item.status === 'running');
                const badgeClass = isRunning ? 'running' : 'waiting';
                const badgeText = isRunning ? '⚡ В работе' : `В очереди (#${idx + 1})`;
                return `
                    <div class="queue-item ${isActive ? 'active' : ''}" onclick="switchActiveJob('${item.id}')" style="cursor: pointer;" title="Нажмите, чтобы следить за этим роликом">
                        <span class="queue-item-title">${idx + 1}. ${escapeHtml(item.topic || 'Без названия')}</span>
                        <span class="queue-item-badge ${badgeClass}">${badgeText}</span>
                    </div>
                `;
            }).join('');
        } else {
            box.style.display = 'none';
        }
    } catch (e) {
        console.debug('Queue poll error:', e);
    }
}

function switchActiveJob(jobId) {
    if (!jobId) return;
    currentJobId = jobId;
    localStorage.setItem('active_news_job_id', currentJobId);
    showPanel('progress');
    checkStatus();
    startPolling();
}

// === Update Progress ===
function updateProgress(job) {
    const fill = document.getElementById('progressFill');
    const percent = document.getElementById('progressPercent');
    const step = document.getElementById('progressStep');
    
    fill.style.width = job.progress + '%';
    percent.textContent = job.progress + '%';
    step.textContent = job.current_step;
    
    // Title Banner
    const titleCard = document.getElementById('titleBannerCard');
    const titleText = document.getElementById('titleBannerText');
    const titleLead = document.getElementById('titleBannerLead');
    const titleRu = document.getElementById('titleBannerRu');
    const titleRuText = document.getElementById('titleBannerRuText');
    const thumbBanner = document.getElementById('titleBannerThumb');
    const thumbOrig = document.getElementById('titleBannerThumbOrig');
    const thumbRu = document.getElementById('titleBannerThumbRu');

    if (job.generated_title) {
        titleText.textContent = job.generated_title;
        if (job.title_ru && titleRu && titleRuText) {
            titleRuText.textContent = job.title_ru;
            titleRu.style.display = 'block';
        } else if (titleRu) {
            titleRu.style.display = 'none';
        }

        if (job.thumbnail_hook && thumbBanner && thumbOrig) {
            thumbOrig.textContent = job.thumbnail_hook;
            if (thumbRu) {
                thumbRu.textContent = job.thumbnail_hook_ru ? `(🇷🇺 ${job.thumbnail_hook_ru})` : '';
            }
            thumbBanner.style.display = 'block';
        } else if (thumbBanner) {
            thumbBanner.style.display = 'none';
        }

        if (job.main_lead_story && titleLead) {
            titleLead.textContent = '🎯 Главная тема: ' + job.main_lead_story;
            titleLead.style.display = 'block';
        } else if (titleLead) {
            titleLead.style.display = 'none';
        }
        titleCard.style.display = 'block';
    }

    // Factual Sources Confirmation Banner
    const sourcesBanner = document.getElementById('sourcesBannerCard');
    const sourcesStatBadge = document.getElementById('sourcesStatBadge');
    if (sourcesBanner && sourcesStatBadge) {
        const summary = job.sources_summary || (job.result && job.result.sources_summary);
        const srcList = job.sources || (job.result && job.result.sources);
        if (summary && summary.count > 0) {
            const count = summary.count;
            const chars = (summary.total_chars || 0).toLocaleString('ru-RU');
            sourcesStatBadge.textContent = `${count} статей · ${chars} знаков реальной фактуры`;
            sourcesBanner.style.display = 'block';
        } else if (srcList && srcList.length > 0) {
            const withText = srcList.filter(s => (s.text_len || 0) >= 250);
            const totalChars = withText.reduce((acc, s) => acc + (s.text_len || 0), 0);
            sourcesStatBadge.textContent = `${withText.length} статей · ${totalChars.toLocaleString('ru-RU')} знаков фактуры`;
            sourcesBanner.style.display = 'block';
        } else {
            sourcesBanner.style.display = 'none';
        }
    }
    
    // Live Activity / Search Query Display
    const activityBox = document.getElementById('liveActivityBox');
    const activityText = document.getElementById('liveActivityText');
    if (job.detail) {
        activityText.textContent = job.detail;
        activityBox.style.display = 'flex';
    }
    
    // Update steps timeline
    const steps = document.querySelectorAll('.step');
    const completed = job.steps_completed || [];
    
    const stepMap = {
        'search_started': 0,
        'news_fetched': 0,
        'script_started': 1,
        'script_done': 1,
        'tts_started': 2,
        'tts_done': 2,
        'images_started': 3,
        'images_downloaded': 3,
        'analysis_started': 3,
        'analysis_done': 3,
        'video_started': 4,
        'video_done': 4,
        'thumbnail_started': 5,
        'thumbnail_done': 5,
        'completed': 5,
    };
    
    // Find current active step
    let activeIdx = -1;
    let completedIndices = new Set();
    
    for (const stepId of completed) {
        const idx = stepMap[stepId];
        if (idx !== undefined) {
            if (stepId.endsWith('_done') || stepId === 'completed' || stepId === 'news_fetched' || stepId === 'images_downloaded') {
                completedIndices.add(idx);
            }
            if (idx > activeIdx) activeIdx = idx;
        }
    }
    
    steps.forEach((el, i) => {
        el.classList.remove('active', 'completed');
        const statusEl = el.querySelector('.step-status');
        
        if (completedIndices.has(i)) {
            el.classList.add('completed');
            statusEl.textContent = '✓ Готово';
        } else if (i === activeIdx) {
            el.classList.add('active');
            const detail = job.detail || '';
            statusEl.textContent = detail ? `⏳ ${detail}` : '⏳ В процессе...';
        } else {
            statusEl.textContent = 'Ожидание';
        }
    });

    // Slide Review Banner
    const slideBanner = document.getElementById('slideReviewBanner');
    const slideCountEl = document.getElementById('slideReviewCount');
    const slideBtnCountEl = document.getElementById('slideReviewBtnCount');
    if (job.status === 'awaiting_slide_review') {
        currentJobId = job.id;
        currentReviewJobId = job.id;
        if (slideBanner) {
            slideBanner.style.display = 'block';
            const count = (job.slides && job.slides.length) || 0;
            if (slideCountEl) slideCountEl.textContent = count;
            if (slideBtnCountEl) slideBtnCountEl.textContent = count;
        }
    } else {
        if (slideBanner) {
            slideBanner.style.display = 'none';
        }
    }
}

// === Show Results ===
let currentJobData = null;

function showResults(job) {
    currentJobId = job.id;
    currentJobData = job;
    const result = job.result || {};
    
    document.getElementById('resultTitle').textContent = result.title || job.topic;
    
    // Russian translation of title
    const titleRuEl = document.getElementById('resultTitleRu');
    const titleRuText = document.getElementById('resultTitleRuText');
    const titleRu = result.title_ru || job.title_ru;
    if (titleRu && titleRuEl && titleRuText) {
        titleRuText.textContent = titleRu;
        titleRuEl.style.display = 'block';
    } else if (titleRuEl) {
        titleRuEl.style.display = 'none';
    }

    // Russian translation of thumbnail hook
    const thumbInfo = document.getElementById('resultThumbInfo');
    const thumbHook = document.getElementById('resultThumbHook');
    const thumbHookRu = document.getElementById('resultThumbHookRu');
    const hook = result.thumbnail_hook || job.thumbnail_hook;
    const hookRu = result.thumbnail_hook_ru || job.thumbnail_hook_ru;
    if (hook && thumbInfo && thumbHook) {
        thumbHook.textContent = hook;
        if (thumbHookRu) {
            thumbHookRu.textContent = hookRu ? `🇷🇺 Перевод: ${hookRu}` : '';
        }
        thumbInfo.style.display = 'block';
    } else if (thumbInfo) {
        thumbInfo.style.display = 'none';
    }

    document.getElementById('resultDescription').textContent = result.description || '';
    document.getElementById('statScript').textContent = (result.script_length || 0).toLocaleString('ru-RU');
    document.getElementById('statSegments').textContent = result.segments_count || 0;
    document.getElementById('statImages').textContent = result.images_count || 0;

    // Factual Sources Confirmation Card
    const resultSourcesCard = document.getElementById('resultSourcesCard');
    const resultSourcesSub = document.getElementById('resultSourcesSub');
    if (resultSourcesCard && resultSourcesSub) {
        const summary = result.sources_summary || job.sources_summary;
        const srcList = result.sources || job.sources;
        if (summary && summary.count > 0) {
            resultSourcesSub.textContent = `${summary.count} статей с полным текстом (${(summary.total_chars || 0).toLocaleString('ru-RU')} знаков фактуры и цитат) переданы в Gemini`;
            resultSourcesCard.style.display = 'block';
        } else if (srcList && srcList.length > 0) {
            const withText = srcList.filter(s => (s.text_len || 0) >= 250);
            const totalChars = withText.reduce((acc, s) => acc + (s.text_len || 0), 0);
            resultSourcesSub.textContent = `${withText.length} статей (${totalChars.toLocaleString('ru-RU')} знаков фактуры) переданы в Gemini`;
            resultSourcesCard.style.display = 'block';
        } else {
            resultSourcesCard.style.display = 'none';
        }
    }
    
    // Thumbnail preview
    const thumbImg = document.getElementById('resultThumbImg');
    if (thumbImg) {
        thumbImg.src = `/api/job/${job.id}/thumbnail?t=${Date.now()}`;
    }

    // Download links
    document.getElementById('btnDownloadVideo').href = `/api/download/${job.id}/video`;
    document.getElementById('btnDownloadThumb').href = `/api/download/${job.id}/thumbnail`;
    document.getElementById('btnDownloadScript').href = `/api/download/${job.id}/script`;
    document.getElementById('btnDownloadSubs').href = `/api/download/${job.id}/subtitles`;
    
    showPanel('results');
}

// === Show Error ===
function showError(message) {
    document.getElementById('errorMessage').textContent = message;
    showPanel('error');
    setStatus('error', 'Ошибка');
}

// === Panel Management ===
function showPanel(name) {
    generatorPanel.style.display = name === 'generator' ? 'block' : 'none';
    progressPanel.style.display = name === 'progress' ? 'block' : 'none';
    resultsPanel.style.display = name === 'results' ? 'block' : 'none';
    errorPanel.style.display = name === 'error' ? 'block' : 'none';
    
    // History ALWAYS stays visible so the user can download and edit previous videos anytime!
    historyPanel.style.display = 'block';
    
    // Manage floating pill visibility
    updateFloatingPillVisibility(name);
}

// === Script Modal Dialog ===
let loadedScriptText = "";

async function openScriptModal() {
    if (!currentJobId) return;
    
    const modal = document.getElementById('scriptModal');
    const titleEl = document.getElementById('modalScriptTitle');
    const metaEl = document.getElementById('modalScriptMeta');
    const bodyEl = document.getElementById('modalScriptBody');
    const copyBtn = document.getElementById('btnCopyScript');
    
    titleEl.textContent = 'Загрузка сценария...';
    metaEl.textContent = '';
    bodyEl.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted)">⏳ Загрузка текста...</div>';
    copyBtn.disabled = true;
    modal.style.display = 'flex';
    
    try {
        const resp = await fetch(`/api/job/${currentJobId}/script`);
        if (!resp.ok) {
            throw new Error('Сценарий еще формируется или не найден');
        }
        const data = await resp.json();
        
        loadedScriptText = data.script || '';
        titleEl.textContent = data.title || 'Сценарий выпуска';
        
        const charsCount = loadedScriptText.length.toLocaleString('ru-RU');
        const wordsCount = loadedScriptText.split(/\s+/).filter(Boolean).length.toLocaleString('ru-RU');
        const approxMin = Math.max(1, Math.round(loadedScriptText.length / 850));
        metaEl.innerHTML = `<span>📏 Длина: <b>${charsCount}</b> знаков</span> · <span>📝 Слов: <b>${wordsCount}</b></span> · <span>⏱️ Хронометраж: <b>~${approxMin} мин</b></span>`;
        
        // Format paragraphs nicely
        const paragraphs = loadedScriptText.split('\n\n').filter(p => p.trim());
        bodyEl.innerHTML = paragraphs.map((p, idx) => `<div class="script-paragraph" style="margin-bottom:18px;line-height:1.75;font-size:15px;"><span class="seg-badge" style="background:#2563eb;color:#fff;border-radius:4px;padding:3px 8px;font-size:11px;font-weight:600;margin-right:8px;vertical-align:middle;">Абзац ${idx + 1}</span>${p.trim()}</div>`).join('');
        
        copyBtn.disabled = false;
    } catch (e) {
        titleEl.textContent = 'Ошибка загрузки';
        bodyEl.innerHTML = `<div style="color:var(--error);padding:20px;">${e.message}</div>`;
    }
}

function closeScriptModal(e) {
    if (e && e.target && e.target.id !== 'scriptModal' && !e.target.classList.contains('modal-close') && !e.target.classList.contains('btn-close-modal')) {
        return;
    }
    const modal = document.getElementById('scriptModal');
    if (modal) modal.style.display = 'none';
}

async function copyScriptText() {
    if (!loadedScriptText) return;
    const btn = document.getElementById('btnCopyScript');
    try {
        await navigator.clipboard.writeText(loadedScriptText);
        btn.innerHTML = '<span>✓</span> Скопировано!';
        btn.style.borderColor = 'var(--success)';
        setTimeout(() => {
            btn.innerHTML = '<span>📋</span> Скопировать весь текст';
            btn.style.borderColor = '';
        }, 2000);
    } catch(err) {
        console.error('Copy failed:', err);
    }
}

function resetGenerator() {
    currentJobId = null;
    currentJobData = null;
    localStorage.removeItem('active_news_job_id');
    stopPolling();
    showPanel('generator');
    setStatus('ready', 'Готов к работе');
    document.getElementById('titleBannerCard').style.display = 'none';
    document.getElementById('liveActivityBox').style.display = 'none';
}

async function cancelCurrentJob() {
    if (!confirm('Прервать текущую генерацию и сбросить?')) return;
    
    const jobIdToCancel = currentJobId || localStorage.getItem('active_news_job_id');
    localStorage.removeItem('active_news_job_id');
    
    stopPolling();
    
    try {
        if (jobIdToCancel) {
            await fetch(`/api/job/${jobIdToCancel}/cancel`, { method: 'POST' }).catch(() => {});
        }
        await fetch('/api/jobs/reset', { method: 'POST' }).catch(() => {});
    } catch(e) {
        console.warn('Error cancelling job:', e);
    }
    
    currentJobId = null;
    currentJobData = null;
    setStatus('ready', 'Готов к работе');
    showPanel('generator');
    loadHistory();
}

// === Status ===
function setStatus(type, text) {
    statusDot.className = 'status-dot';
    if (type === 'busy') statusDot.classList.add('busy');
    if (type === 'error') statusDot.classList.add('error');
    statusText.textContent = text;
}

// === History ===
function addToHistory(job, prepend = true) {
    const historyList = document.getElementById('historyList');
    if (!historyList || !job || !job.id) return;
    
    // Check if element already exists to PREVENT DUPLICATES!
    let item = document.getElementById(`hist-item-${job.id}`);
    const isNew = !item;
    if (isNew) {
        item = document.createElement('div');
        item.id = `hist-item-${job.id}`;
        item.className = 'history-item';
    }
    
    const titleText = escapeHtml(job.result?.title || job.generated_title || job.topic || '');
    const titleRu = escapeHtml(job.result?.title_ru || job.title_ru || '');
    const titleDisplay = titleRu ? `${titleText} <span style="color:#60a5fa; font-weight: 500;">(🇷🇺 ${titleRu})</span>` : titleText;
    const topicText = escapeHtml(job.topic || 'Без темы');
    const dateText = job.created_at ? new Date(job.created_at).toLocaleString('ru-RU') : '';
    const isCompleted = (job.status === 'completed');

    item.innerHTML = `
        <img src="/api/job/${job.id}/thumbnail?t=${Date.now()}" class="history-thumb-mini" alt="" onerror="this.style.display='none'" />
        <div class="history-item-info">
            <span class="history-item-topic">${topicText}</span>
            <span class="history-item-meta">${dateText} · ${titleDisplay}</span>
        </div>
        <div class="history-item-actions">
            ${isCompleted ? `
                <button type="button" class="btn-hist-action btn-hist-edit" onclick="event.stopPropagation(); openThumbnailModal('${job.id}')" title="Редактировать обложку">
                    🎨 Обложка
                </button>
                <a href="/api/download/${job.id}/video" class="btn-hist-action btn-hist-dl" onclick="event.stopPropagation()" title="Скачать видео MP4" target="_blank">
                    📹 Видео
                </a>
                <a href="/api/download/${job.id}/thumbnail" class="btn-hist-action" onclick="event.stopPropagation()" title="Скачать обложку" target="_blank">
                    🖼️
                </a>
            ` : ''}
            <span class="history-item-status ${job.status}">${isCompleted ? '✓ Готово' : job.status}</span>
        </div>
    `;
    
    item.onclick = () => {
        currentJobId = job.id;
        currentJobData = job;
        showResults(job);
    };
    
    const empty = historyList.querySelector('.history-empty');
    if (empty) empty.remove();
    
    if (isNew) {
        if (prepend) {
            historyList.prepend(item);
        } else {
            historyList.appendChild(item);
        }
    }
}

// === Load history on start & Auto-restore active job on page refresh ===
async function loadHistory() {
    try {
        const response = await fetch('/api/jobs');
        if (!response.ok) return;
        const data = await response.json();
        
        const historyList = document.getElementById('historyList');
        if (!historyList) return;
        
        // Clear history list before populating to prevent duplicate cards!
        historyList.innerHTML = '';
        
        const jobs = data.jobs || [];
        // Sort newest first
        jobs.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
        
        let completedCount = 0;
        for (const job of jobs) {
            if (job.status === 'completed') {
                try {
                    addToHistory(job, false);
                    completedCount++;
                } catch (je) {
                    console.warn('Error adding job to history:', job.id, je);
                }
            }
        }
        
        if (completedCount === 0) {
            historyList.innerHTML = '<div class="history-empty">Пока нет завершённых генераций</div>';
        }

        // Check if there was an active job running before the page refresh
        const activeId = localStorage.getItem('active_news_job_id');
        if (activeId) {
            try {
                const resp = await fetch(`/api/status/${activeId}`);
                if (resp.ok) {
                    const job = await resp.json();
                    currentJobId = job.id;
                    currentJobData = job;

                    if (job.status === 'running' || job.status === 'queued' || job.status === 'awaiting_slide_review') {
                        document.getElementById('jobTopic').textContent = job.topic || '';
                        showPanel('progress');
                        if (job.status === 'awaiting_slide_review') {
                            setStatus('busy', '⏸️ Ожидание проверки слайдов');
                        } else {
                            setStatus('busy', 'Генерация...');
                        }
                        updateProgress(job);
                        startPolling();
                    } else if (job.status === 'completed') {
                        showResults(job);
                        setStatus('ready', 'Готов к работе');
                    } else if (job.status === 'failed' || job.status === 'cancelled') {
                        localStorage.removeItem('active_news_job_id');
                    }
                } else {
                    localStorage.removeItem('active_news_job_id');
                }
            } catch(err) {
                console.warn('Error reconnecting to active job:', err);
            }
        }

    } catch (e) {
        // Server might not be ready yet
    }
}

// === Thumbnail Studio State & Handlers ===
// === Professional Thumbnail Studio & Drag-and-Drop Editor ===
let thumbRandomOffset = 0;

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

let thumbEditorState = {
    title: '',
    topic: '',
    showBadge: true,
    fontSize: null,        // null = auto, or number e.g. 64, 92
    textXPercent: 5,       // % of width
    textYPercent: 32,      // % of height
    textAlign: 'left',     // 'left', 'center', 'right'
    flipHorizontal: false,
    showSafeZone: true,
    isCustomPos: false,    // true if dragged or position button clicked
};
let isThumbDragging = false;
let dragStartX = 0;
let dragStartY = 0;
let dragElemStartX = 0;
let dragElemStartY = 0;

function setThumbLoading(loading, text = "Генерация новой обложки...") {
    const overlay = document.getElementById('thumbLoadingOverlay');
    const loadingText = document.getElementById('thumbLoadingText');
    if (loadingText) loadingText.textContent = text;
    if (overlay) overlay.style.display = loading ? 'flex' : 'none';
}

function getThumbnailPayload(extra = {}) {
    const titleInput = document.getElementById('modalThumbTitle');
    const topicInput = document.getElementById('modalThumbTopic');
    const showBadgeCheck = document.getElementById('modalThumbShowBadge');
    
    const title = titleInput ? titleInput.value.trim() : thumbEditorState.title;
    const topic = topicInput ? topicInput.value.trim() : thumbEditorState.topic;
    const showBadge = showBadgeCheck ? showBadgeCheck.checked : thumbEditorState.showBadge;
    
    let textX = null;
    let textY = null;
    if (thumbEditorState.isCustomPos) {
        textX = Math.round((thumbEditorState.textXPercent / 100) * 1280);
        textY = Math.round((thumbEditorState.textYPercent / 100) * 720);
    }
    
    return {
        title: title,
        topic: topic,
        show_badge: Boolean(showBadge && topic),
        font_size: thumbEditorState.fontSize,
        text_x: textX,
        text_y: textY,
        text_align: thumbEditorState.textAlign,
        flip_horizontal: thumbEditorState.flipHorizontal,
        ...extra
    };
}

function updateThumbLiveOverlay() {
    const topicInput = document.getElementById('modalThumbTopic');
    const showBadgeCheck = document.getElementById('modalThumbShowBadge');
    const badgeEl = document.getElementById('thumbBadgeLive');
    const badgeText = document.getElementById('thumbBadgeLiveText');
    const curTopic = (topicInput ? topicInput.value.trim() : thumbEditorState.topic);
    const isBadgeOn = (showBadgeCheck ? showBadgeCheck.checked : thumbEditorState.showBadge) && curTopic.length > 0;
    
    if (badgeEl && badgeText) {
        if (isBadgeOn) {
            badgeEl.style.display = 'block';
            badgeText.textContent = curTopic.startsWith('●') ? curTopic : `● ${curTopic}`;
            if (thumbEditorState.textAlign === 'right') {
                badgeEl.style.left = 'auto';
                badgeEl.style.right = '5%';
                badgeEl.style.transform = 'none';
            } else if (thumbEditorState.textAlign === 'center') {
                badgeEl.style.left = '50%';
                badgeEl.style.right = 'auto';
                badgeEl.style.transform = 'translateX(-50%)';
            } else {
                badgeEl.style.left = '5%';
                badgeEl.style.right = 'auto';
                badgeEl.style.transform = 'none';
            }
        } else {
            badgeEl.style.display = 'none';
        }
    }

    // Live gradient backing behind text
    const gradEl = document.getElementById('thumbGradientLive');
    if (gradEl) {
        if (thumbEditorState.textAlign === 'right' || (thumbEditorState.isCustomPos && thumbEditorState.textXPercent > 55)) {
            gradEl.style.background = 'linear-gradient(to left, rgba(8, 10, 15, 0.95) 0%, rgba(8, 10, 15, 0.72) 36%, rgba(8, 10, 15, 0) 65%)';
        } else if (thumbEditorState.textAlign === 'center') {
            gradEl.style.background = 'radial-gradient(circle at center, rgba(8, 10, 15, 0.88) 0%, rgba(8, 10, 15, 0.45) 55%, rgba(8, 10, 15, 0.1) 100%)';
        } else {
            gradEl.style.background = 'linear-gradient(to right, rgba(8, 10, 15, 0.95) 0%, rgba(8, 10, 15, 0.72) 36%, rgba(8, 10, 15, 0) 65%)';
        }
    }
    
    // Live text lines and styling
    const titleInput = document.getElementById('modalThumbTitle');
    const titleText = (titleInput ? titleInput.value.trim() : thumbEditorState.title).toUpperCase() || 'ТЕКСТ ОБЛОЖКИ';
    const dragContent = document.getElementById('thumbDragContent');
    const dragBox = document.getElementById('thumbDragBox');
    const stage = document.getElementById('thumbPreviewStage');
    
    if (dragContent && stage) {
        const stageW = stage.clientWidth || 640;
        const scale = stageW / 1280;
        const fs = thumbEditorState.fontSize ? Math.round(thumbEditorState.fontSize * scale) : Math.round(56 * scale);
        dragContent.style.fontSize = `${Math.max(14, fs)}px`;
        dragContent.style.textAlign = thumbEditorState.textAlign;
        
        const words = titleText.split(/\s+/).filter(Boolean);
        let lines = [];
        if (words.length <= 3) {
            lines = [words.join(' ')];
        } else if (words.length <= 6) {
            const mid = Math.ceil(words.length / 2);
            lines = [words.slice(0, mid).join(' '), words.slice(mid).join(' ')];
        } else {
            const p1 = Math.ceil(words.length / 3);
            const p2 = Math.ceil((words.length * 2) / 3);
            lines = [words.slice(0, p1).join(' '), words.slice(p1, p2).join(' '), words.slice(p2).join(' ')];
        }
        
        const palette = ['#ffde00', '#ffffff', '#ffde00', '#ffffff'];
        dragContent.innerHTML = lines.map((l, i) => `
            <div class="thumb-drag-line" style="color: ${palette[i % palette.length]};">${escapeHtml(l)}</div>
        `).join('');
    }
    
    if (dragBox) {
        if (thumbEditorState.isCustomPos) {
            dragBox.style.left = `${thumbEditorState.textXPercent}%`;
            dragBox.style.top = `${thumbEditorState.textYPercent}%`;
            dragBox.style.right = 'auto';
            dragBox.style.transform = 'none';
        } else {
            if (thumbEditorState.textAlign === 'center') {
                dragBox.style.left = '50%';
                dragBox.style.right = 'auto';
                dragBox.style.transform = 'translateX(-50%)';
            } else if (thumbEditorState.textAlign === 'right') {
                dragBox.style.left = 'auto';
                dragBox.style.right = '5%';
                dragBox.style.transform = 'none';
            } else {
                dragBox.style.left = '5%';
                dragBox.style.right = 'auto';
                dragBox.style.transform = 'none';
            }
            dragBox.style.top = '32%';
        }
    }
    
    // Live image horizontal flip preview
    const previewImg = document.getElementById('modalThumbPreview');
    if (previewImg) {
        previewImg.style.transform = thumbEditorState.flipHorizontal ? 'scaleX(-1)' : 'none';
    }
    
    // Live YouTube safe zone badge
    const safeZone = document.getElementById('thumbYtSafeZone');
    if (safeZone) {
        safeZone.style.display = thumbEditorState.showSafeZone ? 'flex' : 'none';
    }
}

function initThumbDragAndDrop() {
    const dragBox = document.getElementById('thumbDragBox');
    const stage = document.getElementById('thumbPreviewStage');
    if (!dragBox || !stage || dragBox.dataset.dragInitialized) return;
    dragBox.dataset.dragInitialized = '1';

    function onPointerDown(e) {
        if (e.button && e.button !== 0) return;
        isThumbDragging = true;
        dragBox.classList.add('dragging');
        
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        dragStartX = clientX;
        dragStartY = clientY;
        
        const rect = dragBox.getBoundingClientRect();
        const stageRect = stage.getBoundingClientRect();
        dragElemStartX = rect.left - stageRect.left;
        dragElemStartY = rect.top - stageRect.top;
        
        if (e.cancelable) e.preventDefault();
    }

    function onPointerMove(e) {
        if (!isThumbDragging) return;
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        
        const deltaX = clientX - dragStartX;
        const deltaY = clientY - dragStartY;
        
        const stageRect = stage.getBoundingClientRect();
        let newX = dragElemStartX + deltaX;
        let newY = dragElemStartY + deltaY;
        
        const boxW = dragBox.offsetWidth;
        const boxH = dragBox.offsetHeight;
        
        newX = Math.max(10, Math.min(stageRect.width - boxW - 10, newX));
        newY = Math.max(10, Math.min(stageRect.height - boxH - 10, newY));
        
        const xPercent = (newX / stageRect.width) * 100;
        const yPercent = (newY / stageRect.height) * 100;
        
        thumbEditorState.textXPercent = Math.round(xPercent * 10) / 10;
        thumbEditorState.textYPercent = Math.round(yPercent * 10) / 10;
        thumbEditorState.isCustomPos = true;
        
        dragBox.style.left = `${thumbEditorState.textXPercent}%`;
        dragBox.style.top = `${thumbEditorState.textYPercent}%`;
        dragBox.style.right = 'auto';
        dragBox.style.transform = 'none';
    }

    function onPointerUp() {
        if (isThumbDragging) {
            isThumbDragging = false;
            dragBox.classList.remove('dragging');
        }
    }

    dragBox.addEventListener('mousedown', onPointerDown);
    window.addEventListener('mousemove', onPointerMove);
    window.addEventListener('mouseup', onPointerUp);

    dragBox.addEventListener('touchstart', onPointerDown, { passive: false });
    window.addEventListener('touchmove', onPointerMove, { passive: false });
    window.addEventListener('touchend', onPointerUp);
}

function onThumbSliderChange(val) {
    thumbEditorState.fontSize = parseInt(val, 10);
    const badge = document.getElementById('thumbFontSizeVal');
    if (badge) badge.textContent = `${val} pt`;
    
    document.querySelectorAll('.thumb-tool-controls .btn-thumb-chip').forEach(b => b.classList.remove('active'));
    updateThumbLiveOverlay();
}

function setThumbFontSizePreset(val) {
    const slider = document.getElementById('thumbFontSizeSlider');
    const badge = document.getElementById('thumbFontSizeVal');
    
    document.querySelectorAll('#chipFontAuto, #chipFont64, #chipFont92').forEach(b => b.classList.remove('active'));
    
    if (val === null) {
        thumbEditorState.fontSize = null;
        if (badge) badge.textContent = 'Авто';
        const btnAuto = document.getElementById('chipFontAuto');
        if (btnAuto) btnAuto.classList.add('active');
    } else {
        thumbEditorState.fontSize = val;
        if (slider) slider.value = val;
        if (badge) badge.textContent = `${val} pt`;
        const activeBtn = val === 64 ? document.getElementById('chipFont64') : document.getElementById('chipFont92');
        if (activeBtn) activeBtn.classList.add('active');
    }
    updateThumbLiveOverlay();
}

function setThumbAlign(align) {
    thumbEditorState.textAlign = align;
    ['left', 'center', 'right'].forEach(a => {
        const btn = document.getElementById(`btnAlign${a.charAt(0).toUpperCase() + a.slice(1)}`);
        if (btn) btn.classList.toggle('active', a === align);
    });
    
    if (!thumbEditorState.isCustomPos) {
        if (align === 'left') thumbEditorState.textXPercent = 5;
        else if (align === 'right') thumbEditorState.textXPercent = 65;
        else thumbEditorState.textXPercent = 35;
    }
    updateThumbLiveOverlay();
}

function setThumbPosQuick(pos) {
    thumbEditorState.isCustomPos = true;
    if (pos === 'top') thumbEditorState.textYPercent = 14;
    else if (pos === 'mid') thumbEditorState.textYPercent = 36;
    else if (pos === 'bottom') thumbEditorState.textYPercent = 64;
    updateThumbLiveOverlay();
}

function resetThumbTextPos() {
    thumbEditorState.isCustomPos = false;
    thumbEditorState.textXPercent = 5;
    thumbEditorState.textYPercent = 32;
    updateThumbLiveOverlay();
}

function toggleThumbFlip() {
    thumbEditorState.flipHorizontal = !thumbEditorState.flipHorizontal;
    const btn = document.getElementById('btnFlipPhoto');
    if (btn) btn.classList.toggle('active', thumbEditorState.flipHorizontal);
    updateThumbLiveOverlay();
}

function toggleSafeZone() {
    thumbEditorState.showSafeZone = !thumbEditorState.showSafeZone;
    const btn = document.getElementById('btnToggleSafeZone');
    if (btn) btn.classList.toggle('active', thumbEditorState.showSafeZone);
    updateThumbLiveOverlay();
}

function onThumbBadgeToggle() {
    const chk = document.getElementById('modalThumbShowBadge');
    thumbEditorState.showBadge = chk ? chk.checked : true;
    updateThumbLiveOverlay();
}

function onThumbTopicInput() {
    const inp = document.getElementById('modalThumbTopic');
    thumbEditorState.topic = inp ? inp.value.trim() : '';
    if (thumbEditorState.topic.length > 0) {
        const chk = document.getElementById('modalThumbShowBadge');
        if (chk && !chk.checked) chk.checked = true;
        thumbEditorState.showBadge = true;
    }
    updateThumbLiveOverlay();
}

function clearThumbTopic() {
    const inp = document.getElementById('modalThumbTopic');
    const chk = document.getElementById('modalThumbShowBadge');
    if (inp) inp.value = '';
    if (chk) chk.checked = false;
    thumbEditorState.topic = '';
    thumbEditorState.showBadge = false;
    updateThumbLiveOverlay();
}

async function openThumbnailModal(targetJobId = null) {
    if (targetJobId && targetJobId !== currentJobId) {
        currentJobId = targetJobId;
        try {
            const resp = await fetch(`/api/status/${targetJobId}`);
            if (resp.ok) {
                currentJobData = await resp.json();
            }
        } catch(e) {
            console.warn('Failed to load target job:', e);
        }
    }
    if (!currentJobId) return;
    
    const modal = document.getElementById('thumbnailModal');
    const preview = document.getElementById('modalThumbPreview');
    const titleInput = document.getElementById('modalThumbTitle');
    const topicInput = document.getElementById('modalThumbTopic');
    const badgeCheck = document.getElementById('modalThumbShowBadge');
    
    // Set preview to CLEAN background image (no baked text, no baked badges!)
    preview.onerror = function() {
        this.onerror = null;
        this.src = `/api/job/${currentJobId}/thumbnail?t=${Date.now()}`;
    };
    preview.src = `/api/job/${currentJobId}/thumbnail-bg?t=${Date.now()}`;
    preview.style.transform = 'none';
    
    // Defaults from job
    // Restore from saved thumbnail_settings if present, else fallback to job defaults
    const saved = currentJobData?.thumbnail_settings || {};
    const hook = saved.title
        || currentJobData?.thumbnail_hook
        || currentJobData?.script_data?.thumbnail_hook 
        || currentJobData?.result?.thumbnail_hook
        || currentJobData?.result?.title 
        || document.getElementById('resultTitle')?.textContent 
        || '';
    const hookRu = currentJobData?.thumbnail_hook_ru
        || currentJobData?.script_data?.thumbnail_hook_ru
        || currentJobData?.result?.thumbnail_hook_ru
        || '';
    const topic = (saved.topic !== undefined) ? saved.topic : (currentJobData?.topic || 'НОВОСТИ');
    const showBadge = (saved.show_badge !== undefined) ? Boolean(saved.show_badge && topic) : Boolean(topic);
    
    thumbEditorState.title = hook;
    thumbEditorState.topic = topic;
    thumbEditorState.showBadge = showBadge;
    thumbEditorState.flipHorizontal = Boolean(saved.flip_horizontal);
    thumbEditorState.fontSize = (saved.font_size !== undefined && saved.font_size !== null) ? saved.font_size : null;
    thumbEditorState.textAlign = saved.text_align || 'left';
    
    if (saved.text_x !== undefined && saved.text_x !== null && saved.text_y !== undefined && saved.text_y !== null) {
        thumbEditorState.isCustomPos = true;
        thumbEditorState.textXPercent = Math.round((saved.text_x / 1280) * 1000) / 10;
        thumbEditorState.textYPercent = Math.round((saved.text_y / 720) * 1000) / 10;
    } else {
        thumbEditorState.isCustomPos = false;
    }
    
    titleInput.value = hook;
    topicInput.value = topic;
    if (badgeCheck) badgeCheck.checked = showBadge;
    
    // Set toolbar UI elements according to restored state
    const flipBtn = document.getElementById('btnFlipPhoto');
    if (flipBtn) flipBtn.classList.toggle('active', thumbEditorState.flipHorizontal);
    setThumbFontSizePreset(thumbEditorState.fontSize);
    setThumbAlign(thumbEditorState.textAlign);

    const titleRuWrap = document.getElementById('modalThumbTitleRu');
    const titleRuSpan = document.getElementById('modalThumbTitleRuText');
    if (hookRu && titleRuWrap && titleRuSpan) {
        titleRuSpan.textContent = hookRu;
        titleRuWrap.style.display = 'block';
    } else if (titleRuWrap) {
        titleRuWrap.style.display = 'none';
    }

    const variantsWrap = document.getElementById('modalThumbVariantsWrap');
    if (variantsWrap) variantsWrap.style.display = 'none';
    
    modal.style.display = 'flex';
    setThumbLoading(false);
    
    initThumbDragAndDrop();
    updateThumbLiveOverlay();
    
    // Automatically fetch candidates and saved settings for this story
    await loadThumbCandidates();
}

async function generateAiHeadlineVariants() {
    const btn = document.getElementById('btnAiRegenTitle');
    const wrap = document.getElementById('modalThumbVariantsWrap');
    const list = document.getElementById('modalThumbVariantsList');
    if (!wrap || !list) return;

    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> Подбор...';
    wrap.style.display = 'block';
    list.innerHTML = '<div style="color: var(--text-muted); padding: 8px; font-size: 13px;">🤖 ИИ генерирует кликбейтные заголовки с переводом...</div>';

    try {
        const resp = await fetch(`/api/job/${currentJobId}/thumbnail/generate-titles`, {
            method: 'POST',
        });
        if (!resp.ok) throw new Error('Ошибка генерации');
        const data = await resp.json();
        const variants = data.variants || [];

        if (variants.length === 0) {
            list.innerHTML = '<div style="color: var(--error); padding: 8px;">Не удалось сгенерировать варианты.</div>';
            return;
        }

        list.innerHTML = variants.map(v => {
            const escapedText = escapeHtml(v.text);
            const escapedRu = escapeHtml(v.text_ru);
            return `
                <div class="thumb-variant-card" onclick="selectHeadlineVariant('${encodeURIComponent(v.text)}', '${encodeURIComponent(v.text_ru)}')" style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); padding: 8px 12px; border-radius: 6px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#34d399'" onmouseout="this.style.borderColor='rgba(255,255,255,0.12)'">
                    <div style="font-weight: 700; color: #fff; font-size: 13px;">${escapedText}</div>
                    <div style="color: #60a5fa; font-size: 12px; margin-top: 3px;">🇷🇺 ${escapedRu}</div>
                </div>
            `;
        }).join('');
    } catch (e) {
        list.innerHTML = `<div style="color: var(--error); padding: 8px;">${e.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>✨</span> Варианты AI';
    }
}

async function selectHeadlineVariant(encodedText, encodedRu) {
    const text = decodeURIComponent(encodedText);
    const ru = decodeURIComponent(encodedRu);
    const titleInput = document.getElementById('modalThumbTitle');
    const titleRuWrap = document.getElementById('modalThumbTitleRu');
    const titleRuSpan = document.getElementById('modalThumbTitleRuText');
    
    titleInput.value = text;
    thumbEditorState.title = text;
    if (titleRuWrap && titleRuSpan) {
        titleRuSpan.textContent = ru;
        titleRuWrap.style.display = 'block';
    }
    document.getElementById('modalThumbVariantsWrap').style.display = 'none';

    updateThumbLiveOverlay();
    await applyAndSaveThumbnail();
}

let thumbInputTimeout = null;
function onThumbTitleInput() {
    clearTimeout(thumbInputTimeout);
    const titleInput = document.getElementById('modalThumbTitle');
    const title = titleInput ? titleInput.value.trim() : '';
    thumbEditorState.title = title;
    
    // Instantly update live draggable preview
    updateThumbLiveOverlay();
    
    const titleRuWrap = document.getElementById('modalThumbTitleRu');
    const titleRuSpan = document.getElementById('modalThumbTitleRuText');
    if (!title) {
        if (titleRuWrap) titleRuWrap.style.display = 'none';
        return;
    }
    thumbInputTimeout = setTimeout(async () => {
        try {
            const resp = await fetch('/api/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: title }),
            });
            if (resp.ok) {
                const data = await resp.json();
                if (data.translation && titleRuWrap && titleRuSpan) {
                    titleRuSpan.textContent = data.translation;
                    titleRuWrap.style.display = 'block';
                }
            }
        } catch(e) {}
    }, 600);
}

function closeThumbnailModal(event) {
    if (event && event.target && event.target.id !== 'thumbnailModal' && !event.target.classList.contains('modal-close') && !event.target.classList.contains('btn-close-modal')) return;
    const modal = document.getElementById('thumbnailModal');
    if (modal) modal.style.display = 'none';
}

async function loadThumbCandidates(customQuery = '') {
    const grid = document.getElementById('thumbCandidatesGrid');
    const sec = document.getElementById('thumbCandidatesSection');
    const queryInput = document.getElementById('modalThumbQuery');
    
    sec.style.display = 'block';
    grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 24px; color: var(--text-muted);">⏳ Поиск вариантов фона в Яндекс Картинках...</div>';
    
    try {
        const qParam = customQuery ? `?query=${encodeURIComponent(customQuery)}` : '';
        const resp = await fetch(`/api/job/${currentJobId}/thumbnail/candidates${qParam}`);
        if (!resp.ok) throw new Error('Не удалось найти изображения');
        const data = await resp.json();
        
        if (!customQuery && data.query) {
            queryInput.value = data.query;
        }
        
        // Restore saved settings if present
        if (data.show_badge !== undefined) {
            thumbEditorState.showBadge = Boolean(data.show_badge);
            const chk = document.getElementById('modalThumbShowBadge');
            if (chk) chk.checked = thumbEditorState.showBadge;
        }
        if (data.font_size !== undefined && data.font_size !== null) {
            setThumbFontSizePreset(data.font_size);
        }
        if (data.text_align) {
            setThumbAlign(data.text_align);
        }
        if (data.text_x !== undefined && data.text_x !== null && data.text_y !== undefined && data.text_y !== null) {
            thumbEditorState.isCustomPos = true;
            thumbEditorState.textXPercent = Math.round((data.text_x / 1280) * 1000) / 10;
            thumbEditorState.textYPercent = Math.round((data.text_y / 720) * 1000) / 10;
        }
        if (data.current_topic !== undefined) {
            const topicInput = document.getElementById('modalThumbTopic');
            if (topicInput) topicInput.value = data.current_topic;
            thumbEditorState.topic = data.current_topic;
        }
        updateThumbLiveOverlay();
        
        let oldThumbNotice = '';
        if (data.has_clean_bg === false) {
            oldThumbNotice = '<div style="grid-column: 1/-1; background: rgba(255, 170, 0, 0.12); border: 1px solid rgba(255, 170, 0, 0.35); border-radius: 8px; padding: 10px 14px; font-size: 13px; color: #ffca28; margin-bottom: 8px;">⚠️ <b>Старая обложка:</b> Исходный чистый кадр без надписей не сохранён для этого старого ролика. Нажмите <b>«🎲 Случайное фото»</b> или кликните любой вариант ниже, чтобы получить чистую основу без дублирования надписей.</div>';
        }
        
        if (!data.candidates || data.candidates.length === 0) {
            grid.innerHTML = oldThumbNotice + '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: var(--text-muted);">Фото не найдены. Попробуйте другой запрос выше.</div>';
            return;
        }
        
        grid.innerHTML = oldThumbNotice + data.candidates.map((c) => {
            const rawUrl = c.thumbnail || c.url;
            const proxyUrl = `/api/proxy-thumb?url=${encodeURIComponent(rawUrl)}`;
            return `
            <div class="thumb-candidate-card" onclick="selectCandidateImage('${encodeURIComponent(c.url)}')">
                <img src="${proxyUrl}" 
                     referrerpolicy="no-referrer" 
                     loading="lazy" 
                     onerror="if (!this.dataset.triedRaw) { this.dataset.triedRaw = '1'; this.src = '${rawUrl}'; } else { this.closest('.thumb-candidate-card')?.remove(); }" />
            </div>
            `;
        }).join('');
    } catch(err) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: var(--error);">${err.message}</div>`;
    }
}

async function searchThumbCandidates() {
    const q = document.getElementById('modalThumbQuery').value.trim();
    if (q) {
        await loadThumbCandidates(q);
    }
}

async function selectCandidateImage(encodedUrl) {
    const rawUrl = decodeURIComponent(encodedUrl);
    setThumbLoading(true, "Скачивание и создание обложки...");
    
    try {
        const payload = getThumbnailPayload({ image_url: rawUrl });
        const resp = await fetch(`/api/job/${currentJobId}/thumbnail/regenerate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!resp.ok) throw new Error('Ошибка генерации');
        const data = await resp.json();
        
        // Refresh previews
        const newUrl = `${data.thumbnail_url}&t=${Date.now()}`;
        const modalPrev = document.getElementById('modalThumbPreview');
        if (modalPrev) {
            modalPrev.src = `/api/job/${currentJobId}/thumbnail-bg?t=${Date.now()}`;
            modalPrev.style.transform = 'none';
        }
        thumbEditorState.flipHorizontal = false;
        const btnFlip = document.getElementById('btnFlipPhoto');
        if (btnFlip) btnFlip.classList.remove('active');
        
        const resImg = document.getElementById('resultThumbImg');
        if (resImg) resImg.src = newUrl;
        const dlBtn = document.getElementById('btnDownloadThumb');
        if (dlBtn) dlBtn.href = `/api/download/${currentJobId}/thumbnail?t=${Date.now()}`;
        
        // Mark clicked card
        document.querySelectorAll('.thumb-candidate-card').forEach(card => card.classList.remove('active'));
        if (window.event && window.event.currentTarget) {
            window.event.currentTarget.classList.add('active');
        }
        updateThumbLiveOverlay();
    } catch(err) {
        alert('Ошибка при смене обложки: ' + err.message);
    } finally {
        setThumbLoading(false);
    }
}

async function quickRandomThumb() {
    thumbRandomOffset += 1;
    setThumbLoading(true, "Подбираем другое фото...");
    
    try {
        const q = document.getElementById('modalThumbQuery').value.trim();
        const payload = getThumbnailPayload({ query: q, offset: thumbRandomOffset });
        
        const resp = await fetch(`/api/job/${currentJobId}/thumbnail/regenerate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!resp.ok) throw new Error('Ошибка генерации');
        const data = await resp.json();
        
        const newUrl = `${data.thumbnail_url}&t=${Date.now()}`;
        const modalPrev = document.getElementById('modalThumbPreview');
        if (modalPrev) {
            modalPrev.src = `/api/job/${currentJobId}/thumbnail-bg?t=${Date.now()}`;
            modalPrev.style.transform = 'none';
        }
        thumbEditorState.flipHorizontal = false;
        const btnFlip = document.getElementById('btnFlipPhoto');
        if (btnFlip) btnFlip.classList.remove('active');
        
        const resImg = document.getElementById('resultThumbImg');
        if (resImg) resImg.src = newUrl;
        const dlBtn = document.getElementById('btnDownloadThumb');
        if (dlBtn) dlBtn.href = `/api/download/${currentJobId}/thumbnail?t=${Date.now()}`;
        updateThumbLiveOverlay();
    } catch(err) {
        alert('Не удалось сменить фото: ' + err.message);
    } finally {
        setThumbLoading(false);
    }
}

async function handleThumbFileUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    
    setThumbLoading(true, "Загрузка вашего фото и рендеринг...");
    
    try {
        const payload = getThumbnailPayload();
        const formData = new FormData();
        formData.append('file', file);
        formData.append('title', payload.title);
        formData.append('topic', payload.topic);
        formData.append('show_badge', payload.show_badge);
        if (payload.font_size !== null) formData.append('font_size', payload.font_size);
        if (payload.text_x !== null) formData.append('text_x', payload.text_x);
        if (payload.text_y !== null) formData.append('text_y', payload.text_y);
        formData.append('text_align', payload.text_align);
        formData.append('flip_horizontal', payload.flip_horizontal);
        
        const resp = await fetch(`/api/job/${currentJobId}/thumbnail/upload`, {
            method: 'POST',
            body: formData,
        });
        
        if (!resp.ok) throw new Error('Ошибка загрузки фото');
        const data = await resp.json();
        
        const newUrl = `${data.thumbnail_url}&t=${Date.now()}`;
        const modalPrev = document.getElementById('modalThumbPreview');
        if (modalPrev) {
            modalPrev.src = `/api/job/${currentJobId}/thumbnail-bg?t=${Date.now()}`;
            modalPrev.style.transform = 'none';
        }
        thumbEditorState.flipHorizontal = false;
        const btnFlip = document.getElementById('btnFlipPhoto');
        if (btnFlip) btnFlip.classList.remove('active');
        
        const resImg = document.getElementById('resultThumbImg');
        if (resImg) resImg.src = newUrl;
        const dlBtn = document.getElementById('btnDownloadThumb');
        if (dlBtn) dlBtn.href = `/api/download/${currentJobId}/thumbnail?t=${Date.now()}`;
        updateThumbLiveOverlay();
    } catch(err) {
        alert('Ошибка загрузки: ' + err.message);
    } finally {
        setThumbLoading(false);
        event.target.value = '';
    }
}

async function applyAndSaveThumbnail() {
    const btn = document.getElementById('btnSaveThumbModal');
    btn.disabled = true;
    btn.textContent = 'Сохранение...';
    
    try {
        const payload = getThumbnailPayload();
        const resp = await fetch(`/api/job/${currentJobId}/thumbnail/regenerate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!resp.ok) throw new Error('Не удалось обновить');
        const data = await resp.json();
        
        const newUrl = `${data.thumbnail_url}&t=${Date.now()}`;
        const modalPrev = document.getElementById('modalThumbPreview');
        if (modalPrev) {
            modalPrev.src = newUrl;
            modalPrev.style.transform = 'none';
        }
        thumbEditorState.flipHorizontal = false;
        const btnFlip = document.getElementById('btnFlipPhoto');
        if (btnFlip) btnFlip.classList.remove('active');
        
        const resImg = document.getElementById('resultThumbImg');
        if (resImg) resImg.src = newUrl;
        const dlBtn = document.getElementById('btnDownloadThumb');
        if (dlBtn) dlBtn.href = `/api/download/${currentJobId}/thumbnail?t=${Date.now()}`;
        
        // Update history card thumbnail
        const histThumb = document.querySelector(`#hist-item-${currentJobId} .history-thumb-mini`);
        if (histThumb) {
            histThumb.src = newUrl;
            histThumb.style.display = 'block';
        }
        
        // Update completed modal thumbnail if visible
        const compThumb = document.getElementById('completedModalThumb');
        if (compThumb) compThumb.src = newUrl;
        
        // Cache settings locally on job
        if (currentJobData) {
            if (!currentJobData.thumbnail_settings) currentJobData.thumbnail_settings = {};
            Object.assign(currentJobData.thumbnail_settings, payload);
            currentJobData.thumbnail_hook = payload.title;
            currentJobData.topic = payload.topic;
        }
        
        closeThumbnailModal();
    } catch(err) {
        alert('Ошибка сохранения: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '✓ Применить текст и сохранить';
    }
}

// === Sources & Fact Confirmation Modal ===
async function openSourcesModal() {
    if (!currentJobId) return;
    const modal = document.getElementById('sourcesModal');
    const metaEl = document.getElementById('modalSourcesMeta');
    const bodyEl = document.getElementById('modalSourcesBody');
    
    modal.style.display = 'flex';
    bodyEl.innerHTML = '<div style="text-align:center;padding:35px;color:var(--text-muted)">⏳ Загрузка проверенной фактуры и текстов статей...</div>';
    
    try {
        const resp = await fetch(`/api/job/${currentJobId}/sources`);
        if (!resp.ok) {
            throw new Error('Первоисточники для этого ролика еще формируются или не найдены');
        }
        const data = await resp.json();
        const sources = data.sources || [];
        const summary = data.summary || {};
        
        const count = summary.count || sources.filter(s => (s.text_len || 0) >= 250).length;
        const totalChars = (summary.total_chars || sources.reduce((a, s) => a + (s.text_len || 0), 0)).toLocaleString('ru-RU');
        
        metaEl.innerHTML = `<span>📰 Полных текстов статей: <b>${count}</b></span> · <span>📊 Объём фактуры: <b>${totalChars}</b> знаков</span> · <span>🤖 Модель: <b>Gemini AI</b></span>`;
        
        if (!sources.length) {
            bodyEl.innerHTML = '<div style="padding:30px;text-align:center;color:var(--text-muted)">Статьи не найдены</div>';
            return;
        }
        
        bodyEl.innerHTML = sources.map((art, idx) => {
            const agency = art.source || 'Информационное агентство';
            const chars = (art.text_len || (art.full_text ? art.full_text.length : 0)).toLocaleString('ru-RU');
            const rawText = (art.full_text || art.preview || 'Текст не извлечен').trim();
            const hasFullText = (art.text_len || 0) >= 250;
            const badgeColor = hasFullText ? '#10b981' : '#f59e0b';
            const statusLabel = hasFullText ? `✓ Полный текст (${chars} знаков)` : `Краткий сниппет (${chars} знаков)`;
            const linkHtml = art.url ? `<a href="${art.url}" target="_blank" rel="noopener noreferrer" class="source-link-out">↗ Открыть оригинал статьи</a>` : '';
            
            return `
            <div class="source-article-card">
                <div class="source-article-top">
                    <div class="source-article-tags">
                        <span class="source-agency-badge">${agency}</span>
                        <span class="source-status-badge" style="background:${badgeColor}20; color:${badgeColor}; border:1px solid ${badgeColor}40;">${statusLabel}</span>
                    </div>
                    ${linkHtml}
                </div>
                <h4 class="source-article-title">${art.title}</h4>
                <div class="source-text-block">
                    <div class="source-text-label">
                        <span>Сырой текст статьи, переданный в Gemini AI:</span>
                    </div>
                    <div class="source-text-body">${rawText.replace(/\n/g, '<br>')}</div>
                </div>
            </div>
            `;
        }).join('');
        
    } catch (e) {
        bodyEl.innerHTML = `<div style="color:var(--error);padding:25px;text-align:center;">${e.message}</div>`;
    }
}

function closeSourcesModal(e) {
    if (e && e.target && e.target.id !== 'sourcesModal' && !e.target.classList.contains('modal-close') && !e.target.classList.contains('btn-close-modal')) {
        return;
    }
    const modal = document.getElementById('sourcesModal');
    if (modal) modal.style.display = 'none';
}

function closeResultSourcesCard() {
    const card = document.getElementById('resultSourcesCard');
    if (card) {
        card.style.display = 'none';
    }
}

// === Completion Modal & Smooth Queue Transitions ===
let lastCompletedJob = null;
let nextQueueJob = null;

async function handleJobCompleted(job) {
    lastCompletedJob = job;
    
    // Check if next job is already queued/running
    nextQueueJob = null;
    try {
        const qRes = await fetch('/api/queue');
        if (qRes.ok) {
            const qData = await qRes.json();
            const queue = qData.queue || [];
            nextQueueJob = queue.find(j => j.id !== job.id) || null;
        }
    } catch(e) {}
    
    showCompletedModal(job, nextQueueJob);
    checkBackgroundQueue();
}

function showCompletedModal(job, nextJob) {
    const modal = document.getElementById('jobCompletedModal');
    if (!modal) return;
    
    const titleEl = document.getElementById('completedModalTitle');
    const topicEl = document.getElementById('completedModalTopic');
    const statsEl = document.getElementById('completedModalStats');
    const thumbImg = document.getElementById('completedModalThumb');
    const dlVideo = document.getElementById('btnCompletedVideo');
    const dlThumb = document.getElementById('btnCompletedThumb');
    const queueCard = document.getElementById('completedQueueCard');
    const queueTopic = document.getElementById('completedQueueTopic');
    
    const result = job.result || {};
    titleEl.textContent = result.title || job.topic;
    
    const titleRuEl = document.getElementById('completedModalTitleRu');
    const titleRu = result.title_ru || job.title_ru;
    if (titleRu && titleRuEl) {
        titleRuEl.textContent = `🇷🇺 Перевод: ${titleRu}`;
        titleRuEl.style.display = 'block';
    } else if (titleRuEl) {
        titleRuEl.style.display = 'none';
    }

    topicEl.textContent = job.topic || 'НОВОСТИ';
    const thumbTextEl = document.getElementById('completedModalThumbText');
    const hook = result.thumbnail_hook || job.thumbnail_hook;
    const hookRu = result.thumbnail_hook_ru || job.thumbnail_hook_ru;
    if (hook && thumbTextEl) {
        thumbTextEl.textContent = `🖼️ Обложка: ${hook}` + (hookRu ? ` (🇷🇺 ${hookRu})` : '');
        thumbTextEl.style.display = 'block';
    } else if (thumbTextEl) {
        thumbTextEl.style.display = 'none';
    }
    
    const scriptLen = result.script_length || 0;
    const segments = result.segments_count || 0;
    const approxMin = Math.max(1, Math.round(scriptLen / 850));
    statsEl.innerHTML = `<span>⏱️ ~${approxMin} мин</span> · <span>📝 ${scriptLen.toLocaleString('ru-RU')} знаков</span> · <span>🖼️ ${segments} слайдов</span>`;
    
    thumbImg.src = `/api/job/${job.id}/thumbnail?t=${Date.now()}`;
    dlVideo.href = `/api/download/${job.id}/video`;
    dlThumb.href = `/api/download/${job.id}/thumbnail`;
    
    if (nextJob) {
        queueCard.style.display = 'flex';
        queueTopic.textContent = nextJob.topic || 'Следующий ролик';
    } else {
        queueCard.style.display = 'none';
    }
    
    modal.style.display = 'flex';
}

function closeCompletedModal(e) {
    if (e && e.target && e.target.id !== 'jobCompletedModal' && !e.target.classList.contains('modal-close') && !e.target.classList.contains('btn-close-modal')) {
        return;
    }
    const modal = document.getElementById('jobCompletedModal');
    if (modal) modal.style.display = 'none';
}

function openThumbFromCompletedModal() {
    if (!lastCompletedJob) return;
    closeCompletedModal();
    openThumbnailModal(lastCompletedJob.id);
}

function openScriptFromCompletedModal() {
    if (!lastCompletedJob) return;
    closeCompletedModal();
    currentJobId = lastCompletedJob.id;
    currentJobData = lastCompletedJob;
    openScriptModal();
}

function openFullResultsFromModal() {
    if (!lastCompletedJob) return;
    closeCompletedModal();
    currentJobId = lastCompletedJob.id;
    currentJobData = lastCompletedJob;
    showResults(lastCompletedJob);
}

function switchActiveFromModal() {
    if (!nextQueueJob) return;
    closeCompletedModal();
    switchActiveJob(nextQueueJob.id);
}

// === Background Queue Tracker & Floating Pill ===
let backgroundWatcherInterval = null;
let activeRunningJob = null;

async function checkBackgroundQueue() {
    try {
        const res = await fetch('/api/queue');
        if (!res.ok) return;
        const qData = await res.json();
        const queue = qData.queue || [];
        
        const running = queue.find(j => j.status === 'running') || queue[0];
        if (running) {
            activeRunningJob = running;
            updateFloatingPill(running);
            if (!backgroundWatcherInterval) {
                backgroundWatcherInterval = setInterval(checkBackgroundQueue, 3000);
            }
        } else {
            activeRunningJob = null;
            hideFloatingPill();
            if (backgroundWatcherInterval) {
                clearInterval(backgroundWatcherInterval);
                backgroundWatcherInterval = null;
            }
        }
    } catch (e) {
        console.debug('Background queue check error:', e);
    }
}

function updateFloatingPill(job) {
    const pill = document.getElementById('activeJobFloatingPill');
    const titleEl = document.getElementById('pillJobTitle');
    const progEl = document.getElementById('pillJobProgress');
    if (!pill || !titleEl || !progEl) return;
    
    // Only show pill if user is NOT currently looking at the progress panel
    const progressPanel = document.getElementById('progressPanel');
    const isProgressActive = (progressPanel && progressPanel.style.display !== 'none');
    
    if (isProgressActive) {
        pill.style.display = 'none';
        return;
    }
    
    titleEl.textContent = job.topic || 'Без названия';
    progEl.textContent = `${job.progress || 0}% · ${job.current_step || 'В работе'}`;
    pill.style.display = 'flex';
}

function hideFloatingPill() {
    const pill = document.getElementById('activeJobFloatingPill');
    if (pill) pill.style.display = 'none';
}

function updateFloatingPillVisibility(activePanelName) {
    if (activePanelName === 'progress' || !activeRunningJob) {
        hideFloatingPill();
    } else {
        updateFloatingPill(activeRunningJob);
    }
}

function goToActiveJob() {
    if (!activeRunningJob) return;
    switchActiveJob(activeRunningJob.id);
}

async function openTelegramModal() {
    const modal = document.getElementById('telegramModal');
    const alertBox = document.getElementById('tgStatusAlert');
    if (alertBox) alertBox.style.display = 'none';

    try {
        const resp = await fetch('/api/telegram/config');
        if (resp.ok) {
            const data = await resp.json();
            const tokenInput = document.getElementById('tgBotToken');
            if (data.has_token) {
                tokenInput.value = '';
                tokenInput.placeholder = `✓ Токен сохранен (${data.bot_token_masked}). Оставьте пустым, чтобы не менять`;
            } else {
                tokenInput.value = '';
                tokenInput.placeholder = '7123456789:AAH...';
            }
            document.getElementById('tgChatId').value = data.chat_id || '';
            document.getElementById('tgServerUrl').value = data.server_url || 'http://45.147.31.53:8501';
            updateTelegramIndicator(data.enabled);
        }
    } catch(e) {
        console.warn('Failed to load telegram config:', e);
    }
    modal.style.display = 'flex';
}

function closeTelegramModal(e) {
    if (e && e.target && e.target.id !== 'telegramModal' && !e.target.classList.contains('modal-close') && !e.target.classList.contains('btn-close-modal')) return;
    const modal = document.getElementById('telegramModal');
    if (modal) modal.style.display = 'none';
}

async function saveTelegramSettings() {
    const token = document.getElementById('tgBotToken').value.trim();
    const chatId = document.getElementById('tgChatId').value.trim();
    const serverUrl = document.getElementById('tgServerUrl').value.trim();
    const alertBox = document.getElementById('tgStatusAlert');

    try {
        const resp = await fetch('/api/telegram/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                bot_token: token,
                chat_id: chatId,
                server_url: serverUrl,
                enabled: true
            })
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.15)';
            alertBox.style.color = '#34d399';
            alertBox.style.border = '1px solid #10b981';
            alertBox.textContent = '✓ Настройки Telegram сохранены!';
            updateTelegramIndicator(data.enabled);
            setTimeout(() => { closeTelegramModal(); }, 1200);
        }
    } catch(e) {
        alertBox.style.display = 'block';
        alertBox.style.background = 'rgba(239, 68, 68, 0.15)';
        alertBox.style.color = '#f87171';
        alertBox.style.border = '1px solid #ef4444';
        alertBox.textContent = 'Ошибка сохранения: ' + e.message;
    }
}

async function testTelegramSettings() {
    const token = document.getElementById('tgBotToken').value.trim();
    const chatId = document.getElementById('tgChatId').value.trim();
    const serverUrl = document.getElementById('tgServerUrl').value.trim();
    const alertBox = document.getElementById('tgStatusAlert');
    const testBtn = document.getElementById('btnTestTelegram');

    testBtn.disabled = true;
    testBtn.innerHTML = '<span>⏳</span> Отправка...';
    alertBox.style.display = 'none';

    try {
        const resp = await fetch('/api/telegram/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                bot_token: token,
                chat_id: chatId,
                server_url: serverUrl,
                enabled: true
            })
        });
        const data = await resp.json();
        alertBox.style.display = 'block';
        if (data.success) {
            alertBox.style.background = 'rgba(16, 185, 129, 0.15)';
            alertBox.style.color = '#34d399';
            alertBox.style.border = '1px solid #10b981';
            alertBox.textContent = '✓ ' + (data.message || 'Тестовое сообщение успешно отправлено!');
            updateTelegramIndicator(true);
        } else {
            alertBox.style.background = 'rgba(239, 68, 68, 0.15)';
            alertBox.style.color = '#f87171';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.textContent = '❌ ' + (data.error || 'Ошибка отправки');
        }
    } catch(e) {
        alertBox.style.display = 'block';
        alertBox.style.background = 'rgba(239, 68, 68, 0.15)';
        alertBox.style.color = '#f87171';
        alertBox.style.border = '1px solid #ef4444';
        alertBox.textContent = 'Ошибка: ' + e.message;
    } finally {
        testBtn.disabled = false;
        testBtn.innerHTML = '<span>✉️</span> Отправить тест';
    }
}

function updateTelegramIndicator(active) {
    const ind = document.getElementById('tgIndicator');
    if (ind) ind.classList.toggle('active', !!active);
}

async function checkTelegramStatusOnLoad() {
    try {
        const resp = await fetch('/api/telegram/config');
        if (resp.ok) {
            const data = await resp.json();
            updateTelegramIndicator(data.enabled);
        }
    } catch(e) {}
}

// === Slide Review Studio & Candidate Picker ===
let currentReviewJobId = null;
let currentSlidesData = [];
let currentSlideFilter = 'all';
let currentSlideSearchQuery = '';
let activeCandidateSlideIndex = null;

async function openSlideReviewModal(jobId = null) {
    const targetId = jobId || currentReviewJobId || currentJobId || localStorage.getItem('active_news_job_id');
    if (!targetId) {
        showError('Нет активной задачи для просмотра слайдов');
        return;
    }
    currentReviewJobId = targetId;
    currentJobId = targetId;

    const modal = document.getElementById('slideReviewModal');
    if (!modal) return;
    modal.style.display = 'flex';

    const grid = document.getElementById('slidesGrid');
    if (grid) {
        grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-muted);"><div class="spinner" style="margin: 0 auto 12px auto;"></div>Загрузка слайдов ролика...</div>';
    }

    try {
        const resp = await fetch(`/api/job/${targetId}/slides`);
        if (!resp.ok) throw new Error('Не удалось получить список слайдов');
        const data = await resp.json();
        
        currentSlidesData = data.slides || [];
        
        const topicEl = document.getElementById('slideModalTopic');
        if (topicEl) {
            topicEl.textContent = data.topic ? `Кадры выпуска: ${data.topic}` : 'Проверка отобранных кадров';
        }
        
        const badgeEl = document.getElementById('slideModalStatusBadge');
        if (badgeEl) {
            badgeEl.textContent = (data.status === 'awaiting_slide_review') 
                ? '⏸️ Ожидание модерации' 
                : (data.status === 'completed' ? '✓ Ролик готов' : '⚡ В процессе');
        }

        updateSlideCounters();
        renderSlidesGrid();
    } catch (e) {
        console.error('Failed to load slides:', e);
        if (grid) {
            grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 30px; color: var(--error);">Ошибка: ${escapeHtml(e.message)}</div>`;
        }
    }
}

function closeSlideReviewModal(e) {
    if (e && e.target && e.target !== e.currentTarget) return;
    const modal = document.getElementById('slideReviewModal');
    if (modal) modal.style.display = 'none';
}

function updateSlideCounters() {
    const total = currentSlidesData.length;
    const flagged = currentSlidesData.filter(s => s.flagged).length;
    const replaced = currentSlidesData.filter(s => s.replaced).length;

    const countAll = document.getElementById('countAllSlides');
    const countFlagged = document.getElementById('countFlaggedSlides');
    const countReplaced = document.getElementById('countReplacedSlides');
    const countAction = document.getElementById('countFlaggedAction');
    const btnBulk = document.getElementById('btnBulkReplace');

    if (countAll) countAll.textContent = total;
    if (countFlagged) countFlagged.textContent = flagged;
    if (countReplaced) countReplaced.textContent = replaced;
    if (countAction) countAction.textContent = flagged;

    if (btnBulk) {
        btnBulk.disabled = (flagged === 0);
    }
}

function filterSlides(type) {
    currentSlideFilter = type;
    document.querySelectorAll('.slide-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === type);
    });
    renderSlidesGrid();
}

function onSlideSearchInput(val) {
    currentSlideSearchQuery = (val || '').toLowerCase().trim();
    renderSlidesGrid();
}

function renderSlidesGrid() {
    const grid = document.getElementById('slidesGrid');
    if (!grid) return;

    let filtered = currentSlidesData.slice();

    if (currentSlideFilter === 'flagged') {
        filtered = filtered.filter(s => s.flagged);
    } else if (currentSlideFilter === 'replaced') {
        filtered = filtered.filter(s => s.replaced);
    }

    if (currentSlideSearchQuery) {
        filtered = filtered.filter(s => {
            const num = '#' + (s.index + 1);
            const text = (s.text || '').toLowerCase();
            const query = (s.query || '').toLowerCase();
            return num.includes(currentSlideSearchQuery) || text.includes(currentSlideSearchQuery) || query.includes(currentSlideSearchQuery);
        });
    }

    if (filtered.length === 0) {
        grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-muted);">Нет слайдов, соответствующих фильтру</div>';
        return;
    }

    grid.innerHTML = filtered.map(s => {
        const durStr = s.duration_sec ? `${s.duration_sec}s` : '5s';
        const isFlagged = !!s.flagged;
        const isReplaced = !!s.replaced;
        
        let cardClass = 'slide-card';
        if (isFlagged) cardClass += ' flagged';
        if (isReplaced) cardClass += ' replaced';

        return `
            <div class="${cardClass}" id="slideCard_${s.index}">
                <div class="slide-card-thumb-wrap" onclick="openCandidatePicker(${s.index})" title="Нажмите, чтобы подобрать альтернативное фото">
                    <img src="${s.thumb_url || s.image_url}" data-full="${s.image_url}" alt="Слайд #${s.index + 1}" loading="lazy" id="slideImg_${s.index}" />
                    <div class="slide-card-index-chip">
                        <span>#${s.index + 1}</span> · <span>⏱️ ${durStr}</span>
                    </div>
                    ${isFlagged ? '<div class="slide-card-status-badge flagged">❌ На замену</div>' : ''}
                    ${isReplaced && !isFlagged ? '<div class="slide-card-status-badge replaced">✓ Заменено</div>' : ''}
                </div>
                <div class="slide-card-body">
                    <div class="slide-card-text" title="${escapeHtml(s.text || '')}">
                        «${escapeHtml(s.text || 'Дикторское сопровождение')}»
                    </div>
                    ${s.query ? `<div class="slide-card-query" title="${escapeHtml(s.query)}"><b>Запрос:</b> ${escapeHtml(s.query)}</div>` : ''}
                    <div class="slide-card-actions">
                        <button type="button" class="btn-card-flag ${isFlagged ? 'active' : ''}" onclick="toggleSlideFlag(${s.index})">
                            ${isFlagged ? '❌ Отмечено на замену' : '🚩 Отметить на замену'}
                        </button>
                        <button type="button" class="btn-card-action" onclick="openCandidatePicker(${s.index})" title="Подобрать другое фото">
                            <span>🔍</span> Подобрать
                        </button>
                        <button type="button" class="btn-card-action" onclick="quickCycleSlide(${s.index})" title="Случайная замена из пула">
                            <span>🎲</span> Пул
                        </button>
                        <input type="file" id="slideUploadInput_${s.index}" accept="image/*" style="display: none;" onchange="handleSlideCardUpload(${s.index}, event)" />
                        <button type="button" class="btn-card-action" onclick="document.getElementById('slideUploadInput_${s.index}').click()" title="Загрузить свое фото">
                            <span>📁</span> Своё
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function toggleSlideFlag(index) {
    const slide = currentSlidesData.find(s => s.index === index);
    if (!slide) return;

    slide.flagged = !slide.flagged;
    updateSlideCounters();

    // Optimistic UI update
    const card = document.getElementById(`slideCard_${index}`);
    if (card) {
        card.classList.toggle('flagged', slide.flagged);
        const flagBtn = card.querySelector('.btn-card-flag');
        if (flagBtn) {
            flagBtn.classList.toggle('active', slide.flagged);
            flagBtn.textContent = slide.flagged ? '❌ Отмечено на замену' : '🚩 Отметить на замену';
        }
    }

    try {
        await fetch(`/api/job/${currentReviewJobId}/slide/${index}/flag`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flagged: slide.flagged }),
        });
    } catch (e) {
        console.error('Flag toggle error:', e);
    }
}

async function quickCycleSlide(index) {
    if (!currentReviewJobId) return;
    const card = document.getElementById(`slideCard_${index}`);
    if (card) card.style.opacity = '0.6';

    try {
        const resp = await fetch(`/api/job/${currentReviewJobId}/slide/${index}/quick-cycle`, { method: 'POST' });
        if (!resp.ok) throw new Error('Не удалось сменить фото из пула');
        const data = await resp.json();

        const slide = currentSlidesData.find(s => s.index === index);
        if (slide) {
            slide.image_url = data.image_url;
            slide.thumb_url = data.thumb_url || data.image_url;
            slide.replaced = true;
            slide.flagged = false;
        }
        updateSlideCounters();
        renderSlidesGrid();
    } catch (e) {
        alert(e.message);
    } finally {
        if (card) card.style.opacity = '1';
    }
}

async function handleSlideCardUpload(index, event) {
    const file = event.target.files && event.target.files[0];
    if (!file || !currentReviewJobId) return;

    const formData = new FormData();
    formData.append('file', file);

    const card = document.getElementById(`slideCard_${index}`);
    if (card) card.style.opacity = '0.6';

    try {
        const resp = await fetch(`/api/job/${currentReviewJobId}/slide/${index}/upload`, {
            method: 'POST',
            body: formData,
        });
        if (!resp.ok) throw new Error('Не удалось загрузить изображение');
        const data = await resp.json();

        const slide = currentSlidesData.find(s => s.index === index);
        if (slide) {
            slide.image_url = data.image_url;
            slide.thumb_url = data.thumb_url || data.image_url;
            slide.replaced = true;
            slide.flagged = false;
        }
        updateSlideCounters();
        renderSlidesGrid();
    } catch (e) {
        alert(e.message);
    } finally {
        if (card) card.style.opacity = '1';
        event.target.value = '';
    }
}

async function replaceFlaggedSlidesBatch() {
    if (!currentReviewJobId) return;
    const flaggedCount = currentSlidesData.filter(s => s.flagged).length;
    if (flaggedCount === 0) return;

    const btn = document.getElementById('btnBulkReplace');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span>⏳</span> Заменяем ${flaggedCount} слайдов...`;
    }

    try {
        const resp = await fetch(`/api/job/${currentReviewJobId}/slides/replace-flagged`, { method: 'POST' });
        if (!resp.ok) throw new Error('Ошибка массовой автозамены');
        const data = await resp.json();

        // Reload slides
        await openSlideReviewModal(currentReviewJobId);
        alert(`✓ Успешно заменено слайдов: ${data.replaced_count || flaggedCount}`);
    } catch (e) {
        alert('Ошибка: ' + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<span>🔄</span> Заменить отмеченные (${document.getElementById('countFlaggedSlides')?.textContent || 0})`;
        }
    }
}

// === Candidate Picker Modal ===
let currentCandidateTopic = '';
let currentCandidateTitle = '';

async function openCandidatePicker(index) {
    activeCandidateSlideIndex = index;
    const slide = currentSlidesData.find(s => s.index === index);
    if (!slide) return;

    const modal = document.getElementById('slideCandidateModal');
    if (!modal) return;
    modal.style.display = 'flex';

    document.getElementById('candidateSlideIndex').textContent = index + 1;
    document.getElementById('candidateCurrentImg').src = slide.image_url;
    document.getElementById('candidateCurrentText').textContent = slide.text || '';
    
    const searchInput = document.getElementById('candidateSearchInput');
    // Clear search input initially so backend constructs smart thematic query
    searchInput.value = '';

    await searchCandidatePhotos('');
}

function closeSlideCandidateModal(e) {
    if (e && e.target && e.target !== e.currentTarget) return;
    const modal = document.getElementById('slideCandidateModal');
    if (modal) modal.style.display = 'none';
    activeCandidateSlideIndex = null;
}

function applyCandidatePreset(type) {
    const input = document.getElementById('candidateSearchInput');
    if (!input) return;

    const topic = currentCandidateTopic || 'Nachrichten Deutschland';
    const title = currentCandidateTitle || topic;

    if (type === 'topic') {
        input.value = topic;
    } else if (type === 'title') {
        input.value = title.length > 50 ? title.slice(0, 50) : title;
    } else if (type === 'politics') {
        input.value = `${topic} Politik Debatte`;
    } else if (type === 'action') {
        input.value = `${topic} Kontrolle Polizei Einsatz`;
    }
    searchCandidatePhotos(input.value);
}

async function searchCandidatePhotos(customQuery = null) {
    if (activeCandidateSlideIndex === null || !currentReviewJobId) return;

    const queryInput = document.getElementById('candidateSearchInput');
    const query = customQuery !== null ? customQuery : (queryInput ? queryInput.value.trim() : '');

    const loader = document.getElementById('candidateLoadingIndicator');
    const grid = document.getElementById('candidatesResultsGrid');

    if (loader) {
        loader.style.display = 'block';
        const txt = loader.querySelector('span');
        if (txt) txt.textContent = 'Поиск лучших новостных фото по теме...';
    }
    if (grid) grid.innerHTML = '';

    try {
        const resp = await fetch(`/api/job/${currentReviewJobId}/slide/${activeCandidateSlideIndex}/search-candidates`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query }),
        });
        if (!resp.ok) throw new Error('Поиск фото не дал результатов');
        const data = await resp.json();

        if (loader) loader.style.display = 'none';

        if (data.query && queryInput) {
            queryInput.value = data.query;
        }
        if (data.topic) currentCandidateTopic = data.topic;
        if (data.title) currentCandidateTitle = data.title;

        const candidates = data.candidates || [];
        window.currentCandidatesList = candidates;
        if (candidates.length === 0) {
            if (grid) grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 20px; color: var(--text-muted);">Ничего не найдено. Нажмите «Тема выпуска» или измените поисковый запрос.</div>';
            return;
        }

        if (grid) {
            grid.innerHTML = candidates.map((c, idx) => {
                const thumbSrc = c.thumbnail || c.url;
                const proxySrc = c.proxy_url || c.url;
                return `
                <div class="candidate-photo-card ${c.already_used ? 'is-already-used' : 'is-fresh'}" 
                     data-cand-idx="${idx}" 
                     title="${c.already_used ? 'Уже использовалось в ролике — кликните для применения' : 'Свежее фото — кликните, чтобы применить'}">
                    <img src="${thumbSrc}" 
                         alt="${escapeHtml(c.alt || '')}" 
                         loading="lazy" 
                         onerror="if(this.src!=='${proxySrc}'){this.src='${proxySrc}';}else{this.style.opacity='0.2';}" />
                    <span class="candidate-photo-source">${escapeHtml(c.source || 'web')}</span>
                    ${c.already_used 
                        ? '<span class="candidate-badge used" style="position: absolute; top: 6px; left: 6px; background: rgba(239, 68, 68, 0.85); color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold;">В ролике</span>' 
                        : '<span class="candidate-badge fresh" style="position: absolute; top: 6px; left: 6px; background: rgba(16, 185, 129, 0.85); color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold;">✨ Свежее</span>'}
                </div>
            `;
            }).join('');

            grid.onclick = (e) => {
                const card = e.target.closest('.candidate-photo-card');
                if (!card) return;
                const idx = parseInt(card.dataset.candIdx, 10);
                const cand = window.currentCandidatesList?.[idx];
                if (cand && cand.url) {
                    selectCandidate(cand.url, cand.fallback_url || '', cand.thumbnail || '');
                }
            };
        }
    } catch (e) {
        if (loader) loader.style.display = 'none';
        if (grid) grid.innerHTML = `<div style="grid-column: 1 / -1; color: var(--error); padding: 20px; text-align: center;">Ошибка: ${escapeHtml(e.message)}</div>`;
    }
}

async function selectCandidate(url, fallbackUrl = '', thumbUrl = '') {
    if (activeCandidateSlideIndex === null || !currentReviewJobId) return;

    const loader = document.getElementById('candidateLoadingIndicator');
    if (loader) {
        loader.style.display = 'block';
        loader.querySelector('span').textContent = 'Скачивание и применение фото...';
    }

    try {
        const resp = await fetch(`/api/job/${currentReviewJobId}/slide/${activeCandidateSlideIndex}/select-candidate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, fallback_url: fallbackUrl, thumbnail: thumbUrl }),
        });
        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.detail || 'Не удалось скачать выбранное фото');
        }
        const data = await resp.json();

        const slide = currentSlidesData.find(s => s.index === activeCandidateSlideIndex);
        if (slide) {
            slide.image_url = data.image_url;
            slide.thumb_url = data.thumb_url || data.image_url;
            slide.replaced = true;
            slide.flagged = false;
            const curQ = document.getElementById('candidateSearchInput')?.value;
            if (curQ) slide.query = curQ;
        }
        updateSlideCounters();
        renderSlidesGrid();
        closeSlideCandidateModal();
    } catch (e) {
        alert('Ошибка применения: ' + e.message);
    } finally {
        if (loader) loader.style.display = 'none';
    }
}

async function cycleFromPoolCandidate() {
    if (activeCandidateSlideIndex === null || !currentReviewJobId) return;
    await quickCycleSlide(activeCandidateSlideIndex);
    closeSlideCandidateModal();
}

async function handleCandidateFileUpload(e) {
    if (activeCandidateSlideIndex === null || !currentReviewJobId) return;
    await handleSlideCardUpload(activeCandidateSlideIndex, e);
    closeSlideCandidateModal();
}

async function approveAndCompileVideo() {
    const targetId = currentReviewJobId || currentJobId || localStorage.getItem('active_news_job_id');
    if (!targetId) return;

    const btn = document.getElementById('btnApproveSlides');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span>⏳</span> Запуск сборки видео...';
    }

    try {
        const resp = await fetch(`/api/job/${targetId}/slides/approve`, { method: 'POST' });
        if (!resp.ok) throw new Error('Ошибка запуска сборки видео');
        
        closeSlideReviewModal();
        
        const banner = document.getElementById('slideReviewBanner');
        if (banner) banner.style.display = 'none';
        
        // Resume polling
        startPolling();
    } catch (e) {
        alert('Ошибка: ' + e.message);
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span>🚀</span> Утвердить и начать сборку видео →';
        }
    }
}

async function approveSlidesDirect() {
    await approveAndCompileVideo();
}

// === Acute Topics Modal ===
let currentAcuteTopicsList = [];
let acuteCurrentOffset = 0;
let acuteExcludedIds = new Set();

async function openAcuteTopicsModal(isNext = false) {
    const modal = document.getElementById('acuteTopicsModal');
    if (!modal) return;
    modal.style.display = 'flex';

    const topicInput = document.getElementById('topicInput');
    const currentTopic = topicInput ? topicInput.value.trim() : '';
    const voiceSelect = document.getElementById('voiceSelect');
    const lang = voiceSelect ? (voiceSelect.value.startsWith('de') ? 'de' : (voiceSelect.value.startsWith('ru') ? 'ru' : 'en')) : 'de';

    const loader = document.getElementById('acuteTopicsLoadingIndicator');
    const grid = document.getElementById('acuteTopicsGrid');
    const counterBadge = document.getElementById('acuteCounterInfo');

    if (!isNext) {
        acuteCurrentOffset = 0;
        acuteExcludedIds.clear();
    } else {
        // Collect current cards and mark them as dismissed/excluded
        if (currentAcuteTopicsList && currentAcuteTopicsList.length > 0) {
            const idsToDismiss = currentAcuteTopicsList.map(t => t.id).filter(Boolean);
            idsToDismiss.forEach(id => acuteExcludedIds.add(id));
            try {
                fetch('/api/topics/acute/dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ angle_ids: idsToDismiss })
                }).catch(e => console.warn('Failed to dismiss acute angles:', e));
            } catch (_) {}
        }
        acuteCurrentOffset += 8;
    }

    if (loader) loader.style.display = 'block';
    if (grid) grid.innerHTML = '';

    try {
        const excludeParam = Array.from(acuteExcludedIds).join(',');
        const resp = await fetch(`/api/topics/acute?topic=${encodeURIComponent(currentTopic)}&lang=${lang}&offset=${acuteCurrentOffset}&exclude_ids=${encodeURIComponent(excludeParam)}`);
        if (!resp.ok) throw new Error('Не удалось получить острые сюжеты');
        const data = await resp.json();

        if (loader) loader.style.display = 'none';

        const topics = data.topics || [];
        currentAcuteTopicsList = topics;

        if (counterBadge) {
            if (data.fresh_catalog_count !== undefined) {
                counterBadge.textContent = `Доступно свежих ракурсов: ${data.fresh_catalog_count} из ${data.total_catalog}`;
            } else {
                counterBadge.textContent = '';
            }
        }

        const btnNext = document.getElementById('btnAcuteNextBatch');
        if (btnNext) {
            btnNext.style.display = 'inline-flex';
            btnNext.disabled = !data.has_more;
            if (!data.has_more) {
                btnNext.title = 'Все сюжеты из каталога уже показаны';
            } else {
                btnNext.title = 'Показать следующую порцию свежих тем';
            }
        }
        
        if (topics.length === 0) {
            if (grid) {
                grid.innerHTML = `
                    <div style="grid-column: 1 / -1; text-align: center; padding: 40px 20px; color: var(--text-muted);">
                        <div style="font-size: 32px; margin-bottom: 12px;">🏁</div>
                        <div style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">
                            Все сюжеты по теме «${escapeHtml(currentTopic || 'Все темы')}» уже использованы
                        </div>
                        <div style="font-size: 13px; margin-bottom: 16px;">
                            Вы можете сбросить историю просмотров, чтобы увидеть все ракурсы заново.
                        </div>
                        <button type="button" class="btn btn-secondary" onclick="resetAcuteHistoryUI()" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 18px; border-radius: 8px; font-weight: 600;">
                            <span>↺</span> Сбросить историю использованных тем
                        </button>
                    </div>
                `;
            }
            return;
        }

        if (grid) {
            grid.innerHTML = topics.map((t, idx) => {
                const titleRu = t.title_ru || t.title;
                const titleOrig = t.title;
                const isDifferentTitle = titleRu && titleOrig && titleRu.toLowerCase().trim() !== titleOrig.toLowerCase().trim();
                const hookRu = t.hook_sample_ru || t.hook_sample;
                const isDifferentHook = hookRu && t.hook_sample && hookRu.toLowerCase().trim() !== t.hook_sample.toLowerCase().trim();

                return `
                <div class="acute-topic-card" onclick="selectAcuteTopicByIndex(${idx})">
                    <div class="acute-topic-header">
                        <span class="acute-topic-badge">${escapeHtml(t.badge || '⚡ Тема')}</span>
                        ${t.is_recent ? '<span class="acute-topic-status used">Использовалась ранее</span>' : '<span class="acute-topic-status fresh">🔥 Свежий ракурс</span>'}
                    </div>
                    
                    <div class="acute-topic-title-ru">🇷🇺 ${escapeHtml(titleRu)}</div>
                    ${isDifferentTitle ? `<div class="acute-topic-title-orig">🇩🇪 ${escapeHtml(titleOrig)}</div>` : ''}
                    
                    ${t.desc_ru ? `<div class="acute-topic-desc">${escapeHtml(t.desc_ru)}</div>` : ''}

                    ${t.live_headline ? `
                        <div class="acute-topic-live-box">
                            <div class="acute-live-tag">
                                <span class="live-dot"></span>
                                <span>Свежая новость (${escapeHtml(t.live_source || 'Агентство')}):</span>
                                ${t.live_pub_date ? `<span class="acute-live-date">⏱️ ${escapeHtml(t.live_pub_date)}</span>` : ''}
                            </div>
                            ${t.live_headline_ru ? `<div class="acute-live-ru">🇷🇺 ${escapeHtml(t.live_headline_ru)}</div>` : ''}
                            <div class="acute-live-orig">🇩🇪 «${escapeHtml(t.live_headline)}»</div>
                        </div>
                    ` : ''}

                    <div class="acute-topic-footer">
                        <div class="acute-topic-hook-wrap">
                            <span class="acute-hook-label">Кликбейт на обложку:</span>
                            <span class="acute-hook-value">
                                <strong style="color: #34d399;">«${escapeHtml(hookRu)}»</strong>
                                ${isDifferentHook ? `<small style="color: var(--text-muted); font-size: 11px; margin-left: 4px;">(🇩🇪 ${escapeHtml(t.hook_sample)})</small>` : ''}
                            </span>
                        </div>
                        <button type="button" class="btn-select-topic">Выбрать в 1 клик →</button>
                    </div>
                </div>
            `;
            }).join('');
        }
    } catch (e) {
        if (loader) loader.style.display = 'none';
        if (grid) grid.innerHTML = `<div style="grid-column: 1 / -1; color: var(--error); padding: 20px; text-align: center;">Ошибка: ${escapeHtml(e.message)}</div>`;
    }
}

async function loadNextAcuteBatch() {
    const btn = document.getElementById('btnAcuteNextBatch');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span>⏳</span> Загрузка...';
    }
    await openAcuteTopicsModal(true);
    if (btn) {
        btn.innerHTML = '<span>🔄</span> Показать другие сюжеты';
    }
}

async function resetAcuteHistoryUI() {
    const resetBtn = document.getElementById('btnAcuteResetHistory');
    if (resetBtn) {
        resetBtn.disabled = true;
        resetBtn.textContent = 'Сброс...';
    }
    try {
        await fetch('/api/topics/acute/reset-history', { method: 'POST' });
        acuteExcludedIds.clear();
        acuteCurrentOffset = 0;
        await openAcuteTopicsModal(false);
    } catch (e) {
        console.error('Reset history error:', e);
    } finally {
        if (resetBtn) {
            resetBtn.disabled = false;
            resetBtn.textContent = '↺ Сбросить историю';
        }
    }
}

function closeAcuteTopicsModal(e) {
    if (e && e.target && e.target.id !== 'acuteTopicsModal' && !e.target.classList.contains('modal-close') && !e.target.classList.contains('btn-close-modal')) {
        return;
    }
    const modal = document.getElementById('acuteTopicsModal');
    if (modal) modal.style.display = 'none';
}

let selectedAcuteAngleId = '';

if (topicInput) {
    topicInput.addEventListener('input', () => {
        // If user manually edits topic, clear preset acute angle id
        selectedAcuteAngleId = '';
    });
}

async function selectAcuteTopicByIndex(idx) {
    if (currentAcuteTopicsList && currentAcuteTopicsList[idx]) {
        const item = currentAcuteTopicsList[idx];
        selectedAcuteAngleId = item.id || '';
        try {
            fetch('/api/topics/acute/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    angle_id: item.id,
                    topic_query: item.topic_query || item.title
                })
            }).catch(e => console.warn('Failed to record acute topic selection:', e));
        } catch (_) {}

        // Select the most natural language title for topicInput
        const vSelect = document.getElementById('voiceSelect');
        const isDe = vSelect && vSelect.value.startsWith('de');
        let chosenTitle = item.title;
        if (!isDe && item.title_ru) {
            chosenTitle = item.title_ru;
        } else if (item.title) {
            chosenTitle = item.title;
        } else {
            chosenTitle = item.topic_query || '';
        }

        if (chosenTitle) {
            chosenTitle = chosenTitle.replace(/\s*[-–—|]\s*(Tagesschau|Spiegel|Welt|Focus|Bild|ZDF|FAZ|SZ|N-TV|Zeit|Lenta|РИА Новости|ТАСС|Интерфакс|Коммерсантъ).*$/i, '').trim();
        }

        selectAcuteTopic(chosenTitle);
    }
}

function selectAcuteTopic(query) {
    const input = document.getElementById('topicInput');
    if (input) {
        input.value = query;
        input.focus();
        input.style.boxShadow = '0 0 0 2px var(--accent)';
        setTimeout(() => { input.style.boxShadow = ''; }, 1200);
    }
    closeAcuteTopicsModal();
}


// === Init ===
document.addEventListener('DOMContentLoaded', async () => {
    await loadHistory();
    await checkTelegramStatusOnLoad();
    await checkBackgroundQueue();

    // Check if opened with ?edit_thumb=jobId
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('edit_thumb')) {
        const targetId = urlParams.get('edit_thumb');
        setTimeout(() => {
            openThumbnailModal(targetId);
        }, 500);
    }

    const btnAcuteTopics = document.getElementById('btnAcuteTopics');
    if (btnAcuteTopics) {
        btnAcuteTopics.addEventListener('click', (e) => {
            e.preventDefault();
            openAcuteTopicsModal();
        });
    }
});

