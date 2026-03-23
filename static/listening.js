/**
 * Listening page — audio player with 2-play limit (FCE exam rule).
 */
(function () {
  'use strict';

  var audio = document.getElementById('listening-audio');
  var playBtn = document.getElementById('listening-play-btn');
  var progressWrap = document.getElementById('listening-progress-wrap');
  var progressBar = document.getElementById('listening-progress-bar');
  var timeDisplay = document.getElementById('listening-time');
  var playsLeftEl = document.getElementById('listening-plays-left');

  if (!audio || !playBtn) return;

  var MAX_PLAYS = 2;
  var playCount = 0;

  function fmtTime(s) {
    if (isNaN(s) || !isFinite(s)) return '0:00';
    var m = Math.floor(s / 60);
    var sec = Math.floor(s % 60);
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }

  function updatePlaysLeft() {
    var left = MAX_PLAYS - playCount;
    if (playsLeftEl) {
      playsLeftEl.textContent = left + ' play' + (left !== 1 ? 's' : '') + ' left';
      if (left <= 0) playsLeftEl.classList.add('listening-no-plays');
    }
  }

  function updateButton() {
    if (audio.paused) {
      playBtn.textContent = '▶';
      playBtn.title = 'Play';
    } else {
      playBtn.textContent = '⏸';
      playBtn.title = 'Pause';
    }
  }

  playBtn.addEventListener('click', function () {
    if (audio.paused) {
      if (playCount >= MAX_PLAYS) {
        playBtn.classList.add('listening-btn-shake');
        setTimeout(function () { playBtn.classList.remove('listening-btn-shake'); }, 400);
        return;
      }
      // Only increment play count when starting from the beginning
      if (audio.currentTime === 0 || audio.ended) {
        playCount++;
        updatePlaysLeft();
      }
      audio.play();
    } else {
      audio.pause();
    }
    updateButton();
  });

  audio.addEventListener('play', updateButton);
  audio.addEventListener('pause', updateButton);

  audio.addEventListener('ended', function () {
    updateButton();
    if (playCount >= MAX_PLAYS) {
      playBtn.disabled = true;
      playBtn.classList.add('listening-btn-disabled');
    }
  });

  audio.addEventListener('timeupdate', function () {
    if (!audio.duration) return;
    var pct = (audio.currentTime / audio.duration) * 100;
    if (progressBar) progressBar.style.width = pct + '%';
    if (timeDisplay) {
      timeDisplay.textContent = fmtTime(audio.currentTime) + ' / ' + fmtTime(audio.duration);
    }
  });

  // Click on progress bar to seek
  if (progressWrap) {
    progressWrap.addEventListener('click', function (e) {
      if (!audio.duration) return;
      var rect = progressWrap.getBoundingClientRect();
      var pct = (e.clientX - rect.left) / rect.width;
      audio.currentTime = pct * audio.duration;
    });
  }

  updatePlaysLeft();
})();
