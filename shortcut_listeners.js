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
