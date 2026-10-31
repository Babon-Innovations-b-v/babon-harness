// dashkit/frontend/api.js: shared fetch helpers for dashkit dashboards.
//
// Every dashboard sits behind Caddy forward_auth, so cookies are
// already attached. We always pass credentials: 'include' so the
// browser forwards them on cross-origin previews too.

(function (global) {
  var API_BASE = '';

  async function apiGet(url) {
    var resp = await fetch(API_BASE + url, { credentials: 'include' });
    if (!resp.ok) throw new Error('GET ' + url + ' failed: ' + resp.status);
    return resp.json();
  }

  async function apiPost(url, body) {
    var resp = await fetch(API_BASE + url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error('POST ' + url + ' failed: ' + resp.status);
    return resp.json();
  }

  async function apiPut(url, body) {
    var resp = await fetch(API_BASE + url, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error('PUT ' + url + ' failed: ' + resp.status);
    return resp.json();
  }

  async function apiDelete(url) {
    var resp = await fetch(API_BASE + url, {
      method: 'DELETE',
      credentials: 'include'
    });
    if (!resp.ok) throw new Error('DELETE ' + url + ' failed: ' + resp.status);
    return resp.json();
  }

  async function apiGetHtml(url) {
    var resp = await fetch(API_BASE + url, { credentials: 'include' });
    if (!resp.ok) throw new Error('GET ' + url + ' failed: ' + resp.status);
    return resp.text();
  }

  global.dashkit = global.dashkit || {};
  global.dashkit.apiGet = apiGet;
  global.dashkit.apiPost = apiPost;
  global.dashkit.apiPut = apiPut;
  global.dashkit.apiDelete = apiDelete;
  global.dashkit.apiGetHtml = apiGetHtml;

  // Also expose at top-level for dashboards that call these helpers inline.
  global.apiGet = apiGet;
  global.apiPost = apiPost;
  global.apiPut = apiPut;
  global.apiDelete = apiDelete;
  global.apiGetHtml = apiGetHtml;
})(window);
