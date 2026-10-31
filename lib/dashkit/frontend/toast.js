// dashkit/frontend/toast.js: shared toast + confirm dialog helpers.
//
// Requires the host page to provide:
//   <div id="toast-container"></div>
//   <div id="confirm-overlay">...</div>
//   <div id="confirm-icon">, <div id="confirm-title">,
//   <div id="confirm-message">, <button id="confirm-action-btn">
//
// (New dashboards
// copy them from base.css's accompanying HTML snippet.)

(function (global) {
  var confirmCallback = null;

  // Use shared escapeHtml from dashboard-common.js if available,
  // otherwise fall back to a local copy for standalone usage.
  function esc(s) {
    if (global.escapeHtml) return global.escapeHtml(s);
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function showToast(message, isError) {
    var container = document.getElementById('toast-container');
    if (!container) {
      // No container; fail silent so dashboards without toasts don't crash.
      return;
    }
    var toast = document.createElement('div');
    toast.className = 'toast' + (isError ? ' error' : '');
    toast.innerHTML =
      '<span class="toast-icon">' + (isError ? '\u2716' : '\u2714') + '</span>' +
      '<span class="toast-text">' + esc(message) + '</span>';
    container.appendChild(toast);
    setTimeout(function () {
      toast.style.animation = 'toast-out 0.3s ease forwards';
      setTimeout(function () { toast.remove(); }, 300);
    }, 4000);
  }

  function showConfirm(opts) {
    var overlay = document.getElementById('confirm-overlay');
    if (!overlay) return;
    var icon = document.getElementById('confirm-icon');
    if (icon) {
      icon.className = 'confirm-icon ' + (opts.type || 'review');
      icon.innerHTML = opts.icon || '\u2714';
    }
    var titleEl = document.getElementById('confirm-title');
    if (titleEl) titleEl.textContent = opts.title;
    var msgEl = document.getElementById('confirm-message');
    if (msgEl) msgEl.innerHTML = opts.message;
    var btn = document.getElementById('confirm-action-btn');
    if (btn) {
      btn.textContent = opts.btnText || 'Confirm';
      btn.className = 'btn ' + (opts.btnClass || 'btn-review');
    }
    confirmCallback = opts.onConfirm;
    overlay.classList.add('open');
  }

  function closeConfirm() {
    var overlay = document.getElementById('confirm-overlay');
    if (overlay) overlay.classList.remove('open');
    confirmCallback = null;
  }

  function executeConfirm() {
    if (confirmCallback) {
      confirmCallback();
    }
    closeConfirm();
  }

  global.dashkit = global.dashkit || {};
  global.dashkit.showToast = showToast;
  global.dashkit.showConfirm = showConfirm;
  global.dashkit.closeConfirm = closeConfirm;
  global.dashkit.executeConfirm = executeConfirm;

  global.showToast = showToast;
  global.showConfirm = showConfirm;
  global.closeConfirm = closeConfirm;
  global.executeConfirm = executeConfirm;
})(window);
