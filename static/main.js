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
    var body = document.body;
    var isMock = body && body.getAttribute('data-mock-mode') === '1';
    var mockRemaining = isMock ? parseInt(body.getAttribute('data-mock-remaining') || '0', 10) : 0;
    var total = isMock ? mockRemaining : 75 * 60;
    var sec = total;
    var interval = null;
    var el = document.getElementById('timer');
    var autoSubmitted = false;

    function tick() {
      sec--;
      if (sec <= 0) sec = 0;
      if (el) el.textContent = fmtTime(sec);
      if (sec <= 0 && interval) {
        clearInterval(interval);
        interval = null;
        if (el) {
          el.classList.add('global-timer-expired');
          el.textContent = "0:00 — Time's up!";
        }
        // Auto-submit in mock mode
        if (isMock && !autoSubmitted) {
          autoSubmitted = true;
          var finishForm = document.getElementById('mock-finish-form');
          if (finishForm) finishForm.submit();
        }
      }
    }
    if (el) el.textContent = fmtTime(sec);
    // Auto-start timer in mock mode
    if (isMock && sec > 0 && el) {
      interval = setInterval(tick, 1000);
    }
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
      var partInput = document.querySelector('.task-card .task-form input[name="part"]');
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
          // Use the main task form only (not the generate form, which also has input name="part")
          var partInput = document.querySelector('.task-card .task-form input[name="part"]');
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
      var partInput = document.querySelector('.task-card .task-form input[name="part"]');
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

    // Build a lookup: index → sentence text (strip leading "A) " prefix)
    var sentenceTexts = {};
    drags.forEach(function(el) {
      var idx = el.getAttribute('data-sentence-index');
      var text = el.textContent.replace(/^[A-G]\)\s*/, '').trim();
      sentenceTexts[idx] = text;
    });
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
      var sentSpan = drop.querySelector('.part6-gap-sentence');
      if (!input || !label) return;
      if (idx === '' || idx === null || idx === undefined) {
        input.value = '';
        label.textContent = '—';
        if (sentSpan) sentSpan.textContent = '';
        drop.classList.remove('part6-gap-has-value');
      } else {
        input.value = idx;
        var letterStr = letters[parseInt(idx, 10)] || '—';
        label.textContent = letterStr;
        if (sentSpan) sentSpan.textContent = sentenceTexts[idx] || '';
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
      var inp = drop.querySelector('input[name^="p6_"]');
      if (inp && inp.value !== '') {
        drop.classList.add('part6-gap-has-value');
        // Restore sentence text on page load (e.g. after check)
        var sentSpan = drop.querySelector('.part6-gap-sentence');
        var label = drop.querySelector('.part6-gap-label');
        if (sentSpan && sentenceTexts[inp.value]) {
          sentSpan.textContent = sentenceTexts[inp.value];
        }
        if (label) {
          label.textContent = letters[parseInt(inp.value, 10)] || '—';
        }
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

  // ── Vocabulary notebook: double-click to save a word ──────────────────────
  (function() {
    // Works on Part 5/6/7 reading text areas
    var textAreas = document.querySelectorAll('.reading-text, .part7-text-col');
    if (!textAreas.length) return;

    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
    var body = document.body;
    var currentPart = parseInt(body.getAttribute('data-current-part') || '0', 10);

    // Create the save popup
    var popup = document.createElement('div');
    popup.className = 'vocab-popup';
    popup.innerHTML =
      '<div class="vocab-popup-header">' +
        '<span class="vocab-popup-title">Save word</span>' +
        '<button class="vocab-popup-close" type="button">&times;</button>' +
      '</div>' +
      '<div class="vocab-popup-word-row">' +
        '<span class="vocab-popup-word"></span>' +
        '<button class="vocab-popup-speak" type="button" title="Pronounce">🔊</button>' +
      '</div>' +
      '<div class="vocab-popup-forms"></div>' +
      '<div class="vocab-popup-sentence"></div>' +
      '<div class="vocab-popup-buttons">' +
        '<button class="btn vocab-popup-save" type="button">📒 Save to notebook</button>' +
      '</div>' +
      '<div class="vocab-popup-status"></div>';
    popup.style.display = 'none';
    document.body.appendChild(popup);

    var popupWord = popup.querySelector('.vocab-popup-word');
    var popupForms = popup.querySelector('.vocab-popup-forms');
    var popupSentence = popup.querySelector('.vocab-popup-sentence');
    var popupSave = popup.querySelector('.vocab-popup-save');
    var popupClose = popup.querySelector('.vocab-popup-close');
    var popupStatus = popup.querySelector('.vocab-popup-status');
    var popupSpeak = popup.querySelector('.vocab-popup-speak');

    var selectedWord = '';
    var selectedSentence = '';
    var selectedForms = '';
    var _isPhrase = false;
    var _dblClickGuard = false;

    function hidePopup() {
      popup.style.display = 'none';
      popupStatus.textContent = '';
      popupForms.textContent = '';
      popupForms.style.display = 'none';
    }

    popupClose.addEventListener('click', hidePopup);
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') hidePopup();
    });

    // Browser TTS pronunciation
    function speakWord(word) {
      if (!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      var utter = new SpeechSynthesisUtterance(word);
      utter.lang = 'en-GB';
      utter.rate = 0.9;
      window.speechSynthesis.speak(utter);
    }
    popupSpeak.addEventListener('click', function() {
      if (selectedWord) speakWord(selectedWord);
    });

    // Find the single sentence containing the selected word
    function getSentenceForWord(node, word) {
      var el = node.nodeType === 3 ? node.parentElement : node;
      // Walk up to find a block-level element (p, div, li, h1-h6)
      while (el && el !== document.body) {
        var tag = el.tagName.toLowerCase();
        if (tag === 'p' || tag === 'div' || tag === 'li' || /^h[1-6]$/.test(tag)) {
          break;
        }
        el = el.parentElement;
      }
      if (!el || el === document.body) return '';
      var text = el.textContent.trim();
      // Split into sentences (by . ! ? followed by space or end)
      var sentences = text.match(/[^.!?]*[.!?]+[\s]*/g) || [text];
      var lw = word.toLowerCase();
      for (var i = 0; i < sentences.length; i++) {
        if (sentences[i].toLowerCase().indexOf(lw) !== -1) {
          return sentences[i].trim();
        }
      }
      // Fallback: return first sentence
      return sentences[0] ? sentences[0].trim() : text;
    }

    function showPopup(word, sentence, x, y, isPhrase) {
      selectedWord = word;
      selectedSentence = sentence;
      selectedForms = '';
      _isPhrase = !!isPhrase;
      popupWord.textContent = word;
      popup.querySelector('.vocab-popup-title').textContent = isPhrase ? 'Save phrase' : 'Save word';
      popupSentence.textContent = sentence ? (sentence.length > 200 ? sentence.slice(0, 200) + '…' : sentence) : '';
      popupStatus.textContent = '';
      popupForms.textContent = '';
      popupForms.style.display = 'none';
      popupSave.disabled = false;
      popupSave.textContent = '📒 Save to notebook';

      popup.style.display = 'block';
      // Position near click, but keep on screen
      var pw = popup.offsetWidth, ph = popup.offsetHeight;
      var winW = window.innerWidth, winH = window.innerHeight;
      var left = Math.min(x + 10, winW - pw - 20);
      var top = Math.min(y + 10, winH - ph - 20);
      if (left < 10) left = 10;
      if (top < 10) top = 10;
      popup.style.left = left + 'px';
      popup.style.top = top + 'px';

      // Fetch word forms for single words (not phrases)
      if (!isPhrase && word.indexOf(' ') === -1) {
        fetchWordForms(word);
      }
    }

    // Fetch word forms from server
    function fetchWordForms(word) {
      fetch('/api/vocab/word-forms?word=' + encodeURIComponent(word))
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.forms && Object.keys(data.forms).length > 0) {
            selectedForms = JSON.stringify(data.forms);
            var html = '';
            var labels = {noun: 'noun', verb: 'verb', adjective: 'adj', adverb: 'adv'};
            for (var pos in labels) {
              if (data.forms[pos] && data.forms[pos].length) {
                var vals = Array.isArray(data.forms[pos]) ? data.forms[pos].join(', ') : data.forms[pos];
                html += '<span class="vocab-form-tag vocab-form-' + pos + '">' + labels[pos] + ': ' + vals + '</span> ';
              }
            }
            if (data.forms.synonyms && data.forms.synonyms.length) {
              var syns = Array.isArray(data.forms.synonyms) ? data.forms.synonyms.join(', ') : data.forms.synonyms;
              html += '<span class="vocab-form-tag vocab-form-synonym">syn: ' + syns + '</span> ';
            }
            popupForms.innerHTML = html;
            popupForms.style.display = 'block';
          }
        })
        .catch(function() {});
    }

    // Listen for double-click on reading text (single word)
    for (var i = 0; i < textAreas.length; i++) {
      textAreas[i].addEventListener('dblclick', function(e) {
        _dblClickGuard = true;
        setTimeout(function() { _dblClickGuard = false; }, 300);

        var sel = window.getSelection();
        var word = sel ? sel.toString().trim() : '';
        // Keep only the first word, strip punctuation
        word = word.split(/\s+/)[0].replace(/[^a-zA-Z'-]/g, '');
        if (!word || word.length < 2) return;

        var sentence = '';
        if (sel.anchorNode) {
          sentence = getSentenceForWord(sel.anchorNode, word);
        }

        showPopup(word.toLowerCase(), sentence, e.clientX, e.clientY, false);
      });

      // Listen for mouseup — phrase selection (highlight + release)
      textAreas[i].addEventListener('mouseup', function(e) {
        // Skip if this was a double-click (handled above)
        setTimeout(function() {
          if (_dblClickGuard) return;
          var sel = window.getSelection();
          var text = sel ? sel.toString().trim() : '';
          if (!text || text.length < 3) return;
          // Must have at least 2 words to count as a phrase
          var words = text.split(/\s+/);
          if (words.length < 2) return;
          // Clean: strip trailing/leading punctuation
          text = text.replace(/^[^a-zA-Z]+|[^a-zA-Z]+$/g, '');
          if (text.length < 3) return;

          var sentence = '';
          if (sel.anchorNode) {
            sentence = getSentenceForWord(sel.anchorNode, words[0]);
          }

          showPopup(text.toLowerCase(), sentence, e.clientX, e.clientY, true);
        }, 50);
      });
    }

    // Save button
    popupSave.addEventListener('click', function() {
      if (!selectedWord) return;
      popupSave.disabled = true;
      popupSave.textContent = 'Saving…';

      fetch('/api/vocab/save', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          word: selectedWord,
          sentence: selectedSentence,
          source_part: currentPart || null,
          word_forms: selectedForms || null,
        }),
      })
      .then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); })
      .then(function(res) {
        if (res.status === 200 && res.data.ok) {
          popupStatus.className = 'vocab-popup-status vocab-popup-ok';
          popupStatus.textContent = '✓ Saved! Translation will appear in your notebook.';
          popupSave.textContent = '✓ Saved';
          setTimeout(hidePopup, 1800);
        } else if (res.status === 409) {
          popupStatus.className = 'vocab-popup-status vocab-popup-dup';
          popupStatus.textContent = 'Already in your notebook';
          popupSave.textContent = '📒 Already saved';
          setTimeout(hidePopup, 1500);
        } else if (res.status === 401 || res.status === 302) {
          popupStatus.className = 'vocab-popup-status vocab-popup-err';
          popupStatus.textContent = 'Please log in first';
          popupSave.disabled = false;
          popupSave.textContent = '📒 Save to notebook';
        } else {
          popupStatus.className = 'vocab-popup-status vocab-popup-err';
          popupStatus.textContent = res.data.error || 'Save failed';
          popupSave.disabled = false;
          popupSave.textContent = '📒 Save to notebook';
        }
      })
      .catch(function() {
        popupStatus.className = 'vocab-popup-status vocab-popup-err';
        popupStatus.textContent = 'Network error';
        popupSave.disabled = false;
        popupSave.textContent = '📒 Save to notebook';
      });
    });
  })();

  // ── AI action loading indicators ─────────────────────────────────────────
  // Shows a spinner on the clicked button whenever a "generate" or "check"
  // form is submitted, so users know the AI call is in progress.
  (function () {
    function setLoading(btn, label) {
      btn.disabled = true;
      btn.dataset.origText = btn.textContent;
      btn.innerHTML =
        '<span class="btn-spinner" aria-hidden="true"></span>' + label;
      btn.classList.add('btn--loading');
    }

    // Generate buttons (.part2-generate-form → any submit button)
    document.querySelectorAll('.part2-generate-form').forEach(function (form) {
      form.addEventListener('submit', function () {
        var btn = form.querySelector('button[type="submit"]');
        if (btn) setLoading(btn, 'Generating…');
      });
    });

    // Check-answers forms (.task-form with action=check btn)
    document.querySelectorAll('.task-form').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        var submitter = e.submitter;
        if (submitter && submitter.value === 'check') {
          setLoading(submitter, 'Checking…');
        }
      });
    });

    // Writing: generate form
    document.querySelectorAll('.writing-generate-form').forEach(function (form) {
      form.addEventListener('submit', function () {
        var btn = form.querySelector('button[type="submit"]');
        if (btn) setLoading(btn, 'Generating…');
      });
    });

    // Writing: check with AI (editor form, button value="check")
    document.querySelectorAll('.writing-editor-wrap').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        var submitter = e.submitter;
        if (submitter && submitter.value === 'check') {
          setLoading(submitter, 'Checking with AI…');
        }
      });
    });
  })();
