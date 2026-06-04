(function() {
  var page = document.querySelector('.writing-page');
  if (!page) return;

  var totalSec = parseInt(page.getAttribute('data-total-minutes') || '80', 10) * 60;
  var wordMin = parseInt(page.getAttribute('data-word-min') || '140', 10);
  var wordMax = parseInt(page.getAttribute('data-word-max') || '190', 10);
  var autosaveUrl = page.getAttribute('data-autosave-url') || '';
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

  function fmtTime(s) {
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var z = s % 60;
    if (h > 0) {
      return h + ':' + (m < 10 ? '0' : '') + m + ':' + (z < 10 ? '0' : '') + z;
    }
    return m + ':' + (z < 10 ? '0' : '') + z;
  }

  function countWords(text) {
    if (!text || !text.trim()) return 0;
    return text.trim().split(/\s+/).filter(Boolean).length;
  }

  function updateCheckButton(el, wordCount) {
    var form = el && el.closest ? el.closest('form') : null;
    var btn = form ? form.querySelector('button[name="action"][value="check"]') : null;
    if (!btn) return;
    var ready = wordCount >= wordMin;
    btn.disabled = !ready;
    btn.setAttribute('aria-disabled', ready ? 'false' : 'true');
    btn.title = ready ? '' : 'Write at least ' + wordMin + ' words before checking with AI.';
  }

  function updateWordCount(el, countEl) {
    var text = (el && el.value) || '';
    var n = countWords(text);
    if (countEl) {
      countEl.textContent = n + ' words (' + wordMin + '\u2013' + wordMax + ')';
      countEl.classList.remove('writing-count-ok', 'writing-count-low', 'writing-count-high');
      if (n >= wordMin && n <= wordMax) countEl.classList.add('writing-count-ok');
      else if (n > 0 && n < wordMin) countEl.classList.add('writing-count-low');
      else if (n > wordMax) countEl.classList.add('writing-count-high');
    }
    updateCheckButton(el, n);
  }

  function statusForTextarea(textarea) {
    var form = textarea && textarea.closest ? textarea.closest('form') : null;
    return form ? form.querySelector('[data-draft-status]') : null;
  }

  function setDraftStatus(textarea, text, state) {
    var statusEl = statusForTextarea(textarea);
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.classList.remove(
      'writing-draft-status-saving',
      'writing-draft-status-saved',
      'writing-draft-status-error',
      'writing-draft-status-dirty'
    );
    if (state) statusEl.classList.add('writing-draft-status-' + state);
  }

  function formatSavedTime() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    return h + ':' + m;
  }

  function saveDraft(textarea, immediate) {
    if (!autosaveUrl || !textarea) return;
    var answer = textarea.value || '';
    if (!immediate && answer === textarea._writingLastSaved) return;
    if (textarea._writingSaving) {
      textarea._writingPendingSave = true;
      return;
    }
    textarea._writingSaving = true;
    textarea._writingPendingSave = false;
    setDraftStatus(textarea, 'Saving…', 'saving');
    var part = parseInt(textarea.getAttribute('data-part') || '0', 10);
    var optionId = textarea.getAttribute('data-option-id') || '';
    fetch(autosaveUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: JSON.stringify({
        part: part,
        option_id: optionId,
        answer: answer
      }),
      keepalive: !!immediate && answer.length < 30000
    }).then(function(resp) {
      if (!resp.ok) throw new Error('Draft save failed');
      return resp.json();
    }).then(function(data) {
      if (!data || data.ok !== true) throw new Error('Draft save failed');
      textarea._writingLastSaved = answer;
      setDraftStatus(textarea, 'Saved ' + formatSavedTime(), 'saved');
    }).catch(function() {
      setDraftStatus(textarea, 'Autosave failed', 'error');
    }).finally(function() {
      textarea._writingSaving = false;
      if (textarea._writingPendingSave || textarea.value !== textarea._writingLastSaved) {
        textarea._writingPendingSave = false;
        scheduleDraftSave(textarea);
      }
    });
  }

  function scheduleDraftSave(textarea) {
    if (!autosaveUrl || !textarea) return;
    if (textarea._writingDraftTimer) clearTimeout(textarea._writingDraftTimer);
    if (textarea.value !== textarea._writingLastSaved) {
      setDraftStatus(textarea, 'Unsaved changes', 'dirty');
    }
    textarea._writingDraftTimer = setTimeout(function() {
      saveDraft(textarea, false);
    }, 1200);
  }

  function registerAutosave(textarea) {
    if (!autosaveUrl || !textarea) return;
    textarea._writingLastSaved = textarea.value || '';
    setDraftStatus(textarea, textarea.value ? 'Draft saved' : 'Autosave ready', textarea.value ? 'saved' : '');
    textarea.addEventListener('input', function() {
      scheduleDraftSave(textarea);
    });
    textarea.addEventListener('paste', function() {
      setTimeout(function() { scheduleDraftSave(textarea); }, 0);
    });
    var form = textarea.closest ? textarea.closest('form') : null;
    if (form) {
      form.addEventListener('submit', function() {
        saveDraft(textarea, true);
      });
    }
  }

  function createWritingResizer(layoutId, resizerId, cssVarName, storageKey) {
    var layout = document.getElementById(layoutId);
    var resizer = document.getElementById(resizerId);
    if (!layout || !resizer) return;
    var minPct = 25, maxPct = 75;
    function setPct(pct, save) {
      pct = Math.max(minPct, Math.min(maxPct, pct));
      layout.style.setProperty(cssVarName, pct + '%');
      if (save !== false) {
        try { localStorage.setItem(storageKey, String(pct)); } catch (e) {}
      }
    }
    function restoreSaved() {
      try {
        var saved = localStorage.getItem(storageKey);
        if (saved != null && saved !== '') {
          var n = parseFloat(String(saved).trim(), 10);
          if (!isNaN(n) && n >= minPct && n <= maxPct) {
            setPct(n, false);
          }
        }
      } catch (e) {}
    }
    restoreSaved();
    resizer.addEventListener('mousedown', function(e) {
      e.preventDefault();
      function move(ev) {
        var r = layout.getBoundingClientRect();
        var pct = ((ev.clientX - r.left) / r.width) * 100;
        setPct(pct);
      }
      function stop() {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', stop);
      }
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', stop);
    });
  }

  // Tabs: Part 1 / Part 2
  var tab1 = document.getElementById('writing-tab-1');
  var tab2 = document.getElementById('writing-tab-2');
  var panel1 = document.getElementById('writing-part1-panel');
  var panel2 = document.getElementById('writing-part2-panel');
  if (tab1 && tab2 && panel1 && panel2) {
    tab1.addEventListener('click', function() {
      tab1.classList.add('writing-tab-active');
      tab1.setAttribute('aria-selected', 'true');
      tab2.classList.remove('writing-tab-active');
      tab2.setAttribute('aria-selected', 'false');
      panel1.classList.add('writing-panel-active');
      panel1.removeAttribute('hidden');
      panel2.classList.remove('writing-panel-active');
      panel2.setAttribute('hidden', '');
    });
    tab2.addEventListener('click', function() {
      tab2.classList.add('writing-tab-active');
      tab2.setAttribute('aria-selected', 'true');
      tab1.classList.remove('writing-tab-active');
      tab1.setAttribute('aria-selected', 'false');
      panel2.classList.add('writing-panel-active');
      panel2.removeAttribute('hidden');
      panel1.classList.remove('writing-panel-active');
      panel1.setAttribute('hidden', '');
    });
  }

  // Resizer between prompt and editor (Part 1)
  createWritingResizer('writing-layout', 'writing-resizer', '--writing-left-pct', 'fce_writing_left_pct');

  // Part 1 word count
  var part1Text = document.getElementById('writing-part1-text');
  var part1Count = document.getElementById('writing-part1-count');
  if (part1Text && part1Count) {
    part1Text.addEventListener('input', function() { updateWordCount(part1Text, part1Count); });
    part1Text.addEventListener('paste', function() { setTimeout(function() { updateWordCount(part1Text, part1Count); }, 0); });
    updateWordCount(part1Text, part1Count);
  }

  // Part 2: expand/collapse option and word counts
  var optionBtns = page.querySelectorAll('.writing-option-btn');
  optionBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      var id = btn.getAttribute('data-option-id');
      var promptEl = document.getElementById('writing-option-prompt-' + id);
      if (!promptEl) return;
      var isExpanded = btn.getAttribute('aria-expanded') === 'true';
      page.querySelectorAll('.writing-option-btn').forEach(function(b) { b.setAttribute('aria-expanded', 'false'); });
      page.querySelectorAll('.writing-option-prompt').forEach(function(p) { p.setAttribute('hidden', ''); });
      if (!isExpanded) {
        btn.setAttribute('aria-expanded', 'true');
        promptEl.removeAttribute('hidden');
        var ta = promptEl.querySelector('.writing-textarea');
        if (ta) { ta.focus(); updateWordCount(ta, promptEl.querySelector('.writing-word-count')); }
      }
    });
  });
  page.querySelectorAll('.writing-part2-text').forEach(function(ta) {
    var wrap = ta.closest('.writing-option-prompt');
    var countEl = wrap && wrap.querySelector('.writing-word-count');
    ta.addEventListener('input', function() { updateWordCount(ta, countEl); });
    ta.addEventListener('paste', function() { setTimeout(function() { updateWordCount(ta, countEl); }, 0); });
    updateWordCount(ta, countEl);
  });

  page.querySelectorAll('.writing-textarea').forEach(function(ta) {
    registerAutosave(ta);
  });

  if (autosaveUrl) {
    setInterval(function() {
      page.querySelectorAll('.writing-textarea').forEach(function(ta) {
        saveDraft(ta, false);
      });
    }, 5000);
    window.addEventListener('beforeunload', function() {
      page.querySelectorAll('.writing-textarea').forEach(function(ta) {
        saveDraft(ta, true);
      });
    });
  }

  // Timer
  var timerEl = document.getElementById('writing-timer');
  var startBtn = document.getElementById('writing-timer-start');
  if (timerEl && startBtn) {
    var sec = totalSec;
    var interval = null;
    timerEl.textContent = fmtTime(sec);
    startBtn.addEventListener('click', function() {
      if (interval) return;
      sec = totalSec;
      timerEl.textContent = fmtTime(sec);
      timerEl.classList.remove('writing-timer-expired');
      startBtn.textContent = 'Started';
      startBtn.disabled = true;
      interval = setInterval(function() {
        sec--;
        if (sec <= 0) sec = 0;
        timerEl.textContent = fmtTime(sec);
        if (sec <= 0) {
          clearInterval(interval);
          interval = null;
          startBtn.textContent = 'Start';
          startBtn.disabled = false;
          timerEl.classList.add('writing-timer-expired');
          timerEl.textContent = '0:00 \u2014 Time\'s up!';
        }
      }, 1000);
    });
  }
})();
