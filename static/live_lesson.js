(function() {
  var body = document.body;
  if (!body || body.getAttribute('data-live-lesson-role') !== 'student') return;

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
  var lastPayload = '';
  var lastSentAt = 0;
  var pending = false;

  function isVisible(el) {
    if (!el) return false;
    if (el.offsetParent !== null) return true;
    return !!(el.getClientRects && el.getClientRects().length);
  }

  function getActiveExerciseForm() {
    var forms = [
      document.querySelector('.task-card .task-form'),
      document.getElementById('listening-form')
    ];
    var writingForms = document.querySelectorAll('.writing-editor-wrap');
    for (var i = 0; i < writingForms.length; i++) {
      if (isVisible(writingForms[i])) forms.push(writingForms[i]);
    }
    for (var j = 0; j < forms.length; j++) {
      if (forms[j] && isVisible(forms[j])) return forms[j];
    }
    return null;
  }

  function cleanText(value, limit) {
    var text = String(value || '').replace(/\s+/g, ' ').trim();
    limit = limit || 500;
    if (text.length > limit) return text.slice(0, limit) + '...';
    return text;
  }

  function cleanBlockText(value, limit) {
    var lines = String(value || '')
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n')
      .split('\n')
      .map(function(line) { return line.replace(/\s+/g, ' ').trim(); })
      .filter(Boolean);
    var text = lines.join('\n');
    limit = limit || 8000;
    if (text.length > limit) return text.slice(0, limit) + '...';
    return text;
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
    return String(value).replace(/["\\]/g, '\\$&');
  }

  function fieldLabel(field) {
    var label = field.closest('label');
    if (label) return cleanText(label.textContent, 120);
    var id = field.getAttribute('id');
    if (id) {
      var explicit = document.querySelector('label[for="' + cssEscape(id) + '"]');
      if (explicit) return cleanText(explicit.textContent, 120);
    }
    var name = field.getAttribute('name') || '';
    var m = name.match(/(?:p\d+_|q_)(\d+)/);
    if (m) return 'Question ' + (parseInt(m[1], 10) + 1);
    return cleanText(name || field.getAttribute('aria-label') || 'Answer', 120);
  }

  function readFieldValue(field) {
    var type = (field.type || '').toLowerCase();
    if (type === 'radio') {
      if (!field.checked) return null;
      return field.value;
    }
    if (type === 'checkbox') return field.checked ? field.value || 'checked' : '';
    return field.value || '';
  }

  function fieldChoiceLabel(field) {
    var label = field.closest('label');
    if (label) return cleanText(label.textContent, 220);
    var value = readFieldValue(field);
    return cleanText(value, 120);
  }

  function selectChoices(field) {
    var choices = [];
    var selectedText = '';
    for (var i = 0; i < field.options.length; i++) {
      var opt = field.options[i];
      if (!opt.value) continue;
      var label = cleanText(opt.textContent, 220);
      choices.push({
        value: opt.value,
        label: label,
        selected: opt.selected
      });
      if (opt.selected) selectedText = label;
    }
    return { choices: choices, selectedText: selectedText };
  }

  function radioChoices(form, name) {
    var fields = form.querySelectorAll('input[type="radio"][name="' + cssEscape(name) + '"]');
    var choices = [];
    var selectedText = '';
    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var label = fieldChoiceLabel(field);
      choices.push({
        value: field.value,
        label: label,
        selected: field.checked
      });
      if (field.checked) selectedText = label;
    }
    return { choices: choices, selectedText: selectedText };
  }

  function collectAnswers(form) {
    if (!form) return [];
    var skip = { csrf_token: true, action: true, switch_to_part: true, part: true, option_id: true };
    var fields = form.querySelectorAll('input, textarea, select');
    var answers = [];
    var seenRadio = {};
    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var name = field.getAttribute('name') || '';
      var type = (field.type || '').toLowerCase();
      if (!name || skip[name] || type === 'hidden' || type === 'password' || type === 'submit' || type === 'button') {
        continue;
      }
      if (type === 'radio') {
        if (seenRadio[name]) continue;
        seenRadio[name] = true;
        var selected = form.querySelector('input[type="radio"][name="' + cssEscape(name) + '"]:checked');
        var radioData = radioChoices(form, name);
        answers.push({
          name: name,
          label: fieldLabel(selected || field),
          value: selected ? readFieldValue(selected) : '',
          display_value: radioData.selectedText,
          choices: radioData.choices,
          filled: !!selected
        });
        continue;
      }
      if ((field.tagName || '').toLowerCase() === 'select') {
        var selectData = selectChoices(field);
        answers.push({
          name: name,
          label: fieldLabel(field),
          value: readFieldValue(field),
          display_value: selectData.selectedText,
          choices: selectData.choices,
          filled: cleanText(readFieldValue(field), 10) !== ''
        });
        continue;
      }
      var value = readFieldValue(field);
      answers.push({
        name: name,
        label: fieldLabel(field),
        value: value,
        filled: cleanText(value, 10) !== ''
      });
    }
    return answers;
  }

  function pageTitle(form) {
    var section = form && form.closest('section');
    var title = section && section.querySelector('h1, h2, h3');
    if (!title) title = document.querySelector('main h1, main h2, .listening-heading, .writing-title');
    return title ? cleanText(title.textContent, 160) : cleanText(document.title, 160);
  }

  function scoreText() {
    var score = document.querySelector('.score-banner, .listening-score, .writing-feedback-scores');
    return score ? cleanText(score.textContent, 160) : '';
  }

  function getExerciseContainer(form) {
    if (form) {
      var activeSection = form.closest('section');
      if (activeSection) return activeSection;
      var listening = form.closest('.listening-page');
      if (listening) return listening;
      var writing = form.closest('.writing-panel-active');
      if (writing) return writing;
    }
    return document.querySelector('.part-section.active, .listening-page, .writing-panel-active, main');
  }

  function exerciseText(form) {
    var container = getExerciseContainer(form);
    if (!container) return '';
    var clone = container.cloneNode(true);
    var removeSelectors = [
      'script',
      'style',
      '.actions',
      '.writing-actions',
      '.listening-actions',
      '.part2-generate-row',
      '.part4-db-only-row',
      '.feedback',
      '.score-banner',
      '.listening-score',
      '.writing-feedback',
      '.listening-transcript-wrap',
      '.vocab-popup',
      'button',
      'input[type="hidden"]'
    ];
    removeSelectors.forEach(function(selector) {
      clone.querySelectorAll(selector).forEach(function(el) { el.remove(); });
    });
    clone.querySelectorAll('input, textarea, select').forEach(function(field) {
      var type = (field.type || '').toLowerCase();
      if (type === 'radio' || type === 'checkbox') {
        field.remove();
        return;
      }
      var marker = document.createElement('span');
      marker.textContent = type === 'textarea' || field.tagName.toLowerCase() === 'textarea' ? '[student answer]' : '_____';
      field.replaceWith(marker);
    });
    return cleanBlockText(clone.textContent, 8000);
  }

  function buildState() {
    var form = getActiveExerciseForm();
    var answers = collectAnswers(form);
    var filled = answers.filter(function(item) { return item.filled; }).length;
    var partField = form && form.querySelector('input[name="part"]');
    var bodyPart = body.getAttribute('data-current-part') || '';
    return {
      url: window.location.href,
      path: window.location.pathname + window.location.search,
      page_title: cleanText(document.title, 120),
      section_title: pageTitle(form),
      part: partField ? partField.value : bodyPart,
      task_id: '',
      exercise_text: exerciseText(form),
      score_text: scoreText(),
      filled_count: filled,
      total_fields: answers.length,
      answers: answers
    };
  }

  function sendState(force) {
    if (pending) return;
    var state = buildState();
    var payload = JSON.stringify(state);
    var now = Date.now();
    if (!force && payload === lastPayload && now - lastSentAt < 10000) return;
    pending = true;
    fetch('/api/lessons/live-state', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: payload
    }).then(function() {
      lastPayload = payload;
      lastSentAt = Date.now();
    }).catch(function() {
    }).finally(function() {
      pending = false;
    });
  }

  document.addEventListener('input', function() { sendState(false); }, true);
  document.addEventListener('change', function() { sendState(false); }, true);
  document.addEventListener('submit', function() { sendState(true); }, true);
  setTimeout(function() { sendState(true); }, 400);
  setInterval(function() { sendState(false); }, 2000);
})();
