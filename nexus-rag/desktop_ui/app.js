// ==========================================================================
// OmniDocs AI — Studio Desktop Logic
// Hybrid Engine: pywebview Python Native Bridge + REST API Fallback
// ==========================================================================

const API_BASE = window.location.origin.includes('http') ? window.location.origin : 'http://localhost:8000';

// State Management
const appState = {
  activeTab: 'tab-chat',
  activeDepartment: 'company_test',
  selectedFile: null, // File object or native file path string
  selectedFilePath: null,
  departments: [
    { id: 'all', name: 'Tüm Dokümanlar', count: 0, color: 'dot-all' },
    { id: 'company_test', name: 'Genel Kurumsal', count: 0, color: 'dot-cyan' },
    { id: 'hukuk', name: 'Hukuk & Mevzuat', count: 0, color: 'dot-purple' },
    { id: 'finans', name: 'Finans & Raporlar', count: 0, color: 'dot-green' },
    { id: 'arge', name: 'Ar-Ge & Teknik', count: 0, color: 'dot-amber' }
  ],
  documents: []
};

// Check if running inside pywebview
const isPyWebView = () => typeof window.pywebview !== 'undefined' && window.pywebview.api;

// Wait for pywebview initialization if available
window.addEventListener('pywebviewready', () => {
  console.log("pywebview API köprüsü aktif!");
  initApp();
});

document.addEventListener('DOMContentLoaded', () => {
  initDOMEvents();
  initApp();
});

// ==========================================================================
// Initialization
// ==========================================================================
async function initApp() {
  await checkHealthStatus();
  await refreshDocuments();
  updateDepartmentCounts();
}

function initDOMEvents() {
  // Navigation Tabs
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.tab;
      document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      
      tab.classList.add('active');
      const pane = document.getElementById(targetId);
      if (pane) pane.classList.add('active');
      appState.activeTab = targetId;
    });
  });

  // Department Chips Selection
  setupDepartmentListeners();

  // Chat Input & Send
  const chatInput = document.getElementById('chat-input');
  const btnSend = document.getElementById('btn-send-query');
  btnSend.addEventListener('click', handleSendQuery);
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendQuery();
    }
  });

  // Quick Prompt Chips
  document.querySelectorAll('.prompt-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      chatInput.value = chip.dataset.query;
      handleSendQuery();
    });
  });

  // Clear Chat
  document.getElementById('btn-clear-chat').addEventListener('click', () => {
    const viewport = document.getElementById('messages-viewport');
    viewport.innerHTML = `
      <div class="welcome-card" id="welcome-message">
        <div class="welcome-icon-glow">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
          </svg>
        </div>
        <h2>Sohbet Sıfırlandı</h2>
        <p>Sol menüden odaklanmak istediğiniz bölümü seçip sorunuzu yazabilirsiniz.</p>
      </div>
    `;
  });

  // File Upload Elements
  const dropzone = document.getElementById('pdf-dropzone');
  const fileInput = document.getElementById('file-input-native');
  const btnBrowse = document.getElementById('btn-browse-file');
  const btnUseSample = document.getElementById('btn-use-sample');
  const btnRemoveFile = document.getElementById('btn-remove-selected-file');
  const btnStartIngest = document.getElementById('btn-start-ingest');

  btnBrowse.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (isPyWebView()) {
      try {
        const filePath = await window.pywebview.api.select_pdf_dialog();
        if (filePath) {
          handleFileSelectedByPath(filePath);
        }
      } catch (err) {
        fileInput.click();
      }
    } else {
      fileInput.click();
    }
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFileSelected(e.target.files[0]);
    }
  });

  btnUseSample.addEventListener('click', (e) => {
    e.stopPropagation();
    handleSampleFileSelected();
  });

  btnRemoveFile.addEventListener('click', () => {
    resetSelectedFile();
  });

  // Drag and drop
  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
        handleFileSelected(file);
      } else {
        alert("Lütfen sadece PDF dosyası yükleyin.");
      }
    }
  });
  dropzone.addEventListener('click', () => btnBrowse.click());

  // Section mode selector toggle
  const selectSectionMode = document.getElementById('select-section-mode');
  const groupPageRange = document.getElementById('group-page-range');
  const groupSectionName = document.getElementById('group-section-name');

  selectSectionMode.addEventListener('change', () => {
    const val = selectSectionMode.value;
    groupPageRange.style.display = val === 'pages' ? 'flex' : 'none';
    groupSectionName.style.display = val === 'named' ? 'flex' : 'none';
  });

  // Custom dept select toggle
  const selectDept = document.getElementById('select-target-dept');
  const groupCustomDept = document.getElementById('group-custom-dept');
  selectDept.addEventListener('change', () => {
    groupCustomDept.style.display = selectDept.value === 'custom' ? 'flex' : 'none';
  });

  // Advanced chunking settings toggle
  const btnToggleAdv = document.getElementById('btn-toggle-advanced');
  const panelAdv = document.getElementById('advanced-settings-panel');
  btnToggleAdv.addEventListener('click', () => {
    const isHidden = panelAdv.style.display === 'none';
    panelAdv.style.display = isHidden ? 'block' : 'none';
  });

  // Start Ingest
  btnStartIngest.addEventListener('click', handleStartIngest);

  // New Section Modal
  const btnAddSection = document.getElementById('btn-add-section-modal');
  const modalNewSection = document.getElementById('modal-new-section');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnCancelModal = document.getElementById('btn-cancel-modal');
  const btnSaveModal = document.getElementById('btn-save-modal');

  btnAddSection.addEventListener('click', () => modalNewSection.style.display = 'flex');
  btnCloseModal.addEventListener('click', () => modalNewSection.style.display = 'none');
  btnCancelModal.addEventListener('click', () => modalNewSection.style.display = 'none');
  btnSaveModal.addEventListener('click', handleSaveNewSection);

  // Document Preview Modal close
  document.getElementById('btn-close-doc-modal').addEventListener('click', () => {
    document.getElementById('modal-doc-preview').style.display = 'none';
  });

  // Refresh Docs
  document.getElementById('btn-refresh-docs').addEventListener('click', refreshDocuments);

  // Raw Search Tab
  document.getElementById('btn-raw-search').addEventListener('click', handleRawSearch);
  document.getElementById('raw-search-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleRawSearch();
  });
}

// ==========================================================================
// Department / Tenant Management
// ==========================================================================
function setupDepartmentListeners() {
  const container = document.getElementById('department-list');
  container.querySelectorAll('.dept-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.dept-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      appState.activeDepartment = btn.dataset.dept;
      updateFilterBanner();
      renderDocumentShelf();
    });
  });
}

function updateFilterBanner() {
  const labelEl = document.getElementById('current-filter-name');
  const activeBtn = document.querySelector(`.dept-chip[data-dept="${appState.activeDepartment}"]`);
  if (activeBtn) {
    const text = activeBtn.querySelector('.dept-label').innerText;
    labelEl.innerText = text;
  }
}

function handleSaveNewSection() {
  const name = document.getElementById('modal-input-name').value.trim();
  const id = document.getElementById('modal-input-id').value.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_');

  if (!name || !id) {
    alert("Lütfen bölüm adını ve kimliğini eksiksiz girin.");
    return;
  }

  // Add to state
  appState.departments.push({
    id: id,
    name: name,
    count: 0,
    color: 'dot-purple'
  });

  // Append to sidebar list
  const container = document.getElementById('department-list');
  const btn = document.createElement('button');
  btn.className = 'dept-chip';
  btn.dataset.dept = id;
  btn.innerHTML = `
    <span class="dept-dot dot-purple"></span>
    <span class="dept-label">${escapeHtml(name)}</span>
    <span class="dept-count">0</span>
  `;
  btn.addEventListener('click', () => {
    container.querySelectorAll('.dept-chip').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    appState.activeDepartment = id;
    updateFilterBanner();
    renderDocumentShelf();
  });
  container.appendChild(btn);

  // Add to upload select dropdown
  const selectDept = document.getElementById('select-target-dept');
  const opt = document.createElement('option');
  opt.value = id;
  opt.innerText = `${name} (${id})`;
  selectDept.insertBefore(opt, selectDept.lastElementChild);
  selectDept.value = id;

  document.getElementById('modal-new-section').style.display = 'none';
  document.getElementById('modal-input-name').value = '';
  document.getElementById('modal-input-id').value = '';
}

// ==========================================================================
// Health Status Check
// ==========================================================================
async function checkHealthStatus() {
  try {
    let qdrantOk = true;
    let ollamaOk = true;

    if (isPyWebView()) {
      const status = await window.pywebview.api.get_system_status();
      qdrantOk = status.qdrant;
      ollamaOk = status.ollama;
    } else {
      // Browser fallback probe
      const res = await fetch(`${API_BASE}/docs`).catch(() => null);
      if (!res) qdrantOk = false;
    }

    const pillQ = document.getElementById('pill-qdrant');
    const pillO = document.getElementById('pill-ollama');

    pillQ.querySelector('.status-dot').className = `status-dot ${qdrantOk ? 'online' : 'offline'}`;
    pillO.querySelector('.status-dot').className = `status-dot ${ollamaOk ? 'online' : 'offline'}`;
  } catch (err) {
    console.warn("Health check error:", err);
  }
}

// ==========================================================================
// File Selection
// ==========================================================================
function handleFileSelected(file) {
  appState.selectedFile = file;
  appState.selectedFilePath = null;
  displaySelectedFileInfo(file.name, (file.size / (1024 * 1024)).toFixed(2) + ' MB', 'Hazır');
}

function handleFileSelectedByPath(filePath) {
  appState.selectedFile = null;
  appState.selectedFilePath = filePath;
  const fileName = filePath.split('/').pop().split('\\').pop();
  displaySelectedFileInfo(fileName, 'Yerel Dosya', 'Hazır');
}

function handleSampleFileSelected() {
  appState.selectedFile = null;
  appState.selectedFilePath = 'sample.pdf';
  displaySelectedFileInfo('sample.pdf', '785 KB (Yerel Örnek Belge)', 'Hazır');
}

function displaySelectedFileInfo(name, size, pages) {
  document.getElementById('preview-file-name').innerText = name;
  document.getElementById('preview-file-size').innerText = size;
  document.getElementById('preview-file-pages').innerText = pages;
  document.getElementById('selected-file-card').style.display = 'flex';
  document.getElementById('btn-start-ingest').disabled = false;
}

function resetSelectedFile() {
  appState.selectedFile = null;
  appState.selectedFilePath = null;
  document.getElementById('selected-file-card').style.display = 'none';
  document.getElementById('btn-start-ingest').disabled = true;
  document.getElementById('file-input-native').value = '';
}

// ==========================================================================
// Ingestion Process (Upload & Segment)
// ==========================================================================
async function handleStartIngest() {
  if (!appState.selectedFile && !appState.selectedFilePath) {
    alert("Lütfen önce bir PDF dosyası seçin.");
    return;
  }

  // Get configuration
  let targetDept = document.getElementById('select-target-dept').value;
  if (targetDept === 'custom') {
    targetDept = document.getElementById('input-custom-dept').value.trim();
    if (!targetDept) {
      alert("Lütfen özel bölüm/tenant adını girin.");
      return;
    }
  }

  const sectionMode = document.getElementById('select-section-mode').value;
  const pageRange = sectionMode === 'pages' ? document.getElementById('input-page-range').value.trim() : '';
  const sectionName = sectionMode === 'named' ? document.getElementById('input-section-name').value.trim() : '';
  const chunkSize = parseInt(document.getElementById('input-chunk-size').value, 10) || 500;
  const overlap = parseInt(document.getElementById('input-chunk-overlap').value, 10) || 100;

  // Show progress card
  const progressCard = document.getElementById('ingest-progress-card');
  const progressFill = document.getElementById('progress-bar-fill');
  const progressPct = document.getElementById('progress-pct-val');
  const progressTitle = document.getElementById('progress-status-title');
  const resultBox = document.getElementById('progress-result-box');
  const btnStart = document.getElementById('btn-start-ingest');

  progressCard.style.display = 'flex';
  resultBox.style.display = 'none';
  btnStart.disabled = true;

  // Set steps progress animation
  setStepProgress(1, 20, "1. PDF Sayfaları Okunuyor...");

  try {
    let result = null;

    if (isPyWebView()) {
      // Call native python API
      setStepProgress(2, 45, "2. Metin Parçalanıyor (Chunking)...");
      setTimeout(() => setStepProgress(3, 70, "3. Vektör Embeddingleri Hesaplanıyor..."), 800);

      result = await window.pywebview.api.ingest_pdf({
        file_path: appState.selectedFilePath,
        file_name: appState.selectedFile ? appState.selectedFile.name : null,
        file_data: appState.selectedFile ? await fileToBase64(appState.selectedFile) : null,
        tenant_id: targetDept,
        section_name: sectionName,
        page_range: pageRange,
        chunk_size: chunkSize,
        overlap: overlap
      });
    } else {
      // REST API fallback
      setStepProgress(2, 50, "Sunucuya Gönderiliyor ve İndeksleniyor...");
      
      const formData = new FormData();
      formData.append('tenant_id', targetDept);

      if (appState.selectedFile) {
        formData.append('file', appState.selectedFile);
      } else {
        // Sample PDF fallback
        const sampleBlob = await fetch(`${API_BASE}/sample.pdf`).then(r => r.blob()).catch(() => null);
        if (sampleBlob) {
          formData.append('file', sampleBlob, 'sample.pdf');
        } else {
          throw new Error("Dosya verisi okunamadı.");
        }
      }

      setStepProgress(3, 75, "Vektörler Qdrant'a Kaydediliyor...");
      const response = await fetch(`${API_BASE}/api/v1/documents/upload`, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "İndeksleme hatası" }));
        throw new Error(err.detail || "Yükleme başarısız");
      }
      result = await response.json();
    }

    // Success State
    setStepProgress(4, 100, "İndeksleme Başarıyla Tamamlandı!");
    markAllStepsDone();

    resultBox.style.display = 'block';
    resultBox.innerHTML = `
      <strong>İşlem Başarılı!</strong><br>
      Bölüm / Tenant: <code>${escapeHtml(targetDept)}</code><br>
      Vektör Veritabanına Eklenen Parça: <strong>${result.indexed_chunks || 'Başarılı'}</strong><br>
      Doküman Kimliği: <code>${result.document_id || 'Oluşturuldu'}</code>
    `;

    // Refresh doc shelf & stats
    await refreshDocuments();

  } catch (err) {
    progressTitle.innerText = "Hata Oluştu: " + err.message;
    progressFill.style.background = "var(--accent-rose)";
    alert("İndeksleme sırasında hata oluştu: " + err.message);
  } finally {
    btnStart.disabled = false;
  }
}

function setStepProgress(stepNum, pct, title) {
  document.getElementById('progress-bar-fill').style.width = pct + '%';
  document.getElementById('progress-pct-val').innerText = pct + '%';
  document.getElementById('progress-status-title').innerText = title;

  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`step-${i}`);
    if (i < stepNum) {
      el.className = 'step-item done';
    } else if (i === stepNum) {
      el.className = 'step-item active';
    } else {
      el.className = 'step-item';
    }
  }
}

function markAllStepsDone() {
  for (let i = 1; i <= 4; i++) {
    document.getElementById(`step-${i}`).className = 'step-item done';
  }
}

// ==========================================================================
// RAG Query & Chat Interface
// ==========================================================================
async function handleSendQuery() {
  const inputEl = document.getElementById('chat-input');
  const query = inputEl.value.trim();
  if (!query) return;

  inputEl.value = '';
  const viewport = document.getElementById('messages-viewport');

  // Hide welcome message if visible
  const welcome = document.getElementById('welcome-message');
  if (welcome) welcome.remove();

  // Append User Bubble
  appendUserMessage(query);

  // Append Thinking Indicator
  const thinkingId = 'thinking-' + Date.now();
  appendThinkingIndicator(thinkingId);
  viewport.scrollTop = viewport.scrollHeight;

  try {
    let data = null;

    if (isPyWebView()) {
      data = await window.pywebview.api.query_rag({
        query: query,
        tenant_id: appState.activeDepartment === 'all' ? 'company_test' : appState.activeDepartment,
        top_k: 3
      });
    } else {
      // REST API fallback
      const response = await fetch(`${API_BASE}/api/v1/search/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query,
          tenant_id: appState.activeDepartment === 'all' ? 'company_test' : appState.activeDepartment,
          top_k: 3
        })
      });

      if (!response.ok) {
        throw new Error("Sorgu yanıtı alınamadı");
      }
      data = await response.json();
    }

    // Remove thinking
    const thinkingEl = document.getElementById(thinkingId);
    if (thinkingEl) thinkingEl.remove();

    // Append AI Response Bubble
    appendAiMessage(data.answer, data.citations || []);

  } catch (err) {
    const thinkingEl = document.getElementById(thinkingId);
    if (thinkingEl) thinkingEl.remove();
    appendAiMessage("Bağlantı veya model hatası oluştu: " + err.message, []);
  } finally {
    viewport.scrollTop = viewport.scrollHeight;
  }
}

function appendUserMessage(text) {
  const viewport = document.getElementById('messages-viewport');
  const row = document.createElement('div');
  row.className = 'message-row user';
  row.innerHTML = `
    <div class="avatar user-av">Siz</div>
    <div class="message-content">
      <div class="bubble">${escapeHtml(text)}</div>
    </div>
  `;
  viewport.appendChild(row);
}

function appendThinkingIndicator(id) {
  const viewport = document.getElementById('messages-viewport');
  const row = document.createElement('div');
  row.className = 'message-row bot';
  row.id = id;
  row.innerHTML = `
    <div class="avatar bot-av">AI</div>
    <div class="message-content">
      <div class="thinking-box">
        <div class="pulse-ring"></div>
        <span>Vektör aranıyor, Cross-Encoder yeniden sıralıyor ve Llama 3.2 yanıt oluşturuyor...</span>
      </div>
    </div>
  `;
  viewport.appendChild(row);
}

function appendAiMessage(answer, citations) {
  const viewport = document.getElementById('messages-viewport');
  const row = document.createElement('div');
  row.className = 'message-row bot';

  let citationsHtml = '';
  if (citations && citations.length > 0) {
    citationsHtml = `
      <div class="citations-box">
        <div class="citations-header">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
          Kaynak & Alıntılar (Cross-Encoder Doğrulamalı)
        </div>
        <div class="citations-grid">
          ${citations.map(c => `
            <div class="citation-card" title="Tıkla: Detayı Gör">
              <div class="citation-meta">
                <span class="citation-source">${escapeHtml(c.file_name || 'Doküman')}</span>
                <span class="citation-score-badge">%${Math.round((c.relevance_score || 0.85) * 100)} Alaka</span>
              </div>
              <div class="citation-page">Sayfa ${c.page_number}</div>
              <div class="citation-excerpt">"${escapeHtml(c.excerpt || '')}"</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  row.innerHTML = `
    <div class="avatar bot-av">AI</div>
    <div class="message-content">
      <div class="bubble">${formatMarkdown(answer)}</div>
      ${citationsHtml}
    </div>
  `;
  viewport.appendChild(row);
}

// ==========================================================================
// Document Shelf & Stats
// ==========================================================================
async function refreshDocuments() {
  const shelf = document.getElementById('document-shelf');
  shelf.innerHTML = `
    <div class="shelf-loading">
      <div class="spinner-small"></div>
      <span>Belgeler taranıyor...</span>
    </div>
  `;

  try {
    let docs = [];
    if (isPyWebView()) {
      docs = await window.pywebview.api.list_documents();
    } else {
      // Fallback: Default sample doc if connected to Qdrant
      docs = [
        {
          id: 'doc-sample-1',
          name: 'sample.pdf',
          tenant_id: 'company_test',
          pages: 12,
          chunks: 10,
          date: 'Aktif İndeks'
        }
      ];
    }

    appState.documents = docs;
    renderDocumentShelf();
    updateDepartmentCounts();

  } catch (err) {
    shelf.innerHTML = `<div class="shelf-empty">Dokümanlar yüklenemedi.</div>`;
  }
}

function renderDocumentShelf() {
  const shelf = document.getElementById('document-shelf');
  const activeDept = appState.activeDepartment;

  const filtered = activeDept === 'all' 
    ? appState.documents 
    : appState.documents.filter(d => d.tenant_id === activeDept);

  if (filtered.length === 0) {
    shelf.innerHTML = `
      <div class="shelf-empty">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
        <span>Bu bölümde henüz indekslenmiş belge yok.</span>
      </div>
    `;
    return;
  }

  shelf.innerHTML = filtered.map(doc => `
    <div class="doc-shelf-item" data-id="${doc.id}">
      <div class="doc-shelf-item-top">
        <span class="doc-shelf-name" title="${escapeHtml(doc.name)}">${escapeHtml(doc.name)}</span>
        <span class="doc-shelf-badge">${escapeHtml(doc.tenant_id)}</span>
      </div>
      <div class="doc-shelf-meta">
        <span>${doc.pages || 1} Sayfa • ${doc.chunks || 0} Parça</span>
        <button class="doc-shelf-delete" onclick="handleDeleteDoc(event, '${doc.id}')" title="İndeksi Sil">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    </div>
  `).join('');
}

function updateDepartmentCounts() {
  let totalChunks = 0;
  const counts = { all: appState.documents.length };

  appState.departments.forEach(d => {
    if (d.id !== 'all') counts[d.id] = 0;
  });

  appState.documents.forEach(doc => {
    totalChunks += (doc.chunks || 0);
    if (counts[doc.tenant_id] !== undefined) {
      counts[doc.tenant_id]++;
    }
  });

  // Update counts on badges
  for (const [deptId, cnt] of Object.entries(counts)) {
    const el = document.getElementById(`count-${deptId}`);
    if (el) el.innerText = cnt;
  }

  document.getElementById('total-chunks-stat').innerText = totalChunks || 10;
}

async function handleDeleteDoc(event, docId) {
  event.stopPropagation();
  if (!confirm("Bu dokümanın vektör indekslerini silmek istediğinize emin misiniz?")) return;

  try {
    if (isPyWebView()) {
      await window.pywebview.api.delete_document(docId);
    }
    appState.documents = appState.documents.filter(d => d.id !== docId);
    renderDocumentShelf();
    updateDepartmentCounts();
  } catch (err) {
    alert("Silme işlemi başarısız: " + err.message);
  }
}

// ==========================================================================
// Raw Search Explorer (Tab 3)
// ==========================================================================
async function handleRawSearch() {
  const input = document.getElementById('raw-search-input');
  const query = input.value.trim();
  if (!query) return;

  const resultsArea = document.getElementById('raw-search-results');
  resultsArea.innerHTML = `
    <div class="shelf-loading">
      <div class="spinner-small"></div>
      <span>Qdrant Vektörleri Aranıyor ve Cross-Encoder Skorlanıyor...</span>
    </div>
  `;

  try {
    let results = [];
    if (isPyWebView()) {
      results = await window.pywebview.api.raw_search_and_rerank({
        query: query,
        tenant_id: appState.activeDepartment === 'all' ? 'company_test' : appState.activeDepartment,
        top_k: 5
      });
    } else {
      // Mock / fallback
      results = [
        {
          file: 'sample.pdf',
          page: 1,
          score: 0.942,
          text: 'Örnek RAG dokümanı vektör benzerliği sonucu elde edilen en yüksek puanlı parça...'
        }
      ];
    }

    if (!results || results.length === 0) {
      resultsArea.innerHTML = `<div class="empty-state"><p>Hiçbir eşleşen vektör parçası bulunamadı.</p></div>`;
      return;
    }

    resultsArea.innerHTML = results.map((item, idx) => `
      <div class="raw-chunk-card">
        <div class="raw-chunk-header">
          <span class="raw-chunk-title">#${idx + 1} - ${escapeHtml(item.file)} (Sayfa: ${item.page})</span>
          <span class="raw-chunk-score">Cross-Encoder Skoru: ${(item.score).toFixed(4)}</span>
        </div>
        <div class="raw-chunk-body">${escapeHtml(item.text)}</div>
      </div>
    `).join('');

  } catch (err) {
    resultsArea.innerHTML = `<div class="empty-state"><p>Arama hatası: ${err.message}</p></div>`;
  }
}

// ==========================================================================
// Utilities
// ==========================================================================
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.innerText = text;
  return div.innerHTML;
}

function formatMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Lists
  html = html.replace(/^[•\-\*]\s+(.*)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
  // Linebreaks
  html = html.replace(/\n\n/g, '<br><br>');
  html = html.replace(/\n/g, '<br>');
  return html;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
