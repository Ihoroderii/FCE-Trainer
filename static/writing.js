(function() {
  var page = document.querySelector('.writing-page');
  if (!page) return;

  var totalSec = parseInt(page.getAttribute('data-total-minutes') || '80', 10) * 60;
  var wordMin = parseInt(page.getAttribute('data-word-min') || '140', 10);
  var wordMax = parseInt(page.getAttribute('data-word-max') || '190', 10);

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

  function updateWordCount(el, countEl) {
    if (!countEl) return;
    var text = (el && el.value) || '';
    var n = countWords(text);
    countEl.textContent = n + ' words (' + wordMin + '\u2013' + wordMax + ')';
    countEl.classList.remove('writing-count-ok', 'writing-count-low', 'writing-count-high');
    if (n >= wordMin && n <= wordMax) countEl.classList.add('writing-count-ok');
    else if (n > 0 && n < wordMin) countEl.classList.add('writing-count-low');
    else if (n > wordMax) countEl.classList.add('writing-count-high');
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
