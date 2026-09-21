// みんなの「読みたい」と一言レビュー。minna_api（Cloudflare Workers）を呼ぶ。
// <section id="ugc" data-api="…" data-site="shinkan" data-key="9784…"> に描画する。
// API に届かなければ何も出さない（静的サイトとしては壊れない）。
(function () {
  var root = document.getElementById('ugc');
  if (!root || !root.dataset.api) return;
  var API = root.dataset.api.replace(/\/$/, ''), SITE = root.dataset.site, KEY = root.dataset.key;
  var VOTE_KEY = 'shinkan-want-' + KEY;   // 「今日はもう押した」をブラウザ側でも覚えておく

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function stars(n) { return n ? '★'.repeat(n) + '☆'.repeat(5 - n) : ''; }
  function today() { return new Date().toISOString().slice(0, 10); }
  function votedToday() {
    try { return localStorage.getItem(VOTE_KEY) === today(); } catch (e) { return false; }
  }
  function rememberVote() {
    try { localStorage.setItem(VOTE_KEY, today()); } catch (e) { /* プライベートモードなどでは覚えない */ }
  }

  function render(data) {
    var s = data.stats || {}, votes = data.votes || {}, want = votes.want || 0;
    var voted = votedToday();
    var html = '<h2>この本を読みたい人・読んだ人</h2>';

    // ---- 読みたいボタン（1 人 1 日 1 票） ----
    html += '<div class="want-box">' +
      '<button type="button" class="want-btn' + (voted ? ' voted' : '') + '"' + (voted ? ' disabled' : '') + '>' +
      (voted ? '読みたいに入れました' : '読みたい') + '</button>' +
      '<span class="want-count">' + (want ? want + ' 人が読みたいと言っています' : 'まだ誰も押していません') + '</span>' +
      '<span class="want-msg small"></span>' +
      '<p class="small">押すと<a href="../../wanted/">読みたい本ランキング</a>に反映されます（1 人 1 日 1 回）。</p></div>';

    // ---- 一言レビュー ----
    html += '<h3>一言レビュー</h3>';
    if (s.count) {
      html += '<div class="ugc-stats"><span>レビュー ' + s.count + ' 件</span>' +
        (s.avg_rating ? '<span class="ugc-stars">' + stars(Math.round(s.avg_rating)) + '</span><span>おすすめ度 ' + s.avg_rating + ' / 5（' + s.rating_count + ' 人）</span>' : '') +
        '</div>';
      html += '<ul class="ugc-list">' + (data.posts || []).map(function (p) {
        return '<li><div class="ugc-head">' +
          (p.rating ? '<span class="ugc-stars">' + stars(p.rating) + '</span> ' : '') +
          '<span class="meta">' + esc(p.name || '匿名') + ' ・ ' + esc(String(p.created_at).slice(0, 10)) + '</span>' +
          '<button type="button" class="ugc-report" data-id="' + esc(p.id) + '" title="通報">通報</button></div>' +
          '<p>' + esc(p.body).replace(/\n/g, '<br>') + '</p></li>';
      }).join('') + '</ul>';
    } else {
      html += '<p class="small">まだレビューはありません。読んだ感想が、次に手に取る人の助けになります。</p>';
    }

    html += '<form class="ugc-form" autocomplete="off">' +
      '<div class="ugc-row">' +
      '<label>おすすめ度 <select name="rating"><option value="">未評価</option>' +
      '<option value="5">★5 とてもよかった</option><option value="4">★4 よかった</option>' +
      '<option value="3">★3 ふつう</option><option value="2">★2 いまひとつ</option>' +
      '<option value="1">★1 合わなかった</option></select></label>' +
      '<label>お名前（任意） <input name="name" maxlength="30" placeholder="匿名"></label></div>' +
      '<textarea name="body" maxlength="600" rows="4" placeholder="どんな人に向くか、読みどころ、読んだきっかけなど。URL や連絡先は書けません（5〜600 字）"></textarea>' +
      '<input name="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px">' +
      '<div class="ugc-row"><button type="submit" class="button">レビューを投稿する</button><span class="ugc-msg small"></span></div>' +
      '<p class="small">投稿は匿名で公開されます。個人が特定される情報は書かないでください。不適切な投稿は通報 3 件で自動的に非表示になります。</p></form>';

    root.innerHTML = html;
    root.querySelector('.want-btn').addEventListener('click', castVote);
    root.querySelector('.ugc-form').addEventListener('submit', submit);
    Array.prototype.forEach.call(root.querySelectorAll('.ugc-report'), function (b) {
      b.addEventListener('click', function () {
        if (!confirm('この投稿を通報しますか？')) return;
        fetch(API + '/v1/reports', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ post_id: b.dataset.id }) })
          .then(function () { b.textContent = '通報済み'; b.disabled = true; });
      });
    });
  }

  function castVote() {
    var btn = root.querySelector('.want-btn'), count = root.querySelector('.want-count'), msg = root.querySelector('.want-msg');
    btn.disabled = true;
    msg.textContent = '送信中…';
    fetch(API + '/v1/votes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ site: SITE, key: KEY, kind: 'want' }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) { msg.textContent = j.error; btn.disabled = false; return; }
        rememberVote();
        btn.classList.add('voted');
        btn.textContent = '読みたいに入れました';
        count.textContent = (j.count || 0) + ' 人が読みたいと言っています';
        msg.textContent = j.already ? '今日はもう押しています' : 'ありがとうございます';
      })
      .catch(function () { msg.textContent = '通信に失敗しました'; btn.disabled = false; });
  }

  function submit(e) {
    e.preventDefault();
    var f = e.target, msg = f.querySelector('.ugc-msg'), btn = f.querySelector('button[type=submit]');
    var payload = { site: SITE, key: KEY, kind: 'review', rating: f.rating.value, name: f.name.value, body: f.body.value, website: f.website.value };
    btn.disabled = true;
    msg.textContent = '送信中…';
    fetch(API + '/v1/posts', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'minna' }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok) { msg.textContent = '投稿しました。ありがとうございます。'; load(); }
        else { msg.textContent = res.j.error || '投稿できませんでした'; btn.disabled = false; }
      })
      .catch(function () { msg.textContent = '通信に失敗しました'; btn.disabled = false; });
  }

  function load() {
    fetch(API + '/v1/posts?site=' + encodeURIComponent(SITE) + '&key=' + encodeURIComponent(KEY))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || data.error) { root.innerHTML = ''; return; }
        render(data);
      })
      .catch(function () { root.innerHTML = ''; });
  }
  load();
})();
