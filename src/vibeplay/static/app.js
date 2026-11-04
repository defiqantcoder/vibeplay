/* vibeplay — Audiophile Precision Console Client-side Interactions */

// Tab Navigation
function showTab(tabId) {
  const tabs = ['library', 'builder'];
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

if (typeof window.selectTrackRow !== 'function') {
  window.selectTrackRow = function(rowEl, trackId) {
    document.querySelectorAll('.data-table tbody tr').forEach(r => r.classList.remove('selected-inspector-row'));
    if (rowEl) rowEl.classList.add('selected-inspector-row');
  };
}

if (typeof window.handleTrackRowPlay !== 'function') {
  window.handleTrackRowPlay = function(event, rowEl, trackId) {
    window.selectTrackRow(rowEl, trackId);
    const inspector = document.getElementById('workspace-inspector-content');
    if (inspector && typeof htmx !== 'undefined') {
      htmx.ajax('GET', '/api/track/' + trackId + '?view=inspector', { target: '#workspace-inspector-content', swap: 'innerHTML' });
    }
  };
}

if (typeof window.openFullscreenNowPlaying !== 'function') {
  window.openFullscreenNowPlaying = function() {
    const overlay = document.getElementById('fullscreen-now-playing');
    if (overlay) overlay.classList.remove('hidden');
  };
}

if (typeof window.closeFullscreenNowPlaying !== 'function') {
  window.closeFullscreenNowPlaying = function() {
    const overlay = document.getElementById('fullscreen-now-playing');
    if (overlay) overlay.classList.add('hidden');
  };
}

if (typeof window.toggleFullscreenNowPlaying !== 'function') {
  window.toggleFullscreenNowPlaying = function() {
    const overlay = document.getElementById('fullscreen-now-playing');
    if (overlay) overlay.classList.toggle('hidden');
  };
}

if (typeof window.filterCrateCategory !== 'function') {
  window.filterCrateCategory = function(category, btn) {
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
  };
}

if (typeof window.setTableDensity !== 'function') {
  window.setTableDensity = function(mode) {
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
  };
}

if (typeof window.dismissBanner !== 'function') {
  window.dismissBanner = function() {
    const banner = document.getElementById('alert-banner');
    if (banner) {
      banner.style.opacity = '0';
      setTimeout(() => { banner.style.display = 'none'; }, 250);
    }
  };
}

if (typeof window.toggleFavoriteCurrentTrack !== 'function') {
  window.toggleFavoriteCurrentTrack = function(e) {
    if (e) e.stopPropagation();
    const btn = e ? e.currentTarget : null;
    if (btn) {
      btn.classList.toggle('is-favorited');
      btn.style.transform = 'scale(1.25)';
      setTimeout(() => { btn.style.transform = ''; }, 200);
    }
  };
}

if (typeof window.closeContextMenu !== 'function') {
  window.closeContextMenu = function() {
    const menu = document.getElementById('track-context-menu');
    if (menu) menu.classList.add('hidden');
  };
}

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




