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
      var target = document.querySelector('[data-subsection-target="' + label.dataset.subsection + '"]');
      if (!target) return;

      function toggleGroup() {
        var collapsed = target.classList.toggle('collapsed');
        label.classList.toggle('collapsed-label', collapsed);
        label.setAttribute('aria-expanded', String(!collapsed));
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

    var searchUrl = dialog.dataset.searchUrl || '';

    var input = dialog.querySelector('.palette-input');
    var list = dialog.querySelector('.palette-results');
    var activeIndex = -1;
    var localMatches = items;
    var remoteMatches = [];
    var remoteLoading = false;
    var debounceTimer = null;
    var abortController = null;
    var requestToken = 0;

    function combined() {
      return localMatches.concat(remoteMatches);
    }

    function isSameOrigin(href) {
      try {
        var url = new URL(href, window.location.href);
        return url.origin === window.location.origin;
      } catch (e) {
        return false;
      }
    }

    function clampActiveIndex() {
      var len = combined().length;
      if (!len) {
        activeIndex = -1;
        return;
      }
      if (activeIndex < 0) activeIndex = 0;
      if (activeIndex >= len) activeIndex = len - 1;
    }

    function render() {
      if (!list) return;
      list.innerHTML = '';
      var all = combined();
      if (!all.length && !remoteLoading) {
        var empty = document.createElement('li');
        empty.className = 'palette-empty';
        empty.textContent = 'No matches';
        list.appendChild(empty);
        if (input) input.removeAttribute('aria-activedescendant');
        return;
      }
      all.forEach(function (item, index) {
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
      if (remoteLoading) {
        var loading = document.createElement('li');
        loading.className = 'palette-loading';
        loading.textContent = 'Searching…';
        list.appendChild(loading);
      }
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

    function localFilter(query) {
      var q = query.trim().toLowerCase();
      if (!q) return items;
      var labelMatches = [];
      var otherMatches = [];
      items.forEach(function (item) {
        var label = item.label ? String(item.label).toLowerCase() : '';
        var section = item.section ? String(item.section).toLowerCase() : '';
        var description = item.description ? String(item.description).toLowerCase() : '';
        if (label.indexOf(q) !== -1) {
          labelMatches.push(item);
        } else if (section.indexOf(q) !== -1 || description.indexOf(q) !== -1) {
          otherMatches.push(item);
        }
      });
      return labelMatches.concat(otherMatches);
    }

    function fetchRemote(query) {
      if (debounceTimer) {
        clearTimeout(debounceTimer);
        debounceTimer = null;
      }
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
      var q = query.trim();
      var token = ++requestToken;
      if (!searchUrl || q.replace(/\s+/g, '').length < 2) {
        remoteMatches = [];
        remoteLoading = false;
        render();
        return;
      }
      remoteLoading = true;
      render();
      debounceTimer = setTimeout(function () {
        var controller = typeof AbortController === 'function' ? new AbortController() : null;
        abortController = controller;
        fetch(searchUrl + '?q=' + encodeURIComponent(q), {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
          signal: controller ? controller.signal : undefined,
        })
          .then(function (response) {
            if (!response.ok) throw new Error('search request failed');
            return response.json();
          })
          .then(function (data) {
            if (token !== requestToken) return;
            remoteMatches = data && Array.isArray(data.results) ? data.results : [];
            remoteLoading = false;
            clampActiveIndex();
            render();
          })
          .catch(function () {
            if (token !== requestToken) return;
            remoteMatches = [];
            remoteLoading = false;
            clampActiveIndex();
            render();
          });
      }, 200);
    }

    function filterItems(query) {
      localMatches = localFilter(query);
      activeIndex = combined().length ? 0 : -1;
      render();
      fetchRemote(query);
    }

    function navigate(item) {
      closePalette();
      if (item.method === 'post') {
        var template = document.getElementById('manage-palette-post-form');
        if (!template) {
          window.location.href = item.href;
          return;
        }
        var sameOrigin = typeof item.same_origin === 'boolean' ? item.same_origin : isSameOrigin(item.href);
        var form = template.cloneNode(true);
        form.removeAttribute('id');
        form.removeAttribute('hidden');
        form.style.display = 'none';
        form.action = item.href;
        if (!sameOrigin) {
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
      if (debounceTimer) {
        clearTimeout(debounceTimer);
        debounceTimer = null;
      }
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
      localMatches = items;
      remoteMatches = [];
      remoteLoading = false;
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
        var len = combined().length;
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (len) activeIndex = Math.min(activeIndex + 1, len - 1);
          render();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (len) activeIndex = Math.max(activeIndex - 1, 0);
          render();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          var target = combined()[activeIndex];
          if (target) navigate(target);
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
