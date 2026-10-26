/* vibeplay — Audiophile Precision Console Client-side Interactions */

// Tab Navigation
function showTab(tabId) {
  const tabs = ['library', 'clusters', 'builder'];
  tabs.forEach(t => {
    const section = document.getElementById(`tab-${t}`);
    const btn = document.getElementById(`nav-btn-${t}`);
    if (section) {
      if (t === tabId) {
        section.style.display = 'block';
      } else {
        section.style.display = 'none';
      }
    }
    if (btn) {
      if (t === tabId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    }
  });
}

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
  const container = document.getElementById('playlist-tracks-list');
  if (!container) return;

  const items = container.querySelectorAll('.playlist-track-row');
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

// Function Key (F5-F7 volume, F9-F11 play/skip) & Hardware Media Key Keyboard Bindings
document.addEventListener('keydown', (event) => {
  const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
  const isInput = activeTag === 'input' || activeTag === 'textarea' || (document.activeElement && document.activeElement.isContentEditable);

  const code = event.code;
  const key = event.key;

  // Volume Down: F5 or AudioVolumeDown
  if (key === 'F5' || code === 'F5' || key === 'AudioVolumeDown') {
    event.preventDefault();
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/volume-step', {
        target: '#transport-footer-container',
        swap: 'innerHTML',
        values: { delta: -5 }
      });
    }
    return;
  }

  // Volume Mute/Unmute: F6 or AudioVolumeMute
  if (key === 'F6' || code === 'F6' || key === 'AudioVolumeMute') {
    event.preventDefault();
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/mute-toggle', {
        target: '#transport-footer-container',
        swap: 'innerHTML'
      });
    }
    return;
  }

  // Volume Up: F7 or AudioVolumeUp
  if (key === 'F7' || code === 'F7' || key === 'AudioVolumeUp') {
    event.preventDefault();
    if (window.htmx) {
      htmx.ajax('POST', '/api/player/volume-step', {
        target: '#transport-footer-container',
        swap: 'innerHTML',
        values: { delta: 5 }
      });
    }
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

// Settings & Telemetry HUD Helpers (Web Shell Fallback)
if (typeof window.openSettingsTab !== 'function') {
  window.openSettingsTab = function(tabName) {
    if (typeof toggleSettingsDialog === 'function') {
      toggleSettingsDialog(tabName);
    }
  };
}

if (typeof window.handleVolumeInput !== 'function') {
  let appVolumeTimer = null;
  window.handleVolumeInput = function(slider) {
    const val = parseInt(slider.value, 10);
    const readout = document.getElementById('volume-readout');
    if (readout) readout.textContent = val + '%';
    if (appVolumeTimer) clearTimeout(appVolumeTimer);
    appVolumeTimer = setTimeout(() => {
      fetch('/api/player/volume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `volume=${val}`
      }).catch(() => {});
    }, 40);
  };
}

if (typeof window.toggleTelemetryHud !== 'function') {
  window.toggleTelemetryHud = function() {
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
  };
}
