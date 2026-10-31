// dashkit/frontend/audit.js: generic activity-feed renderer.
//
// Reads /api/audit-log (the dashkit endpoint) and renders into
// #activity-list, with #activity-count showing the total. Domain
// dashboards can pass a custom action_type → label map via
// dashkit.registerActivityLabels({...}); the defaults below cover the
// most common verbs (review/approve/comment/edit/delete/ai_*).
//
// Activity row schema (from dashkit.audit.fetch_activity):
//   { id, action_type, type, user, doc_path, path, section_id,
//     detail, timestamp }

(function (global) {
  var DEFAULT_LABELS = {
    review:                 { icon: '\u2714', verb: 'reviewed' },
    approve:                { icon: '\u2691', verb: 'approved' },
    unreview:               { icon: '\u21A9', verb: 'reverted review on' },
    comment_add:            { icon: '\u{1F4AC}', verb: 'commented on', cls: 'comment' },
    comment_delete:         { icon: '\u2715', verb: 'deleted a comment on', cls: 'comment' },
    checklist_add:          { icon: '\u2610', verb: 'added a checklist item on' },
    checklist_toggle:       { icon: '\u2610', verb: 'toggled a checklist item on' },
    section_edit:           { icon: '\u270E', verb: 'edited section' },
    section_unlock:         { icon: '\u{1F513}', verb: 'unlocked section' },
    section_accept_suggestion: { icon: '\u2714', verb: 'accepted auto-suggestion for' },
    ai_analyze:             { icon: '\u2728', verb: 'ran ai_analyze on' },
    ai_analyze_all:         { icon: '\u2728', verb: 'ran ai_analyze_all on' },
    ai_coherence:           { icon: '\u2728', verb: 'ran ai_coherence on' },
    ai_generate:            { icon: '\u2728', verb: 'ran ai_generate on' },
    ai_generate_batch:      { icon: '\u2728', verb: 'ran ai_generate_batch on' },
    ai_verify_batch:        { icon: '\u2728', verb: 'ran ai_verify_batch on' },
    ai_backup_create:       { icon: '\u2728', verb: 'created an AI backup of' },
    ai_backup_restore:      { icon: '\u2728', verb: 'restored an AI backup of' },
    ai_config_update:       { icon: '\u2728', verb: 'updated AI config' },
    ai_sources_update:      { icon: '\u2728', verb: 'updated AI sources' },
    ai_toggle_enabled:      { icon: '\u2728', verb: 'toggled AI enabled' },
    ambient_capture:        { icon: '\u{1F4DD}', verb: 'captured', cls: 'capture' },
    export:                 { icon: '\u21C4', verb: 'exported' },
    import:                 { icon: '\u21C4', verb: 'imported' },
    autofill:               { icon: '\u21C4', verb: 'ran autofill' },
  };

  var customLabels = {};

  function registerActivityLabels(labels) {
    Object.assign(customLabels, labels);
  }

  // Use shared escapeHtml from dashboard-common.js if available,
  // otherwise fall back to a local copy for standalone usage.
  function escapeHtmlSafe(s) {
    if (global.escapeHtml) return global.escapeHtml(s);
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function shortName(email) {
    if (!email) return 'Unknown';
    var parts = email.split('@')[0].split('.');
    return parts.map(function (p) { return p.charAt(0).toUpperCase() + p.slice(1); }).join(' ');
  }

  function pathName(path) {
    if (!path) return '';
    var parts = path.split('/');
    return parts[parts.length - 1].replace('.md', '');
  }

  function fmtDate(s) {
    if (global.formatDate) return global.formatDate(s);
    return s || '';
  }

  function lookupLabel(type) {
    return customLabels[type] || DEFAULT_LABELS[type];
  }

  async function loadActivityFeed(opts) {
    opts = opts || {};
    var endpoint = opts.endpoint || '/api/audit-log?limit=100';
    var listId = opts.listId || 'activity-list';
    var countId = opts.countId || 'activity-count';

    var listEl = document.getElementById(listId);
    if (!listEl) return;

    try {
      var data = await global.apiGet(endpoint);
      var activities = (data && data.activity) || [];
      var countEl = document.getElementById(countId);
      if (countEl) countEl.textContent = activities.length + ' events';

      if (activities.length === 0) {
        listEl.innerHTML =
          '<div class="empty-state"><div class="empty-state-icon">&#128340;</div>' +
          '<div class="empty-state-text">No audit entries yet.</div></div>';
        return;
      }

      var html = activities.map(function (a) {
        var type = a.action_type || a.type || 'unknown';
        var label = lookupLabel(type);
        var iconCls = (label && label.cls) || type;
        var iconChar = (label && label.icon) || '\u2714';
        var pathDisplay = a.doc_path || a.path || '';
        var who = '<strong>' + escapeHtmlSafe(shortName(a.user)) + '</strong>';
        var pathHtml = pathDisplay
          ? ' <span class="path">' + escapeHtmlSafe(pathName(pathDisplay)) + '</span>'
          : '';
        var sectionHtml = a.section_id
          ? ' <code>' + escapeHtmlSafe(a.section_id) + '</code>'
          : '';

        var desc;
        if (label) {
          desc = who + ' ' + label.verb + sectionHtml + pathHtml;
        } else {
          desc = who + ' performed <code>' + escapeHtmlSafe(type) + '</code>' + pathHtml;
        }

        var detailLine = '';
        if (a.detail) {
          try {
            detailLine = '<div class="activity-quote"><code>' +
              escapeHtmlSafe(JSON.stringify(a.detail)) + '</code></div>';
          } catch (e) { /* ignore */ }
        }

        return '<li class="activity-item">' +
          '<div class="activity-icon ' + iconCls + '">' + iconChar + '</div>' +
          '<div class="activity-body">' +
            '<div class="activity-desc">' + desc + '</div>' +
            detailLine +
            '<div class="activity-time">' + fmtDate(a.timestamp) + '</div>' +
          '</div>' +
          '</li>';
      }).join('');

      listEl.innerHTML = html;
    } catch (err) {
      listEl.innerHTML =
        '<div class="empty-state"><div class="empty-state-text">Failed to load activity: ' + escapeHtmlSafe(err.message) + '</div></div>';
    }
  }

  global.dashkit = global.dashkit || {};
  global.dashkit.loadActivityFeed = loadActivityFeed;
  global.dashkit.registerActivityLabels = registerActivityLabels;
})(window);
