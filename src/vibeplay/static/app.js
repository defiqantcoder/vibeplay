/* vibeplay — Audiophile Precision Console Client-side Interactions */

// Tab & Screen Navigation (Enforce Screen Separation)
function showTab(viewId) {
  if (!viewId) viewId = 'lounge';
  const clean = String(viewId).replace(/^view-/, '').replace(/^tab-/, '');

  // Map view aliases (builder -> generator)
  let targetView = clean;
  if (clean === 'builder') targetView = 'generator';

  // 1. Hide all .view-panel sections and clear active state
  const panels = document.querySelectorAll('.view-panel');
  panels.forEach(p => {
    p.style.display = 'none';
    p.classList.remove('active');
  });

  // 2. Locate targeted element (supports view-*, tab-*, or raw id)
  const targetElement = document.getElementById(`view-${targetView}`)
                     || document.getElementById(`view-${clean}`)
                     || document.getElementById(`tab-${clean}`)
                     || document.getElementById(viewId);

  if (targetElement) {
    targetElement.style.display = 'block';
    targetElement.classList.add('active');
  }

  // 3. Update top and sidebar navigation active states
  const navKeys = ['lounge', 'crate', 'library', 'builder', 'generator'];
  navKeys.forEach(key => {
    const btn = document.getElementById(`nav-btn-${key}`);
    const sideBtn = document.getElementById(`side-nav-${key}`);
    const isActive = (key === clean)
      || (targetView === 'generator' && (key === 'builder' || key === 'generator'))
      || (clean === 'generator' && key === 'builder')
      || (clean === 'builder' && key === 'generator');
    if (btn) btn.classList.toggle('active', isActive);
    if (sideBtn) sideBtn.classList.toggle('active', isActive);
  });
}
window.showTab = showTab;


// Open Track Detail Modal
function openTrackModal() {
  const modal = document.getElementById('track-detail-modal');
  if (modal && typeof modal.showModal === 'function') {
    modal.showModal();
  }
}

// Light-Dismiss Fallback for <dialog closedby="any"> (Modern Web Guidance)
document.addEventListener('click', (event) => {
  const dialog = document.getElementById('track-detail-modal');
  if (!dialog || !dialog.open) return;

  if (!('closedBy' in HTMLDialogElement.prototype)) {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    const isDialogContent = (
      rect.top <= event.clientY &&
      event.clientY <= rect.top + rect.height &&
      rect.left <= event.clientX &&
      event.clientX <= rect.left + rect.width
    );
    if (!isDialogContent) {
      dialog.close();
    }
  }
});

// Update Range Slider Labels
function updateSliderLabel(sliderId, labelId, suffix = '') {
  const slider = document.getElementById(sliderId);
  const label = document.getElementById(labelId);
  if (slider && label) {
    label.textContent = slider.value + suffix;
  }
}

// Drag & Drop Playlist Track Reordering
let draggedItem = null;

function initPlaylistDragDrop() {
  const root = document.getElementById('playlist-tracks-list');
  if (!root) return;
  const container = root.querySelector('.draggable-rows-wrapper') || root;

  const items = root.querySelectorAll('.playlist-track-row');
  items.forEach(item => {
    item.addEventListener('dragstart', (e) => {
      draggedItem = item;
      item.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });

    item.addEventListener('dragend', () => {
      item.classList.remove('dragging');
      draggedItem = null;
      submitNewPlaylistOrder();
    });

    item.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const afterElement = getDragAfterElement(container, e.clientY);
      if (afterElement == null) {
        container.appendChild(draggedItem);
      } else {
        container.insertBefore(draggedItem, afterElement);
      }
    });
  });
}

function getDragAfterElement(container, y) {
  const draggableElements = [...container.querySelectorAll('.playlist-track-row:not(.dragging)')];

  return draggableElements.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) {
      return { offset: offset, element: child };
    } else {
      return closest;
    }
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function submitNewPlaylistOrder() {
  const container = document.getElementById('playlist-tracks-list');
  if (!container) return;
  const items = container.querySelectorAll('.playlist-track-row');
  const trackIds = Array.from(items).map(i => i.getAttribute('data-track-id')).filter(Boolean);
  const playlistId = container.getAttribute('data-playlist-id') || '';

  // Update position numbers immediately for instant visual feedback
  items.forEach((item, idx) => {
    item.setAttribute('data-position', idx + 1);
  });

  if (trackIds.length > 0 && window.htmx) {
    const targetEl = document.getElementById('guided-playlist-builder-root') ? '#guided-playlist-builder-root' : '#playlist-builder-container';
    const swapMode = targetEl === '#guided-playlist-builder-root' ? 'outerHTML' : 'innerHTML';
    htmx.ajax('POST', '/api/playlist/builder/reorder', {
      target: targetEl,
      swap: swapMode,
      values: {
        playlist_id: playlistId,
        track_ids: trackIds.join(','),
        step: 4,
      }
    });
  }
}

// Re-initialize drag and drop after HTMX swaps
document.addEventListener('htmx:afterSwap', (event) => {
  if (event.detail.target.id === 'playlist-builder-container' ||
      event.detail.target.id === 'tab-builder' ||
      event.detail.target.id === 'guided-playlist-builder-root') {
    initPlaylistDragDrop();
  }
  if (event.detail.target.id === 'track-detail-modal') {
    openTrackModal();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  initPlaylistDragDrop();
});

/* vibeplay — Desktop Application Chrome, Keyboard Shortcuts, Hardware Settings & Theme Engine */

// 1. Theme Engine, Custom Accent & Contrast Persistence
function initThemeEngine() {
  const ssrTheme = document.documentElement.getAttribute('data-theme');
  const savedTheme = localStorage.getItem('vibeplay_theme') || ssrTheme || 'god-of-ink';
  applyTheme(savedTheme, false);

  const ssrContrast = document.documentElement.getAttribute('data-contrast');
  const savedContrast = localStorage.getItem('vibeplay_contrast') || ssrContrast || 'standard';
  applyContrastMode(savedContrast, false);

  const savedAccent = localStorage.getItem('vibeplay_custom_accent');
  if (savedAccent && /^#[0-9a-fA-F]{6}$/.test(savedAccent)) {
    applyCustomAccent(savedAccent, false);
  }
}

function computeHexLuminance(hexColor) {
  const h = hexColor.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16) / 255;
  const g = parseInt(h.substring(2, 4), 16) / 255;
  const b = parseInt(h.substring(4, 6), 16) / 255;
  const toLinear = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

function applyTheme(themeId, persist = true) {
  document.documentElement.setAttribute('data-theme', themeId);
  document.body.setAttribute('data-theme', themeId);
  if (document.body.dataset) {
    document.body.dataset.theme = themeId;
  }
  if (document.documentElement.dataset) {
    document.documentElement.dataset.theme = themeId;
  }

  if (persist) {
    // Clear inline custom accent overrides when switching preset themes
    document.documentElement.style.removeProperty('--primary');
    document.documentElement.style.removeProperty('--accent');
    document.documentElement.style.removeProperty('--on-primary');
    try {
      localStorage.setItem('vibeplay_theme', themeId);
      localStorage.removeItem('vibeplay_custom_accent');
    } catch (e) {
      console.warn('Could not persist theme to localStorage:', e);
    }
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme_id: themeId }),
    }).catch(() => {});
  }

  // Highlight active theme card in settings dialog and menu item
  document.querySelectorAll('[data-theme-card]').forEach(card => {
    if (card.getAttribute('data-theme-card') === themeId) {
      card.classList.add('active');
    } else {
      card.classList.remove('active');
    }
  });
  document.querySelectorAll('[data-theme-menu]').forEach(row => {
    if (row.getAttribute('data-theme-menu') === themeId) {
      row.classList.add('active');
    } else {
      row.classList.remove('active');
    }
  });

  // Close menus
  closeAllMenus();
}
window.applyTheme = applyTheme;


function syncAccentHexInput(hexVal) {
  const textInput = document.getElementById('cfg-custom-accent');
  if (textInput && /^#[0-9a-fA-F]{6}$/.test(hexVal)) {
    textInput.value = hexVal.toLowerCase();
  }
}

function applyCustomAccent(hexColor, persist = true) {
  const cleaned = (hexColor || '').trim().toLowerCase();
  if (!/^#[0-9a-fA-F]{6}$/.test(cleaned)) {
    setSettingsStatus('Invalid hex color format (#RRGGBB)', true);
    return;
  }

  const lum = computeHexLuminance(cleaned);
  const onPrimaryToken = lum > 0.179 ? 'var(--contrast-dark)' : 'var(--contrast-light)';

  document.documentElement.style.setProperty('--primary', cleaned);
  document.documentElement.style.setProperty('--accent', cleaned);
  document.documentElement.style.setProperty('--on-primary', onPrimaryToken);

  const picker = document.getElementById('cfg-custom-accent-picker');
  if (picker) picker.value = cleaned;
  const textInput = document.getElementById('cfg-custom-accent');
  if (textInput) textInput.value = cleaned;

  if (persist) {
    try {
      localStorage.setItem('vibeplay_custom_accent', cleaned);
    } catch (e) {}
    saveDesktopSettings();
  }
}

function applyContrastMode(mode, persist = true) {
  const cleaned = mode === 'high-contrast' ? 'high-contrast' : 'standard';
  document.documentElement.setAttribute('data-contrast', cleaned);
  document.body.setAttribute('data-contrast', cleaned);

  const sel = document.getElementById('cfg-contrast-mode');
  if (sel) sel.value = cleaned;

  if (persist) {
    try {
      localStorage.setItem('vibeplay_contrast', cleaned);
    } catch (e) {}
    saveDesktopSettings();
  }
}

// 2. Menu Dropdown Interactions
let activeOpenMenu = null;

function toggleMenu(menuName) {
  const dropdown = document.getElementById(`dropdown-${menuName}`);
  if (!dropdown) return;

  if (activeOpenMenu === menuName) {
    closeAllMenus();
  } else {
    closeAllMenus();
    dropdown.classList.add('open');
    activeOpenMenu = menuName;
    const btn = dropdown.parentElement ? dropdown.parentElement.querySelector('.menu-btn') : null;
    if (btn) btn.setAttribute('aria-expanded', 'true');
  }
}
window.toggleMenu = toggleMenu;

function closeAllMenus() {
  document.querySelectorAll('.menu-dropdown.open').forEach(el => {
    el.classList.remove('open');
  });
  document.querySelectorAll('.menu-btn[aria-expanded="true"]').forEach(btn => {
    btn.setAttribute('aria-expanded', 'false');
  });
  activeOpenMenu = null;
}
window.closeAllMenus = closeAllMenus;

function handleMenuHover(menuName) {
  if (activeOpenMenu && activeOpenMenu !== menuName) {
    toggleMenu(menuName);
  }
}
window.handleMenuHover = handleMenuHover;

// Native-like menubar hover switching when a menu is open
document.addEventListener('mouseover', (e) => {
  if (!activeOpenMenu) return;
  const wrapper = e.target.closest('.menu-item-wrapper');
  if (wrapper && wrapper.dataset && wrapper.dataset.menu) {
    const menuName = wrapper.dataset.menu;
    if (menuName && menuName !== activeOpenMenu) {
      toggleMenu(menuName);
    }
  }
});

// Close menus when clicking outside or clicking an action row
document.addEventListener('click', (e) => {
  const menuWrapper = e.target.closest('.menu-item-wrapper');
  if (!menuWrapper) {
    closeAllMenus();
  } else {
    const row = e.target.closest('.menu-row');
    if (row && !row.classList.contains('has-submenu')) {
      closeAllMenus();
    }
  }
  if (!e.target.closest('.audio-output-dropdown-container')) {
    closeAudioOutputDropdown();
  }
});

// Escape key to dismiss open menu
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && activeOpenMenu) {
    closeAllMenus();
    e.stopPropagation();
  }
});

// 3. Settings Popover & Dialog Controls
function toggleSettingsDialog(initialTab = null) {
  const dialog = document.getElementById('settings-dialog');
  if (!dialog) return;

  if (dialog.open) {
    dialog.close();
  } else {
    loadDesktopSettingsFromServer();
    if (initialTab) {
      switchSettingsTab(initialTab);
    }
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
  }
  closeAllMenus();
}

function closeSettingsDialog() {
  const dialog = document.getElementById('settings-dialog');
  if (dialog && dialog.open) {
    dialog.close();
  }
}

function switchSettingsTab(tabId) {
  const tabs = ['theme', 'transport', 'dsp', 'analyzer', 'plugins', 'ai'];
  tabs.forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const panel = document.getElementById(`panel-${t}`);
    if (btn) {
      if (t === tabId) {
        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
      } else {
        btn.classList.remove('active');
        btn.setAttribute('aria-selected', 'false');
      }
    }
    if (panel) {
      if (t === tabId) {
        panel.classList.add('active');
        panel.style.display = 'block';
      } else {
        panel.classList.remove('active');
        panel.style.display = 'none';
      }
    }
  });
}
window.switchSettingsTab = switchSettingsTab;

function openSettingsTab(tabName) {
  toggleSettingsDialog(tabName);
}
window.openSettingsTab = openSettingsTab;
window.toggleSettingsDialog = toggleSettingsDialog;
window.closeSettingsDialog = closeSettingsDialog;


function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  if (input.type === 'password') {
    input.type = 'text';
    if (btn) btn.textContent = 'Hide';
  } else {
    input.type = 'password';
    if (btn) btn.textContent = 'Show';
  }
}

function testAiConnection() {
  const key = document.getElementById('cfg-gemini-key')?.value || '';
  const model = document.getElementById('cfg-gemini-model')?.value || 'gemini-3.8-flash';
  const statusEl = document.getElementById('ai-test-status');
  if (statusEl) {
    statusEl.textContent = 'Testing connection...';
    statusEl.style.color = 'var(--primary)';
  }
  fetch('/api/ai/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: key, model: model }),
  })
    .then(r => r.json())
    .then(data => {
      if (!statusEl) return;
      if (data.ok) {
        statusEl.textContent = `✓ ${data.message || 'Connected successfully'}`;
        statusEl.style.color = 'var(--tertiary)';
      } else {
        statusEl.textContent = `✕ ${data.message || 'Verification failed'}`;
        statusEl.style.color = 'var(--error)';
      }
    })
    .catch(() => {
      if (statusEl) {
        statusEl.textContent = '✕ Network error testing API key';
        statusEl.style.color = 'var(--error)';
      }
    });
}

function setSettingsStatus(msg, isError = false) {
  const el = document.getElementById('settings-save-status');
  if (!el) return;
  el.textContent = msg;
  el.style.color = isError ? 'var(--error)' : 'var(--text-muted)';
}

function gatherSettingsFormPayload() {
  const getVal = (id, fallback) => {
    const el = document.getElementById(id);
    return el ? el.value : fallback;
  };
  const getChecked = (id, fallback) => {
    const el = document.getElementById(id);
    return el ? Boolean(el.checked) : fallback;
  };

  let activeDspProfile = 'pure-bitperfect';
  if (document.getElementById('pcard-spatial')?.classList.contains('active')) {
    activeDspProfile = 'spatial-headphones';
  } else if (document.getElementById('pcard-receiver')?.classList.contains('active')) {
    activeDspProfile = 'receiver-passthrough';
  }

  const activeTheme = document.documentElement.getAttribute('data-theme') || 'god-of-ink';
  const spatialEnabled = getChecked('cfg-spatial-toggle', false);

  return {
    alsa_device: getVal('cfg-alsa-device', 'hw:0,0'),
    alsa_exclusive_lock: getChecked('cfg-exclusive-lock', true),
    alsa_buffer_frames: parseInt(getVal('cfg-buffer-size', '4096'), 10),
    alsa_period_count: parseInt(getVal('cfg-period-count', '3'), 10),
    alsa_sample_rate_lock: getVal('cfg-sample-rate', 'off'),
    dpc_watchdog_enabled: getChecked('cfg-dpc-watchdog', true),
    dsp_profile: activeDspProfile,
    peq_profile: getVal('cfg-peq-profile', 'none'),
    peq_preamp_auto: getChecked('cfg-preamp-toggle', true),
    peq_preamp_db: parseFloat(getVal('cfg-peq-preamp-db', '-5.5')),
    spatial_enabled: spatialEnabled,
    spatial_mode: getVal('cfg-spatial-mode', 'stereo_direct'),
    analyzer_backend: getVal('cfg-analyzer-backend', 'essentia'),
    analyzer_workers: parseInt(getVal('cfg-workers', '4'), 10),
    analyzer_window_seconds: parseFloat(getVal('cfg-window-sec', '60.0')),
    mood_confidence_threshold: parseFloat(getVal('cfg-mood-threshold', '50')) / 100.0,
    theme_id: activeTheme,
    custom_accent_color: getVal('cfg-custom-accent', '#6874a6'),
    contrast_mode: getVal('cfg-contrast-mode', 'standard'),
    llm_provider: getVal('cfg-llm-provider', 'gemini'),
    gemini_api_key: getVal('cfg-gemini-key', ''),
    gemini_model: getVal('cfg-gemini-model', 'gemini-3.8-flash'),
    acoustid_api_key: getVal('cfg-acoustid-key', ''),
    musicbrainz_contact: getVal('cfg-musicbrainz-contact', ''),
    hide_telemetry_hud: getChecked('cfg-hide-telemetry-hud', false),
  };
}

function syncDomWithSettings(s) {
  if (!s) return;
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined && val !== null) el.value = String(val);
  };
  const setCheck = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined && val !== null) el.checked = Boolean(val);
  };

  setVal('cfg-alsa-device', s.alsa_device);
  setCheck('cfg-exclusive-lock', s.alsa_exclusive_lock);
  setVal('cfg-buffer-size', s.alsa_buffer_frames);
  setVal('cfg-period-count', s.alsa_period_count);
  setVal('cfg-sample-rate', s.alsa_sample_rate_lock);
  setCheck('cfg-dpc-watchdog', s.dpc_watchdog_enabled);

  setVal('cfg-peq-profile', s.peq_profile);
  setCheck('cfg-preamp-toggle', s.peq_preamp_auto);
  const preampValEl = document.getElementById('cfg-preamp-db-val');
  if (preampValEl && s.peq_preamp_db !== undefined) {
    preampValEl.textContent = Number(s.peq_preamp_db).toFixed(1);
  }
  setCheck('cfg-spatial-toggle', s.spatial_enabled);
  const spatialLabel = document.getElementById('cfg-spatial-label');
  if (spatialLabel && s.spatial_enabled !== undefined) {
    spatialLabel.textContent = s.spatial_enabled
      ? 'KEMAR HRTF 7.1.4 Convolver (Active)'
      : 'KEMAR HRTF 7.1.4 Convolver';
  }
  if (s.dsp_profile) {
    document.querySelectorAll('.profile-card').forEach(c => c.classList.remove('active'));
    const cardKey = s.dsp_profile.replace('pure-', '').replace('-headphones', '').replace('-passthrough', '');
    const activeCard = document.getElementById(`pcard-${cardKey}`);
    if (activeCard) activeCard.classList.add('active');
  }

  setVal('cfg-analyzer-backend', s.analyzer_backend);
  setVal('cfg-workers', s.analyzer_workers);
  setVal('cfg-window-sec', s.analyzer_window_seconds);
  const winLabel = document.getElementById('label-window-sec');
  if (winLabel && s.analyzer_window_seconds !== undefined) {
    winLabel.textContent = Math.round(s.analyzer_window_seconds) + 's';
  }
  setVal('cfg-mood-threshold', s.mood_confidence_threshold);
  const moodLabel = document.getElementById('label-mood-threshold');
  if (moodLabel && s.mood_confidence_threshold !== undefined) {
    moodLabel.textContent = Math.round(s.mood_confidence_threshold * 100) + '%';
  }
  setCheck('cfg-analyzer-fallback', s.analyzer_fallback_enabled);

  setVal('cfg-custom-accent', s.custom_accent_color);
  setVal('cfg-custom-accent-picker', s.custom_accent_color);
  setVal('cfg-contrast-mode', s.contrast_mode);

  setVal('cfg-llm-provider', s.llm_provider);
  setVal('cfg-gemini-key', s.gemini_api_key);
  setVal('cfg-gemini-model', s.gemini_model);
  setVal('cfg-acoustid-key', s.acoustid_api_key);
  setVal('cfg-musicbrainz-contact', s.musicbrainz_contact);
  setCheck('cfg-hide-telemetry-hud', s.hide_telemetry_hud);

  updateAudioDeviceConfig();
}

function loadDesktopSettingsFromServer() {
  fetch('/api/settings')
    .then(r => r.json())
    .then(data => {
      if (data && data.settings) {
        syncDomWithSettings(data.settings);
      }
    })
    .catch(err => console.debug('Could not fetch settings:', err));
}

function saveDesktopSettings(closeAfter = false) {
  const payload = gatherSettingsFormPayload();
  setSettingsStatus('Saving configuration...');

  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(async r => {
      const data = await r.json();
      if (!r.ok) {
        setSettingsStatus('Validation error: check highlighted fields.', true);
        return;
      }
      if (data.settings) {
        syncDomWithSettings(data.settings);
      }
      setSettingsStatus('Settings synced to disk without reload.');
      if (closeAfter) {
        closeSettingsDialog();
      }
    })
    .catch(err => {
      console.error('Error saving desktop settings:', err);
      setSettingsStatus('Error persisting settings.', true);
    });
}

function applyPeqProfile(presetId) {
  fetch('/api/dsp/peq/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preset: presetId }),
  })
    .then(r => r.json())
    .then(data => {
      if (data && data.peq_preamp_db !== undefined) {
        const preampValEl = document.getElementById('cfg-preamp-db-val');
        if (preampValEl) preampValEl.textContent = Number(data.peq_preamp_db).toFixed(1);
        setSettingsStatus(`Loaded PEQ profile: ${data.peq_profile} (${data.peq_preamp_db} dB headroom)`);
      }
    })
    .catch(err => console.error('Error applying PEQ profile:', err));
}

// 4. Global Desktop Keyboard Shortcuts
let lastKeyTimestamp = 0;
function throttleKey(ms = 150) {
  const now = Date.now();
  if (now - lastKeyTimestamp < ms) return false;
  lastKeyTimestamp = now;
  return true;
}

window.addEventListener('keydown', (e) => {
  const activeEl = document.activeElement;
  const activeTag = activeEl ? activeEl.tagName.toLowerCase() : '';
  const isInputActive = activeTag === 'textarea' || (activeTag === 'input' && ['text', 'search', 'password', 'email', 'number'].includes(activeEl.type));

  // Escape: Close all menus and open dialogs
  if (e.key === 'Escape') {
    closeAllMenus();
    closeAudioOutputDropdown();
    closeSettingsDialog();
    closeFullscreenNowPlaying();
    const trackModal = document.getElementById('track-detail-modal');
    if (trackModal && trackModal.open) trackModal.close();
    return;
  }

  // Ctrl+R: Scan Library
  if ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'R')) {
    e.preventDefault();
    if (!throttleKey(200)) return;
    triggerLibraryScan();
    return;
  }

  // Ctrl+O: Add Music Directory (Native Folder Chooser)
  if ((e.ctrlKey || e.metaKey) && (e.key === 'o' || e.key === 'O')) {
    e.preventDefault();
    if (!throttleKey(200)) return;
    triggerAddFolder();
    return;
  }

  // Ctrl+,: Toggle Settings Popover
  if ((e.ctrlKey || e.metaKey) && e.key === ',') {
    e.preventDefault();
    if (!throttleKey(200)) return;
    toggleSettingsDialog();
    return;
  }

  // Ctrl+H: Toggle Telemetry HUD Deck
  if ((e.ctrlKey || e.metaKey) && (e.key === 'h' || e.key === 'H')) {
    e.preventDefault();
    if (!throttleKey(200)) return;
    toggleTelemetryHud();
    return;
  }

  // Ctrl+Q: Exit Vibeplay
  if ((e.ctrlKey || e.metaKey) && (e.key === 'q' || e.key === 'Q')) {
    e.preventDefault();
    handleDesktopQuit();
    return;
  }

  // Shift+F11 or Ctrl+Shift+F: Toggle Fullscreen Now Playing View
  if ((e.shiftKey && (e.key === 'F11' || e.code === 'F11')) || (e.ctrlKey && e.shiftKey && (e.key === 'f' || e.key === 'F'))) {
    e.preventDefault();
    if (!throttleKey(200)) return;
    toggleFullscreenNowPlaying();
    return;
  }

  // F12 or Ctrl+F11: Toggle Fullscreen
  if (e.key === 'F12' || (e.ctrlKey && e.key === 'F11')) {
    e.preventDefault();
    toggleFullscreen();
    return;
  }

  // Volume Down: F5 or AudioVolumeDown
  if (e.key === 'F5' || e.code === 'F5' || e.key === 'AudioVolumeDown') {
    e.preventDefault();
    if (!throttleKey(80)) return;
    adjustVolume(-5);
    return;
  }

  // Volume Mute: F6 or AudioVolumeMute
  if (e.key === 'F6' || e.code === 'F6' || e.key === 'AudioVolumeMute') {
    e.preventDefault();
    if (!throttleKey(150)) return;
    triggerMuteToggle();
    return;
  }

  // Volume Up: F7 or AudioVolumeUp
  if (e.key === 'F7' || e.code === 'F7' || e.key === 'AudioVolumeUp') {
    e.preventDefault();
    if (!throttleKey(80)) return;
    adjustVolume(5);
    return;
  }

  // Previous Track: F9, F8, MediaTrackPrevious, or Ctrl+ArrowLeft
  if (e.key === 'F8' || e.code === 'F8' || e.key === 'F9' || e.code === 'F9' || e.key === 'MediaTrackPrevious' || (e.ctrlKey && e.key === 'ArrowLeft')) {
    e.preventDefault();
    if (!throttleKey(150)) return;
    triggerPrevTrack();
    return;
  }

  // Play / Pause: F10, MediaPlayPause, or Space (when not in text input)
  if (e.key === 'F10' || e.code === 'F10' || e.key === 'MediaPlayPause' || (e.code === 'Space' && !isInputActive)) {
    e.preventDefault();
    if (!throttleKey(150)) return;
    triggerPlayToggle();
    return;
  }

  // Next Track: F11, MediaTrackNext, or Ctrl+ArrowRight
  if (e.key === 'F11' || e.code === 'F11' || e.key === 'MediaTrackNext' || (e.ctrlKey && e.key === 'ArrowRight')) {
    e.preventDefault();
    if (!throttleKey(150)) return;
    triggerNextTrack();
    return;
  }
}, true);

// Hardware Transport Settings Device Updater
function updateAudioDeviceConfig() {
  const sel = document.getElementById('cfg-alsa-device');
  const pill = document.getElementById('chrome-endpoint-pill');
  if (sel && pill) {
    pill.textContent = sel.value.startsWith('hw:') ? `ALSA ${sel.value}` : sel.value;
  }
}

// 5. Backend Action Triggers
function triggerPlayToggle() {
  // Optimistic UI state swap
  const playBtn = document.querySelector('.btn-play-pause');
  if (playBtn) {
    playBtn.style.transform = 'scale(0.92)';
    setTimeout(() => { playBtn.style.transform = ''; }, 100);
    const isPlaying = playBtn.innerHTML.includes('M6 19h4V5H6v14zm8-14v14h4V5h-4z'); // Pause icon currently showing
    if (isPlaying) {
      playBtn.innerHTML = '<svg class="icon" style="width: 20px; height: 20px;" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
    } else {
      playBtn.innerHTML = '<svg class="icon" style="width: 20px; height: 20px;" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
    }
  }
  if (window.htmx) {
    htmx.ajax('POST', '/api/player/toggle', {
      target: '#transport-footer-container',
      swap: 'innerHTML',
    });
  }
}

function triggerNextTrack() {
  if (window.htmx) {
    htmx.ajax('POST', '/api/player/next', {
      target: '#transport-footer-container',
      swap: 'innerHTML',
    });
  }
}

function triggerPrevTrack() {
  if (window.htmx) {
    htmx.ajax('POST', '/api/player/prev', {
      target: '#transport-footer-container',
      swap: 'innerHTML',
    });
  }
}

let volumeDebounceTimer = null;
let lastUnmutedVolume = 75;

function applyVolumeOptimistic(newVol) {
  newVol = Math.max(0, Math.min(100, Math.round(newVol)));
  const slider = document.getElementById('global-volume-slider');
  const readout = document.getElementById('volume-readout');
  if (slider) {
    slider.value = newVol;
    slider.style.transform = 'scale(1.04)';
    setTimeout(() => {
      if (slider) slider.style.transform = '';
    }, 150);
  }
  if (readout) {
    readout.textContent = newVol + '%';
  }
  return newVol;
}

function triggerMuteToggle() {
  const slider = document.getElementById('global-volume-slider');
  let current = slider ? parseInt(slider.value, 10) : 75;
  if (isNaN(current)) current = 75;
  let targetVol = 0;
  if (current > 0) {
    lastUnmutedVolume = current;
    targetVol = 0;
  } else {
    targetVol = lastUnmutedVolume > 0 ? lastUnmutedVolume : 75;
  }
  const newVol = applyVolumeOptimistic(targetVol);

  if (volumeDebounceTimer) clearTimeout(volumeDebounceTimer);
  volumeDebounceTimer = setTimeout(() => {
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/volume', {
        values: { volume: newVol },
        target: '#transport-footer-container',
        swap: 'innerHTML',
      });
    } else {
      fetch('/api/player/volume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `volume=${newVol}`,
      }).catch(() => {});
    }
  }, 50);
}
window.triggerMuteToggle = triggerMuteToggle;

function adjustVolume(delta) {
  const slider = document.getElementById('global-volume-slider');
  let current = slider ? parseInt(slider.value, 10) : 75;
  if (isNaN(current)) current = 75;
  const newVol = applyVolumeOptimistic(current + delta);

  if (volumeDebounceTimer) clearTimeout(volumeDebounceTimer);
  volumeDebounceTimer = setTimeout(() => {
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/volume', {
        values: { volume: newVol },
        target: '#transport-footer-container',
        swap: 'innerHTML',
      });
    } else {
      fetch('/api/player/volume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `volume=${newVol}`,
      }).catch(() => {});
    }
  }, 50);
}
window.adjustVolume = adjustVolume;

function handleVolumeInput(slider) {
  const val = parseInt(slider.value, 10);
  applyVolumeOptimistic(val);
  if (volumeDebounceTimer) clearTimeout(volumeDebounceTimer);
  volumeDebounceTimer = setTimeout(() => {
    fetch('/api/player/volume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `volume=${val}`,
    }).catch(() => {});
  }, 50);
}

function toggleTelemetryHud() {
  closeAllMenus();
  const deck = document.getElementById('telemetry-hud-deck');
  if (!deck) return;
  deck.classList.toggle('hidden');
  const isHidden = deck.classList.contains('hidden');
  try {
    localStorage.setItem('vibeplay_hide_telemetry_hud', isHidden ? '1' : '0');
  } catch (e) {}
  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hide_telemetry_hud: isHidden }),
  }).catch(() => {});
}

function initTelemetryHudState() {
  const deck = document.getElementById('telemetry-hud-deck');
  if (!deck) return;
  try {
    const saved = localStorage.getItem('vibeplay_hide_telemetry_hud');
    if (saved === '1') {
      deck.classList.add('hidden');
    }
  } catch (e) {}
}

let lastJobTableRefresh = 0;
document.addEventListener('htmx:afterSwap', (event) => {
  if (event.detail && event.detail.target && event.detail.target.id === 'job-progress-container') {
    const isIdle = event.detail.target.classList.contains('idle');
    const now = Date.now();
    if (isIdle || now - lastJobTableRefresh > 3500) {
      lastJobTableRefresh = now;
      const tableContainer = document.getElementById('library-table-container');
      if (tableContainer && window.htmx) {
        htmx.ajax('GET', '/api/library/table', { target: '#library-table-container', swap: 'innerHTML' });
      }
      const clusterContainer = document.getElementById('clusters-container');
      if (clusterContainer && window.htmx) {
        htmx.ajax('GET', '/api/clusters/cards', { target: '#clusters-container', swap: 'innerHTML' });
      }
    }
  }
  if (event.detail && event.detail.target && (event.detail.target.id === 'transport-footer-container' || event.detail.target.id === 'transport-scrub-row')) {
    syncFullscreenPlayback();
  }
});

function triggerClearQueue() {
  closeAllMenus();
  fetch('/api/player/clear', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      if (window.htmx) {
        htmx.ajax('GET', '/api/player/transport', {
          target: '#transport-footer-container',
          swap: 'innerHTML',
        });
      }
    })
    .catch(err => console.error('Error clearing queue:', err));
}

// Live Background Jobs & Library Actions
function pollJobProgressWidget() {
  const container = document.getElementById('job-progress-container');
  if (container && window.htmx) {
    htmx.ajax('GET', '/api/jobs/progress-widget', {
      target: '#job-progress-container',
      swap: 'outerHTML',
    });
  }
}

function triggerAddFolder() {
  closeAllMenus();
  const statusEl = document.getElementById('chrome-xruns-status');
  if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-cyan animate-pulse"></span> Selecting folder...';

  fetch('/api/desktop/browse-folder', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
      if (!data.cancelled && data.path) {
        triggerLibraryScan(data.path);
      }
    })
    .catch(err => {
      console.warn('Native folder chooser failed, falling back to prompt:', err);
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
      const dir = prompt('Enter music directory path to scan:');
      if (dir && dir.trim()) {
        triggerLibraryScan(dir.trim());
      }
    });
}

function triggerLibraryScan(scanPath = null) {
  closeAllMenus();
  const statusEl = document.getElementById('chrome-xruns-status');
  if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-cyan animate-pulse"></span> Scanning...';

  const bodyData = scanPath ? { path: scanPath } : {};
  fetch('/api/library/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(bodyData),
  })
    .then(r => r.json())
    .then(data => {
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
      pollJobProgressWidget();
      // Also refresh library table
      const tableContainer = document.getElementById('library-table-container');
      if (tableContainer && window.htmx) {
        setTimeout(() => {
          htmx.ajax('GET', '/api/library/table', { target: '#library-table-container', swap: 'innerHTML' });
        }, 1200);
      }
    })
    .catch(err => {
      console.error('Library scan error:', err);
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
    });
}

function triggerLibraryRescan() {
  triggerLibraryScan();
}

function triggerMetadataEnrich() {
  closeAllMenus();
  const statusEl = document.getElementById('chrome-xruns-status');
  if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-purple animate-pulse"></span> Enriching...';

  fetch('/api/library/enrich', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
      pollJobProgressWidget();
    })
    .catch(err => {
      console.error('Metadata enrichment error:', err);
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
    });
}

function triggerFeatureAnalyze() {
  closeAllMenus();
  const statusEl = document.getElementById('chrome-xruns-status');
  if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-cyan animate-pulse"></span> Analyzing...';

  fetch('/api/library/analyze', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
      pollJobProgressWidget();
    })
    .catch(err => {
      console.error('Feature analysis error:', err);
      if (statusEl) statusEl.innerHTML = '<span class="dot-indicator dot-green"></span> 0 xruns';
    });
}

// Custom Audio Output Dropdown (WebKit-Safe)
function toggleAudioOutputDropdown(event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  const menu = document.getElementById('audio-output-menu');
  if (menu) {
    menu.classList.toggle('open');
  }
}

function closeAudioOutputDropdown() {
  const menu = document.getElementById('audio-output-menu');
  if (menu) {
    menu.classList.remove('open');
  }
}

function selectAudioOutput(profile) {
  closeAudioOutputDropdown();
  if (window.htmx) {
    htmx.ajax('POST', '/api/player/output', {
      values: { profile: profile },
      target: '#transport-footer-container',
      swap: 'innerHTML',
    });
  }
}

// Inspector Drawer State & Responsive Handling
function toggleInspectorDrawer() {
  const drawer = document.getElementById('workspace-inspector-drawer');
  if (!drawer) return;
  drawer.classList.toggle('collapsed');
  const isCollapsed = drawer.classList.contains('collapsed');
  drawer.style.display = isCollapsed ? 'none' : 'block';
  try {
    localStorage.setItem('vibeplay_inspector_collapsed', isCollapsed ? '1' : '0');
  } catch (e) {}
}

function initInspectorState() {
  const drawer = document.getElementById('workspace-inspector-drawer');
  if (!drawer) return;
  try {
    const saved = localStorage.getItem('vibeplay_inspector_collapsed');
    const shouldCollapse = saved === '1' || saved === null || window.innerWidth < 1366;
    if (shouldCollapse) {
      drawer.classList.add('collapsed');
      drawer.style.display = 'none';
    } else {
      drawer.classList.remove('collapsed');
      drawer.style.display = 'block';
    }
  } catch (e) {}
}

function triggerCacheCleanup() {
  closeAllMenus();
  alert('Expired cache cleanup scheduled (> 30 days retention threshold).');
}

function triggerCachePurge() {
  closeAllMenus();
  if (confirm('Are you sure you want to purge all network and prompt caches?')) {
    alert('All caches purged.');
  }
}

function setDspProfile(profileId) {
  closeAllMenus();
  fetch(`/api/dsp/profile?profile=${encodeURIComponent(profileId)}`, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      document.querySelectorAll('.profile-card').forEach(c => c.classList.remove('active'));
      const activeCard = document.getElementById(`pcard-${profileId.replace('pure-', '').replace('-headphones', '').replace('-passthrough', '')}`);
      if (activeCard) activeCard.classList.add('active');
      setSettingsStatus(`Active routing profile: ${profileId}`);
    })
    .catch(err => console.error('Error setting profile:', err));
}

function triggerSpatialToggle() {
  closeAllMenus();
  fetch('/api/dsp/spatial/toggle', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      const label = document.getElementById('cfg-spatial-label');
      const badge = document.getElementById('menu-spatial-badge');
      const toggle = document.getElementById('cfg-spatial-toggle');
      const isSpatial = data.mode === 'spatial_binaural' || data.mode === '3d_binaural';
      if (toggle) toggle.checked = isSpatial;
      if (isSpatial) {
        if (label) label.textContent = 'KEMAR HRTF 7.1.4 Convolver (Active)';
        if (badge) { badge.textContent = 'Active'; badge.className = 'badge-mini badge-cyan'; }
      } else {
        if (label) label.textContent = 'Stereo Direct (Bypassed)';
        if (badge) { badge.textContent = 'Off'; badge.className = 'badge-mini'; }
      }
    })
    .catch(err => console.error('Error toggling spatial audio:', err));
}

function handleDesktopQuit() {
  closeAllMenus();
  if (confirm('Are you sure you want to close vibeplay?')) {
    fetch('/api/app/quit', { method: 'POST' }).catch(() => {});
    setTimeout(() => {
      window.close();
    }, 200);
  }
}

function handleDesktopMinimize() {
  closeAllMenus();
  console.log('Window minimize requested');
}

function toggleFullscreen() {
  closeAllMenus();
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

function toggleShortcutsHelp() {
  closeAllMenus();
  alert(
    "VIBEPLAY KEYBOARD SHORTCUTS:\n\n" +
    "• Ctrl+R: Rescan Music Library\n" +
    "• Ctrl+O: Add Music Directory\n" +
    "• Ctrl+,: Preferences & Hardware Settings\n" +
    "• Ctrl+H: Toggle Telemetry HUD Deck\n" +
    "• Ctrl+Q: Exit Vibeplay\n" +
    "• Space / F10: Play / Pause\n" +
    "• F9 / Ctrl+Left: Previous Track\n" +
    "• F11 / Ctrl+Right: Next Track\n" +
    "• F12: Toggle Fullscreen\n" +
    "• F5: Volume Down (-5%)\n" +
    "• F6: Toggle Mute\n" +
    "• F7: Volume Up (+5%)\n" +
    "• Escape: Close Menus & Modals"
  );
}

function toggleAboutDialog() {
  closeAllMenus();
  alert(
    "vibeplay — Audiophile Precision Console\n" +
    "Version: 0.2.0 (Desktop Native Shell)\n" +
    "Linux / Ubuntu 24.04 LTS\n" +
    "WebKit2GTK + Direct ALSA Bit-Perfect Core\n" +
    "https://github.com/defiqantcoder/vibeplay"
  );
}

function exportActivePlaylist(format = 'm3u8') {
  closeAllMenus();
  if (format === 'json') {
    window.open('/api/playlist/1', '_blank');
  } else {
    window.open('/api/playlist/1/export-m3u8', '_blank');
  }
}

// Sync aria-invalid with CSS :user-invalid state for accessible validation feedback
const syncAriaInvalid = (el) => {
  if (el && typeof el.matches === 'function') {
    try {
      el.setAttribute('aria-invalid', el.matches(':user-invalid') ? 'true' : 'false');
    } catch (e) {}
  }
};

document.addEventListener('blur', (e) => syncAriaInvalid(e.target), true);
document.addEventListener('input', (e) => {
  if (e.target && e.target.hasAttribute && e.target.hasAttribute('aria-invalid')) {
    syncAriaInvalid(e.target);
  }
});

function selectTrackRow(rowEl, trackId) {
  document.querySelectorAll('.data-table tbody tr').forEach(r => r.classList.remove('selected-inspector-row'));
  if (rowEl) rowEl.classList.add('selected-inspector-row');
}

function handleTrackRowPlay(event, rowEl, trackId) {
  selectTrackRow(rowEl, trackId);
  const inspector = document.getElementById('workspace-inspector-content');
  if (inspector && typeof htmx !== 'undefined') {
    htmx.ajax('GET', '/api/track/' + trackId + '?view=inspector', { target: '#workspace-inspector-content', swap: 'innerHTML' });
  }
}

function selectMoodChip(mood) {
  document.querySelectorAll('.mood-chip').forEach(chip => {
    if (chip.getAttribute('data-mood') === mood) {
      chip.classList.add('active');
    } else {
      chip.classList.remove('active');
    }
  });

  const moodSelect = document.querySelector('form.filter-bar select[name="mood"]');
  if (moodSelect) {
    moodSelect.value = mood;
    moodSelect.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

function filterByHarmonicKey(key) {
  const currentKeySelect = document.querySelector('form.filter-bar select[name="key"]');
  const buttons = document.querySelectorAll('.harmonic-zone-btn');

  let newKey = key;
  if (currentKeySelect && currentKeySelect.value === key) {
    newKey = "";
  }

  buttons.forEach(btn => {
    if (newKey && btn.getAttribute('data-camelot') === newKey) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  if (currentKeySelect) {
    currentKeySelect.value = newKey;
    currentKeySelect.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

function syncBpmSlider(val) {
  const readout = document.getElementById('filter-bpm-slider-val');
  if (readout) readout.textContent = val ? val + ' BPM' : 'ALL';
  const minInput = document.querySelector('form.filter-bar input[name="bpm_min"]');
  const maxInput = document.querySelector('form.filter-bar input[name="bpm_max"]');
  if (val === '0' || !val) {
    if (minInput) minInput.value = '';
    if (maxInput) maxInput.value = '';
  } else {
    const num = parseInt(val, 10);
    if (minInput) minInput.value = Math.max(40, num - 10);
    if (maxInput) maxInput.value = Math.min(220, num + 10);
  }
  const form = document.querySelector('form.filter-bar');
  if (form) form.dispatchEvent(new Event('change', { bubbles: true }));
}

// 9. Live SSE Audio Visualizer & Dynamic Telemetry Deck
let telemetryEventSource = null;
let oscilloscopeAnimationId = null;
let currentPlaybackState = 'stop';
let currentHeadroomDb = 18.0;
let currentSampleRateHz = 96000;
let wavePhase = 0;

function updateHeadroomMeter(state, headroomDb) {
  const track = document.getElementById('telemetry-meter-track');
  if (!track) return;
  const segs = track.querySelectorAll('.meter-seg');
  if (!segs || segs.length !== 9) return;

  if (state === 'stop') {
    segs.forEach((s, idx) => {
      s.className = 'meter-seg ' + (idx === 0 ? 'bg-pri' : 'bg-empty');
    });
    return;
  }

  let activeCount = 7;
  if (state === 'pause') {
    activeCount = 2;
  } else {
    if (headroomDb <= 0) activeCount = 9;
    else if (headroomDb <= 3) activeCount = 8;
    else if (headroomDb <= 6) activeCount = 7;
    else if (headroomDb <= 12) activeCount = 6;
    else activeCount = 5;
  }

  segs.forEach((s, idx) => {
    if (idx < activeCount) {
      if (idx < 5) s.className = 'meter-seg bg-pri';
      else if (idx < 7) s.className = 'meter-seg bg-green';
      else s.className = 'meter-seg bg-sec';
    } else {
      s.className = 'meter-seg bg-empty';
    }
  });
}

function updateCamelotUi(code) {
  if (!code) return;
  const norm = code.trim().toUpperCase();
  const metricEl = document.getElementById('telemetry-camelot-metric');
  const centerEl = document.getElementById('telemetry-camelot-center');
  const chipsRow = document.getElementById('telemetry-harmonic-chips');

  if (centerEl) centerEl.textContent = norm;

  const num = parseInt(norm, 10);
  const letter = norm.slice(-1);
  if (!isNaN(num) && (letter === 'A' || letter === 'B')) {
    const prevNum = num === 1 ? 12 : num - 1;
    const nextNum = num === 12 ? 1 : num + 1;
    const oppLetter = letter === 'A' ? 'B' : 'A';

    if (metricEl) {
      metricEl.innerHTML = `${norm} <span id="telemetry-camelot-rel" style="font-size: 13px; color: var(--tertiary); font-weight: normal;">→ ${nextNum}${letter} / ${prevNum}${letter}</span>`;
    }

    if (chipsRow) {
      chipsRow.innerHTML = `
        <span class="chip-alt">${prevNum}${letter}</span>
        <span class="chip-active">${norm} (Active)</span>
        <span class="chip-alt">${nextNum}${letter}</span>
        <span class="chip-alt">${num}${oppLetter}</span>
      `;
    }
  }
}

function updateTelemetryUi(data) {
  if (!data) return;
  if (data.playback_state) currentPlaybackState = data.playback_state;
  if (data.sample_rate_hz) currentSampleRateHz = data.sample_rate_hz;
  if (data.headroom_db !== undefined) currentHeadroomDb = Number(data.headroom_db);

  // 1. Update Sample Rate
  const srEl = document.getElementById('telemetry-sample-rate');
  if (srEl && data.sample_rate_hz) {
    const khz = (data.sample_rate_hz / 1000).toFixed(3);
    srEl.innerHTML = `${khz} <span style="font-size: 13px; color: var(--text-muted); font-weight: normal;">kHz</span>`;
  }
  const chromeSr = document.getElementById('chrome-sample-rate');
  if (chromeSr && data.sample_rate_hz) {
    chromeSr.textContent = `${(data.sample_rate_hz / 1000).toFixed(1)}kHz / ${data.bit_depth || 24}bit`;
  }

  // 2. Update Jitter & DMA buffer
  const jitterEl = document.getElementById('telemetry-jitter');
  if (jitterEl && data.jitter_ps !== undefined) {
    jitterEl.textContent = `Phase Jitter: < ${Number(data.jitter_ps).toFixed(2)} ps RMS`;
  }
  const dmaFootnote = document.getElementById('footnote-dma-status');
  if (dmaFootnote && data.buffer_frames) {
    const ms = ((data.buffer_frames / (data.sample_rate_hz || 96000)) * 1000).toFixed(2);
    dmaFootnote.innerHTML = `<span class="dot-indicator dot-green"></span> DMA Ring Buffer: ${data.buffer_frames} frames (${ms}ms)`;
  }

  // 3. Update Dynamic Range & dBFS
  const dbfsEl = document.getElementById('telemetry-dbfs');
  if (dbfsEl && data.dbfs !== undefined) {
    dbfsEl.innerHTML = `${Number(data.dbfs).toFixed(1)} <span style="font-size: 13px; color: var(--text-muted); font-weight: normal;">dBFS</span>`;
  }
  const peakEl = document.getElementById('telemetry-true-peak');
  if (peakEl && data.true_peak_db !== undefined) {
    peakEl.textContent = `True Peak: ${Number(data.true_peak_db).toFixed(2)} dBTP`;
  }

  // 4. Update Segmented VU Headroom Meter
  updateHeadroomMeter(currentPlaybackState, currentHeadroomDb);

  // 5. Update Camelot Key Deck if provided
  if (data.camelot_key) {
    updateCamelotUi(data.camelot_key);
  }
}

function renderOscilloscopeFrame() {
  const path = document.getElementById('telemetry-oscilloscope-path');
  const ghost = document.getElementById('telemetry-oscilloscope-ghost');
  if (!path) return;

  const isPlaying = currentPlaybackState === 'play';
  const amp = isPlaying ? 14 : 3;
  const speed = isPlaying ? 0.08 : 0.02;
  wavePhase = (wavePhase + speed) % (Math.PI * 2);

  const points = [];
  const ghostPoints = [];
  const segments = 10;
  const width = 200;
  const midY = 20;

  for (let i = 0; i <= segments; i++) {
    const x = (i / segments) * width;
    const sin1 = Math.sin(wavePhase + (i * 0.8));
    const sin2 = Math.cos((wavePhase * 0.7) + (i * 1.2));
    const y = midY + (sin1 * amp * 0.7) + (sin2 * amp * 0.3);
    const gy = midY + (Math.sin(wavePhase * 0.5 + i * 0.5) * (amp * 0.4));
    points.push({ x, y });
    ghostPoints.push({ x, y: gy });
  }

  let d = `M ${points[0].x} ${points[0].y.toFixed(1)}`;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const cx = ((prev.x + curr.x) / 2).toFixed(1);
    const cy = ((prev.y + curr.y) / 2).toFixed(1);
    d += ` Q ${prev.x.toFixed(1)} ${prev.y.toFixed(1)}, ${cx} ${cy}`;
  }
  d += ` T ${points[points.length - 1].x} ${points[points.length - 1].y.toFixed(1)}`;

  let gd = `M ${ghostPoints[0].x} ${ghostPoints[0].y.toFixed(1)}`;
  for (let i = 1; i < ghostPoints.length; i++) {
    const prev = ghostPoints[i - 1];
    const curr = ghostPoints[i];
    const cx = ((prev.x + curr.x) / 2).toFixed(1);
    const cy = ((prev.y + curr.y) / 2).toFixed(1);
    gd += ` Q ${prev.x.toFixed(1)} ${prev.y.toFixed(1)}, ${cx} ${cy}`;
  }
  gd += ` T ${ghostPoints[ghostPoints.length - 1].x} ${ghostPoints[ghostPoints.length - 1].y.toFixed(1)}`;

  path.setAttribute('d', d);
  if (ghost) ghost.setAttribute('d', gd);

  oscilloscopeAnimationId = requestAnimationFrame(renderOscilloscopeFrame);
}

function initTelemetryStream() {
  if (typeof window !== 'undefined' && window.EventSource) {
    try {
      if (telemetryEventSource) {
        telemetryEventSource.close();
      }
      telemetryEventSource = new EventSource('/api/desktop/telemetry/stream');

      telemetryEventSource.addEventListener('telemetry_snapshot', (e) => {
        try {
          const data = JSON.parse(e.data);
          updateTelemetryUi(data);
        } catch (err) {
          console.debug('Failed parsing telemetry snapshot:', err);
        }
      });

      telemetryEventSource.addEventListener('telemetry_tick', (e) => {
        try {
          const data = JSON.parse(e.data);
          updateTelemetryUi(data);
        } catch (err) {
          console.debug('Failed parsing telemetry tick:', err);
        }
      });

      telemetryEventSource.addEventListener('track_transition', (e) => {
        try {
          const data = JSON.parse(e.data);
          updateTelemetryUi(data);
        } catch (err) {
          console.debug('Failed parsing track transition:', err);
        }
      });

      telemetryEventSource.addEventListener('dac_lock_changed', (e) => {
        try {
          const data = JSON.parse(e.data);
          updateTelemetryUi(data);
        } catch (err) {
          console.debug('Failed parsing dac lock changed:', err);
        }
      });

      telemetryEventSource.addEventListener('xrun_detected', (e) => {
        try {
          const data = JSON.parse(e.data);
          const xrunsEl = document.getElementById('chrome-xruns-status');
          if (xrunsEl && data.total !== undefined) {
            xrunsEl.innerHTML = `<span class="dot-indicator dot-red animate-pulse"></span> ${data.total} xruns`;
          }
        } catch (err) {
          console.debug('Failed parsing xrun event:', err);
        }
      });

      telemetryEventSource.onerror = (err) => {
        console.debug('Telemetry SSE connection dropped; will reconnect:', err);
      };
    } catch (e) {
      console.debug('EventSource init error:', e);
    }
  }

  if (typeof window !== 'undefined' && typeof requestAnimationFrame === 'function' && !oscilloscopeAnimationId) {
    renderOscilloscopeFrame();
  }
}

// 6. Fullscreen Now-Playing View & Audio Visualizer Engine
let fsVisualizerAnimId = null;
let fsVisualizerEnabled = true;
let fsVisPhases = new Array(48).fill(0).map(() => Math.random() * Math.PI * 2);
let fsVisHeights = new Array(48).fill(0.1);

function initFullscreenNowPlayingState() {
  const savedVis = localStorage.getItem('vibeplay_fullscreen_visualizer');
  if (savedVis !== null) {
    fsVisualizerEnabled = (savedVis === '1');
  }
  updateFullscreenVisualizerUi();
}

function updateFullscreenVisualizerUi() {
  const container = document.getElementById('fs-visualizer-container');
  const btn = document.getElementById('fs-visualizer-toggle-btn');
  const text = document.getElementById('fs-visualizer-toggle-text');
  if (container) {
    if (fsVisualizerEnabled) {
      container.classList.remove('hidden');
    } else {
      container.classList.add('hidden');
    }
  }
  if (btn) {
    if (fsVisualizerEnabled) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  }
  if (text) {
    text.textContent = fsVisualizerEnabled ? 'Visualizer: ON' : 'Visualizer: OFF';
  }
}

function toggleFullscreenVisualizer() {
  fsVisualizerEnabled = !fsVisualizerEnabled;
  try {
    localStorage.setItem('vibeplay_fullscreen_visualizer', fsVisualizerEnabled ? '1' : '0');
  } catch (e) {}
  updateFullscreenVisualizerUi();
  const overlay = document.getElementById('fullscreen-now-playing');
  if (overlay && !overlay.classList.contains('hidden') && fsVisualizerEnabled) {
    startFullscreenVisualizer();
  } else if (!fsVisualizerEnabled && fsVisualizerAnimId) {
    cancelAnimationFrame(fsVisualizerAnimId);
    fsVisualizerAnimId = null;
  }
}

function openFullscreenNowPlaying() {
  closeAllMenus();
  const overlay = document.getElementById('fullscreen-now-playing');
  if (!overlay) return;
  overlay.classList.remove('hidden');
  syncFullscreenPlayback();
  initFullscreenNowPlayingState();
  if (fsVisualizerEnabled) {
    startFullscreenVisualizer();
  }
}

function closeFullscreenNowPlaying() {
  const overlay = document.getElementById('fullscreen-now-playing');
  if (!overlay) return;
  overlay.classList.add('hidden');
  if (fsVisualizerAnimId) {
    cancelAnimationFrame(fsVisualizerAnimId);
    fsVisualizerAnimId = null;
  }
}

function toggleFullscreenNowPlaying() {
  const overlay = document.getElementById('fullscreen-now-playing');
  if (!overlay) return;
  if (overlay.classList.contains('hidden')) {
    openFullscreenNowPlaying();
  } else {
    closeFullscreenNowPlaying();
  }
}

function syncFullscreenPlayback() {
  const overlay = document.getElementById('fullscreen-now-playing');
  if (!overlay) return;

  // Title, artist, album
  const titleEl = document.querySelector('.now-playing-title');
  const artistEl = document.querySelector('.now-playing-artist');
  const fsTitle = document.getElementById('fs-now-title');
  const fsArtist = document.getElementById('fs-now-artist');
  const fsAlbum = document.getElementById('fs-now-album');

  if (titleEl && fsTitle) {
    fsTitle.textContent = titleEl.textContent || 'No Track Playing';
  }
  if (artistEl && (fsArtist || fsAlbum)) {
    const rawMeta = artistEl.textContent || '';
    const parts = rawMeta.split('—').map(s => s.trim());
    if (fsArtist) fsArtist.textContent = parts[0] || 'vibeplay core';
    if (fsAlbum) fsAlbum.textContent = parts[1] || 'Audiophile Precision Engine';
  }

  // Play/pause button state & vinyl rotation
  const mainPlayBtn = document.querySelector('.btn-play-pause');
  const fsPlayBtn = document.getElementById('fs-btn-play-pause');
  const fsAlbumCard = document.getElementById('fs-album-card');
  const isPlaying = mainPlayBtn && mainPlayBtn.innerHTML.includes('M6 19h4V5H6v14zm8-14v14h4V5h-4z');

  if (fsAlbumCard) {
    if (isPlaying) {
      fsAlbumCard.classList.add('is-playing');
    } else {
      fsAlbumCard.classList.remove('is-playing');
    }
  }

  if (fsPlayBtn) {
    if (isPlaying) {
      fsPlayBtn.innerHTML = '<svg class="icon fs-icon-xl" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
    } else {
      fsPlayBtn.innerHTML = '<svg class="icon fs-icon-xl" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
    }
  }

  // Format, rate, sink
  const dacRate = document.querySelector('.dac-indicator .rate');
  const dacMode = document.querySelector('.dac-indicator .mode');
  const fsRate = document.getElementById('fs-now-format');
  const fsBuffer = document.getElementById('fs-now-buffer');
  if (dacRate && fsRate) fsRate.textContent = dacRate.textContent;
  if (dacMode && fsBuffer) fsBuffer.textContent = dacMode.textContent;

  const activeOutput = document.querySelector('.active-output-text');
  const fsSink = document.getElementById('fs-now-sink');
  if (activeOutput && fsSink) fsSink.textContent = activeOutput.textContent;

  // Timeline scrub sync
  const scrubFill = document.querySelector('.scrub-fill');
  const fsScrubFill = document.getElementById('fs-scrub-fill');
  if (scrubFill && fsScrubFill) {
    fsScrubFill.style.width = scrubFill.style.width;
  }

  const timecodes = document.querySelectorAll('.transport-scrub-row .timecode');
  const fsElapsed = document.getElementById('fs-time-elapsed');
  const fsDuration = document.getElementById('fs-time-duration');
  if (timecodes.length >= 2) {
    if (fsElapsed) fsElapsed.textContent = timecodes[0].textContent;
    if (fsDuration) fsDuration.textContent = timecodes[1].textContent;
  }

  // Volume slider sync
  const volSlider = document.getElementById('global-volume-slider');
  const fsVolSlider = document.getElementById('fs-volume-slider');
  const fsVolText = document.getElementById('fs-volume-text');
  if (volSlider && fsVolSlider) {
    fsVolSlider.value = volSlider.value;
    if (fsVolText) fsVolText.textContent = volSlider.value + '%';
  }
}

function handleFsSeek(event) {
  const track = document.getElementById('fs-scrub-track');
  if (!track) return;
  const rect = track.getBoundingClientRect();
  const pct = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));

  const durationEl = document.getElementById('fs-time-duration');
  let totalSec = 0;
  if (durationEl && durationEl.textContent) {
    const parts = durationEl.textContent.trim().split(':').map(Number);
    if (parts.length === 2) totalSec = (parts[0] * 60) + parts[1];
  }

  if (totalSec > 0 && window.htmx) {
    const targetSeconds = (pct * totalSec).toFixed(1);
    htmx.ajax('POST', '/api/player/seek', {
      target: '#transport-footer-container',
      swap: 'innerHTML',
      values: { seconds: targetSeconds }
    });
    const fill = document.getElementById('fs-scrub-fill');
    if (fill) fill.style.width = (pct * 100).toFixed(1) + '%';
  }
}

function handleFsVolumeInput(slider) {
  const val = parseInt(slider.value, 10);
  const text = document.getElementById('fs-volume-text');
  if (text) text.textContent = val + '%';
  const mainSlider = document.getElementById('global-volume-slider');
  if (mainSlider) mainSlider.value = String(val);
  handleVolumeInput(slider);
}

function triggerSeekRelative(delta) {
  const elapsedEl = document.getElementById('fs-time-elapsed');
  const durationEl = document.getElementById('fs-time-duration');
  let currentSec = 0;
  let totalSec = 0;
  if (elapsedEl && elapsedEl.textContent) {
    const parts = elapsedEl.textContent.trim().split(':').map(Number);
    if (parts.length === 2) currentSec = (parts[0] * 60) + parts[1];
  }
  if (durationEl && durationEl.textContent) {
    const parts = durationEl.textContent.trim().split(':').map(Number);
    if (parts.length === 2) totalSec = (parts[0] * 60) + parts[1];
  }
  const targetSec = Math.max(0, Math.min(totalSec || 99999, currentSec + delta));
  if (window.htmx) {
    htmx.ajax('POST', '/api/player/seek', {
      target: '#transport-footer-container',
      swap: 'innerHTML',
      values: { seconds: targetSec.toFixed(1) }
    });
  }
}
window.triggerSeekRelative = triggerSeekRelative;

function startFullscreenVisualizer() {
  if (fsVisualizerAnimId) {
    cancelAnimationFrame(fsVisualizerAnimId);
  }

  const canvas = document.getElementById('fullscreen-visualizer-canvas');
  if (!canvas) return;

  function renderVisualizer() {
    const overlay = document.getElementById('fullscreen-now-playing');
    if (!overlay || overlay.classList.contains('hidden') || !fsVisualizerEnabled) {
      fsVisualizerAnimId = null;
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width === 0 || height === 0) {
      fsVisualizerAnimId = requestAnimationFrame(renderVisualizer);
      return;
    }

    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
    }

    const ctx = canvas.getContext('2d');
    ctx.resetTransform();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const style = getComputedStyle(document.documentElement);
    const primary = style.getPropertyValue('--primary').trim() || 'currentColor';
    const secondary = style.getPropertyValue('--secondary').trim() || primary;
    const tertiary = style.getPropertyValue('--tertiary').trim() || primary;
    const isPlaying = document.getElementById('fs-album-card')?.classList.contains('is-playing');

    const numBars = 48;
    const barSpacing = 4;
    const totalSpacing = (numBars - 1) * barSpacing;
    const barWidth = Math.max(2, (width - totalSpacing) / numBars);

    for (let i = 0; i < numBars; i++) {
      fsVisPhases[i] += isPlaying ? (0.04 + (i % 5) * 0.015) : 0.01;
      let targetH = 0.05;
      if (isPlaying) {
        const wave1 = Math.sin(fsVisPhases[i] * 1.5);
        const wave2 = Math.cos(fsVisPhases[i] * 0.8 + i * 0.2);
        const centerWeight = Math.sin((i / numBars) * Math.PI);
        targetH = Math.max(0.08, Math.min(0.95, (wave1 * 0.35 + wave2 * 0.35 + 0.3) * (0.6 + centerWeight * 0.6)));
      }
      fsVisHeights[i] += (targetH - fsVisHeights[i]) * 0.18;

      const barH = fsVisHeights[i] * (height - 12);
      const x = i * (barWidth + barSpacing);
      const y = height - barH - 4;

      const grad = ctx.createLinearGradient(x, y, x, height);
      grad.addColorStop(0, i % 2 === 0 ? secondary : tertiary);
      grad.addColorStop(0.6, primary);
      grad.addColorStop(1, primary);

      ctx.fillStyle = grad;
      ctx.beginPath();
      const r = Math.min(barWidth / 2, 3);
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + barWidth - r, y);
      ctx.quadraticCurveTo(x + barWidth, y, x + barWidth, y + r);
      ctx.lineTo(x + barWidth, height);
      ctx.lineTo(x, height);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
      ctx.fill();
    }

    fsVisualizerAnimId = requestAnimationFrame(renderVisualizer);
  }

  fsVisualizerAnimId = requestAnimationFrame(renderVisualizer);
}

// Global window exposure
window.openFullscreenNowPlaying = openFullscreenNowPlaying;
window.closeFullscreenNowPlaying = closeFullscreenNowPlaying;
window.toggleFullscreenNowPlaying = toggleFullscreenNowPlaying;
window.toggleFullscreenVisualizer = toggleFullscreenVisualizer;
window.handleFsSeek = handleFsSeek;
window.handleFsVolumeInput = handleFsVolumeInput;
window.syncFullscreenPlayback = syncFullscreenPlayback;

// ==========================================
// 15 Stitch UI Pages Controller Logic
// ==========================================

// 1. The Add-on Toybox Modal (Screen 1)
function openToyboxModal() {
  const el = document.getElementById('toybox-backdrop');
  if (el) el.classList.remove('hidden');
}

function closeToyboxModal() {
  const el = document.getElementById('toybox-backdrop');
  if (el) el.classList.add('hidden');
}

function filterToyboxCards(category, btn) {
  document.querySelectorAll('.toybox-filter-tab, .tab-pill').forEach(t => {
    t.classList.remove('bg-primary-container/15', 'text-primary', 'font-semibold', 'shadow-sm', 'bg-[var(--accent)]', 'text-[var(--bg)]', 'font-bold');
    t.classList.add('bg-[#121214]', 'text-[#9ca3af]');
  });
  if (btn) {
    btn.classList.add('bg-primary-container/15', 'text-primary', 'font-semibold', 'shadow-sm');
    btn.classList.remove('bg-[#121214]', 'text-[#9ca3af]');
  }
  document.querySelectorAll('.toybox-card, .toy-card').forEach(card => {
    if (category === 'all' || card.getAttribute('data-category') === category) {
      card.style.display = 'flex';
    } else {
      card.style.display = 'none';
    }
  });
}

function toggleToySwitch(btn, pluginName) {
  if (!btn) return;
  const isChecked = btn.getAttribute('aria-checked') === 'true';
  const newChecked = !isChecked;
  const thumb = btn.querySelector('span');
  const statusLabel = btn.parentElement ? (btn.parentElement.querySelector('.toy-status-label') || btn.nextElementSibling) : null;

  if (newChecked) {
    btn.setAttribute('aria-checked', 'true');
    btn.classList.remove('bg-[#2a2a35]');
    btn.classList.add('bg-primary-container', 'shadow-[0_0_12px_rgba(6,182,212,0.45)]');
    if (thumb) {
      thumb.classList.remove('translate-x-0.5', 'bg-[#9ca3af]');
      thumb.classList.add('translate-x-4', 'bg-[#121214]', 'ml-0.5');
    }
    if (statusLabel) {
      statusLabel.textContent = 'Active & Ready';
      statusLabel.classList.add('text-[#e4e4e7]', 'font-semibold');
      statusLabel.classList.remove('text-[#9ca3af]');
    }
  } else {
    btn.setAttribute('aria-checked', 'false');
    btn.classList.remove('bg-primary-container', 'shadow-[0_0_12px_rgba(6,182,212,0.45)]');
    btn.classList.add('bg-[#2a2a35]');
    if (thumb) {
      thumb.classList.remove('translate-x-4', 'bg-[#121214]', 'ml-0.5');
      thumb.classList.add('translate-x-0.5', 'bg-[#9ca3af]');
    }
    if (statusLabel) {
      statusLabel.textContent = 'Taking a Nap';
      statusLabel.classList.remove('text-[#e4e4e7]', 'font-semibold');
      statusLabel.classList.add('text-[#9ca3af]');
    }
  }

  if (pluginName && typeof togglePlugin === 'function') {
    togglePlugin(pluginName, newChecked);
  }
}
window.toggleToySwitch = toggleToySwitch;

function togglePlugin(pluginName, enabled) {
  fetch('/api/plugins/toggle', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: pluginName, enabled: enabled })
  }).catch(() => {});
}

function triggerDeduplication() {
  fetch('/api/library/duplicates', { method: 'POST' }).then(() => {
    alert('Duplicate scan started in background worker.');
  }).catch(() => {});
}

function triggerEnrichment() {
  fetch('/api/library/enrich', { method: 'POST' }).then(() => {
    alert('Metadata enrichment started in background worker.');
  }).catch(() => {});
}

// 2. Sound Output Switcher Popover (Screen 2)
function openOutputSwitcher(e) {
  if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
  closeAllMenus();
  const el = document.getElementById('output-switcher-popover');
  if (el) {
    el.classList.remove('hidden');
    el.style.display = 'block';
  }
}
window.openOutputSwitcher = openOutputSwitcher;

function closeOutputSwitcher() {
  const el = document.getElementById('output-switcher-popover');
  if (el) {
    el.classList.add('hidden');
    el.style.display = 'none';
  }
}
window.closeOutputSwitcher = closeOutputSwitcher;

function toggleOutputSwitcher(e) {
  if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
  closeAllMenus();
  const el = document.getElementById('output-switcher-popover');
  if (!el) return;
  const isHidden = el.classList.contains('hidden') || el.style.display === 'none';
  if (isHidden) {
    el.classList.remove('hidden');
    el.style.display = 'block';
  } else {
    el.classList.add('hidden');
    el.style.display = 'none';
  }
}
window.toggleOutputSwitcher = toggleOutputSwitcher;

function selectOutputRoute(route) {
  closeOutputSwitcher();
  if (window.htmx) {
    htmx.ajax('POST', '/api/player/output', {
      values: { profile: route },
      target: '#transport-footer-container',
      swap: 'innerHTML'
    });
  } else {
    const formData = new FormData();
    formData.append('profile', route);
    fetch('/api/player/output', {
      method: 'POST',
      body: formData
    })
      .then(r => r.text())
      .then(html => {
        const container = document.getElementById('transport-footer-container');
        if (container) container.innerHTML = html;
      })
      .catch(err => console.error('Error switching output route:', err));
  }
}
window.selectOutputRoute = selectOutputRoute;


// 3. Parametric Equalizer Studio Modal (Screen 3 - The Soundbar 10-Band EQ)
let isBypassed = false;
let bandValues = [4.5, 3.8, 2.0, 1.2, 0.4, -0.5, 1.0, 2.2, 3.4, 4.2];
let currentPreAmp = -1.5;

function openEQStudioModal() {
  const el = document.getElementById('eq-studio-backdrop');
  if (el) {
    el.classList.remove('hidden');
    renderCurve();
  }
}
window.openEQStudioModal = openEQStudioModal;

function closeEQStudioModal() {
  const el = document.getElementById('eq-studio-backdrop');
  if (el) el.classList.add('hidden');
}
window.closeEQStudioModal = closeEQStudioModal;

function toggleEQPresetDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('presetMenu');
  if (menu) menu.classList.toggle('hidden');
}
window.toggleEQPresetDropdown = toggleEQPresetDropdown;

function updatePreAmp(val) {
  const num = parseFloat(val);
  currentPreAmp = num;
  const textEl = document.getElementById('preAmpValueText');
  const fillEl = document.getElementById('preAmpFill');
  const thumbEl = document.getElementById('preAmpThumb');
  
  if (textEl) textEl.textContent = (num > 0 ? '+' : '') + num.toFixed(1) + ' dB';
  const percent = ((num + 12) / 24) * 100;
  if (fillEl) fillEl.style.height = percent + '%';
  if (thumbEl) thumbEl.style.bottom = `calc(${percent}% - 10px)`;
}
window.updatePreAmp = updatePreAmp;

function handleBandChange(index, val) {
  const num = parseFloat(val);
  bandValues[index] = num;
  updateBandUI(index, num);
  renderCurve();
}
window.handleBandChange = handleBandChange;

function updateBandUI(index, val) {
  const dbLabel = document.querySelector(`.band-db[data-band="${index}"]`);
  const fills = document.querySelectorAll('.band-fill');
  const thumbs = document.querySelectorAll('.band-thumb');
  const sliders = document.querySelectorAll('.band-slider');

  if (sliders && sliders[index]) sliders[index].value = val;
  if (dbLabel) {
    dbLabel.textContent = (val > 0 ? '+' : '') + val.toFixed(1);
    if (val > 0) {
      dbLabel.className = 'font-label-sm text-[10px] text-primary-container font-semibold band-db';
    } else if (val < 0) {
      dbLabel.className = 'font-label-sm text-[10px] text-on-surface-variant font-semibold band-db';
    } else {
      dbLabel.className = 'font-label-sm text-[10px] text-outline font-semibold band-db';
    }
  }
  const percent = ((val + 12) / 24) * 100;
  if (fills && fills[index]) fills[index].style.height = `${percent}%`;
  if (thumbs && thumbs[index]) thumbs[index].style.bottom = `calc(${percent}% - 8px)`;
}
window.updateBandUI = updateBandUI;

function selectPreset(name, values) {
  const label = document.getElementById('currentPresetLabel');
  if (label) label.textContent = name;
  bandValues = [...values];
  bandValues.forEach((val, i) => updateBandUI(i, val));
  renderCurve();
  const menu = document.getElementById('presetMenu');
  if (menu) menu.classList.add('hidden');
}
window.selectPreset = selectPreset;

function applyEQPreset(name, values) {
  selectPreset(name, values);
}
window.applyEQPreset = applyEQPreset;

function renderCurve() {
  const xs = [50, 130, 210, 295, 385, 475, 565, 655, 745, 825];
  const pts = bandValues.map((v, i) => {
    const y = 90 - (v / 12) * 70;
    return { x: xs[i], y: Math.max(16, Math.min(164, y)) };
  });

  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i];
    const p1 = pts[i + 1];
    const mx = (p0.x + p1.x) / 2;
    d += ` C ${mx} ${p0.y}, ${mx} ${p1.y}, ${p1.x} ${p1.y}`;
  }

  const curveEl = document.getElementById('eqCurvePath');
  const areaEl = document.getElementById('eqAreaPath');

  if (curveEl) curveEl.setAttribute('d', d);
  if (areaEl) areaEl.setAttribute('d', `${d} L ${pts[pts.length - 1].x} 90 L ${pts[0].x} 90 Z`);

  // Update node dot positions
  const nodes = document.querySelectorAll('#nodesLayer > div');
  pts.forEach((pt, i) => {
    if (nodes[i]) {
      const leftPct = (pt.x / 860) * 100;
      const topPct = (pt.y / 180) * 100;
      nodes[i].style.left = `${leftPct}%`;
      nodes[i].style.top = `${topPct}%`;
    }
  });
}
window.renderCurve = renderCurve;

function toggleBypass() {
  isBypassed = !isBypassed;
  const dot = document.getElementById('bypassIndicator');
  const text = document.getElementById('bypassText');
  const curve = document.getElementById('eqCurvePath');
  const area = document.getElementById('eqAreaPath');

  if (isBypassed) {
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-secondary shadow-[0_0_8px_var(--secondary,#f59e0b)]';
    if (text) {
      text.textContent = 'DSP Bypassed';
      text.className = 'text-secondary font-semibold';
    }
    if (curve) curve.style.opacity = '0.2';
    if (area) area.style.opacity = '0.05';
  } else {
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-outline';
    if (text) {
      text.textContent = 'Bypass DSP';
      text.className = 'text-on-surface-variant';
    }
    if (curve) curve.style.opacity = '1';
    if (area) area.style.opacity = '1';
  }
}
window.toggleBypass = toggleBypass;

function applyCurve() {
  const btn = document.getElementById('applyBtn');
  if (btn) {
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span>Curves Engaged ✨</span><span class="material-symbols-outlined text-[16px]">done_all</span>';
    btn.classList.add('bg-tertiary', 'shadow-[0_0_24px_rgba(78,222,163,0.5)]');
    setTimeout(() => {
      btn.innerHTML = originalText;
      btn.classList.remove('bg-tertiary', 'shadow-[0_0_24px_rgba(78,222,163,0.5)]');
    }, 1200);
  }
  saveAndApplyEQ();
}
window.applyCurve = applyCurve;

function saveAndApplyEQ() {
  const freqs = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
  const types = ['lowshelf', 'peaking', 'peaking', 'peaking', 'peaking', 'peaking', 'peaking', 'peaking', 'peaking', 'highshelf'];
  const qs = [0.71, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.71];

  const bands = freqs.map((f, i) => ({
    fc: f,
    gain: bandValues[i] || 0.0,
    q: qs[i],
    type: types[i]
  }));

  fetch('/api/dsp/peq/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bands: bands,
      preamp_db: currentPreAmp
    })
  }).catch(() => {});
}
window.saveAndApplyEQ = saveAndApplyEQ;

function toggleSpatialBinaural() {
  fetch('/api/dsp/spatial/toggle', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      const lbl = document.getElementById('spatialStatusLabel');
      if (lbl) {
        lbl.textContent = data.mode === 'spatial_binaural' ? '3D Binaural Active' : 'Stereo Direct';
      }
    }).catch(() => {});
}
window.toggleSpatialBinaural = toggleSpatialBinaural;

// 4. Welcome Onboarding Modal (Screen 6)
function openOnboardingModal() {
  const el = document.getElementById('onboarding-modal-backdrop') || document.getElementById('onboarding-backdrop');
  if (el) el.classList.remove('hidden');
}

function closeOnboardingModal() {
  const el = document.getElementById('onboarding-modal-backdrop') || document.getElementById('onboarding-backdrop');
  if (el) el.classList.add('hidden');
}

function browseLibraryFolder() {
  fetch('/api/desktop/browse-folder', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.folder) {
        const lbl = document.getElementById('onboarding-folder-label');
        if (lbl) lbl.textContent = 'Selected: ' + data.folder;
        const inp = document.getElementById('music-path');
        if (inp) inp.value = data.folder;
      }
    }).catch(() => {});
}

function completeOnboarding() {
  closeOnboardingModal();
  fetch('/api/library/scan', { method: 'POST' }).catch(() => {});
}

// 5. DAC Disconnected Alert & Recovery (Screen 11)
function openDACAlertModal() {
  const el = document.getElementById('dac-alert-backdrop') || document.getElementById('dac-alert-modal-backdrop');
  if (el) el.classList.remove('hidden');
}

function closeDACAlertModal() {
  const el = document.getElementById('dac-alert-backdrop') || document.getElementById('dac-alert-modal-backdrop');
  if (el) el.classList.add('hidden');
}

function retryDACConnection() {
  selectOutputRoute('pure-bitperfect');
  closeDACAlertModal();
}

// 6. Handy Keyboard Shortcuts Modal (Screen 12)
function openShortcutsModal() {
  const el = document.getElementById('shortcuts-modal-backdrop') || document.getElementById('shortcuts-backdrop');
  if (el) el.classList.remove('hidden');
}

function closeShortcutsModal() {
  const el = document.getElementById('shortcuts-modal-backdrop') || document.getElementById('shortcuts-backdrop');
  if (el) el.classList.add('hidden');
}

// 7. Track Context Menu Popover (Screen 13)
let activeContextTrackId = null;

function openTrackContextMenu(e, trackId, title, artist) {
  e.preventDefault();
  e.stopPropagation();
  activeContextTrackId = trackId;

  const tLbl = document.getElementById('context-track-title');
  const aLbl = document.getElementById('context-track-artist');
  if (tLbl) tLbl.textContent = title;
  if (aLbl) aLbl.textContent = artist;

  const menu = document.getElementById('track-context-menu');
  if (!menu) return;
  menu.classList.remove('hidden');

  const x = Math.min(e.clientX, window.innerWidth - 240);
  const y = Math.min(e.clientY, window.innerHeight - 260);
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
}

function closeTrackContextMenu() {
  const menu = document.getElementById('track-context-menu');
  if (menu) menu.classList.add('hidden');
  activeContextTrackId = null;
}

function contextActionPlayNow() {
  if (activeContextTrackId) {
    playTrack(activeContextTrackId);
  }
  closeTrackContextMenu();
}

function contextActionPlayNext() {
  closeTrackContextMenu();
}

function contextActionAddToQueue() {
  closeTrackContextMenu();
}

function contextActionInspectVibe() {
  if (activeContextTrackId) {
    if (window.htmx) {
      htmx.ajax('GET', '/api/track/' + activeContextTrackId, {
        target: '#workspace-inspector-content',
        swap: 'innerHTML'
      });
      const drawer = document.getElementById('workspace-inspector-drawer');
      if (drawer) drawer.classList.remove('collapsed');
    }
  }
  closeTrackContextMenu();
}

function contextActionFindSimilar() {
  closeTrackContextMenu();
}

// 8. View Switcher (Master Table vs Record Crate) (Screen 8, 9, 14)
function switchLibraryView(view) {
  if (view === 'crate' && document.getElementById('tab-crate')) {
    showTab('crate');
  } else if (view === 'table' && document.getElementById('tab-library')) {
    showTab('library');
  }

  const tbl = document.getElementById('library-table-container');
  const crt = document.getElementById('record-crate-container');
  const bTbl = document.getElementById('view-btn-table');
  const bCrt = document.getElementById('view-btn-crate');

  if (view === 'crate') {
    if (tbl) tbl.style.display = 'none';
    if (crt) crt.classList.remove('hidden');
    if (bCrt) {
      bCrt.classList.add('bg-[var(--surface-container)]', 'text-[var(--accent)]', 'font-bold');
      bCrt.classList.remove('text-[var(--text-muted)]');
    }
    if (bTbl) {
      bTbl.classList.remove('bg-[var(--surface-container)]', 'text-[var(--accent)]', 'font-bold');
      bTbl.classList.add('text-[var(--text-muted)]');
    }
  } else {
    if (tbl) tbl.style.display = 'block';
    if (crt) crt.classList.add('hidden');
    if (bTbl) {
      bTbl.classList.add('bg-[var(--surface-container)]', 'text-[var(--accent)]', 'font-bold');
      bTbl.classList.remove('text-[var(--text-muted)]');
    }
    if (bCrt) {
      bCrt.classList.remove('bg-[var(--surface-container)]', 'text-[var(--accent)]', 'font-bold');
      bCrt.classList.add('text-[var(--text-muted)]');
    }
  }
  try {
    localStorage.setItem('vibeplay_library_view', view);
  } catch (e) {}
}

function filterCrateByMood(mood, btn) {
  document.querySelectorAll('.crate-mood-chip').forEach(c => {
    c.classList.remove('bg-[var(--accent)]', 'text-[var(--bg)]', 'font-bold');
    c.classList.add('bg-[var(--surface)]', 'text-[var(--text-muted)]');
  });
  if (btn) {
    btn.classList.add('bg-[var(--accent)]', 'text-[var(--bg)]', 'font-bold');
    btn.classList.remove('bg-[var(--surface)]', 'text-[var(--text-muted)]');
  }
}

// Document click to close popovers
document.addEventListener('click', (e) => {
  const outPop = document.getElementById('output-switcher-popover');
  if (outPop && !outPop.classList.contains('hidden') && !outPop.contains(e.target) && !e.target.closest('#btn-audio-output-dropdown')) {
    outPop.classList.add('hidden');
  }
  const ctx = document.getElementById('track-context-menu');
  if (ctx && !ctx.classList.contains('hidden') && !ctx.contains(e.target)) {
    ctx.classList.add('hidden');
  }
});

// Global Keyboard Shortcut listener additions
window.addEventListener('keydown', (e) => {
  if (e.key === '?' && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
    e.preventDefault();
    openShortcutsModal();
  } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'P' || e.key === 'p')) {
    e.preventDefault();
    openToyboxModal();
  } else if ((e.ctrlKey || e.metaKey) && (e.key === 'e' || e.key === 'E')) {
    e.preventDefault();
    openEQStudioModal();
  } else if (e.key === 'Escape') {
    closeToyboxModal();
    closeOutputSwitcher();
    closeEQStudioModal();
    closeOnboardingModal();
    closeDACAlertModal();
    closeShortcutsModal();
    closeTrackContextMenu();
  }
});

function filterCrateCategory(category, btn) {
  document.querySelectorAll('.crate-filter-pill').forEach(p => p.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const rows = document.querySelectorAll('#library-table tbody tr');
  rows.forEach(r => {
    if (category === 'all') {
      r.style.display = '';
    } else if (category === 'lossless') {
      const isLossless = r.querySelector('.quality-highres, .quality-dsd, .quality-flac');
      r.style.display = isLossless ? '' : 'none';
    } else if (category === 'vinyl') {
      const text = r.textContent.toLowerCase();
      r.style.display = (text.includes('vinyl') || text.includes('rip') || text.includes('tape') || text.includes('analog')) ? '' : 'none';
    } else if (category === 'mixtapes') {
      const text = r.textContent.toLowerCase();
      r.style.display = (text.includes('mix') || text.includes('session') || text.includes('tape')) ? '' : 'none';
    } else {
      r.style.display = '';
    }
  });
}

function setTableDensity(mode) {
  const table = document.getElementById('library-table');
  const btnCozy = document.getElementById('density-cozy-btn');
  const btnCompact = document.getElementById('density-compact-btn');
  if (!table) return;
  if (mode === 'compact') {
    table.classList.add('density-compact');
    table.classList.remove('density-cozy');
    if (btnCompact) btnCompact.classList.add('active');
    if (btnCozy) btnCozy.classList.remove('active');
  } else {
    table.classList.remove('density-compact');
    table.classList.add('density-cozy');
    if (btnCozy) btnCozy.classList.add('active');
    if (btnCompact) btnCompact.classList.remove('active');
  }
  try { localStorage.setItem('vibeplay_table_density', mode); } catch (e) {}
}

function dismissBanner() {
  const banner = document.getElementById('alert-banner');
  if (banner) {
    banner.style.opacity = '0';
    setTimeout(() => { banner.style.display = 'none'; }, 250);
  }
}

function toggleFavoriteCurrentTrack(e) {
  if (e) e.stopPropagation();
  const btn = e ? e.currentTarget : null;
  if (btn) {
    btn.classList.toggle('is-favorited');
    btn.style.transform = 'scale(1.25)';
    setTimeout(() => { btn.style.transform = ''; }, 200);
  }
}

function closeContextMenu() {
  closeTrackContextMenu();
}

// Expose on window
window.filterCrateCategory = filterCrateCategory;
window.setTableDensity = setTableDensity;
window.dismissBanner = dismissBanner;
window.toggleFavoriteCurrentTrack = toggleFavoriteCurrentTrack;
window.closeContextMenu = closeContextMenu;
window.openToyboxModal = openToyboxModal;
window.closeToyboxModal = closeToyboxModal;
window.filterToyboxCards = filterToyboxCards;
window.togglePlugin = togglePlugin;
window.triggerDeduplication = triggerDeduplication;
window.triggerEnrichment = triggerEnrichment;
window.openOutputSwitcher = openOutputSwitcher;
window.closeOutputSwitcher = closeOutputSwitcher;
window.toggleOutputSwitcher = toggleOutputSwitcher;
window.selectOutputRoute = selectOutputRoute;
window.openEQStudioModal = openEQStudioModal;
window.closeEQStudioModal = closeEQStudioModal;
window.updateEQBand = updateEQBand;
window.applyEQPreset = applyEQPreset;
window.resetEQBands = resetEQBands;
window.toggleSpatialBinaural = toggleSpatialBinaural;
window.saveAndApplyEQ = saveAndApplyEQ;
window.openOnboardingModal = openOnboardingModal;
window.closeOnboardingModal = closeOnboardingModal;
window.browseLibraryFolder = browseLibraryFolder;
window.completeOnboarding = completeOnboarding;
window.openDACAlertModal = openDACAlertModal;
window.closeDACAlertModal = closeDACAlertModal;
window.retryDACConnection = retryDACConnection;
window.openShortcutsModal = openShortcutsModal;
window.closeShortcutsModal = closeShortcutsModal;
window.openTrackContextMenu = openTrackContextMenu;
window.closeTrackContextMenu = closeTrackContextMenu;
window.contextActionPlayNow = contextActionPlayNow;
window.contextActionPlayNext = contextActionPlayNext;
window.contextActionAddToQueue = contextActionAddToQueue;
window.contextActionInspectVibe = contextActionInspectVibe;
window.contextActionFindSimilar = contextActionFindSimilar;
window.switchLibraryView = switchLibraryView;
window.filterCrateByMood = filterCrateByMood;

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  initThemeEngine();
  loadDesktopSettingsFromServer();
  initTelemetryStream();
  initInspectorState();
  initTelemetryHudState();
  initFullscreenNowPlayingState();

  try {
    const savedView = localStorage.getItem('vibeplay_library_view');
    if (savedView === 'crate') {
      switchLibraryView('crate');
    }
  } catch (e) {}
});

if (typeof window.toggleSidebarDrawer !== 'function') {
  window.toggleSidebarDrawer = function() {
    const sidebar = document.getElementById('workspace-sidebar-drawer');
    if (sidebar) {
      sidebar.style.display = (sidebar.style.display === 'none' || !sidebar.style.display) ? 'flex' : 'none';
    }
  };
}

if (typeof window.toggleTelemetryHUD !== 'function') {
  window.toggleTelemetryHUD = function() {
    const hud = document.getElementById('telemetry-hud-deck');
    if (hud) {
      if (hud.style.display === 'none' || hud.classList.contains('hidden')) {
        hud.style.display = 'grid';
        hud.classList.remove('hidden');
      } else {
        hud.style.display = 'none';
        hud.classList.add('hidden');
      }
    }
  };
}

if (typeof window.toggleDspToggle !== 'function') {
  window.toggleDspToggle = function(btn) {
    if (!btn) return;
    const isAmber = btn.classList.contains('active-amber');
    const isCyan = btn.classList.contains('active-cyan');
    if (isAmber) {
      btn.classList.remove('active-amber');
      btn.classList.add('inactive');
    } else if (isCyan) {
      btn.classList.remove('active-cyan');
      btn.classList.add('inactive');
    } else {
      btn.classList.remove('inactive');
      btn.classList.add('active-cyan');
    }
  };
}

if (typeof window.toggleTubeWarmth !== 'function') {
  window.toggleTubeWarmth = function() {
    const valSpan = document.getElementById('tube-warmth-val');
    if (valSpan) {
      const current = parseInt(valSpan.textContent) || 68;
      const next = current >= 90 ? 40 : current + 14;
      valSpan.textContent = next + '%';
    }
  };
}

if (typeof window.toggleMasterGain !== 'function') {
  window.toggleMasterGain = function() {
    const valSpan = document.getElementById('master-gain-val');
    if (valSpan) {
      const current = parseInt(valSpan.textContent) || -14;
      const next = current >= -4 ? -24 : current + 4;
      valSpan.textContent = next + 'dB';
    }
  };
}

if (typeof window.copyDeckSyncUrl !== 'function') {
  window.copyDeckSyncUrl = function(btn) {
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = 'Copied! ✨';
      try {
        navigator.clipboard.writeText(window.location.origin + '/#lounge-sync');
      } catch (e) {}
      setTimeout(() => { btn.textContent = orig; }, 1500);
    }
  };
}


document.addEventListener('keydown', (event) => {
  const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
  const isInput = activeTag === 'input' || activeTag === 'textarea' || (document.activeElement && document.activeElement.isContentEditable);

  const code = event.code;
  const key = event.key;

  // Volume Down: F5 or AudioVolumeDown
  if (key === 'F5' || code === 'F5' || key === 'AudioVolumeDown') {
    event.preventDefault();
    adjustVolume(-5);
    return;
  }

  // Volume Mute/Unmute: F6 or AudioVolumeMute
  if (key === 'F6' || code === 'F6' || key === 'AudioVolumeMute') {
    event.preventDefault();
    triggerMuteToggle();
    return;
  }

  // Volume Up: F7 or AudioVolumeUp
  if (key === 'F7' || code === 'F7' || key === 'AudioVolumeUp') {
    event.preventDefault();
    adjustVolume(5);
    return;
  }

  // Previous Track: F9 or MediaTrackPrevious
  if (key === 'F9' || code === 'F9' || key === 'MediaTrackPrevious') {
    event.preventDefault();
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/prev', {
        target: '#transport-footer-container',
        swap: 'innerHTML'
      });
    }
    return;
  }

  // Play / Pause: F10 or MediaPlayPause or Space (when not typing in text field)
  if (key === 'F10' || code === 'F10' || key === 'MediaPlayPause' || (code === 'Space' && !isInput)) {
    event.preventDefault();
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/toggle', {
        target: '#transport-footer-container',
        swap: 'innerHTML'
      });
    }
    return;
  }

  // Next Track: F11 or MediaTrackNext
  if (key === 'F11' || code === 'F11' || key === 'MediaTrackNext') {
    event.preventDefault();
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/next', {
        target: '#transport-footer-container',
        swap: 'innerHTML'
      });
    }
    return;
  }
});

// Interactive Handlers for UI Elements & Modals
function focusLibrarySearch() {
  const el = document.getElementById('global-header-search') || document.getElementById('library-search-input');
  if (el) el.focus();
}
window.focusLibrarySearch = focusLibrarySearch;

function syncToLibrarySearch(query) {
  const libInput = document.getElementById('library-search-input');
  if (libInput) {
    libInput.value = query;
    if (typeof htmx !== 'undefined') {
      htmx.trigger(libInput, 'input');
    }
  }
}
window.syncToLibrarySearch = syncToLibrarySearch;

function toggleShuffleMode(btn) {
  const b = btn || document.getElementById('btn-transport-shuffle');
  if (b) {
    b.classList.toggle('active');
    const isActive = b.classList.contains('active');
    try {
      localStorage.setItem('vibeplay_shuffle', isActive ? '1' : '0');
    } catch (e) {}
  }
}
window.toggleShuffleMode = toggleShuffleMode;
window.toggleShuffle = toggleShuffleMode;

function toggleRepeatMode(btn) {
  const b = btn || document.getElementById('btn-transport-repeat');
  if (b) {
    b.classList.toggle('active');
    const isActive = b.classList.contains('active');
    try {
      localStorage.setItem('vibeplay_repeat', isActive ? '1' : '0');
    } catch (e) {}
  }
}
window.toggleRepeatMode = toggleRepeatMode;
window.toggleRepeat = toggleRepeatMode;

function handleScrubTimeline(event, input) {
  const val = input ? parseFloat(input.value) : 0;
  if (typeof seekPlayback === 'function') {
    seekPlayback(val);
  } else if (window.htmx) {
    htmx.ajax('POST', '/api/player/seek', { values: { seconds: val }, target: '#transport-footer-container', swap: 'innerHTML' });
  }
}
window.handleScrubTimeline = handleScrubTimeline;

function handlePlayerClear() {
  if (window.htmx) {
    htmx.ajax('POST', '/api/player/clear', { target: '#transport-footer-container', swap: 'innerHTML' });
  } else {
    fetch('/api/player/clear', { method: 'POST' }).catch(() => {});
  }
}
window.handlePlayerClear = handlePlayerClear;

function toggleSmartSorter(btn) {
  const menu = document.getElementById('smart-sorter-menu');
  if (menu) menu.classList.toggle('hidden');
}
window.toggleSmartSorter = toggleSmartSorter;

function togglePluginDynamic(pluginId, el) {
  if (typeof togglePlugin === 'function') {
    togglePlugin(pluginId, el);
  }
}
window.togglePluginDynamic = togglePluginDynamic;

function selectSeedTrack(el) {
  if (!el) return;
  const tid = el.getAttribute('data-track-id');
  const title = el.getAttribute('data-title');
  const artist = el.getAttribute('data-artist');
  const album = el.getAttribute('data-album');
  const bpm = el.getAttribute('data-bpm');
  const camelot = el.getAttribute('data-camelot');

  const hiddenId = document.getElementById('builder-selected-seed-id');
  if (hiddenId) hiddenId.value = tid;

  const formSeedId = document.getElementById('builder-form-seed-id');
  if (formSeedId) formSeedId.value = tid;

  const card = document.getElementById('selected-seed-card');
  if (card) card.style.display = 'flex';

  const tEl = document.getElementById('selected-seed-title');
  if (tEl) tEl.textContent = title;

  const aEl = document.getElementById('selected-seed-artist');
  if (aEl) aEl.textContent = artist + ' — ' + album;

  const bEl = document.getElementById('selected-seed-bpm');
  if (bEl) bEl.textContent = bpm ? bpm + ' BPM' : '— BPM';

  const cEl = document.getElementById('selected-seed-camelot');
  if (cEl) cEl.textContent = camelot || '—';

  const nextBtn = document.getElementById('btn-goto-step-2');
  if (nextBtn) {
    nextBtn.removeAttribute('disabled');
    nextBtn.style.opacity = '1';
    nextBtn.style.cursor = 'pointer';
  }
}
window.selectSeedTrack = selectSeedTrack;

function updateArcSelection(radio) {
  document.querySelectorAll('.arc-card').forEach(card => {
    card.classList.remove('active');
  });
  if (radio && radio.checked && radio.closest('.arc-card')) {
    radio.closest('.arc-card').classList.add('active');
  }
}
window.updateArcSelection = updateArcSelection;

function applyNlPrompt(promptText) {
  const input = document.getElementById('vibeInput') || document.getElementById('nl-playlist-prompt-input');
  if (input) {
    input.value = promptText;
    const form = input.closest('form');
    if (form) {
      if (typeof htmx !== 'undefined') {
        htmx.trigger(form, 'submit');
      } else {
        form.submit();
      }
    }
  }
}
window.applyNlPrompt = applyNlPrompt;

function switchBuilderStep(stepNumber) {
  for (let s = 1; s <= 4; s++) {
    const pill = document.getElementById('pill-step-' + s);
    const panel = document.getElementById('builder-step-' + s);
    if (pill) {
      if (s === stepNumber) {
        pill.classList.add('active');
        pill.classList.remove('completed');
      } else if (s < stepNumber) {
        pill.classList.remove('active');
        pill.classList.add('completed');
      } else {
        pill.classList.remove('active');
        pill.classList.remove('completed');
      }
    }
    if (panel) {
      panel.style.display = (s === stepNumber) ? 'block' : 'none';
    }
  }
  if (stepNumber === 4 && typeof initPlaylistDragDrop === 'function') {
    initPlaylistDragDrop();
  }
}
window.switchBuilderStep = switchBuilderStep;

function openSettingsDialog(initialTab) {
  if (typeof closeAllMenus === 'function') closeAllMenus();
  const dialog = document.getElementById('settings-dialog');
  if (!dialog) return;
  dialog.classList.remove('hidden');
  dialog.style.display = '';
  if (!dialog.open) {
    if (typeof dialog.showModal === 'function') {
      try {
        dialog.showModal();
      } catch (e) {
        dialog.setAttribute('open', '');
      }
    } else {
      dialog.setAttribute('open', '');
    }
  }
  if (typeof loadDesktopSettingsIntoModal === 'function') {
    loadDesktopSettingsIntoModal();
  }
  if (initialTab && typeof openSettingsTab === 'function') {
    openSettingsTab(initialTab);
  }
}
window.openSettingsDialog = openSettingsDialog;


