// dashkit/frontend/view.js: view-toggle pattern shared by all dashboards.
//
// Each dashboard has multiple top-level "views" (Documents, Activity,
// Inspector, ...). switchView(name) hides every element with class
// view-* and reveals the matching view-{name}, then highlights the
// corresponding nav button.
//
// Convention:
//   <button class="view-toggle" data-view="activity">Activity</button>
//   <section class="view view-activity">...</section>
//
// On show, an event 'dashkit:view-shown' is dispatched on document
// with detail.view = name, so individual views can lazy-load on first
// reveal.

(function (global) {
  function switchView(name) {
    var views = document.querySelectorAll('.view');
    for (var i = 0; i < views.length; i++) {
      views[i].style.display = 'none';
    }
    var target = document.querySelector('.view-' + name);
    if (target) {
      target.style.display = '';
    }
    var toggles = document.querySelectorAll('.view-toggle');
    for (var j = 0; j < toggles.length; j++) {
      var btn = toggles[j];
      if (btn.getAttribute('data-view') === name) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    }
    document.dispatchEvent(new CustomEvent('dashkit:view-shown', {
      detail: { view: name }
    }));
  }

  global.dashkit = global.dashkit || {};
  global.dashkit.switchView = switchView;
  global.switchView = switchView;
})(window);
