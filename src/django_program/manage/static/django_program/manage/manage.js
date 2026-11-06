(function () {
  'use strict';

  var COLLAPSE_KEY = 'manage-sidebar-collapsed';

  function readCollapsed() {
    try {
      return JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '{}');
    } catch (e) {
      return {};
    }
  }

  function writeCollapsed(state) {
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify(state));
    } catch (e) {
      /* storage unavailable (private browsing, etc.) */
    }
  }

  function initSectionCollapse() {
    var stored = readCollapsed();

    document.querySelectorAll('.sidebar-section[data-section]').forEach(function (section) {
      var id = section.dataset.section;
      var title = section.querySelector('.sidebar-section-title');
      if (!title) return;
      var hasActive = section.querySelector('.sidebar-nav a.active, .sidebar-subnav a.active');

      if (stored[id] && !hasActive) {
        section.classList.add('collapsed');
        title.setAttribute('aria-expanded', 'false');
      }

      function toggleSection() {
        section.classList.toggle('collapsed');
        var collapsed = section.classList.contains('collapsed');
        stored[id] = collapsed;
        title.setAttribute('aria-expanded', String(!collapsed));
        writeCollapsed(stored);
      }

      title.addEventListener('click', toggleSection);
      title.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggleSection();
        }
      });
    });

    document.querySelectorAll('.sidebar-sublabel[data-subsection]').forEach(function (label) {
      var id = label.dataset.subsection;
      var target = document.querySelector('[data-subsection-target="' + id + '"]');
      if (!target) return;
      var hasActive = target.querySelector('a.active');

      if (stored[id] && !hasActive) {
        target.classList.add('collapsed');
        label.classList.add('collapsed-label');
      }

      function toggleGroup() {
        target.classList.toggle('collapsed');
        label.classList.toggle('collapsed-label');
        stored[id] = target.classList.contains('collapsed');
        writeCollapsed(stored);
      }

      label.addEventListener('click', toggleGroup);
      label.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggleGroup();
        }
      });
    });

    document.querySelectorAll('.sidebar-nav-expand-btn[data-expand-target]').forEach(function (btn) {
      var target = document.getElementById(btn.dataset.expandTarget);
      if (!target) return;
      btn.addEventListener('click', function () {
        btn.classList.toggle('open');
        target.classList.toggle('open');
        btn.setAttribute('aria-expanded', String(target.classList.contains('open')));
      });
    });
  }

  function initMobileDrawer() {
    var toggle = document.getElementById('manage-sidebar-toggle');
    var sidebar = document.getElementById('manage-sidebar');
    var scrim = document.getElementById('manage-sidebar-scrim');
    if (!toggle || !sidebar) return;

    var mql = window.matchMedia('(max-width: 900px)');

    function isMobile() {
      return mql.matches;
    }

    function syncInert() {
      if (isMobile() && !sidebar.classList.contains('open')) {
        sidebar.setAttribute('inert', '');
        sidebar.setAttribute('aria-hidden', 'true');
      } else {
        sidebar.removeAttribute('inert');
        sidebar.removeAttribute('aria-hidden');
      }
    }

    function openDrawer() {
      sidebar.classList.add('open');
      toggle.setAttribute('aria-expanded', 'true');
      if (scrim) scrim.hidden = false;
      syncInert();
    }

    function closeDrawer() {
      sidebar.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
      if (scrim) scrim.hidden = true;
      syncInert();
      toggle.focus();
    }

    toggle.addEventListener('click', function () {
      if (sidebar.classList.contains('open')) {
        closeDrawer();
      } else {
        openDrawer();
      }
    });

    if (scrim) scrim.addEventListener('click', closeDrawer);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && sidebar.classList.contains('open')) closeDrawer();
    });

    function handleViewportChange() {
      if (!isMobile() && sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
        if (scrim) scrim.hidden = true;
      }
      syncInert();
    }

    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', handleViewportChange);
    } else if (typeof mql.addListener === 'function') {
      mql.addListener(handleViewportChange);
    }

    syncInert();
  }

  function initPalette() {
    var trigger = document.getElementById('manage-palette-trigger');
    var dialog = document.getElementById('manage-palette');
    if (!dialog) return;

    var dataEl = document.getElementById('manage-palette-data');
    var items = [];
    if (dataEl) {
      try {
        items = JSON.parse(dataEl.textContent);
      } catch (e) {
        items = [];
      }
    }

    var input = dialog.querySelector('.palette-input');
    var list = dialog.querySelector('.palette-results');
    var activeIndex = -1;
    var filtered = items;

    function render() {
      if (!list) return;
      list.innerHTML = '';
      if (!filtered.length) {
        var empty = document.createElement('li');
        empty.className = 'palette-empty';
        empty.textContent = 'No matches';
        list.appendChild(empty);
        if (input) input.removeAttribute('aria-activedescendant');
        return;
      }
      filtered.forEach(function (item, index) {
        var li = document.createElement('li');
        li.className = 'palette-result' + (index === activeIndex ? ' active' : '');
        li.setAttribute('role', 'option');
        li.id = 'palette-result-' + index;
        var sectionEl = document.createElement('span');
        sectionEl.className = 'palette-result-section';
        sectionEl.textContent = item.section || '';
        var labelEl = document.createElement('span');
        labelEl.className = 'palette-result-label';
        labelEl.textContent = item.label;
        li.appendChild(sectionEl);
        li.appendChild(labelEl);
        li.addEventListener('mousedown', function (e) {
          e.preventDefault();
          navigate(item);
        });
        list.appendChild(li);
      });
      if (input) {
        input.setAttribute('aria-activedescendant', activeIndex >= 0 ? 'palette-result-' + activeIndex : '');
      }
      if (activeIndex >= 0) {
        var activeEl = document.getElementById('palette-result-' + activeIndex);
        if (activeEl && typeof activeEl.scrollIntoView === 'function') {
          activeEl.scrollIntoView({ block: 'nearest' });
        }
      }
    }

    function filterItems(query) {
      var q = query.trim().toLowerCase();
      filtered = !q
        ? items
        : items.filter(function (item) {
            return (
              (item.label && item.label.toLowerCase().indexOf(q) !== -1) ||
              (item.section && item.section.toLowerCase().indexOf(q) !== -1) ||
              (item.description && item.description.toLowerCase().indexOf(q) !== -1)
            );
          });
      activeIndex = filtered.length ? 0 : -1;
      render();
    }

    function navigate(item) {
      closePalette();
      if (item.method === 'post') {
        var template = document.getElementById('manage-palette-post-form');
        if (!template) {
          window.location.href = item.href;
          return;
        }
        var form = template.cloneNode(true);
        form.removeAttribute('id');
        form.removeAttribute('hidden');
        form.style.display = 'none';
        form.action = item.href;
        if (!item.same_origin) {
          var csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
          if (csrfInput) csrfInput.remove();
        }
        document.body.appendChild(form);
        form.submit();
      } else {
        window.location.href = item.href;
      }
    }

    function openPalette() {
      filtered = items;
      activeIndex = items.length ? 0 : -1;
      if (input) input.value = '';
      render();
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }
      if (input) input.focus();
    }

    function closePalette() {
      if (typeof dialog.close === 'function' && dialog.open) {
        dialog.close();
      } else {
        dialog.removeAttribute('open');
      }
    }

    if (trigger) {
      trigger.addEventListener('click', openPalette);
      var isMac = /Mac|iPod|iPhone|iPad/.test(navigator.platform || '');
      var kbd = trigger.querySelector('.palette-kbd');
      if (kbd) kbd.textContent = isMac ? kbd.dataset.mac : kbd.dataset.pc;
    }

    document.addEventListener('keydown', function (e) {
      var isShortcut = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
      if (!isShortcut) return;
      e.preventDefault();
      if (dialog.open) {
        closePalette();
      } else {
        openPalette();
      }
    });

    if (input) {
      input.addEventListener('input', function () {
        filterItems(input.value);
      });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (filtered.length) activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
          render();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (filtered.length) activeIndex = Math.max(activeIndex - 1, 0);
          render();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (filtered[activeIndex]) navigate(filtered[activeIndex]);
        } else if (e.key === 'Escape') {
          closePalette();
        }
      });
    }

    dialog.addEventListener('cancel', function (e) {
      e.preventDefault();
      closePalette();
    });

    dialog.addEventListener('click', function (e) {
      if (e.target === dialog) closePalette();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initSectionCollapse();
    initMobileDrawer();
    initPalette();
  });
})();
