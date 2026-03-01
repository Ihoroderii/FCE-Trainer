  function fmtTime(s) {
    var m = Math.floor(s / 60);
    var z = s % 60;
    return m + ':' + (z < 10 ? '0' : '') + z;
  }

  function createResizer(layoutId, resizerId, cssVarName, storageKey) {
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
    requestAnimationFrame(restoreSaved);
    resizer.addEventListener('mousedown', function(e) {
      e.preventDefault();
      function move(e) {
        var r = layout.getBoundingClientRect();
        var pct = ((e.clientX - r.left) / r.width) * 100;
        setPct(pct);
      }
      function stop() {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', stop);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        var current = layout.style.getPropertyValue(cssVarName);
        if (current) {
          var n = parseFloat(current, 10);
          if (!isNaN(n)) try { localStorage.setItem(storageKey, String(n)); } catch (err) {}
        }
      }
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', stop);
    });
  }

  (function() {
    var total = 75 * 60;
    var sec = total;
    var interval = null;
    var el = document.getElementById('timer');
    var btn = document.getElementById('timer-toggle');
    function tick() {
      sec--;
      if (sec <= 0) sec = 0;
      if (el) el.textContent = fmtTime(sec);
      if (sec <= 0 && interval) {
        clearInterval(interval);
        interval = null;
        if (btn) btn.textContent = '▶';
        if (el) {
          el.classList.add('global-timer-expired');
          el.textContent = "0:00 — Time's up!";
        }
      }
    }
    if (el) el.textContent = fmtTime(sec);
    if (btn) btn.addEventListener('click', function() {
      if (interval) {
        clearInterval(interval);
        interval = null;
        btn.textContent = '▶';
      } else {
        if (sec <= 0) sec = total;
        if (el) el.classList.remove('global-timer-expired');
        interval = setInterval(tick, 1000);
        btn.textContent = '⏸';
      }
      tick();
    });
    // Dark mode toggle (top right button)
    (function() {
      var btn = document.getElementById('dark-mode-btn');
      if (btn) btn.addEventListener('click', function() {
        var root = document.documentElement;
        root.classList.toggle('dark-mode');
        localStorage.setItem('darkMode', root.classList.contains('dark-mode') ? '1' : '0');
      });
    })();
    // Submit link: submit the visible main task form (the one with input name="part") if any
    function ensureCsrfToken(form) {
      if (!form) return;
      if (form.querySelector('input[name="csrf_token"]')) return;
      var meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && meta.getAttribute('content')) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'csrf_token';
        input.value = meta.getAttribute('content');
        form.appendChild(input);
      }
    }
    var submitLink = document.getElementById('btn-submit-link');
    if (submitLink) submitLink.addEventListener('click', function(e) {
      var partInput = document.querySelector('.task-card input[name="part"]');
      var form = partInput && partInput.closest('form');
      if (form) {
        ensureCsrfToken(form);
        form.submit();
        e.preventDefault();
      }
    });

    // Part nav: when clicking another part, submit current form first so answers are saved and part is marked done
    (function() {
      var currentPart = document.body && document.body.getAttribute('data-current-part');
      if (!currentPart) return;
      var partLinks = document.querySelectorAll('.part-seg[data-part]');
      for (var i = 0; i < partLinks.length; i++) {
        partLinks[i].addEventListener('click', function(e) {
          var targetPart = this.getAttribute('data-part');
          if (targetPart === currentPart) return;
          // Use the main task form (has input name="part"), not Generate Part 2/4 forms
          var partInput = document.querySelector('.task-card input[name="part"]');
          var form = partInput && partInput.closest('form');
          if (!form) {
            window.location.href = this.getAttribute('href') || ('?part=' + targetPart);
            e.preventDefault();
            return;
          }
          e.preventDefault();
          ensureCsrfToken(form);
          var input = document.createElement('input');
          input.type = 'hidden';
          input.name = 'switch_to_part';
          input.value = targetPart;
          form.appendChild(input);
          form.submit();
        });
      }
    })();

    // Part nav: emphasize task numbers when the corresponding field is filled
    (function() {
      var body = document.body;
      var currentPart = body && body.getAttribute('data-current-part');
      if (!currentPart) return;
      var partInput = document.querySelector('.task-card input[name="part"]');
      var form = partInput && partInput.closest('form');
      if (!form) return;
      var partSeg = document.querySelector('.part-seg[data-part="' + currentPart + '"]');
      if (!partSeg) return;

      function isTaskFilled(name) {
        var els = form.querySelectorAll('[name="' + name + '"]');
        if (!els.length) return false;
        for (var j = 0; j < els.length; j++) {
          var el = els[j];
          var tag = (el.tagName || '').toLowerCase();
          var type = (el.type || '').toLowerCase();
          if (type === 'radio' || type === 'checkbox') {
            if (el.checked) return true;
          } else {
            if ((el.value || '').trim() !== '') return true;
          }
        }
        return false;
      }

      function updateTaskHighlight() {
        var seen = {};
        var filledCount = 0;
        var totalTasks = parseInt(partSeg.getAttribute('data-total') || '0', 10);
        var inputs = form.querySelectorAll('input, select');
        for (var i = 0; i < inputs.length; i++) {
          var name = inputs[i].getAttribute('name') || '';
          var m = name.match(/^p(\d+)_(\d+)$/);
          if (!m || m[1] !== currentPart || seen[name]) continue;
          seen[name] = true;
          var taskIndex = parseInt(m[2], 10) + 1;
          var filled = isTaskFilled(name);
          if (filled) filledCount++;
          var numEl = partSeg.querySelector('.part-seg-task-num[data-task="' + taskIndex + '"]');
          if (numEl) {
            if (filled) numEl.classList.add('filled');
            else numEl.classList.remove('filled');
          }
        }
        var tasksEl = partSeg.querySelector('.part-seg-tasks');
        var allDoneEl = partSeg.querySelector('.part-seg-all-done');
        if (tasksEl && allDoneEl && totalTasks > 0) {
          if (filledCount >= totalTasks) {
            tasksEl.style.display = 'none';
            allDoneEl.style.display = 'inline';
          } else {
            tasksEl.style.display = 'inline-flex';
            allDoneEl.style.display = 'none';
          }
        }
      }

      form.addEventListener('input', updateTaskHighlight);
      form.addEventListener('change', updateTaskHighlight);
      updateTaskHighlight();
    })();
  })();

  // Draggable resizers for parts 3, 5, 6, 7
  createResizer('part3-layout', 'part3-resizer', '--part3-left-pct', 'fce_part3_left_pct');
  createResizer('part5-layout', 'part5-resizer', '--part5-left-pct', 'fce_part5_left_pct');
  createResizer('part6-layout', 'part6-resizer', '--part6-left-pct', 'fce_part6_left_pct');
  createResizer('part7-layout', 'part7-resizer', '--part7-left-pct', 'fce_part7_left_pct');

  // Part 5: 15-minute countdown timer (15:00 → 0:00), starts only when user clicks Start
  (function() {
    if (document.body.getAttribute('data-current-part') !== '5') return;
    var el = document.getElementById('part5-timer');
    var btn = document.getElementById('part5-timer-start');
    if (!el || !btn) return;
    var totalSec = 15 * 60;
    var sec = totalSec;
    var interval = null;
    function tick() {
      sec--;
      if (sec <= 0) sec = 0;
      el.textContent = fmtTime(sec);
      if (sec <= 0 && interval) {
        clearInterval(interval);
        interval = null;
        btn.textContent = 'Start';
        btn.disabled = false;
        el.classList.add('part5-timer-expired');
        el.textContent = "0:00 — Time's up!";
      }
    }
    el.textContent = fmtTime(sec);
    btn.addEventListener('click', function() {
      if (interval) return;
      sec = totalSec;
      el.textContent = fmtTime(sec);
      el.classList.remove('part5-timer-expired');
      btn.textContent = 'Started';
      btn.disabled = true;
      interval = setInterval(tick, 1000);
    });
  })();

  // Part 6: drag sentence from right into gap on left
  (function() {
    var letters = ['A','B','C','D','E','F','G'];
    var drops = document.querySelectorAll('.part6-gap-drop[data-droppable="true"]');
    var drags = document.querySelectorAll('.part6-sentence-drag');
    if (!drops.length || !drags.length) return;
    function getUsedIndices() {
      var used = {};
      drops.forEach(function(drop) {
        var inp = drop.querySelector('input[name^="p6_"]');
        if (inp && inp.value !== '') used[inp.value] = true;
      });
      return used;
    }
    function updateSentencesVisibility() {
      var used = getUsedIndices();
      drags.forEach(function(el) {
        var idx = el.getAttribute('data-sentence-index');
        if (used[idx]) {
          el.classList.add('part6-sentence-used');
        } else {
          el.classList.remove('part6-sentence-used');
        }
      });
    }
    function setGapValue(drop, idx) {
      var gapIndex = drop.getAttribute('data-gap-index');
      var input = drop.querySelector('input[name="p6_' + gapIndex + '"]');
      var label = drop.querySelector('.part6-gap-label');
      if (!input || !label) return;
      if (idx === '' || idx === null || idx === undefined) {
        input.value = '';
        label.textContent = '—';
        drop.classList.remove('part6-gap-has-value');
      } else {
        input.value = idx;
        label.textContent = letters[parseInt(idx, 10)] || '—';
        drop.classList.add('part6-gap-has-value');
      }
      updateSentencesVisibility();
    }
    function clearGap(drop) {
      setGapValue(drop, '');
    }
    drags.forEach(function(el) {
      el.addEventListener('dragstart', function(e) {
        e.dataTransfer.setData('text/plain', el.getAttribute('data-sentence-index'));
        e.dataTransfer.effectAllowed = 'move';
        el.classList.add('part6-dragging');
      });
      el.addEventListener('dragend', function() { el.classList.remove('part6-dragging'); });
    });
    drops.forEach(function(drop) {
      if (drop.querySelector('input[name^="p6_"]').value !== '') {
        drop.classList.add('part6-gap-has-value');
      }
      drop.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        drop.classList.add('part6-drop-over');
      });
      drop.addEventListener('dragleave', function() { drop.classList.remove('part6-drop-over'); });
      drop.addEventListener('drop', function(e) {
        e.preventDefault();
        drop.classList.remove('part6-drop-over');
        var idx = e.dataTransfer.getData('text/plain');
        if (idx === '') return;
        var gapIndex = drop.getAttribute('data-gap-index');
        var input = drop.querySelector('input[name="p6_' + gapIndex + '"]');
        var label = drop.querySelector('.part6-gap-label');
        if (!input || !label) return;
        drops.forEach(function(d) {
          var inp = d.querySelector('input[name^="p6_"]');
          if (inp && inp !== input && inp.value === idx) {
            setGapValue(d, '');
          }
        });
        setGapValue(drop, idx);
      });
      drop.querySelector('.part6-gap-clear') && drop.querySelector('.part6-gap-clear').addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        clearGap(drop);
      });
      drop.addEventListener('dblclick', function(e) {
        if (e.target.classList.contains('part6-gap-clear')) return;
        clearGap(drop);
      });
    });
    updateSentencesVisibility();
  })();

  // Loading state on form submit (Check answers / Generate)
  (function() {
    var taskCard = document.querySelector('.task-card');
    if (!taskCard) return;
    var forms = taskCard.querySelectorAll('form');
    for (var i = 0; i < forms.length; i++) {
      forms[i].addEventListener('submit', function() {
        var form = this;
        var submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn && !submitBtn.disabled) {
          submitBtn.setAttribute('data-original-text', submitBtn.textContent);
          submitBtn.disabled = true;
          if (form.classList.contains('part2-generate-form') || form.classList.contains('part4-generate-form')) {
            submitBtn.textContent = 'Generating…';
          } else {
            submitBtn.textContent = 'Checking…';
          }
        }
        var submitLink = document.getElementById('btn-submit-link');
        if (submitLink) {
          submitLink.setAttribute('data-original-text', submitLink.textContent);
          submitLink.style.pointerEvents = 'none';
          submitLink.textContent = '…';
        }
      });
    }
    window.addEventListener('pageshow', function(e) {
      if (e.persisted) {
        var btns = taskCard.querySelectorAll('button[type="submit"][data-original-text]');
        for (var j = 0; j < btns.length; j++) {
          btns[j].disabled = false;
          btns[j].textContent = btns[j].getAttribute('data-original-text');
          btns[j].removeAttribute('data-original-text');
        }
        var submitLink = document.getElementById('btn-submit-link');
        if (submitLink && submitLink.hasAttribute('data-original-text')) {
          submitLink.style.pointerEvents = '';
          submitLink.textContent = submitLink.getAttribute('data-original-text');
          submitLink.removeAttribute('data-original-text');
        }
      }
    });
  })();

  // After check: scroll first wrong answer into view
  (function() {
    if (!document.getElementById('score-banner')) return;
    var firstWrong = document.querySelector('.result-wrong');
    if (firstWrong) {
      firstWrong.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  })();
