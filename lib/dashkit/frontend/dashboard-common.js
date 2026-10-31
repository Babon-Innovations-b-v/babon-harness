// dashkit/frontend/dashboard-common.js: shared utility functions for all dashboards.
//
// Provides escapeHtml() and formatDate() so individual dashboards don't
// need to duplicate these. Load via:
//   <script src="/static/dashkit/dashboard-common.js"></script>

(function (global) {

  /**
   * HTML-escape a string for safe insertion into innerHTML.
   * Handles null/undefined gracefully.
   */
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /**
   * Format an ISO date string as a human-friendly relative time.
   * "just now" / "3m ago" / "2h ago" / "5d ago" / "14 Apr 2026"
   */
  function formatDate(s) {
    if (!s) return '';
    try {
      var d = new Date(s);
      var diffMs = Date.now() - d;
      var diffMin = Math.floor(diffMs / 60000);
      if (diffMin < 1) return 'just now';
      if (diffMin < 60) return diffMin + 'm ago';
      var diffH = Math.floor(diffMin / 60);
      if (diffH < 24) return diffH + 'h ago';
      var diffD = Math.floor(diffH / 24);
      if (diffD < 7) return diffD + 'd ago';
      return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (e) { return s; }
  }

  global.dashkit = global.dashkit || {};
  global.dashkit.escapeHtml = escapeHtml;
  global.dashkit.formatDate = formatDate;

  // Top-level for back-compat with inline callers.
  global.escapeHtml = escapeHtml;
  global.formatDate = formatDate;

})(window);
