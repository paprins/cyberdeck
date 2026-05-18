// Cyberdeck toast notification engine.
//
// Listens for `notifications-update` (dispatched by the body's poll() with
// the latest /api/system snapshot) and `download-terminal` (dispatched by
// per-row poll loops when a download reaches a terminal state). Compares
// against the previous snapshot and emits `toast` window events for the
// `_toasts.html` container to render.
//
// Severity vocabulary (tactical ops palette, see .impeccable.md):
//   info     - tertiary-container  (vivid blue)   6s
//   success  - tertiary            (sky blue)     6s
//   warning  - primary-container   (signal orange + pulse) 12s
//   error    - error               (red)          persistent

(function () {
  let prev = null;
  const seenKeys = new Set();

  function emit(toast) {
    if (toast.key) {
      if (seenKeys.has(toast.key)) return;
      seenKeys.add(toast.key);
    }
    window.dispatchEvent(new CustomEvent('toast', { detail: toast }));
  }

  // Drain any toasts queued in sessionStorage by a page that just reloaded
  // (the download row pushes here before calling location.reload()).
  function drainSessionQueue() {
    try {
      const raw = sessionStorage.getItem('toast_queue');
      if (!raw) return;
      sessionStorage.removeItem('toast_queue');
      const items = JSON.parse(raw);
      for (const t of items) emit(t);
    } catch (e) {
      sessionStorage.removeItem('toast_queue');
    }
  }

  function deriveToasts(prev, curr) {
    const out = [];
    // First poll has no baseline — every non-zero value would look like a
    // transition from zero. Wait for the second poll before emitting anything,
    // so persistent state (pending updates, last-session upgrade failure,
    // services already down) doesn't fire on every page load.
    if (!curr || !prev) return out;

    // ── Package updates: 0 → N transition (gated server-side) ──
    if (curr.check_for_updates && curr.wifi_connected) {
      const prevCount = prev ? (prev.package_updates || []).length : 0;
      const currCount = (curr.package_updates || []).length;
      if (currCount > prevCount) {
        out.push({
          key: 'pkg_update::' + currCount,
          severity: 'info',
          title: 'UPDATES_AVAILABLE',
          message: currCount + (currCount === 1 ? '_PACKAGE_HAS_NEW_VERSION' : '_PACKAGES_HAVE_NEW_VERSIONS'),
          href: '/settings/packages',
        });
      }
    }

    // ── Firmware update available ──
    if (curr.check_for_updates && curr.wifi_connected && curr.firmware_update_available) {
      const v = curr.firmware_update_available;
      const prevV = prev ? prev.firmware_update_available : null;
      if (v !== prevV) {
        out.push({
          key: 'fw_update::' + v,
          severity: 'info',
          title: 'FIRMWARE_UPDATE_AVAILABLE',
          message: 'V' + v.toUpperCase().replace(/\./g, '_'),
          href: '/settings',
        });
      }
    }

    // ── Linked service down: ok → down transition ──
    const prevSvcs = {};
    if (prev) for (const s of (prev.services || [])) prevSvcs[s.name] = s.state;
    for (const s of (curr.services || [])) {
      const was = prevSvcs[s.name];
      if (was === 'ok' && s.state === 'down') {
        out.push({
          key: 'svc_down::' + s.name + '::' + Date.now(),
          severity: 'warning',
          title: 'SERVICE_DOWN',
          message: s.name.toUpperCase() + '_NOT_REACHABLE',
          href: '/settings/status',
        });
      }
    }

    // ── Download outcomes ──
    // Snapshot lists in-flight states only (downloading, queued, checksum_mismatch).
    // A disappearance from the map is ambiguous: could be success, cancel, or
    // network failure. We only fire toasts for transitions whose meaning is
    // unambiguous in the snapshot itself — checksum mismatch entering the map.
    // Success/failure for the active operator is covered by the per-row
    // sessionStorage bridge in settings.html; cross-page success-toast is a v1 gap.
    const currDl = curr.downloads || {};
    const prevDl = prev ? (prev.downloads || {}) : {};
    for (const id of Object.keys(currDl)) {
      const before = prevDl[id];
      const after = currDl[id];
      if (after.status === 'checksum_mismatch' && (!before || before.status !== 'checksum_mismatch')) {
        const name = (after.display_name || id).toUpperCase().replace(/ /g, '_');
        out.push({
          key: 'dl_checksum::' + id,
          severity: 'error',
          title: 'CHECKSUM_MISMATCH',
          message: name,
          href: '/settings/packages',
        });
      }
    }

    // ── Connectivity check auto-disabled (warning, fires once per disable event) ──
    const prevAutoDisabled = prev.connectivity_check_auto_disabled_at;
    const currAutoDisabled = curr.connectivity_check_auto_disabled_at;
    if (currAutoDisabled != null && currAutoDisabled !== prevAutoDisabled) {
      const mins = curr.connectivity_grace_minutes || 10;
      out.push({
        key: 'conn_check_disabled::' + currAutoDisabled,
        severity: 'warning',
        title: 'CONNECTIVITY_CHECK_DISABLED',
        message: 'NO_INTERNET_FOR_' + mins + '_MINUTES',
        href: '/settings',
      });
    }

    // ── Firmware upgrade outcome: phase → success/failed/rolled_back ──
    const prevPhase = prev ? prev.upgrade_phase : null;
    const phase = curr.upgrade_phase;
    if (phase && phase !== prevPhase) {
      if (phase === 'success') {
        out.push({
          key: 'fw_outcome::success::' + (curr.upgrade_target_version || ''),
          severity: 'success',
          title: 'FIRMWARE_UPGRADE_COMPLETE',
          message: curr.upgrade_target_version ? 'V' + curr.upgrade_target_version.replace(/\./g, '_') : 'RESTART_REQUIRED',
          href: '/settings',
        });
      } else if (phase === 'failed') {
        out.push({
          key: 'fw_outcome::failed::' + (curr.upgrade_target_version || ''),
          severity: 'error',
          title: 'FIRMWARE_UPGRADE_FAILED',
          message: curr.upgrade_target_version ? 'V' + curr.upgrade_target_version.replace(/\./g, '_') : 'CHECK_LOGS',
          href: '/settings',
        });
      } else if (phase === 'rolled_back') {
        out.push({
          key: 'fw_outcome::rolled_back::' + (curr.upgrade_target_version || ''),
          severity: 'warning',
          title: 'FIRMWARE_ROLLED_BACK',
          message: 'PREVIOUS_VERSION_RESTORED',
          href: '/settings',
        });
      }
    }

    return out;
  }

  window.addEventListener('notifications-update', (e) => {
    const curr = e.detail;
    for (const t of deriveToasts(prev, curr)) emit(t);
    prev = curr;
  });

  window.addEventListener('DOMContentLoaded', drainSessionQueue);

  // Expose for the toast container's manual push (used by sessionStorage bridge
  // helpers in inline templates).
  window.cyberdeckToast = emit;
})();
