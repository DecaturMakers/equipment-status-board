/* ESB custom JavaScript */

document.addEventListener('DOMContentLoaded', function () {
  // --- Clickable queue rows / cards (with keyboard support) ---
  // Action buttons + forms inside rows/cards must NOT trigger row-nav.
  // The closest('button, a[href], form, [data-no-nav]') guard catches
  // both interactive descendants and "dead zone" containers (button
  // padding, action-row gaps) tagged with [data-no-nav].
  function isNavBlocker(el) {
    return !!(el && el.closest('button, a[href], form, [data-no-nav]'));
  }

  document.querySelectorAll('.queue-row[data-href], .queue-card[data-href], .repair-history-row[data-href]').forEach(function (row) {
    row.style.cursor = 'pointer';
    row.addEventListener('click', function (e) {
      if (isNavBlocker(e.target)) return;
      // Respect ctrl/cmd/shift modifiers: open in new tab/window like a real link.
      if (e.ctrlKey || e.metaKey || e.shiftKey) {
        window.open(row.dataset.href, '_blank', 'noopener,noreferrer');
        return;
      }
      window.location.href = row.dataset.href;
    });
    // auxclick fires for middle-click (button === 1); open in new tab.
    row.addEventListener('auxclick', function (e) {
      if (e.button !== 1) return;
      if (isNavBlocker(e.target)) return;
      e.preventDefault();
      window.open(row.dataset.href, '_blank', 'noopener,noreferrer');
    });
    row.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (isNavBlocker(e.target)) return;
      e.preventDefault();
      window.location.href = row.dataset.href;
    });
  });

  // --- Kanban card keyboard navigation (Space key; Enter is native on <a>) ---
  document.querySelectorAll('a.kanban-card').forEach(function (card) {
    card.addEventListener('keydown', function (e) {
      if (e.key === ' ') {
        e.preventDefault();
        window.location.href = card.href;
      }
    });
  });

  // --- Queue table sorting ---
  var table = document.getElementById('queue-table');
  if (table) {
    var currentSort = { key: null, asc: true };

    table.querySelectorAll('th[data-sort]').forEach(function (th) {
      th.addEventListener('click', function () {
        var key = th.dataset.sort;
        if (currentSort.key === key) {
          currentSort.asc = !currentSort.asc;
        } else {
          currentSort.key = key;
          currentSort.asc = true;
        }
        sortTable(key, currentSort.asc);
        updateSortIndicators(th, currentSort.asc);
      });
    });

    function getRowSortValue(row, key) {
      switch (key) {
        case 'equipment-name': return row.dataset.equipmentName.toLowerCase();
        case 'severity': return parseInt(row.dataset.severityPriority, 10);
        case 'area': return row.dataset.area.toLowerCase();
        case 'age': return parseInt(row.dataset.ageSeconds, 10);
        case 'status': return row.dataset.status.toLowerCase();
        case 'assignee': return row.dataset.assignee.toLowerCase();
        default: return '';
      }
    }

    function sortTable(key, asc) {
      var tbody = table.querySelector('tbody');
      var rows = Array.from(tbody.querySelectorAll('tr.queue-row'));
      rows.sort(function (a, b) {
        var va = getRowSortValue(a, key);
        var vb = getRowSortValue(b, key);
        if (va < vb) return asc ? -1 : 1;
        if (va > vb) return asc ? 1 : -1;
        return 0;
      });
      rows.forEach(function (row) { tbody.appendChild(row); });
    }

    function updateSortIndicators(activeTh, asc) {
      table.querySelectorAll('.sort-indicator').forEach(function (el) {
        el.textContent = '';
      });
      activeTh.querySelector('.sort-indicator').textContent = asc ? ' \u25B2' : ' \u25BC';
    }
  }

  // --- Queue filtering ---
  var areaFilter = document.getElementById('area-filter');
  var statusFilter = document.getElementById('status-filter');
  var assigneeFilter = document.getElementById('assignee-filter');
  var queueContainer = document.getElementById('queue-table-wrapper');
  var currentUserId = queueContainer ? queueContainer.dataset.currentUserId : '';

  if (areaFilter || statusFilter || assigneeFilter) {
    function applyFilters() {
      var areaVal = areaFilter ? areaFilter.value : '';
      var statusVal = statusFilter ? statusFilter.value : '';
      var assigneeVal = assigneeFilter ? assigneeFilter.value : '';
      var visibleCount = 0;

      function matchesAssignee(el) {
        if (!assigneeVal) return true;
        if (assigneeVal === 'me') {
          // Defensive: if currentUserId is missing (queue container absent or
          // anonymous render), match nothing rather than falling through to
          // matching every row with empty assignee_id (which would silently
          // turn "Mine" into "Unassigned").
          if (!currentUserId) return false;
          return el.dataset.assigneeId === currentUserId;
        }
        if (assigneeVal === 'unassigned') return el.dataset.unassigned === 'true';
        return true;
      }

      // Filter table rows (canonical count source)
      document.querySelectorAll('.queue-row').forEach(function (row) {
        var areaMatch = !areaVal || row.dataset.areaId === areaVal;
        var statusMatch = !statusVal || row.dataset.status === statusVal;
        var assigneeMatch = matchesAssignee(row);
        var visible = areaMatch && statusMatch && assigneeMatch;
        row.style.display = visible ? '' : 'none';
        if (visible) visibleCount++;
      });

      // Filter mobile cards (mirrors table row visibility)
      document.querySelectorAll('.queue-card').forEach(function (card) {
        var areaMatch = !areaVal || card.dataset.areaId === areaVal;
        var statusMatch = !statusVal || card.dataset.status === statusVal;
        var assigneeMatch = matchesAssignee(card);
        card.style.display = (areaMatch && statusMatch && assigneeMatch) ? '' : 'none';
      });

      // Show/hide empty state
      var emptyEl = document.getElementById('queue-empty');
      if (emptyEl) {
        emptyEl.classList.toggle('d-none', visibleCount > 0);
      }
    }

    if (areaFilter) areaFilter.addEventListener('change', applyFilters);
    if (statusFilter) statusFilter.addEventListener('change', applyFilters);
    if (assigneeFilter) assigneeFilter.addEventListener('change', applyFilters);
  }

  // --- Resolve modal: wire up dynamic action + clear stale textarea ---
  var resolveModal = document.getElementById('resolveModal');
  if (resolveModal) {
    // Cache element references once at DOMContentLoaded -- they're stable
    // for the page lifetime.
    var resolveModalForm = document.getElementById('resolveModalForm');
    var resolveModalNote = document.getElementById('resolveModalNote');
    var resolveModalRepairIdSpan = document.getElementById('resolveModalRepairId');
    // SCRIPT_NAME-aware prefix. Empty string when the app is mounted at
    // the server root; otherwise the WSGI mount prefix (e.g. '/esb').
    // Read from a data-attribute on the modal that the template renders
    // from {{ request.script_root }}.
    var resolveModalScriptRoot = resolveModal.getAttribute('data-script-root') || '';
    resolveModal.addEventListener('show.bs.modal', function (event) {
      var trigger = event.relatedTarget;
      if (!trigger) return;
      var rawId = trigger.getAttribute('data-repair-id');
      // Defensive: data-repair-id must be a positive integer. Any other value
      // (path traversal, scheme injection, garbage) silently aborts the
      // dynamic-action patch so the form keeps its inert sentinel action.
      var repairId = parseInt(rawId, 10);
      if (!Number.isInteger(repairId) || repairId <= 0 || String(repairId) !== String(rawId).trim()) return;
      if (resolveModalForm) resolveModalForm.setAttribute('action', resolveModalScriptRoot + '/repairs/' + repairId + '/resolve');
      if (resolveModalNote) resolveModalNote.value = '';
      if (resolveModalRepairIdSpan) resolveModalRepairIdSpan.textContent = '#' + repairId;
    });
  }

  // --- Kiosk shrink-to-fit scaling ---
  // Contract: only `transform` styles may be applied to #kiosk-scale-content.
  // Any non-transform style that affects layout (font-size, width, padding,
  // etc.) breaks the scrollWidth/scrollHeight measurement assumption.
  // See Tech Decision #17 in the spec.
  var kioskScale = document.getElementById('kiosk-scale-content');
  if (kioskScale) {
    var KIOSK_RESIZE_DEBOUNCE_MS = 150;
    // Cap rAF retries so a permanently-zero layout (display:none, hidden
    // iframe, CSS bug) cannot spin the CPU. ~60 frames ~= 1 second at 60Hz.
    var KIOSK_RAF_MAX_RETRIES = 60;
    var rafRetries = 0;
    var resizeTimer = null;
    function applyKioskScale() {
      // scrollWidth/scrollHeight report natural unscaled dimensions per
      // CSS spec -- transforms do not affect layout.
      var contentW = kioskScale.scrollWidth;
      var contentH = kioskScale.scrollHeight;
      var viewportW = document.documentElement.clientWidth;
      var viewportH = document.documentElement.clientHeight;
      if (viewportW <= 0 || viewportH <= 0) return;  // hidden tab / boot
      if (contentW <= 0 || contentH <= 0) {
        // Layout transiently zero (e.g., during font swap). Retry on the
        // next animation frame so we don't get stuck with no transform.
        if (rafRetries < KIOSK_RAF_MAX_RETRIES) {
          rafRetries++;
          requestAnimationFrame(applyKioskScale);
        }
        return;
      }
      rafRetries = 0;
      var scale = Math.min(1, viewportW / contentW, viewportH / contentH);
      kioskScale.style.transform = 'scale(' + scale + ')';
    }
    applyKioskScale();
    // Re-run after images, web-fonts, etc. settle to avoid FOUT-induced miscalibration.
    if (document.readyState === 'complete') {
      // 'load' has already fired before this script ran -- invoke directly.
      applyKioskScale();
    } else {
      window.addEventListener('load', applyKioskScale);
    }
    if (document.fonts && document.fonts.ready && typeof document.fonts.ready.then === 'function') {
      document.fonts.ready.then(applyKioskScale);
    }
    window.addEventListener('resize', function () {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(applyKioskScale, KIOSK_RESIZE_DEBOUNCE_MS);
    });
  }
});

// --- QR code live preview (no-op on pages without #qr-form) ---
(function () {
  var form = document.getElementById('qr-form');
  if (!form) return;
  var img = document.getElementById('qr-preview');
  var errEl = document.getElementById('qr-preview-error');
  var base = form.getAttribute('data-preview-base');
  var timer = null;
  // Attach once so they persist across every debounced img.src reassignment.
  // A 400 (e.g. oversized canvas) degrades to a readable message, not a broken icon.
  img.onerror = function () {
    img.classList.add('d-none');
    if (errEl) errEl.classList.remove('d-none');
  };
  img.onload = function () {
    img.classList.remove('d-none');
    if (errEl) errEl.classList.add('d-none');
  };
  function update() {
    var size = form.querySelector('[name="size"]').value;
    // Checkbox lookups are guarded: the include_url checkbox is absent when a
    // template without url_bbox is active, and an unguarded .checked on a
    // missing element would throw and kill the whole preview updater.
    var incNameEl = form.querySelector('[name="include_name"]');
    var incName = incNameEl && incNameEl.checked ? '1' : '';
    var incUrlEl = form.querySelector('[name="include_url"]');
    var incUrl = incUrlEl && incUrlEl.checked ? '1' : '';
    var wifiInfo = form.querySelector('[name="wifi_info"]');
    var device = form.querySelector('[name="device"]');
    var params = new URLSearchParams({ size: size });
    if (device) params.set('device', device.value);
    if (wifiInfo) params.set('wifi_info', wifiInfo.value);
    if (incName) params.set('include_name', '1');
    if (incUrl) params.set('include_url', '1');
    img.src = base + '?' + params.toString();
  }
  function schedule() {
    // Debounce rapid toggles — letter-preset renders are expensive.
    if (timer) clearTimeout(timer);
    timer = setTimeout(update, 150);
  }
  form.addEventListener('change', schedule);
})();
